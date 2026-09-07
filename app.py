import os
import secrets
import json
import hashlib
import sqlite3
import re
import base64
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, Form, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature
import openai
import edge_tts
import httpx
import uvicorn
from pydantic import BaseModel
import aiosqlite

# =============================================
# 1. إعدادات التسجيل (Logging)
# =============================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================
# 2. المتغيرات الضخمة (القوالب - منسوخة كما هي)
# =============================================

SPH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head>... (نفس المحتوى) ...</html>"""
TOOLS_HTML = """<!DOCTYPE html>... (نفس المحتوى) ...</html>"""
HT = r"""<!DOCTYPE html>... (نفس المحتوى) ...</html>"""
LH = """<!DOCTYPE html>... (نفس المحتوى) ...</html>"""

# =============================================
# 3. إعدادات البيئة والمتغيرات
# =============================================

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود!")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise Exception("OPENAI_MODEL غير موجود! أضفه في متغيرات البيئة.")

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(16))
serializer = URLSafeTimedSerializer(SECRET_KEY)

DB_FILE = "conversations.db"

# =============================================
# 4. دوال قاعدة البيانات غير المتزامنة (aiosqlite)
# =============================================

async def get_db():
    """إرجاع اتصال بقاعدة البيانات."""
    return await aiosqlite.connect(DB_FILE)

async def init_db():
    """إنشاء الجداول إذا لم تكن موجودة."""
    async with await get_db() as conn:
        await conn.execute('''CREATE TABLE IF NOT EXISTS conversations 
            (user_id TEXT, conv_id TEXT PRIMARY KEY, messages TEXT, timestamp TEXT, title TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS cache 
            (question TEXT PRIMARY KEY, answer TEXT, created TEXT)''')
        await conn.execute('''CREATE TABLE IF NOT EXISTS guest_usage 
            (guest_id TEXT PRIMARY KEY, count INT DEFAULT 0, date TEXT)''')
        await conn.commit()
    logger.info("✅ تم تهيئة قاعدة البيانات.")

async def check_guest_limit_safe(gid: str) -> bool:
    """التحقق من حد الضيف (15 سؤال يومياً)."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with await get_db() as conn:
        row = await conn.execute("SELECT count, date FROM guest_usage WHERE guest_id=?", (gid,))
        data = await row.fetchone()
        if not data:
            await conn.execute("INSERT INTO guest_usage VALUES (?,?,?)", (gid, 1, today))
            await conn.commit()
            return True
        count, date = data
        if date != today:
            await conn.execute("UPDATE guest_usage SET count=1, date=? WHERE guest_id=?", (today, gid))
            await conn.commit()
            return True
        if count >= 15:
            return False
        await conn.execute("UPDATE guest_usage SET count=count+1 WHERE guest_id=?", (gid,))
        await conn.commit()
        return True

async def get_cached(question: str) -> Optional[str]:
    """استرجاع إجابة مخزنة مؤقتاً."""
    async with await get_db() as conn:
        row = await conn.execute("SELECT answer FROM cache WHERE question=?", (question.strip(),))
        result = await row.fetchone()
        return result[0] if result else None

async def save_cache(question: str, answer: str):
    """حفظ الإجابة في الكاش."""
    if len(question) < 10 or len(question) > 200:
        return
    if len(answer) > 2000:
        return
    async with await get_db() as conn:
        await conn.execute("INSERT OR REPLACE INTO cache (question, answer, created) VALUES (?,?,?)",
                           (question.strip(), answer, datetime.now().isoformat()))
        await conn.commit()

async def get_user_conversations(user_id: str) -> List[Dict[str, Any]]:
    """جلب جميع محادثات المستخدم."""
    async with await get_db() as conn:
        rows = await conn.execute(
            "SELECT conv_id, messages, timestamp, title FROM conversations WHERE user_id=? ORDER BY timestamp DESC",
            (user_id,)
        )
        results = []
        async for row in rows:
            results.append({
                "id": row[0],
                "messages": json.loads(row[1]),
                "timestamp": row[2],
                "title": row[3]
            })
        return results

async def save_user_conversation(user_id: str, messages: List[Dict], conv_id: Optional[str] = None) -> str:
    """حفظ المحادثة (جديدة أو تحديث)."""
    async with await get_db() as conn:
        if conv_id is None:
            # إنشاء معرف جديد
            title = messages[0]["content"][:30] + "..." if len(messages[0]["content"]) > 30 else messages[0]["content"]
            new_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}{secrets.token_hex(2)}".encode()).hexdigest()[:10]
            await conn.execute(
                "INSERT INTO conversations (user_id, conv_id, messages, timestamp, title) VALUES (?,?,?,?,?)",
                (user_id, new_id, json.dumps(messages, ensure_ascii=False), datetime.now().isoformat(), title)
            )
            await conn.commit()
            return new_id
        else:
            await conn.execute(
                "UPDATE conversations SET messages=?, timestamp=? WHERE user_id=? AND conv_id=?",
                (json.dumps(messages, ensure_ascii=False), datetime.now().isoformat(), user_id, conv_id)
            )
            await conn.commit()
            return conv_id

async def load_conversation_by_id(user_id: str, conv_id: str) -> Optional[List[Dict]]:
    """تحميل محادثة محددة."""
    async with await get_db() as conn:
        row = await conn.execute("SELECT messages FROM conversations WHERE user_id=? AND conv_id=?", (user_id, conv_id))
        result = await row.fetchone()
        return json.loads(result[0]) if result else None

# =============================================
# 5. دوال الصور والفيديو والصوت (غير متزامنة)
# =============================================

async def generate_image(prompt: str) -> str:
    """توليد صورة عبر Pexels (مجاني)."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return "ERROR: PEXELS_API_KEY غير موجود في البيئة"
    query = httpx.quote(prompt)
    url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape"
    headers = {"Authorization": api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(url, headers=headers)
            data = response.json()
            if response.status_code == 200 and data.get("photos") and len(data["photos"]) > 0:
                return data["photos"][0]["src"]["large"]
            else:
                return f"ERROR: {data.get('error','لم أجد صورة مناسبة')}"
        except Exception as e:
            return f"ERROR: {str(e)}"

async def search_video(prompt: str) -> str:
    """البحث عن فيديو عبر Pexels."""
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        return "ERROR: PEXELS_API_KEY غير موجود في البيئة"
    query = httpx.quote(prompt)
    url = f"https://api.pexels.com/videos/search?query={query}&per_page=1"
    headers = {"Authorization": api_key}
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(url, headers=headers)
            data = response.json()
            if response.status_code == 200 and data.get("videos") and len(data["videos"]) > 0:
                video_files = data["videos"][0]["video_files"]
                for vf in video_files:
                    if vf.get("quality") == "hd" and vf.get("link"):
                        return vf["link"]
                if video_files and video_files[0].get("link"):
                    return video_files[0]["link"]
                return "ERROR: ما لقيت رابط فيديو"
            else:
                return f"ERROR: {data.get('error','لم أجد فيديو مناسباً')}"
        except Exception as e:
            return f"ERROR: {str(e)}"

async def generate_speech(text: str, gender: str) -> Optional[str]:
    """توليد صوت باستخدام edge-tts."""
    try:
        voice = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariyahNeural"
        communicate = edge_tts.Communicate(text, voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return base64.b64encode(audio_data).decode('utf-8')
    except Exception as e:
        logger.error(f"❌ فشل الصوت (edge-tts): {e}")
        return None

# =============================================
# 6. المعرفة الأساسية
# =============================================

knowledge_content = ""
for fn in ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]:
    if os.path.exists(fn):
        try:
            with open(fn, "r", encoding="utf-8") as f:
                knowledge_content = f.read()
                break
        except:
            pass
if not knowledge_content:
    knowledge_content = "أنت نبراس، مساعد ذكي."

SYSTEM_PROMPT = f"""أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**

1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.

2. **معرفتك العامة**.

3. **البحث بالويب** تستخدمه فقط عندما تكون أدمن ويسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.

**ملف المعرفة الخاص بك:**

{knowledge_content}

**⚠️ قاعدة التنسيق الذهبية (الأهم):**

- اكتب ردودك في **فقرات نصية متصلة**. كل فقرة تحتوي على **2 إلى 4 جمل** فقط.
- **ممنوع** وضع كل جملة في سطر منفصل. استخدم النقاط والفواصل وعلامات الترقيم داخل الفقرة نفسها.
- **ممنوع** وضع فواصل أسطر (`Enter`) بين الجمل. الفاصل الوحيد المسموح به هو سطر فارغ بين الفقرة والأخرى.
- اجعل الجملة الواحدة بطول معتدل (حوالي 10-20 كلمة)، بحيث تكون واضحة ومختصرة لكنها تحمل فكرة كاملة."""

# =============================================
# 7. تطبيق FastAPI ونماذج Pydantic
# =============================================

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = []
    conv_id: Optional[str] = None
    image: Optional[str] = None  # base64 data URL

class ChatResponse(BaseModel):
    reply: str
    audio: Optional[str] = None
    conv_id: str
    image_url: Optional[str] = None

class DeleteMessageRequest(BaseModel):
    conv_id: str
    index: int

class SetGenderRequest(BaseModel):
    gender: str

# =============================================
# 8. دوال مساعدة للجلسات
# =============================================

def get_user_id_from_cookie(cookie: Optional[str]) -> str:
    if cookie:
        try:
            data = serializer.loads(cookie)
            return data.get("user_id", "guest_" + secrets.token_hex(8))
        except BadSignature:
            pass
    return "guest_" + secrets.token_hex(8)

def set_user_cookie(user_id: str) -> str:
    data = {"user_id": user_id}
    return serializer.dumps(data)

# =============================================
# 9. دورة حياة التطبيق
# =============================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

# مونتاج المجلدات الثابتة (إن وجدت)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
if os.path.exists(".well-known"):
    app.mount("/.well-known", StaticFiles(directory=".well-known"), name="well-known")

# =============================================
# 10. نقاط النهاية (Endpoints)
# =============================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    fake_session = {}
    if user_id.startswith("admin_"):
        fake_session['admin_email'] = user_id.replace("admin_", "")
    elif user_id.startswith("user_"):
        fake_session['user_email'] = user_id.replace("user_", "")
    return HTMLResponse(content=HT.replace("{{ session.get('admin_email') or session.get('user_email') }}", 
                                           fake_session.get('admin_email') or fake_session.get('user_email', '')))

@app.get("/tools", response_class=HTMLResponse)
async def tools_page():
    return HTMLResponse(content=TOOLS_HTML)

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request, error: Optional[str] = None):
    return HTMLResponse(content=LH.replace("{{ error }}", error or ""))

@app.post("/login")
async def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    admin_email = "abdullaha0569361@gmail.com"
    admin_password = os.environ.get("ADMIN_PASSWORD")
    
    if email == admin_email:
        if not admin_password:
            return HTMLResponse(content=LH.replace("{{ error }}", "خطأ: لم يتم إعداد كلمة مرور الأدمن في الخادم."))
        if secrets.compare_digest(password, admin_password):
            response = RedirectResponse(url="/", status_code=302)
            response.set_cookie(key="nibras_session", value=set_user_cookie("admin_" + admin_email), httponly=True, max_age=3600*24*30)
            return response
        else:
            return HTMLResponse(content=LH.replace("{{ error }}", "كلمة مرور الأدمن غير صحيحة."))
    elif "@" in email:
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(key="nibras_session", value=set_user_cookie("user_" + email), httponly=True, max_age=3600*24*30)
        return response
    else:
        return HTMLResponse(content=LH.replace("{{ error }}", "يرجى إدخال بريد إلكتروني صحيح."))

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/")
    response.delete_cookie("nibras_session")
    return response

@app.get("/history")
async def history(request: Request, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    convs = await get_user_conversations(user_id)
    return {"conversations": [{"id": c["id"], "title": c["title"]} for c in convs]}

@app.get("/load_conversation/{cid}")
async def load_conversation(request: Request, cid: str, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    msgs = await load_conversation_by_id(user_id, cid)
    if msgs is None:
        raise HTTPException(status_code=404, detail="المحادثة غير موجودة")
    return {"messages": msgs}

@app.post("/delete_message")
async def delete_message(data: DeleteMessageRequest, request: Request, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    msgs = await load_conversation_by_id(user_id, data.conv_id)
    if not msgs:
        return JSONResponse({"status": "error", "message": "المحادثة غير موجودة"}, status_code=404)
    if data.index < 0 or data.index >= len(msgs):
        return JSONResponse({"status": "error", "message": "الرسالة غير موجودة"}, status_code=404)
    del msgs[data.index]
    await save_user_conversation(user_id, msgs, data.conv_id)
    return {"status": "ok"}

@app.post("/delete_my_data")
async def delete_my_data(request: Request, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    async with await get_db() as conn:
        await conn.execute("DELETE FROM conversations WHERE user_id=?", (user_id,))
        await conn.commit()
    response = JSONResponse({"status": "success", "message": "تم حذف جميع بياناتك ومحادثاتك بنجاح."})
    response.delete_cookie("nibras_session")
    return response

@app.get("/admin")
async def admin_dashboard(request: Request, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    if user_id != "admin_abdullaha0569361@gmail.com":
        return HTMLResponse(content="🚫 هذه الصفحة خاصة بالأدمن فقط.", status_code=403)
    async with await get_db() as conn:
        users_count = await conn.execute("SELECT COUNT(DISTINCT user_id) FROM conversations")
        users_count = (await users_count.fetchone())[0]
        total_convs = await conn.execute("SELECT COUNT(*) FROM conversations")
        total_convs = (await total_convs.fetchone())[0]
        today = datetime.now().strftime("%Y-%m-%d")
        today_convs = await conn.execute("SELECT COUNT(*) FROM conversations WHERE timestamp LIKE ?", (today + '%',))
        today_convs = (await today_convs.fetchone())[0]
        recent = await conn.execute("SELECT user_id, title, timestamp FROM conversations ORDER BY timestamp DESC LIMIT 10")
        recent_rows = await recent.fetchall()
    recent_html = ""
    for row in recent_rows:
        user = row[0][:15] + "..." if len(row[0]) > 15 else row[0]
        title = row[1] or "محادثة بدون عنوان"
        time = row[2][:16] if row[2] else "وقت غير معروف"
        recent_html += f'<div class="conv-item"><b>{title}</b><small>👤 {user} | 🕒 {time}</small></div>'
    if not recent_html:
        recent_html = "<p style='color:#8b949e;text-align:center;'>لا توجد محادثات بعد</p>"
    admin_html = f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>لوحة تحكم نبراس</title><style>body{{font-family:'Segoe UI',Tahoma;background:#0d1117;color:#c9d1d9;padding:20px;margin:0}}.container{{max-width:600px;margin:auto}}h1{{color:#58a6ff;text-align:center}}.card{{background:#161b22;border-radius:15px;padding:15px;margin:15px 0;border:1px solid #30363d}}.stat{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #21262d}}.stat:last-child{{border:none}}.num{{color:#58a6ff;font-weight:bold;font-size:18px}}.conv-item{{padding:10px 0;border-bottom:1px solid #21262d}}.conv-item small{{color:#8b949e;display:block;font-size:12px}}.back{{display:block;text-align:center;color:#58a6ff;text-decoration:none;margin-top:20px}}</style></head><body><div class="container"><h1>📊 لوحة تحكم نبراس</h1><div class="card"><div class="stat"><span>👥 إجمالي المستخدمين</span><span class="num">{users_count}</span></div><div class="stat"><span>💬 إجمالي المحادثات</span><span class="num">{total_convs}</span></div><div class="stat"><span>📅 محادثات اليوم</span><span class="num">{today_convs}</span></div></div><div class="card"><h3>🕒 آخر 10 محادثات</h3>{recent_html}</div><a href="/" class="back">⬅ العودة للرئيسية</a></div></body></html>"""
    return HTMLResponse(content=admin_html)

@app.get("/share/{cid}")
async def shared_conversation(request: Request, cid: str):
    async with await get_db() as conn:
        row = await conn.execute("SELECT messages, title FROM conversations WHERE conv_id=?", (cid,))
        data = await row.fetchone()
    if data:
        messages = json.loads(data[0])
        title = data[1] or "محادثة نبراس"
        # استبدال القالب البسيط (لاحظ أننا نستخدم replace بدلاً من jinja2 لتجنب تعقيدات إضافية)
        html = SPH.replace("{{ title or 'محادثة نبراس' }}", title)
        # بناء رسائل HTML
        msgs_html = ""
        for idx, msg in enumerate(messages):
            role_class = "user" if msg["role"] == "user" else "bot"
            avatar = "👤" if msg["role"] == "user" else "🤖"
            content = msg["content"].replace("\n", "<br>")
            time_str = f"{idx+1}. {'مستخدم' if msg['role'] == 'user' else 'نبراس'}"
            msgs_html += f'<div class="msg {role_class}"><div class="avatar">{avatar}</div><div class="content">{content}<span class="time">{time_str}</span></div></div>'
        html = html.replace("{% for msg in messages %}<div class=\"msg {{ 'user' if msg.role == 'user' else 'bot' }}\"><div class=\"avatar\">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class=\"content\">{{ msg.content|replace('\\n','<br>')|safe }}<span class=\"time\">{{ loop.index }}. {{ 'مستخدم' if msg.role == 'user' else 'نبراس' }}</span></div></div>{% endfor %}", msgs_html)
        return HTMLResponse(content=html)
    return HTMLResponse(content="⚠️ المحادثة غير موجودة أو تم حذفها.", status_code=404)

@app.post("/set_gender")
async def set_gender(data: SetGenderRequest):
    response = JSONResponse({"status": "ok"})
    response.set_cookie("voice_gender", data.gender, max_age=3600*24*30)
    return response

# =============================================
# 11. نقطة النهاية الأساسية: /chat
# =============================================

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: Request, payload: ChatRequest, nibras_session: Optional[str] = Cookie(None)):
    user_id = get_user_id_from_cookie(nibras_session)
    is_admin = user_id == "admin_abdullaha0569361@gmail.com"
    
    # استخراج البيانات
    user_message = payload.message.strip()
    history = payload.history or []
    conv_id = payload.conv_id
    image_data = payload.image  # base64 data URL

    # إذا كانت الرسالة فارغة ولا توجد صورة
    if not user_message and not image_data:
        return ChatResponse(reply="اكتب شيء أساعدك فيه", conv_id=conv_id or "temp")

    # ---- التحقق من حد الزوار ----
    if not is_admin:
        if not await check_guest_limit_safe(user_id):
            limit_reply = "وصلت للحد المجاني اليوم (15 سؤال) 😊\n\n💡 عندك حلين بدون ما تدفع:\n\n1- جرب أدواتنا المجانية 100% (ما تستهلك رصيد):\nhttps://nibras-al.onrender.com/tools\n\n2- ارجع بكرة وتاخذ 15 سؤال جديدة مجاناً\n\nنظامنا مجاني للجميع لأنه بدون بوابة دفع."
            # حفظ المحادثة
            if conv_id is None:
                conv_id = await save_user_conversation(user_id, [{"role": "user", "content": user_message}, {"role": "assistant", "content": limit_reply}])
            else:
                msgs = await load_conversation_by_id(user_id, conv_id)
                if msgs is None:
                    msgs = []
                msgs.append({"role": "user", "content": user_message})
                msgs.append({"role": "assistant", "content": limit_reply})
                await save_user_conversation(user_id, msgs, conv_id)
            return ChatResponse(reply=limit_reply, conv_id=conv_id, audio=None)

    # ---- الكاش (لغير الأدمن) ----
    if not is_admin:
        cached = await get_cached(user_message)
        if cached:
            if conv_id is None:
                conv_id = await save_user_conversation(user_id, [{"role": "user", "content": user_message}, {"role": "assistant", "content": cached}])
            else:
                msgs = await load_conversation_by_id(user_id, conv_id)
                if msgs is None:
                    msgs = []
                msgs.append({"role": "user", "content": user_message})
                msgs.append({"role": "assistant", "content": cached})
                await save_user_conversation(user_id, msgs, conv_id)
            return ChatResponse(reply=cached + "\n\n⚡ جواب سريع من الذاكرة", conv_id=conv_id, audio=None)

    # ---- توليد الصور والفيديو المجاني (للجميع) ----
    draw_phrases = ["ارسم لي", "ابي صورة", "ابي صوره", "ابي صورت", "صوره لي", "ارسم", "أنشئ", "انشئ", "انشى", "صمم", "ولّد", "generate", "draw", "فيديو", "ابي فيديو", "عرض فيديو"]
    is_image_req = any(phrase in user_message.lower() for phrase in draw_phrases) and len(user_message.split()) > 1
    is_video_req = "فيديو" in user_message.lower() or "ابي فيديو" in user_message.lower()

    # إذا كان طلب صورة أو فيديو (وليس مرفق صورة)
    if is_image_req and not image_data:
        if is_video_req:
            video_url = await search_video(user_message)
            if video_url.startswith("ERROR:"):
                reply = f"⚠️ عذراً، ما قدرت أجيب الفيديو. السبب: {video_url.replace('ERROR:', '')}"
            else:
                reply = f"🎬 إليك الفيديو الذي طلبتـه:\n{video_url}"
                # حفظ المحادثة
                if conv_id is None:
                    conv_id = await save_user_conversation(user_id, [{"role": "user", "content": user_message}, {"role": "assistant", "content": reply}])
                else:
                    msgs = await load_conversation_by_id(user_id, conv_id)
                    if msgs is None:
                        msgs = []
                    msgs.append({"role": "user", "content": user_message})
                    msgs.append({"role": "assistant", "content": reply})
                    await save_user_conversation(user_id, msgs, conv_id)
                return ChatResponse(reply=reply, conv_id=conv_id, image_url=video_url if not video_url.startswith("ERROR:") else None)
        else:
            img_url = await generate_image(user_message)
            if img_url.startswith("ERROR:"):
                reply = f"⚠️ عذراً، ما قدرت أولد الصورة. السبب: {img_url.replace('ERROR:', '')}"
            else:
                reply = f"🖼️ إليك الصورة التي طلبتها:\n{img_url}"
                if conv_id is None:
                    conv_id = await save_user_conversation(user_id, [{"role": "user", "content": user_message}, {"role": "assistant", "content": reply}])
                else:
                    msgs = await load_conversation_by_id(user_id, conv_id)
                    if msgs is None:
                        msgs = []
                    msgs.append({"role": "user", "content": user_message})
                    msgs.append({"role": "assistant", "content": reply})
                    await save_user_conversation(user_id, msgs, conv_id)
                return ChatResponse(reply=reply, conv_id=conv_id, image_url=img_url if not img_url.startswith("ERROR:") else None)

    # ---- معالجة الصور المرفقة (للأدمن فقط) ----
    if image_data and not is_admin:
        reply = "عذراً، ميزة تحليل الصور المرفوعة والبحث المباشر غير متاحة حالياً    .\n\n💡 لكن تقدر تطلب صور وفيديوهات مجانية بكلمة (ارسم لي) أو (ابي فيديو)."
        if conv_id is None:
            conv_id = await save_user_conversation(user_id, [{"role": "user", "content": user_message}, {"role": "assistant", "content": reply}])
        else:
            msgs = await load_conversation_by_id(user_id, conv_id)
            if msgs is None:
                msgs = []
            msgs.append({"role": "user", "content": user_message})
            msgs.append({"role": "assistant", "content": reply})
            await save_user_conversation(user_id, msgs, conv_id)
        return ChatResponse(reply=reply, conv_id=conv_id, audio=None)

    # ---- المحادثة العادية (باستخدام OpenAI) ----
    # تحميل المحادثة السابقة إذا كانت موجودة
    if conv_id:
        old_msgs = await load_conversation_by_id(user_id, conv_id)
        if old_msgs is None:
            old_msgs = []
    else:
        old_msgs = []
    
    # إضافة رسالة المستخدم
    old_msgs.append({"role": "user", "content": user_message})

    # بناء قائمة الرسائل للنموذج
    messages_for_api = [{"role": "system", "content": SYSTEM_PROMPT}]
    # نأخذ آخر 30 رسالة للسياق
    context = old_msgs[-30:]
    messages_for_api.extend(context)

    # إضافة الصورة للأدمن
    if image_data and is_admin:
        # نضيف رسالة تحتوي على الصورة (باستخدام صيغة OpenAI)
        messages_for_api.append({
            "role": "user",
            "content": [
                {"type": "text", "text": user_message or "حلل هذه الصورة"},
                {"type": "image_url", "image_url": {"url": image_data}}
            ]
        })

    # البحث بالويب للأدمن
    if is_admin:
        try:
            # تحضير سياق المحادثة
            context_text = ""
            for m in messages_for_api:
                if m["role"] == "user":
                    context_text += m["content"] + "\n"
                elif m["role"] == "assistant":
                    context_text += "نبراس: " + m["content"] + "\n"
            # طلب البحث
            sr = client.responses.create(
                model=OPENAI_MODEL,
                instructions=f"{SYSTEM_PROMPT}\n\nسياق المحادثة السابقة:\n{context_text}",
                input=f"ابحث في الويب عن أحدث المعلومات حول: {user_message}، وقدم لي ملخصاً مفيداً.",
                tools=[{"type": "web_search"}]
            )
            search_result = sr.output_text.strip()
            if search_result:
                messages_for_api.append({"role": "user", "content": f"نتيجة البحث:\n{search_result}\n\nاستخدم هذه المعلومات."})
        except Exception as e:
            logger.warning(f"⚠️ فشل البحث: {e}")

    try:
        reasoning_level = "low" if not is_admin else "high"
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages_for_api,
            max_completion_tokens=8000,
            reasoning_effort=reasoning_level
        )
        reply = response.choices[0].message.content.strip()
        if not reply:
            reply = "ما قدرت أجيب لك رد، حاول مرة أخرى."
    except Exception as e:
        logger.error(f"❌ خطأ OpenAI: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

    # تنسيق الفقرات (إزالة الأسطر الزائدة)
    lines = reply.split('\n')
    merged_paragraphs = []
    current = []
    for line in lines:
        line = line.strip()
        if not line:
            if current:
                merged_paragraphs.append(' '.join(current))
                current = []
        else:
            current.append(line)
    if current:
        merged_paragraphs.append(' '.join(current))
    reply = '\n\n'.join(merged_paragraphs)

    # حفظ المحادثة
    old_msgs.append({"role": "assistant", "content": reply})
    conv_id = await save_user_conversation(user_id, old_msgs, conv_id)

    # حفظ الكاش (لغير الأدمن)
    if not is_admin:
        await save_cache(user_message, reply)

    # توليد الصوت
    gender = request.cookies.get("voice_gender", "male")
    audio_base64 = await generate_speech(reply, gender)

    return ChatResponse(reply=reply, audio=audio_base64, conv_id=conv_id)

# =============================================
# 12. تشغيل التطبيق
# =============================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
