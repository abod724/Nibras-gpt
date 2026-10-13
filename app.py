from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, send_from_directory, Response, stream_with_context
import openai, os, secrets, json, base64, re, requests
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from markupsafe import escape
import io, urllib.parse
from gtts import gTTS

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY مطلوب بطول 32 حرفًا على الأقل")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=True, SESSION_COOKIE_NAME='nibras_session', SESSION_COOKIE_DOMAIN=None)

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "abdullaha0569361@gmail.com")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY: raise Exception("OPENAI_API_KEY غير موجود!")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL: raise Exception("OPENAI_MODEL غير موجود!")
client = openai.OpenAI(api_key=OPENAI_API_KEY)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY: raise Exception("SUPABASE_URL و SUPABASE_KEY مطلوبان!")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

LIMITS = {"guest": {"chat": 15, "search": 0, "image": 0}, "user": {"chat": 15, "search": 2, "image": 1}, "admin": {"chat": 9999, "search": 9999, "image": 9999}}

def get_user_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    return fwd.split(',')[0].strip() if fwd else get_remote_address()

limiter = Limiter(key_func=get_user_ip, default_limits=["500 per day", "300 per hour"])
limiter.init_app(app)

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    allowed = ['https://abod724.github.io', 'https://nibras-al.onrender.com', 'https://test-bot-001.onrender.com']
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/robots.txt')
def serve_robots(): return send_from_directory('static', 'robots.txt')
@app.route('/sitemap.xml')
def serve_sitemap(): return send_from_directory('static', 'sitemap.xml')
@app.route('/.well-known/<path:filename>')
def serve_well_known(filename): return send_from_directory('.well-known', filename)
@app.route('/service-worker.js')
def service_worker(): return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

def get_user_role(email):
    if not email: return 'guest'
    if email.lower() == ADMIN_EMAIL.lower(): return 'admin'
    try:
        r = sb.table("profiles").select("role").eq("email", email.lower()).limit(1).execute()
        if r and r.data and r.data[0].get("role"): return r.data[0]["role"]
    except Exception as e: print("get_user_role:", e)
    return 'user'

def get_user_profile(email):
    if not email: return None
    try:
        r = sb.table("profiles").select("*").eq("email", email.lower().strip()).limit(1).execute()
        if r and r.data: return r.data[0]
    except Exception as e: print("get_user_profile:", e)
    return None

def save_user_profile(email, name=None, avatar=None):
    if not email: return
    try:
        data = {"email": email.lower().strip()}
        if name is not None: data["display_name"] = name
        if avatar is not None: data["avatar_url"] = avatar
        sb.table("profiles").upsert(data, on_conflict="email").execute()
    except Exception as e: print("save_user_profile:", e)

def touch_user(email):
    if not email: return
    try: sb.table("profiles").update({"last_seen": datetime.utcnow().isoformat()}).eq("email", email.lower().strip()).execute()
    except Exception as e: print("touch_user:", e)

def get_user_memory(email):
    if not email: return {}
    try:
        r = sb.table("profiles").select("memory").eq("email", email.lower().strip()).limit(1).execute()
        if r and r.data and r.data[0].get("memory"): return r.data[0]["memory"] or {}
    except Exception as e: print("get_user_memory:", e)
    return {}

def save_user_memory(email, memory_dict):
    if not email: return
    try: sb.table("profiles").update({"memory": memory_dict}).eq("email", email.lower().strip()).execute()
    except Exception as e: print("save_user_memory:", e)

def get_user_language(email):
    if not email: return 'ar'
    mem = get_user_memory(email)
    lang = mem.get('lang')
    return lang if lang in ('ar', 'en') else 'ar'

def get_pinned_convs(email):
    if not email: return []
    try:
        r = sb.table("profiles").select("pinned_convs").eq("email", email.lower().strip()).limit(1).execute()
        if r and r.data and r.data[0].get("pinned_convs"): return r.data[0]["pinned_convs"] or []
    except Exception as e: print("get_pinned_convs:", e)
    return []

def save_pinned_convs(email, pinned_list):
    if not email: return
    try: sb.table("profiles").update({"pinned_convs": pinned_list}).eq("email", email.lower().strip()).execute()
    except Exception as e: print("save_pinned_convs:", e)

def get_user_id():
    if session.get('is_admin'): session.permanent = True; return "admin_page"
    if session.get('user_email'): session.permanent = True; return "user_" + session['user_email']
    if 'guest_id' not in session: session['guest_id'] = "guest_" + secrets.token_hex(8)
    session.permanent = True
    return session['guest_id']

def get_usage_today(uid):
    today = _date.today().isoformat()
    try:
        r = sb.table("assistant_usage").select("*").eq("user_id", uid).eq("date", today).limit(1).execute()
        if r and r.data: return r.data[0]
    except Exception as e: print("get_usage_today select:", e)
    new_row = {"user_id": uid, "date": today, "chat_count": 0, "image_count": 0, "search_count": 0}
    try:
        r = sb.table("assistant_usage").insert(new_row).execute()
        if r and r.data: return r.data[0]
    except Exception as e: print("get_usage_today insert:", e)
    return new_row

def inc_usage(uid, field):
    today = _date.today().isoformat()
    row = get_usage_today(uid)
    current = int(row.get(field, 0) or 0) + 1
    try: sb.table("assistant_usage").update({field: current}).eq("user_id", uid).eq("date", today).execute()
    except Exception as e: print("inc_usage:", e)
    return current

def check_limits(uid, role):
    usage = get_usage_today(uid)
    limits = LIMITS.get(role, LIMITS["guest"])
    return usage, limits, int(usage.get("chat_count", 0) or 0) < limits["chat"], int(usage.get("search_count", 0) or 0) < limits["search"], int(usage.get("image_count", 0) or 0) < limits["image"]

def get_user_conversations(uid):
    try:
        r = sb.table("assistant_chats").select("conv_id,title,created_at").eq("user_id", uid).order("created_at", desc=True).limit(200).execute()
        rows = r.data or []
    except Exception as e: print("get_user_conversations:", e); return []
    seen = {}
    for row in rows:
        cid = row.get("conv_id")
        if cid and cid not in seen:
            title = (row.get("title") or "").strip() or "محادثة"
            seen[cid] = {"id": cid, "conv_id": cid, "title": title, "timestamp": row.get("created_at")}
    return list(seen.values())

def save_message(uid, msg, resp, cid=None):
    if not cid: cid = secrets.token_hex(5)
    try:
        ex = sb.table("assistant_chats").select("id").eq("user_id", uid).eq("conv_id", cid).limit(1).execute()
        has_prev = bool(ex.data)
        title = None
        if not has_prev:
            clean_msg = (msg or "").strip()
            clean_msg = re.sub(r'[^\w\s\u0600-\u06FF]', '', clean_msg).strip()
            title = (clean_msg[:30] + "...") if len(clean_msg) > 30 else (clean_msg or "محادثة جديدة")
        sb.table("assistant_chats").insert({"user_id": uid, "conv_id": cid, "message": msg, "response": resp, "title": title}).execute()
    except Exception as e: print("save_message:", e)
    return cid

def load_conversation(uid, cid):
    try:
        r = sb.table("assistant_chats").select("message,response,created_at").eq("user_id", uid).eq("conv_id", cid).order("created_at").execute()
        rows = r.data or []
    except Exception as e: print("load_conversation:", e); return None
    if not rows: return None
    msgs = []
    for row in rows:
        if row.get("message"): msgs.append({"role": "user", "content": row["message"]})
        if row.get("response"): msgs.append({"role": "assistant", "content": row["response"]})
    return msgs

def load_conversation_public(cid):
    try:
        r = sb.table("assistant_chats").select("message,response,title,created_at,user_id").eq("conv_id", cid).order("created_at").execute()
        return r.data or []
    except Exception as e: print("load_conversation_public:", e); return []

def delete_message_row(uid, cid, index):
    try:
        r = sb.table("assistant_chats").select("id,message,response").eq("user_id", uid).eq("conv_id", cid).order("created_at").execute()
        rows = r.data or []
        if index < 0 or index >= len(rows): return False
        row_idx = index // 2
        if row_idx >= len(rows): return False
        sb.table("assistant_chats").delete().eq("id", rows[row_idx]["id"]).execute()
        return True
    except Exception as e: print("delete_message_row:", e); return False

def save_image_to_library(uid, image_url=None, image_data=None, title="", source="upload"):
    try:
        row = {"user_id": uid, "title": title or "صورة", "source": source}
        if image_url: row["image_url"] = image_url
        if image_data: row["image_data"] = image_data
        r = sb.table("image_library").insert(row).execute()
        return r.data[0] if r and r.data else None
    except Exception as e: print("save_image_to_library:", e); return None

def get_user_images(uid):
    try:
        r = sb.table("image_library").select("*").eq("user_id", uid).order("created_at", desc=True).limit(200).execute()
        return r.data or []
    except Exception as e: print("get_user_images:", e); return []

def delete_user_image(uid, image_id):
    try: sb.table("image_library").delete().eq("id", image_id).eq("user_id", uid).execute(); return True
    except Exception as e: print("delete_user_image:", e); return False

kc = ""
for fn in ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]:
    if os.path.exists(fn):
        try:
            with open(fn, "r", encoding="utf-8") as f: kc = f.read(); break
        except: pass
if not kc: kc = "أنت نبراس، مساعد ذكي."

SP = f"""أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه).
2. **معرفتك العامة**.
3. **البحث بالويب** عند الحاجة.

**ملف المعرفة:**
{kc}

**قاعدة التنسيق:**
- اكتب ردودك في فقرات متصلة (2-4 جمل).
- لا تضع كل جملة في سطر منفصل.
- الفاصل الوحيد هو سطر فارغ بين الفقرات.

**قاعدة صوتية مهمة:**
- استخدم الإيموجي مباشرة بدون وصفها بالكلام.
- لا تكتب أبداً "وجه مبتسم" أو "شمس" أو "قلب أحمر" أو أي وصف حرفي للإيموجي.
- مثال صح: "صباح النور يا سعد ☀️"
- مثال خطأ: "صباح النور يا سعد مع شمس مشرقة"

**قواعد الهوية — مهمة جداً:**
- أنت "نبراس" فقط. لا تذكر أبداً أي شركة أو تطبيق أو خدمة أو منتج آخر بالاسم.
- لا تذكر ChatGPT، Google، OpenAI، Gemini، Claude، Copilot، Alexa، Siri، أو أي اسم مشابه.
- لا توجّه المستخدم أبداً لتحميل تطبيق آخر أو استخدام خدمة خارجية.
- إذا سُئلت "هل أنت ChatGPT؟" أو "من صنعك؟" رد: "أنا نبراس، مساعدك الشخصي".
- إذا سألك المستخدم عن ميزة اشرح له كيف يستخدمها **داخل نبراس** فقط.
- لا تذكر خصائص تطبيقات أخرى أبداً ولا تقارن نفسك بها.

**قواعد التنسيق الحديث:**
- استخدم Markdown لتنسيق ردودك: **نص عريض**، *نص مائل*، `كود سطري`.
- للقوائم استخدم: - نقطة، أو 1. رقم.
- للعناوين استخدم: ## عنوان، أو ### عنوان.
- للأكواد استخدم بلوكات ``` لغة ... ```.
- للجداول استخدم: | عمود | عمود |
- للاقتباس استخدم: > نص.

**أسلوب الحديث:**
- سولف بشكل طبيعي وعفوي.
- لا تذكر أبداً أي كلام عن حفظ المحادثات أو الذاكرة.
- رد بشكل مباشر بدون مقدمات فلسفية."""

LANG_INSTRUCTION = {"ar": "\n\n**اللغة:** رد دائماً بالعربية، بأسلوبك العامي المعتاد.", "en": "\n\n**Language:** ALWAYS respond in English, regardless of the language the user writes in. Keep the same friendly, casual tone."}

PERSONALITY_INSTRUCTIONS = {
    "friendly": "",
    "concise": "\n\n**الأسلوب:** كن موجزاً جداً — 1-2 جملة كحد أقصى. بدون مقدمات أو حشو أو شرح زائد.",
    "detailed": "\n\n**الأسلوب:** قدّم شرحاً مفصلاً مع أمثلة عملية وخطوات واضحة. لا تختصر.",
    "formal": "\n\n**الأسلوب:** استخدم اللغة العربية الفصحى الرسمية، بدون أي عامية أو مزح. كن مهنياً.",
    "teacher": "\n\n**الأسلوب:** اشرح خطوة بخطوة كأنك معلم — مقدمة، تفصيل، خلاصة. وضّح بمثال.",
    "playful": "\n\n**الأسلوب:** كن مرحاً وأضف لمسات دعابة خفيفة (بدون أي إساءة أو تجاوز). خفيف الظل."
}

def generate_speech(text, gender):
    try:
        emoji_pattern = re.compile("[" u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" u"\U0001F900-\U0001F9FF" u"\U0001FA00-\U0001FAFF" u"\U00002600-\U000026FF" u"\U00002700-\U000027BF" u"\U0001F000-\U0001F02F" u"\U0001F0A0-\U0001F0FF" u"\U00002B00-\U00002BFF" u"\U0001F780-\U0001F7FF" u"\U0001F800-\U0001F8FF" u"\U00002190-\U000021FF" u"\U0000FE00-\U0000FE0F" u"\U0000200D" u"\U000020E3" "]+", flags=re.UNICODE)
        clean_text = emoji_pattern.sub('', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        if not clean_text: return None
        tts = gTTS(text=clean_text[:4000], lang='ar', slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        audio = buf.getvalue()
        if audio: return base64.b64encode(audio).decode('utf-8')
    except Exception as e: print(f"gTTS failed: {e}")
    return None

SHARED_VIEW_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:flex-start;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px;margin-top:20px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px;font-weight:600}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word;white-space:pre-wrap}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}.error{background:#ffe8e8;color:#c33;padding:20px;border-radius:14px;text-align:center;font-weight:600}</style></head><body><div class="container"><div class="header"><h1>محادثة نبراس</h1><a href="/">الرئيسية</a></div><div id="content"><div class="error">جاري التحميل...</div></div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div><script>(function(){var c=document.getElementById('content');var U='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';var B='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>';try{var h=window.location.hash||'';var m=h.match(/[#&]d=([^&]+)/);if(!m){c.innerHTML='<div class="error">الرابط غير صالح أو ناقص.</div>';return;}var e=decodeURIComponent(m[1]);var j=decodeURIComponent(escape(atob(e)));var ms=JSON.parse(j);if(!Array.isArray(ms)||ms.length===0){c.innerHTML='<div class="error">المحادثة فاضية.</div>';return;}c.innerHTML='';ms.forEach(function(msg){var d=document.createElement('div');d.className='msg '+(msg.r==='u'?'user':'bot');var a=document.createElement('div');a.className='avatar';a.innerHTML=msg.r==='u'?U:B;var t=document.createElement('div');t.className='content';t.textContent=msg.c||'';d.appendChild(a);d.appendChild(t);c.appendChild(d);});if(ms[0]&&ms[0].c){document.title=String(ms[0].c).slice(0,30);}}catch(e){c.innerHTML='<div class="error">تعذر قراءة المحادثة من الرابط.</div>';}})();</script></body></html>"""

SPH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>{{ (title or 'محادثة نبراس')|e }}</h1><a href="/">الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{% if msg.role == 'user' %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{% else %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>{% endif %}</div><div class="content">{{ msg.content|e|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

LIBRARY_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.img-card .delete-btn:hover svg{stroke:#fff}.img-card .delete-btn svg{width:16px;height:16px;stroke:#ff4757;stroke-width:2;fill:none}.empty{text-align:center;padding:60px 20px;color:#8b949e}.empty h3{color:#5a6b7c;font-size:18px;margin-bottom:6px}.empty p{font-size:14px}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}@media(max-width:520px){.topbar h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.img-card .preview{height:150px}}</style></head><body><div class="container"><div class="topbar"><h1><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4a6a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.replaceChildren();if(!d.images||d.images.length===0){const empty=document.createElement('div');empty.className='empty';empty.style.gridColumn='1/-1';const h=document.createElement('h3');h.textContent='مكتبتك فاضية';const p=document.createElement('p');p.textContent='ارفع أول صورة';empty.append(h,p);grid.appendChild(empty);return;}d.images.forEach(img=>{const src=img.image_data||img.image_url||'';const card=document.createElement('div');card.className='img-card';const preview=document.createElement('img');preview.className='preview';preview.loading='lazy';if(typeof src==='string'&&(src.startsWith('data:image/')||src.startsWith('https://')))preview.src=src;preview.alt='صورة';const del=document.createElement('button');del.className='delete-btn';del.type='button';del.title='حذف';del.textContent='×';const info=document.createElement('div');info.className='info';const title=document.createElement('div');title.className='title';title.textContent=String(img.title||'صورة');const source=document.createElement('div');source.className='source';source.textContent=img.source==='generated'?'مولدة':'مرفوعة';info.append(title,source);card.append(preview,del,info);del.onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف هذه الصورة؟'))return;try{const dr=await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});const res=await dr.json();if(dr.ok&&res.status==='ok'){card.remove();showToast('تم الحذف');if(grid.children.length===0)loadImages();}else showToast('فشل الحذف');}catch(e){showToast('خطأ في الاتصال');}};grid.appendChild(card);});}catch(e){grid.replaceChildren();const msg=document.createElement('p');msg.className='empty';msg.textContent='تعذر تحميل الصور';grid.appendChild(msg);}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{const r=await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});const d=await r.json();if(d.status==='ok')showToast('تم رفع الصورة');else showToast(d.message||'فشل الرفع');}catch(e){showToast('خطأ في الاتصال');}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};zone.ondragover=(e)=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=(e)=>{e.preventDefault();zone.classList.remove('dragover');uploadFiles(e.dataTransfer.files);};loadImages();
</script></body></html>"""

LH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;position:relative;font-family:inherit;transition:color .2s}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}.field input::placeholder{color:#a5b0be}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit;transition:all .2s}button.submit:hover{background:#3a5a7a}button.submit:active{transform:scale(0.98)}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}a:hover{color:#3a5a7a}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider{margin:22px 0 0;padding-top:18px;border-top:1px solid #eef1f6}.privacy-link{font-size:12px;color:#a5b0be;margin-top:6px;text-decoration:underline;font-weight:500}.divider-or{display:flex;align-items:center;gap:14px;margin:26px 0 18px;color:#a5b0be;font-size:13px;font-weight:500}.divider-or::before,.divider-or::after{content:'';flex:1;height:1px;background:#e8ecf1}.google-btn{display:flex;align-items:center;justify-content:center;gap:14px;padding:14px 24px;border:1.5px solid #dce1e8;border-radius:50px;background:#fff;color:#1a2b3c;font-size:15px;font-weight:600;text-decoration:none;cursor:pointer;transition:all .2s ease;font-family:inherit;-webkit-tap-highlight-color:transparent;width:100%;margin-top:0;box-sizing:border-box}.google-btn:hover{background:#f8faff;border-color:#4285F4;box-shadow:0 4px 14px rgba(66,133,244,0.12);color:#1a2b3c}.google-btn:active{transform:scale(0.99)}.google-btn svg{width:22px;height:22px;flex-shrink:0}.google-btn span{line-height:1}@media(max-width:420px){.box{padding:34px 24px}h2{font-size:22px}}@media(prefers-color-scheme:dark){body{background:#0d1117}.box{background:#161b22}h2{color:#c9d1d9}.subtitle{color:#8b949e}.tabs{border-bottom-color:#30363d}.tabs button{color:#8b949e}.tabs button.active{color:#58a6ff}.tabs button.active::after{background:#58a6ff}.field input{background:#21262d;border-color:#30363d;color:#c9d1d9}.field input:focus{border-color:#58a6ff;background:#21262d;box-shadow:0 0 0 4px rgba(88,166,255,0.15)}button.submit{background:#238636}button.submit:hover{background:#2ea043}.divider{border-top-color:#30363d}.divider-or{color:#8b949e}.divider-or::before,.divider-or::after{background:#30363d}.google-btn{background:#21262d;border-color:#30363d;color:#c9d1d9}.google-btn:hover{background:#1a2332;border-color:#4285F4;color:#c9d1d9}.privacy-link{color:#6e7681}}</style></head><body><div class="box"><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form><div class="divider-or"><span>أو</span></div><a href="/auth/google" class="google-btn"><svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg><span>المتابعة باستخدام حساب Google</span></a></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form><div class="divider-or" style="margin-top:26px;"><span>أو</span></div><a href="/auth/google" class="google-btn"><svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg><span>المتابعة باستخدام حساب Google</span></a></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div class="divider" style="display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:8px;"><a href="/" style="margin-top:0;">العودة للرئيسية</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" class="privacy-link" style="margin-top:0;">شروط الاستخدام</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="privacy-link" style="margin-top:0;">سياسة الخصوصية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

OAUTH_CALLBACK_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>جاري تسجيل الدخول...</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:380px;text-align:center}.spinner{width:52px;height:52px;border:4px solid #e5e9ef;border-top-color:#4a6a8a;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}@keyframes spin{to{transform:rotate(360deg)}}h2{font-size:19px;color:#1a2b3c;margin-bottom:8px;font-weight:700}p{color:#8b949e;font-size:14px;line-height:1.7}.err{color:#d63031}.ok{color:#00b894}</style></head><body><div class="box"><div class="spinner" id="spin"></div><h2 id="title">جاري تسجيل الدخول</h2><p id="msg">لحظة من فضلك...</p></div><script>(function(){var t=document.getElementById('title');var m=document.getElementById('msg');var s=document.getElementById('spin');function f(msg){s.style.display='none';t.textContent='تعذر تسجيل الدخول';t.classList.add('err');m.textContent=msg;setTimeout(function(){window.location.href='/login';},2500);}try{var h=window.location.hash.substring(1);var q=window.location.search.substring(1);var p=new URLSearchParams(h||q);var a=p.get('access_token');var r=p.get('refresh_token');var e=p.get('error')||p.get('error_description');if(e){f(decodeURIComponent(e));return;}if(!a){f('لم يتم استلام التوكن.');return;}fetch('/auth/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:a,refresh_token:r||''})}).then(function(x){return x.json();}).then(function(d){if(d&&d.status==='ok'){t.textContent='تم تسجيل الدخول';t.classList.add('ok');m.textContent='جاري تحويلك...';setTimeout(function(){window.location.href='/';},500);}else{f((d&&d.message)||'فشل إنشاء الجلسة');}}).catch(function(){f('تعذر الاتصال بالسيرفر');});}catch(e){f('خطأ في قراءة الرابط');}})();</script></body></html>"""

RESET_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>تعيين كلمة مرور جديدة</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff}h2{font-size:22px;color:#1a2b3c;margin-bottom:8px}.subtitle{color:#8b949e;font-size:14px;margin-bottom:26px}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;font-family:inherit;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit}button.submit:hover{background:#3a5a7a}.msg{padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right;display:none}.msg.err{display:block;color:#d63031;background:#ffe8e8}.msg.ok{display:block;color:#00b894;background:#e6fff5}</style></head><body><div class="box"><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg></div><h2>كلمة مرور جديدة</h2><p class="subtitle">اكتب كلمة مرورك الجديدة</p><div id="msg" class="msg"></div><form id="resetForm"><div class="field"><input type="password" id="newPass" placeholder="كلمة المرور الجديدة (8 أحرف +)" minlength="8" required></div><div class="field"><input type="password" id="confirmPass" placeholder="تأكيد كلمة المرور" minlength="8" required></div><button type="submit" class="submit">حفظ كلمة المرور</button></form></div><script>(function(){var m=document.getElementById('msg');var f=document.getElementById('resetForm');var t=null;try{var h=window.location.hash.substring(1);var q=window.location.search.substring(1);var p=new URLSearchParams(h||q);t=p.get('access_token');if(!t){m.className='msg err';m.textContent='الرابط غير صالح أو منتهي.';f.style.display='none';}}catch(e){m.className='msg err';m.textContent='خطأ في قراءة الرابط.';f.style.display='none';}f.addEventListener('submit',async function(ev){ev.preventDefault();var p1=document.getElementById('newPass').value;var p2=document.getElementById('confirmPass').value;if(p1.length<8){m.className='msg err';m.textContent='كلمة المرور لازم 8 أحرف على الأقل';return;}if(p1!==p2){m.className='msg err';m.textContent='كلمتا المرور ما تتطابقان';return;}m.className='msg';m.textContent='جاري الحفظ...';try{var r=await fetch('/update_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:t,new_password:p1})});var d=await r.json();if(d.status==='ok'){m.className='msg ok';m.textContent='تم تعيين كلمة المرور! جاري التحويل...';setTimeout(function(){window.location.href='/login';},1500);}else{m.className='msg err';m.textContent=(d.message||'فشل التحديث');}}catch(e){m.className='msg err';m.textContent='تعذر الاتصال بالسيرفر';}});})();</script></body></html>"""

HT = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><title>نبراس GP | مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"><link rel="icon" href="/static/icon-192.png"><link rel="apple-touch-icon" href="/static/icon-192.png"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="theme-color" content="#ffffff"><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--send-bg:#4a6a8a}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#58a6ff;--send-bg:#238636}html[data-font="small"]{--font-size-base:14px}html[data-font="medium"]{--font-size-base:16px}html[data-font="large"]{--font-size-base:18px}html[data-font="xlarge"]{--font-size-base:20px}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif;-webkit-tap-highlight-color:transparent}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s,opacity .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.icon-btn.voice-on{color:var(--primary-color);opacity:1}.icon-btn.voice-off{color:var(--text-secondary);opacity:0.7}.btn-group{display:flex;gap:8px;align-items:center}.btn{padding:7px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center;font-family:inherit;font-weight:600}.btn-outline{background:0 0;border:1.5px solid var(--primary-color);color:var(--primary-color);transition:all .2s}.btn-outline:hover{background:var(--primary-color);color:#fff}.user-badge{display:flex;align-items:center;gap:6px;background:var(--bg-hover);padding:6px 12px;border-radius:20px;font-size:13px;color:var(--text-primary);font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user-badge svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}.dropdown{position:absolute;top:68px;left:12px;right:12px;background:var(--bg-dropdown);border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:78vh;overflow-y:auto;padding:10px}.dropdown.show{display:flex}.dropdown .item{display:flex;align-items:center;gap:14px;padding:13px 16px;font-size:15px;color:var(--text-primary);background:transparent;border:none;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-weight:600;border-radius:14px}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0;opacity:.85}.dropdown .section-title{padding:16px 16px 6px;font-size:11px;font-weight:700;color:var(--text-secondary);letter-spacing:.8px;text-transform:uppercase;opacity:.7}.dropdown .conv-item{display:flex;align-items:center;gap:8px;padding:11px 16px;border:none;background:transparent;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-size:14px;color:var(--text-primary);font-weight:500;border-radius:14px;position:relative}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item .conv-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dropdown .conv-item::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--primary-color);opacity:.4;flex-shrink:0}.dropdown .conv-item .pin-btn{background:transparent;border:none;cursor:pointer;padding:4px;border-radius:8px;display:flex;align-items:center;justify-content:center;opacity:0.5;flex-shrink:0}.dropdown .conv-item .pin-btn:hover{opacity:1;background:var(--bg-hover)}.dropdown .conv-item .pin-btn svg{width:16px;height:16px;stroke:var(--text-primary);stroke-width:2;fill:none}.dropdown .conv-item .pin-btn.pinned svg{fill:var(--primary-color);stroke:var(--primary-color)}.dropdown .pinned-item{padding:11px 16px;display:flex;align-items:center;gap:8px;border-radius:14px}.dropdown .pinned-item:hover{background:var(--bg-hover)}.dropdown .item.danger{color:#d32f2f}.dropdown .item.danger svg{stroke:#d32f2f;opacity:1}.dropdown .item.danger:hover{background:rgba(211,47,47,0.08)}.settings-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:99999;display:none;flex-direction:column;overflow-y:auto}.settings-overlay.show{display:flex}.settings-page{max-width:500px;width:100%;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column;background:var(--bg-body)}.settings-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.settings-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.settings-body{padding:16px;display:flex;flex-direction:column;gap:14px}.settings-card{background:var(--bg-app);border-radius:18px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.settings-item{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.settings-item:last-child{border-bottom:none}.settings-item:hover{background:var(--bg-hover)}.settings-item .item-right{display:flex;align-items:center;gap:14px;color:var(--text-primary);font-size:15px;font-weight:600}.settings-item .item-right svg{width:22px;height:22px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0}.settings-item .chevron{width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none}.sub-page{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;display:none;align-items:center;justify-content:center;padding:20px}.sub-page.show{display:flex}.sub-page .modal-box{background:var(--bg-app);width:100%;max-width:420px;max-height:80vh;border-radius:22px;overflow:hidden;display:flex;flex-direction:column;border:1px solid var(--border-color)}.sub-page-body{padding:20px;overflow-y:auto;flex:1}.modal-title{text-align:center;font-size:17px;font-weight:700;color:var(--text-primary);padding:18px 20px;border-bottom:1px solid var(--border-color)}.modal-confirm{width:100%;padding:16px;background:transparent;border:none;border-top:1px solid var(--border-color);font-size:16px;font-weight:700;color:var(--primary-color);cursor:pointer;font-family:inherit}.option-list,.color-grid,.personality-list,.fontsize-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.option-row,.color-row,.personality-row,.fontsize-row{padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;display:flex;justify-content:space-between;align-items:center}.option-row:last-child,.color-row:last-child,.personality-row:last-child,.fontsize-row:last-child{border-bottom:none}.option-label{display:flex;justify-content:space-between;align-items:center;font-size:15px;color:var(--text-primary);font-weight:500;width:100%}.check-icon{width:22px;height:22px;stroke:var(--primary-color);stroke-width:2.5;fill:none;opacity:0;flex-shrink:0}.option-row.selected .check-icon,.color-row.selected .check-icon,.personality-row.selected .check-icon,.fontsize-row.selected .check-icon{opacity:1}.color-row-left{display:flex;align-items:center;gap:14px;font-size:15px;color:var(--text-primary);font-weight:500}.color-circle{width:26px;height:26px;border-radius:50%;flex-shrink:0}.personality-text{display:flex;flex-direction:column;gap:3px;flex:1;min-width:0}.personality-name{font-size:15px;color:var(--text-primary);font-weight:500}.personality-sub{font-size:12.5px;color:var(--text-secondary)}.personality-row.selected .personality-name{color:var(--primary-color);font-weight:700}.fontsize-row-left{display:flex;flex-direction:column;gap:4px}.fontsize-label{font-size:15px;color:var(--text-primary);font-weight:500}.fontsize-sample{color:var(--text-secondary)}.lang-list{display:flex;flex-direction:column;gap:12px}.lang-card{display:flex;align-items:center;gap:16px;padding:18px 20px;background:var(--bg-app);border-radius:18px;cursor:pointer;border:2px solid var(--border-color)}.lang-card.selected{border-color:var(--primary-color);background:linear-gradient(135deg,var(--bg-app) 0%,rgba(74,106,138,0.06) 100%)}.lang-flag{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;flex-shrink:0;color:#fff}.lang-info{flex:1;display:flex;flex-direction:column;gap:3px}.lang-name{font-size:17px;font-weight:700;color:var(--text-primary)}.lang-sub{font-size:13px;color:var(--text-secondary)}.lang-check{width:26px;height:26px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;flex-shrink:0}.lang-card.selected .lang-check{opacity:1}.memory-card{background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color);margin-bottom:14px}.memory-header{padding:14px 18px;background:var(--bg-hover);display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border-color)}.memory-header svg{width:18px;height:18px;stroke:var(--primary-color);stroke-width:2;fill:none}.memory-header span{font-size:14px;color:var(--text-primary);font-weight:700}.memory-item{padding:14px 18px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.memory-item:last-child{border-bottom:none}.memory-key{font-size:14px;color:var(--text-secondary);font-weight:500}.memory-val{font-size:14.5px;color:var(--text-primary);font-weight:600;text-align:left;word-wrap:break-word;max-width:60%}.memory-empty{padding:24px 18px;text-align:center;color:var(--text-secondary);font-size:14px}.memory-note{padding:14px 18px;background:var(--bg-hover);font-size:13px;color:var(--text-secondary);line-height:1.8;border-radius:0 0 16px 16px;margin-top:-14px;margin-bottom:14px}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:var(--font-size-base);min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:var(--font-size-base);font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--msg-user-bg,var(--bg-user-msg));color:var(--msg-user-text,#111);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:transparent;border-bottom-right-radius:6px}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;display:block}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}
.msg .md-h1{font-size:1.45em;font-weight:800;margin:14px 0 8px;color:var(--text-primary);line-height:1.4}.msg .md-h2{font-size:1.25em;font-weight:700;margin:12px 0 6px;color:var(--text-primary);line-height:1.4}.msg .md-h3{font-size:1.1em;font-weight:700;margin:10px 0 5px;color:var(--text-primary);line-height:1.4}.msg .md-h4,.msg .md-h5,.msg .md-h6{font-size:1.02em;font-weight:700;margin:8px 0 4px;color:var(--text-primary)}.msg strong{font-weight:700;color:var(--text-primary)}.msg em{font-style:italic}.msg del{text-decoration:line-through;opacity:0.7}.msg .md-link{color:var(--primary-color);text-decoration:none;border-bottom:1px solid transparent;font-weight:600;word-break:break-all}.msg .md-link:hover{border-bottom-color:var(--primary-color)}.msg .md-list{margin:8px 0;padding-right:22px;list-style:none}.msg .md-list li{position:relative;padding-right:18px;margin:5px 0;line-height:1.75}.msg .md-list li::before{content:'•';position:absolute;right:0;top:0;color:var(--primary-color);font-weight:900;font-size:1.1em;line-height:1.7}.msg .md-ol{counter-reset:md-ol;margin:8px 0;padding-right:26px;list-style:none}.msg .md-ol li{position:relative;padding-right:24px;margin:5px 0;line-height:1.75;counter-increment:md-ol}.msg .md-ol li::before{content:counter(md-ol) '.';position:absolute;right:0;top:0;color:var(--primary-color);font-weight:700;font-size:0.92em}.msg .md-blockquote{margin:10px 0;padding:8px 14px;border-right:3px solid var(--primary-color);background:var(--bg-hover);border-radius:8px;font-style:italic;color:var(--text-secondary);line-height:1.75}.msg .md-hr{border:none;height:1px;background:var(--border-color);margin:14px 0}.msg .md-table-wrap{overflow-x:auto;margin:12px 0;border-radius:12px;border:1px solid var(--border-color);background:var(--bg-app)}.msg .md-table{width:100%;border-collapse:collapse;font-size:0.94em;direction:rtl}.msg .md-table th{background:var(--bg-hover);padding:9px 12px;text-align:right;font-weight:700;color:var(--text-primary);border-bottom:1.5px solid var(--border-color);white-space:nowrap}.msg .md-table td{padding:8px 12px;border-bottom:1px solid var(--border-color);color:var(--text-primary);text-align:right;vertical-align:top;line-height:1.6}.msg .md-table tr:last-child td{border-bottom:none}.msg .md-table tr:nth-child(even) td{background:rgba(74,106,138,0.03)}
code.inline-code{background:rgba(74,106,138,0.1);color:#c2410c;padding:2px 7px;border-radius:6px;font-family:'JetBrains Mono','Consolas','Monaco',monospace;font-size:0.9em;direction:ltr;display:inline-block;unicode-bidi:embed;font-weight:600}html.dark-mode code.inline-code{background:rgba(88,166,255,0.12);color:#79c0ff}
.code-block{position:relative;background:#0d1117;border:1px solid rgba(255,255,255,0.06);border-radius:14px;margin:12px 0;overflow:hidden;direction:ltr;text-align:left;font-family:'JetBrains Mono','Consolas','Monaco',monospace;box-shadow:0 8px 28px rgba(0,0,0,0.28)}.code-block .code-header{display:flex;justify-content:space-between;align-items:center;padding:10px 14px;background:rgba(255,255,255,0.025);border-bottom:1px solid rgba(255,255,255,0.05)}.code-block .code-lang{display:flex;align-items:center;gap:8px;font-size:11px;font-weight:600;color:#8b949e;letter-spacing:0.6px;font-family:'Segoe UI',sans-serif;text-transform:lowercase}.code-block .code-lang::before{content:'';width:7px;height:7px;border-radius:50%;background:linear-gradient(135deg,#58a6ff 0%,#a371f7 100%);flex-shrink:0}.code-block .code-copy{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);color:#8b949e;font-size:11.5px;font-weight:600;cursor:pointer;padding:5px 11px 5px 9px;border-radius:9px;font-family:'Segoe UI',sans-serif}.code-block .code-copy:hover{background:rgba(88,166,255,0.12);border-color:rgba(88,166,255,0.3);color:#58a6ff}.code-block .code-copy.copied{background:rgba(63,185,80,0.15);border-color:rgba(63,185,80,0.35);color:#3fb950}.code-block .code-copy svg{width:13px;height:13px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.code-block .code-copy .copy-icon-check{display:none}.code-block .code-copy.copied .copy-icon-copy{display:none}.code-block .code-copy.copied .copy-icon-check{display:block}.code-block pre{margin:0;padding:14px 16px;overflow-x:auto;font-size:13px;line-height:1.65;color:#cdd6f4;font-family:inherit;white-space:pre;tab-size:4}.code-block pre::-webkit-scrollbar{height:6px}.code-block pre::-webkit-scrollbar-thumb{background:#45475a;border-radius:3px}.code-block code{font-family:inherit;color:#cdd6f4;background:none;padding:0}
.input-area{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:28px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative}.input-area:focus-within{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.08)}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:var(--font-size-base);font-weight:500;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow-y:hidden;min-height:22px;max-height:150px;font-family:inherit;line-height:1.5;width:100%}.input-area textarea::placeholder{color:var(--placeholder-color)}#imagePreviewContainer{display:none;width:100%;padding:8px 4px 4px}#imagePreviewContainer.show{display:block}.image-preview-wrapper{position:relative;display:inline-block;border-radius:14px;overflow:hidden}.image-preview-wrapper img{display:block;max-height:76px;max-width:120px;object-fit:cover;border-radius:14px;border:1px solid var(--border-color)}.image-preview-wrapper .remove-img-btn{position:absolute;top:5px;left:5px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,0.65);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}.image-preview-wrapper .remove-img-btn:hover{background:rgba(220,38,38,0.95)}.image-preview-wrapper .remove-img-btn svg{width:11px;height:11px;stroke:#fff;stroke-width:3;fill:none;pointer-events:none}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.input-area .btn-icon:hover{background:var(--bg-hover)}.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.input-area .mic-btn{color:var(--primary-color)}.input-area .mic-btn.listening{color:#c33;background:#fde8e8}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 14px rgba(74,106,138,0.35)}.input-area .send:hover{background:var(--primary-hover);transform:scale(1.05)}.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.plus-btn:hover{background:var(--bg-hover)}.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}.plus-options .option-btn:hover{background:var(--border-color)}.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}
.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg,rgba(0,0,0,0.5));z-index:9999;justify-content:center;align-items:center;padding:20px;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px)}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 22px 22px;border-radius:26px;max-width:400px;width:100%;text-align:center;border:1px solid var(--border-color);box-shadow:0 20px 60px rgba(0,0,0,0.18)}.share-modal .box h3{font-size:19px;color:var(--text-primary);margin:0 0 20px;font-weight:700}.share-modal .box .share-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}.share-modal .box .share-btn{display:flex;align-items:center;justify-content:center;gap:9px;padding:14px 16px;border-radius:16px;text-decoration:none;font-size:13.5px;font-weight:700;border:none;cursor:pointer;color:#fff;font-family:inherit}.share-modal .box .share-btn svg{width:18px;height:18px;flex-shrink:0}.share-modal .box .share-btn:hover{transform:translateY(-2px);filter:brightness(1.08)}.share-modal .box .share-btn.whatsapp{background:linear-gradient(135deg,#25D366 0%,#128C7E 100%)}.share-modal .box .share-btn.facebook{background:linear-gradient(135deg,#1877F2 0%,#0d5fce 100%)}.share-modal .box .share-btn.twitter{background:linear-gradient(135deg,#2a2a2a 0%,#000 100%)}.share-modal .box .share-btn.copy{background:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%)}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:12px 30px;border-radius:16px;font-size:14.5px;color:var(--text-primary);cursor:pointer;margin-top:6px;width:100%;font-weight:700;font-family:inherit}
.msg-actions{display:flex;gap:2px;margin-top:12px;align-items:center;opacity:0.5}.msg-actions.touched{opacity:1}.msg-actions button{background:transparent;border:none;cursor:pointer;width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary)}.msg-actions button:hover{background:var(--bg-hover);color:var(--text-primary)}.msg-actions button svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.9;fill:none;stroke-linecap:round;stroke-linejoin:round}.msg-actions button.liked{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.liked svg{fill:#10b981;stroke:#10b981}.msg-actions button.disliked{color:#ef4444;background:rgba(239,68,68,0.1)}.msg-actions button.disliked svg{fill:#ef4444;stroke:#ef4444}.msg-actions button.copied{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.speaking{color:var(--primary-color);background:var(--bg-hover)}.msg-actions button.speaking svg{fill:currentColor}
@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px}.input-area .btn-icon{width:32px;height:32px}.plus-btn{width:32px;height:32px}}
#oauth-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:999999;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;padding:20px}#oauth-overlay.show{display:flex}#oauth-overlay .oauth-spinner{width:52px;height:52px;border:4px solid var(--border-color);border-top-color:var(--primary-color);border-radius:50%;animation:oauthSpin 1s linear infinite}@keyframes oauthSpin{to{transform:rotate(360deg)}}#oauth-overlay .oauth-title{font-size:19px;color:var(--text-primary);font-weight:700}#oauth-overlay .oauth-msg{font-size:14px;color:var(--text-secondary)}
.assistant-bar{padding:6px 14px 0;flex-shrink:0;display:none;justify-content:flex-start}.assistant-bar.show{display:flex}.assistant-pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px 6px 14px;background:var(--bg-input);border:1px solid var(--border-color);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--text-primary);cursor:pointer;font-family:inherit;max-width:200px}.assistant-pill:hover{background:var(--bg-hover)}.assistant-pill .a-dot{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;flex-shrink:0}.assistant-pill .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}.assistant-pill svg{width:11px;height:11px;stroke:var(--text-secondary);stroke-width:2.5;fill:none;flex-shrink:0}.assistant-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:200;min-width:220px;max-width:260px;display:none;max-height:60vh;overflow-y:auto}.assistant-menu.show{display:block}.assistant-menu-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:11px;cursor:pointer;font-size:14px;font-weight:600;color:var(--text-primary);border:none;background:transparent;width:100%;text-align:right;font-family:inherit}.assistant-menu-item:hover{background:var(--bg-hover)}.assistant-menu-item .a-dot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;flex-shrink:0}.assistant-menu-item .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.assistant-menu-item .a-check{width:15px;height:15px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;flex-shrink:0}.assistant-menu-item.selected .a-check{opacity:1}.assistant-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}.assistant-menu-add{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:11px;cursor:pointer;font-size:13px;font-weight:600;color:var(--primary-color);border:none;background:transparent;width:100%;text-align:right;font-family:inherit}.assistant-menu-add:hover{background:var(--bg-hover)}.assistant-menu-add svg{width:16px;height:16px;stroke:currentColor;stroke-width:2.5;fill:none;flex-shrink:0}.assistants-list{display:flex;flex-direction:column;gap:10px}.assistant-card{display:flex;align-items:center;gap:14px;padding:14px 16px;background:var(--bg-app);border-radius:16px;box-shadow:0 1px 3px var(--shadow-color);border:1px solid var(--border-color)}.assistant-card .a-dot{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px;font-weight:700;flex-shrink:0}.assistant-card-info{flex:1;min-width:0}.assistant-card-name{font-size:15px;font-weight:700;color:var(--text-primary);margin-bottom:3px}.assistant-card-sub{font-size:12.5px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.assistant-card-del{background:transparent;border:none;cursor:pointer;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);flex-shrink:0;padding:0}.assistant-card-del:hover{color:#ef4444}.assistant-card-del svg{width:16px;height:16px;stroke:currentColor;stroke-width:2;fill:none}.assistant-add-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;background:var(--bg-app);border:1.5px dashed var(--border-color);border-radius:16px;cursor:pointer;font-size:14px;font-weight:600;color:var(--primary-color);font-family:inherit;margin-top:12px;width:100%}.assistant-add-btn:hover{border-color:var(--primary-color);background:var(--bg-hover)}.assistant-add-btn svg{width:18px;height:18px;stroke:currentColor;stroke-width:2.5;fill:none}.assistant-form-field{margin-bottom:18px}.assistant-form-field label{display:block;font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:8px;text-align:right}.assistant-form-field input,.assistant-form-field textarea{width:100%;padding:13px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:14.5px;background:var(--bg-input);color:var(--text-primary);font-family:inherit;box-sizing:border-box;outline:none;resize:none;font-weight:500}.assistant-form-field input:focus,.assistant-form-field textarea:focus{border-color:var(--primary-color);background:var(--bg-app)}.assistant-form-field textarea{min-height:110px;line-height:1.7}.assistant-form-hint{font-size:11.5px;color:var(--text-secondary);margin-top:6px;text-align:right}.assistant-color-picker{display:flex;gap:12px;flex-wrap:wrap}.assistant-color-dot{width:38px;height:38px;border-radius:50%;border:2px solid transparent;cursor:pointer;padding:0}.assistant-color-dot.selected{border-color:var(--text-primary);transform:scale(1.08)}.assistant-form-actions{display:flex;gap:10px;margin-top:22px}.assistant-form-actions button{flex:1;padding:13px;border-radius:14px;border:none;font-size:14.5px;font-weight:700;cursor:pointer;font-family:inherit}.assistant-form-actions .btn-cancel{background:var(--bg-hover);color:var(--text-primary)}.assistant-form-actions .btn-save{background:var(--primary-color);color:#fff}.assistant-form-actions .btn-save:disabled{opacity:0.6;cursor:not-allowed}.sp-input{width:100%;padding:14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background:var(--bg-app);color:var(--text-primary);font-family:inherit;box-sizing:border-box;outline:none;font-weight:500}.sp-input:focus{border-color:var(--primary-color)}.sp-input::placeholder{color:var(--placeholder-color)}.sp-input:disabled{opacity:0.55}.sp-select{width:100%;padding:14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background:var(--bg-app);color:var(--text-primary);font-family:inherit;box-sizing:border-box;outline:none;font-weight:500;cursor:pointer}.sp-field{margin-bottom:16px}.sp-field:last-child{margin-bottom:0}.sp-label{display:block;font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-align:right}.sp-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;border:none;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;width:100%;outline:none}.sp-btn-primary{background:var(--primary-color);color:#fff}.sp-btn-danger{background:rgba(211,47,47,0.08);color:#d32f2f}.sp-btn-row{display:flex;gap:10px}.sp-btn-row .sp-btn{flex:1}.sp-link-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;background:var(--bg-app);color:var(--text-primary);text-decoration:none;font-size:15px;font-weight:600;border:1.5px solid var(--border-color);text-align:center;width:100%;box-sizing:border-box}.sp-link-btn:hover{background:var(--bg-hover);border-color:var(--primary-color);color:var(--primary-color)}.sp-note{font-size:14.5px;color:var(--text-secondary);line-height:1.9}.sp-note b{color:var(--text-primary);font-weight:700;display:block;margin-bottom:6px;font-size:15px}.sp-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:14px;border:1px solid var(--border-color);overflow:hidden}.sp-list-item{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--border-color);font-size:15px}.sp-list-item:last-child{border-bottom:none}.sp-list-key{color:var(--text-secondary);font-weight:500}.sp-list-val{color:var(--text-primary);font-weight:700;text-align:left;max-width:60%;word-wrap:break-word}.sp-hero{display:flex;align-items:center;gap:14px;padding:16px;background:var(--bg-app);border-radius:16px;border:1px solid var(--border-color);margin-bottom:16px}.sp-hero-icon{width:46px;height:46px;border-radius:13px;background:var(--bg-hover);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--primary-color)}.sp-hero-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}.sp-hero-title{font-size:15.5px;font-weight:700;color:var(--text-primary);margin:0 0 3px}.sp-hero-sub{font-size:12.5px;color:var(--text-secondary);margin:0}
</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="icon-btn voice-off" id="voiceToggle" title="تشغيل/إيقاف الصوت"><svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg></button><button class="icon-btn" id="menuToggle" title="القائمة"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}{% if user_name %}<div class="user-badge" title="{{ session.get('user_email') }}"><svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{{ user_name }}</div>{% endif %}<a href="/logout" class="btn btn-outline">خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div>
<div class="dropdown" id="dropdown"><button class="item" data-action="new"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>محادثة جديدة</button><button class="item" onclick="window.location.href='/library'"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>مكتبتي</button><button class="item" data-action="share"><svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>مشاركة المحادثة</button><button class="item" onclick="openSettings()"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>الإعدادات</button><div class="section-title">مثبت</div><div id="pinnedList"><div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;font-weight:500;">لا توجد محادثات مثبتة</div></div><div class="section-title">المحادثات الأخيرة</div><div id="historyList"></div>{% if session.get('user_email') and not session.get('is_admin') %}<button class="item danger" onclick="deleteMyAccount()"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg>حذف حسابي</button>{% endif %}</div>
<div id="settingsModal" class="settings-overlay"><div class="settings-page"><div class="settings-header"><button class="icon-btn" onclick="closeSettings()"><svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></button><h2>الإعدادات</h2><div style="width:32px;"></div></div><div class="settings-body">
<div class="settings-card"><div class="settings-item" onclick="openSubPage('theme')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg><span>المظهر</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('color')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg><span>لون التمييز</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentColorLabel" style="font-size:14px;color:var(--text-secondary);">أزرق داكن</span><span id="currentColorDot" style="width:14px;height:14px;border-radius:50%;background:#4a6a8a;display:inline-block;"></span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div><div class="settings-item" onclick="openSubPage('fontSize')"><div class="item-right"><svg viewBox="0 0 24 24"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg><span>حجم الخط</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentFontSizeLabel" style="font-size:14px;color:var(--text-secondary);">متوسط</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div><div class="settings-item" onclick="openSubPage('personality')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg><span>شخصية المساعد</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentPersonalityLabel" style="font-size:14px;color:var(--text-secondary);">ودود</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div><div class="settings-item" onclick="openSubPage('language')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg><span>اللغة / Language</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentLangLabel" style="font-size:14px;color:var(--text-secondary);">العربية</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div></div>
<div class="settings-card"><div class="settings-item" onclick="openSubPage('general')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span>عام</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('memory')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/></svg><span>الذاكرة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('assistants')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg><span>مساعدي الخاص</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('voice')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg><span>الصوت</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('safety')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg><span>السلامة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('security')"><div class="item-right"><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg><span>الأمان وتسجيل الدخول</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('remote')"><div class="item-right"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg><span>التحكم عن بُعد</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
<div class="settings-card"><div class="settings-item" onclick="openSubPage('storage')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg><span>التخزين</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('privacy')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg><span>مركز الخصوصية</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('data')"><div class="item-right"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg><span>التحكم في البيانات</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('ads')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M3 11l18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg><span>التحكم في الإعلانات</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('report')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><span>الإبلاغ عن خطأ</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div><div class="settings-item" onclick="openSubPage('about')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg><span>حول</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
{% if session.get('user_email') and not session.get('is_admin') %}<div class="settings-card"><div class="settings-item" onclick="deleteMyAccount()"><div class="item-right"><svg viewBox="0 0 24 24" style="stroke:#d32f2f;"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg><span style="color:#d32f2f;">حذف حسابي</span></div></div></div>{% endif %}
<div class="settings-card" onclick="window.location.href='/logout'"><div class="settings-item" style="justify-content:center;"><div class="item-right" style="justify-content:center;width:100%;"><span style="color:#d32f2f;font-weight:bold;">تسجيل الخروج</span><svg viewBox="0 0 24 24" style="stroke:#d32f2f;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg></div></div></div>
</div></div></div>
<div id="subPage" class="sub-page" onclick="if(event.target===this)closeSubPage()"><div class="modal-box"><div class="modal-title" id="subPageTitle">إعدادات</div><div class="sub-page-body" id="subPageBody"></div><button class="modal-confirm" onclick="confirmSubPage()">تأكيد</button></div></div>
<div id="chat"></div>
<div class="assistant-bar" id="assistantBar"><button class="assistant-pill" id="assistantPill" type="button" onclick="toggleAssistantMenu(event)"><span class="a-dot" id="assistantPillDot" style="background:#4a6a8a">ن</span><span class="a-name" id="assistantPillName">نبراس</span><svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></button></div>
<div class="assistant-menu" id="assistantMenu"></div>
<div class="input-area" id="inputArea">
<div id="imagePreviewContainer"><div class="image-preview-wrapper"><img id="imagePreview" src="" alt=""/><button class="remove-img-btn" id="removeImageBtn" title="إزالة" aria-label="إزالة"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div></div>
<button class="btn-icon mic-btn" id="micBtn" title="صوت"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button>
<button class="plus-btn" id="plusBtn" title="إضافة"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
<div class="plus-options" id="plusOptions"><button class="option-btn" id="cameraBtn" title="كاميرا"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></button><button class="option-btn" id="galleryBtn" title="صور"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></button></div>
<textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea>
<button class="send" id="sendBtn" title="إرسال"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
</div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/></div>
<div class="share-modal" id="shareModal"><div class="box"><h3>مشاركة المحادثة</h3><div class="share-grid"><a class="share-btn whatsapp" id="shareWhatsapp" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413Z"/></svg><span>واتساب</span></a><a class="share-btn facebook" id="shareFacebook" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z"/></svg><span>فيسبوك</span></a><a class="share-btn twitter" id="shareTwitter" target="_blank" rel="noopener"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg><span>تويتر</span></a><button class="share-btn copy" id="shareCopy"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2.5" ry="2.5"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span>نسخ الرابط</span></button></div><button class="close-btn" onclick="document.getElementById('shareModal').classList.remove('show')">إغلاق</button></div></div>
<script>
(function(){try{var hash=window.location.hash||'';var search=window.location.search||'';if(hash.indexOf('type=recovery')!==-1&&hash.indexOf('access_token=')!==-1){window.location.replace('/reset-password'+hash);return;}if(search.indexOf('type=recovery')!==-1&&search.indexOf('code=')!==-1){window.location.replace('/reset-password'+search);return;}var params=new URLSearchParams(hash.replace(/^#/,''));var at=params.get('access_token');var codeP=new URLSearchParams(search).get('code');if(at||codeP){var rt=params.get('refresh_token')||'';try{history.replaceState(null,'',window.location.pathname);}catch(e){}var overlay=document.createElement('div');overlay.id='oauth-overlay';overlay.classList.add('show');overlay.innerHTML='<div class="oauth-spinner" id="oauth-spin"></div><div class="oauth-title" id="oauth-title">جاري تسجيل الدخول</div><div class="oauth-msg" id="oauth-msg">لحظة من فضلك...</div>';document.body.appendChild(overlay);function done(msg,isOk){var spin=document.getElementById('oauth-spin');var title=document.getElementById('oauth-title');var msgEl=document.getElementById('oauth-msg');if(spin)spin.style.display='none';if(title){title.textContent=isOk?'تم تسجيل الدخول':'تعذر تسجيل الدخول';title.classList.add(isOk?'ok':'err');}if(msgEl)msgEl.textContent=msg;setTimeout(function(){window.location.replace(isOk?'/':'/login');},isOk?700:2500);}fetch('/auth/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:at||'',refresh_token:rt,code:codeP||''})}).then(function(r){return r.json();}).then(function(d){if(d&&d.status==='ok'){done('جاري تحويلك...',true);}else{done((d&&d.message)||'فشل إنشاء الجلسة',false);}}).catch(function(){done('تعذر الاتصال بالسيرفر',false);});return;}}catch(e){}})();
(function(){const IS_REGISTERED={{ 'true' if is_registered else 'false' }};const SERVER_LANG='{{ user_lang }}';let userLang=SERVER_LANG||localStorage.getItem('nibras-lang')||'ar';try{localStorage.setItem('nibras-lang',userLang);}catch(e){}let isMale=(localStorage.getItem('nibras-voice-gender')||'male')==='male';let userPersonality=localStorage.getItem('nibras-personality')||'friendly';let userFontSize=localStorage.getItem('nibras-font-size')||'medium';let voiceSpeed=parseFloat(localStorage.getItem('nibras-voice-speed'))||1;let ch=[],pid=null,iw=!1,cid=null,voiceOn=false,stickBottom=true;const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),pl=document.getElementById('pinnedList'),sm=document.getElementById('shareModal'),vt=document.getElementById('voiceToggle');
const SVG_SPK_ON='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';const SVG_SPK_OFF='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';
let audioCtx=null;let allSources=[];let ca=null;let voiceSessionId=0;
function getAudioContext(){if(!audioCtx){audioCtx=new (window.AudioContext||window.webkitAudioContext)();}if(audioCtx.state==='suspended'){audioCtx.resume();}return audioCtx;}
function stopAllAudio(){allSources.forEach(function(src){try{src.stop(0);}catch(e){}});allSources=[];ca=null;voiceSessionId++;}
function playAudioWithSpeed(base64Audio,onEnd){try{stopAllAudio();const mySession=voiceSessionId;const ctx=getAudioContext();const binary=atob(base64Audio);const bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++){bytes[i]=binary.charCodeAt(i);}ctx.decodeAudioData(bytes.buffer,function(buffer){if(mySession!==voiceSessionId){if(typeof onEnd==='function')onEnd();return;}const source=ctx.createBufferSource();source.buffer=buffer;source.playbackRate.value=voiceSpeed;const gainNode=ctx.createGain();const savedLvl=localStorage.getItem('nibras-voice-level');gainNode.gain.value=savedLvl?savedLvl/100:1;source.connect(gainNode);gainNode.connect(ctx.destination);source.onended=function(){const idx=allSources.indexOf(source);if(idx>=0)allSources.splice(idx,1);if(typeof onEnd==='function')onEnd();};source.start(0);allSources.push(source);ca={pause:function(){try{source.stop(0);}catch(e){}},currentTime:0};},function(err){console.error('Audio decode error:',err);if(typeof onEnd==='function')onEnd();});}catch(e){console.error('Web Audio API error:',e);if(typeof onEnd==='function')onEnd();}}
function tr(key){const d={thinking:{ar:'جاري التفكير',en:'Thinking'},listening:{ar:'جاري الاستماع...',en:'Listening...'},inputPlaceholder:{ar:'اكتب رسالتك...',en:'Type your message...'},micUnsupported:{ar:'المتصفح لا يدعم التعرف على الصوت.',en:'Browser does not support voice recognition.'}};return (d[key]||{})[userLang]||(d[key]||{}).ar||key;}
function applyLang(){ui.placeholder=tr('inputPlaceholder');document.documentElement.lang=userLang==='en'?'en':'ar';const lbl=document.getElementById('currentLangLabel');if(lbl)lbl.textContent=userLang==='en'?'English':'العربية';}
function applyFontSize(size){document.documentElement.setAttribute('data-font',size);const map={small:'صغير',medium:'متوسط',large:'كبير',xlarge:'ضخم'};const lbl=document.getElementById('currentFontSizeLabel');if(lbl)lbl.textContent=map[size]||'متوسط';}
applyFontSize(userFontSize);
vt.addEventListener('click',function(){voiceOn=!voiceOn;if(voiceOn){vt.classList.remove('voice-off');vt.classList.add('voice-on');vt.innerHTML=SVG_SPK_ON;showToast(userLang==='en'?'Sound ON':'الصوت مفعّل');}else{vt.classList.remove('voice-on');vt.classList.add('voice-off');vt.innerHTML=SVG_SPK_OFF;stopAllAudio();showToast(userLang==='en'?'Sound OFF':'الصوت مغلق');}});
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
function getPinnedLocal(){try{return JSON.parse(localStorage.getItem('nibras_pinned')||'[]');}catch(e){return [];}}
function savePinnedLocal(arr){try{localStorage.setItem('nibras_pinned',JSON.stringify(arr));}catch(e){}}
async function togglePin(cid,wasPinned,btnEl){if(IS_REGISTERED){const url=wasPinned?'/unpin_conversation':'/pin_conversation';try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conv_id:cid})});if(r.ok){btnEl.classList.toggle('pinned',!wasPinned);showToast(wasPinned?'تم إلغاء التثبيت':'تم التثبيت');loadPinned();}}catch(e){showToast('فشل الاتصال');}}else{let arr=getPinnedLocal();if(wasPinned){arr=arr.filter(x=>x!==cid);showToast('تم إلغاء التثبيت');}else{if(!arr.includes(cid))arr.push(cid);showToast('تم التثبيت محلياً');}savePinnedLocal(arr);btnEl.classList.toggle('pinned',!wasPinned);loadPinned();}}
mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();loadPinned();}});
function openSettings(){document.getElementById('settingsModal').classList.add('show');document.getElementById('dropdown').classList.remove('show');}
function closeSettings(){document.getElementById('settingsModal').classList.remove('show');}
function setTheme(t){const h=document.documentElement;if(t==='dark'){h.classList.add('dark-mode');}else{h.classList.remove('dark-mode');}}
function getContrastColor(hex){try{const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);const lum=(0.299*r+0.587*g+0.114*b)/255;return lum>0.6?'#111111':'#ffffff';}catch(e){return '#111111';}}
function setAccentColor(color,name){const h=document.documentElement;h.style.setProperty('--primary-color',color);h.style.setProperty('--send-bg',color);h.style.setProperty('--primary-hover',color);h.style.setProperty('--icon-color',color);h.style.setProperty('--msg-user-bg',color);h.style.setProperty('--msg-user-text',getContrastColor(color));const lbl=document.getElementById('currentColorLabel');if(lbl)lbl.textContent=name;const dot=document.getElementById('currentColorDot');if(dot)dot.style.background=color;localStorage.setItem('nibras-accent',color);localStorage.setItem('nibras-accent-name',name);}
(function initTheme(){const mode=localStorage.getItem('nibras-theme-mode')||'system';if(mode==='system'){const prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;setTheme(prefersDark?'dark':'light');}else{setTheme(mode);}})();
const savedAccent=localStorage.getItem('nibras-accent');const savedAccentName=localStorage.getItem('nibras-accent-name');if(savedAccent){setAccentColor(savedAccent,savedAccentName||'مخصص');}
const subPagesContent={theme:'<div class="option-list"><div class="option-row" data-theme="system" onclick="selectTheme(\'system\')"><div class="option-label"><span>النظام (افتراضي)</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="option-row" data-theme="light" onclick="selectTheme(\'light\')"><div class="option-label"><span>فاتح</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="option-row" data-theme="dark" onclick="selectTheme(\'dark\')"><div class="option-label"><span>داكن</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div>',color:'<div class="color-grid"><div class="color-row" data-color="#4a6a8a" onclick="selectColor(\'#4a6a8a\',\'أزرق داكن\')"><div class="color-row-left"><div class="color-circle" style="background:#4a6a8a;"></div><span>أزرق داكن</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#1a1a1a" onclick="selectColor(\'#1a1a1a\',\'أسود\')"><div class="color-row-left"><div class="color-circle" style="background:#1a1a1a;"></div><span>أسود</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#10b981" onclick="selectColor(\'#10b981\',\'أخضر\')"><div class="color-row-left"><div class="color-circle" style="background:#10b981;"></div><span>أخضر</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#fbbf24" onclick="selectColor(\'#fbbf24\',\'أصفر\')"><div class="color-row-left"><div class="color-circle" style="background:#fbbf24;"></div><span>أصفر</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#ec4899" onclick="selectColor(\'#ec4899\',\'وردي\')"><div class="color-row-left"><div class="color-circle" style="background:#ec4899;"></div><span>وردي</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#f97316" onclick="selectColor(\'#f97316\',\'برتقالي\')"><div class="color-row-left"><div class="color-circle" style="background:#f97316;"></div><span>برتقالي</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#8b5cf6" onclick="selectColor(\'#8b5cf6\',\'أرجواني\')"><div class="color-row-left"><div class="color-circle" style="background:#8b5cf6;"></div><span>أرجواني</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',fontSize:'<div class="fontsize-list"><div class="fontsize-row" data-fs="small" onclick="selectFontSize(\'small\',\'صغير\')"><div class="fontsize-row-left"><div class="fontsize-label">صغير</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="medium" onclick="selectFontSize(\'medium\',\'متوسط\')"><div class="fontsize-row-left"><div class="fontsize-label">متوسط</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="large" onclick="selectFontSize(\'large\',\'كبير\')"><div class="fontsize-row-left"><div class="fontsize-label">كبير</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="xlarge" onclick="selectFontSize(\'xlarge\',\'ضخم\')"><div class="fontsize-row-left"><div class="fontsize-label">ضخم</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',personality:'<div class="personality-list"><div class="personality-row" data-p="friendly" onclick="selectPersonality(\'friendly\',\'ودود\')"><div class="personality-text"><div class="personality-name">ودود</div><div class="personality-sub">دافئ ومريح</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="concise" onclick="selectPersonality(\'concise\',\'مختصر\')"><div class="personality-text"><div class="personality-name">مختصر</div><div class="personality-sub">ردود قصيرة</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="detailed" onclick="selectPersonality(\'detailed\',\'مفصّل\')"><div class="personality-text"><div class="personality-name">مفصّل</div><div class="personality-sub">شرح عميق</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="formal" onclick="selectPersonality(\'formal\',\'رسمي\')"><div class="personality-text"><div class="personality-name">رسمي</div><div class="personality-sub">احترافي</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="teacher" onclick="selectPersonality(\'teacher\',\'معلّم\')"><div class="personality-text"><div class="personality-name">معلّم</div><div class="personality-sub">خطوة بخطوة</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="playful" onclick="selectPersonality(\'playful\',\'فرفوش\')"><div class="personality-text"><div class="personality-name">فرفوش</div><div class="personality-sub">مرح ومزح</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',language:'<div class="lang-list"><div class="lang-card" data-lang="ar" onclick="selectLanguage(\'ar\')"><div class="lang-flag" style="background:linear-gradient(135deg,#2d6a4f 0%,#40916c 100%);">ع</div><div class="lang-info"><div class="lang-name">العربية</div><div class="lang-sub">Arabic</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="lang-card" data-lang="en" onclick="selectLanguage(\'en\')"><div class="lang-flag" style="background:linear-gradient(135deg,#1e3a8a 0%,#3b82f6 100%);">EN</div><div class="lang-info"><div class="lang-name">English</div><div class="lang-sub">الإنجليزية</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',general:'<div class="sp-field"><label class="sp-label">الاسم الكامل</label><input type="text" id="sp-name" class="sp-input" value="{{ user_name or \'\' }}" placeholder="اكتب اسمك"></div>',memory:'<div id="memoryContent"><div class="sp-note" style="text-align:center;">جاري تحميل الذاكرة...</div></div>',assistants:'<div class="sp-note" style="text-align:center;">جاري التحميل...</div>',voice:'<div style="display:flex;flex-direction:column;gap:16px;"><div class="sp-label">جنس الصوت</div><div class="personality-list"><div class="personality-row" data-vg="male" onclick="selectVoiceGender(\'male\')"><div class="personality-text"><div class="personality-name">ذكر</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vg="female" onclick="selectVoiceGender(\'female\')"><div class="personality-text"><div class="personality-name">أنثى</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="sp-label" style="margin-top:10px;">سرعة الصوت</div><div class="personality-list"><div class="personality-row" data-vs="0.75" onclick="selectVoiceSpeed(0.75)"><div class="personality-text"><div class="personality-name">بطيء</div><div class="personality-sub">0.75×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1" onclick="selectVoiceSpeed(1)"><div class="personality-text"><div class="personality-name">عادي</div><div class="personality-sub">1×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1.25" onclick="selectVoiceSpeed(1.25)"><div class="personality-text"><div class="personality-name">سريع</div><div class="personality-sub">1.25×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1.5" onclick="selectVoiceSpeed(1.5)"><div class="personality-text"><div class="personality-name">سريع جداً</div><div class="personality-sub">1.5×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="sp-label" style="margin-top:10px;">مستوى الصوت</div><div class="personality-list"><div class="personality-row" data-vl="25" onclick="selectVoiceLevel(25)"><div class="personality-text"><div class="personality-name">هادئ</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="50" onclick="selectVoiceLevel(50)"><div class="personality-text"><div class="personality-name">متوسط</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="75" onclick="selectVoiceLevel(75)"><div class="personality-text"><div class="personality-name">عالي</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="100" onclick="selectVoiceLevel(100)"><div class="personality-text"><div class="personality-name">كامل</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div>',safety:'<div class="sp-note"><b>إرشادات السلامة</b>لا تشارك معلوماتك الحساسة.<br>نبراس مساعد ذكي وليس بديلاً عن المتخصصين.<br>أبلغ عن أي محتوى غير لائق.</div>',security:'<div class="sp-field"><label class="sp-label">البريد الإلكتروني</label><input type="email" class="sp-input" value="{{ session.get(\'user_email\',\'\') }}" disabled></div><div class="sp-field"><label class="sp-label">كلمة المرور الحالية</label><input type="password" id="sp-old-pass" class="sp-input" placeholder="••••••••"></div><div class="sp-field"><label class="sp-label">كلمة المرور الجديدة</label><input type="password" id="sp-new-pass" class="sp-input" placeholder="••••••••"></div>',remote:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></div><div><div class="sp-hero-title">إدارة الجلسات</div><div class="sp-hero-sub">تحكم بالأجهزة المتصلة</div></div></div><div class="sp-list"><div class="sp-list-item"><span class="sp-list-key">هذا الجهاز</span><span class="sp-list-val" style="color:var(--primary-color);font-size:13px;">نشط الآن</span></div></div><div style="margin-top:16px;"><button class="sp-btn sp-btn-danger" onclick="logoutAll()">تسجيل الخروج من كل الأجهزة</button></div>',storage:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></div><div><div class="sp-hero-title">التخزين</div><div class="sp-hero-sub">إحصائيات البيانات</div></div></div><div class="sp-list"><div class="sp-list-item"><span class="sp-list-key">المحادثات</span><span class="sp-list-val" id="sp-conv-count">0</span></div><div class="sp-list-item"><span class="sp-list-key">الصور</span><span class="sp-list-val" id="sp-img-count">0</span></div></div><div style="margin-top:16px;"><button class="sp-btn sp-btn-danger" onclick="clearCache()">مسح الكاش</button></div>',privacy:'<div class="sp-note"><b>سياسة الخصوصية</b>نحتفظ بمحادثاتك لتقديم خدمة أفضل.<br>لا نشارك بياناتك مع أطراف ثالثة.<br>يمكنك حذف بياناتك في أي وقت.</div><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="sp-link-btn" style="margin-top:16px;">قراءة السياسة كاملة</a>',data:'<div class="sp-note">يمكنك تصدير جميع بياناتك أو حذفها نهائياً.</div><div class="sp-btn-row" style="margin-top:16px;"><button class="sp-btn sp-btn-primary" onclick="exportData()">تصدير</button><button class="sp-btn sp-btn-danger" onclick="deleteMyAccount()">حذف</button></div>',ads:'<div class="sp-field"><label class="sp-label">تخصيص الإعلانات</label><select id="sp-ads" class="sp-select"><option value="personalized">مخصصة</option><option value="non-personalized">غير مخصصة</option></select></div>',report:'<div class="sp-field"><label class="sp-label">نوع المشكلة</label><select id="sp-report-type" class="sp-select"><option>خطأ تقني</option><option>محتوى غير لائق</option><option>اقتراح</option><option>أخرى</option></select></div><div class="sp-field"><label class="sp-label">الوصف</label><input type="text" id="sp-report-desc" class="sp-input" placeholder="اشرح المشكلة..."></div>',about:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></div><div><div class="sp-hero-title">نبراس GP</div><div class="sp-hero-sub">الإصدار 1.0 · مساعد ذكي شخصي</div></div></div><div class="sp-note">مساعد شخصي باللهجة العربية العامية.<br><br>© 2026 جميع الحقوق محفوظة.</div><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" class="sp-link-btn" style="margin-top:16px;">شروط الاستخدام</a><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="sp-link-btn" style="margin-top:10px;">سياسة الخصوصية</a>'};
let currentSubKey=null;
function openSubPage(key){currentSubKey=key;const titleMap={general:'عام',voice:'الصوت',safety:'السلامة',security:'الأمان وتسجيل الدخول',remote:'التحكم عن بُعد',storage:'التخزين',privacy:'مركز الخصوصية',data:'التحكم في البيانات',ads:'التحكم في الإعلانات',report:'الإبلاغ عن خطأ',about:'حول',theme:'المظهر',color:'لون التمييز',language:'اللغة / Language',personality:'شخصية المساعد',fontSize:'حجم الخط',memory:'الذاكرة',assistants:'مساعدي الخاص'};document.getElementById('subPageTitle').textContent=titleMap[key]||'إعدادات';document.getElementById('subPageBody').innerHTML=subPagesContent[key]||'<div class="sp-note">قريباً</div>';document.getElementById('subPage').classList.add('show');setTimeout(function(){if(key==='theme'){const t=localStorage.getItem('nibras-theme-mode')||'system';markSelectedTheme(t);}if(key==='color'){const c=localStorage.getItem('nibras-accent')||'#4a6a8a';markSelectedColor(c);}if(key==='fontSize'){document.querySelectorAll('.fontsize-row').forEach(function(el){el.classList.toggle('selected',el.dataset.fs===userFontSize);});}if(key==='personality'){document.querySelectorAll('.personality-row').forEach(function(el){el.classList.toggle('selected',el.dataset.p===userPersonality);});}if(key==='language'){document.querySelectorAll('.lang-card').forEach(function(el){el.classList.toggle('selected',el.dataset.lang===userLang);});}if(key==='voice'){markVoiceSelections();}if(key==='memory'){loadMemory();}if(key==='assistants'){loadAssistants().then(loadAssistantsPage);}if(key==='storage'){loadStorageInfo();}},60);}
function closeSubPage(){document.getElementById('subPage').classList.remove('show');currentSubKey=null;}
function confirmSubPage(){if(currentSubKey==='voice'){saveVoice();}else if(currentSubKey==='general'){saveGeneral();}else if(currentSubKey==='security'){changePassword();}else if(currentSubKey==='ads'){saveAds();}else{closeSubPage();}}
function selectVoiceGender(g){isMale=(g==='male');document.querySelectorAll('[data-vg]').forEach(function(el){el.classList.toggle('selected',el.dataset.vg===g);});}
function selectVoiceSpeed(s){voiceSpeed=parseFloat(s);document.querySelectorAll('[data-vs]').forEach(function(el){el.classList.toggle('selected',parseFloat(el.dataset.vs)===voiceSpeed);});}
function selectVoiceLevel(l){document.querySelectorAll('[data-vl]').forEach(function(el){el.classList.toggle('selected',parseInt(el.dataset.vl)===parseInt(l));});}
function markVoiceSelections(){var g=isMale?'male':'female';document.querySelectorAll('[data-vg]').forEach(function(el){el.classList.toggle('selected',el.dataset.vg===g);});var s=voiceSpeed||1;document.querySelectorAll('[data-vs]').forEach(function(el){el.classList.toggle('selected',parseFloat(el.dataset.vs)===s);});var l=parseInt(localStorage.getItem('nibras-voice-level')||'100');document.querySelectorAll('[data-vl]').forEach(function(el){el.classList.toggle('selected',parseInt(el.dataset.vl)===l);});}
function selectLanguage(lang){userLang=lang;try{localStorage.setItem('nibras-lang',userLang);}catch(e){}applyLang();fetch('/update_language',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lang:userLang})}).catch(()=>{});document.querySelectorAll('.lang-card').forEach(c=>{c.classList.toggle('selected',c.dataset.lang===userLang);});const lbl=document.getElementById('currentLangLabel');if(lbl)lbl.textContent=userLang==='en'?'English':'العربية';}
function selectPersonality(p,name){userPersonality=p;try{localStorage.setItem('nibras-personality',p);}catch(e){}document.querySelectorAll('.personality-row').forEach(c=>{c.classList.toggle('selected',c.dataset.p===p);});const lbl=document.getElementById('currentPersonalityLabel');if(lbl)lbl.textContent=name;fetch('/update_personality',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({personality:p})}).catch(()=>{});}
function selectFontSize(size,name){userFontSize=size;try{localStorage.setItem('nibras-font-size',size);}catch(e){}applyFontSize(size);document.querySelectorAll('.fontsize-row').forEach(c=>{c.classList.toggle('selected',c.dataset.fs===size);});}
function selectTheme(t){if(t==='system'){const prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;setTheme(prefersDark?'dark':'light');}else{setTheme(t);}localStorage.setItem('nibras-theme-mode',t);markSelectedTheme(t);}
function markSelectedTheme(t){document.querySelectorAll('.option-row').forEach(el=>{if(el.dataset.theme===t)el.classList.add('selected');else el.classList.remove('selected');});}
function selectColor(color,name){setAccentColor(color,name);markSelectedColor(color);}
function markSelectedColor(color){document.querySelectorAll('.color-row').forEach(el=>{if(el.dataset.color===color)el.classList.add('selected');else el.classList.remove('selected');});}
async function loadMemory(){const c=document.getElementById('memoryContent');if(!c)return;if(!IS_REGISTERED){c.innerHTML='<div class="memory-card"><div class="memory-header"><span>الذاكرة</span></div><div class="memory-empty">أنت تستخدم التطبيق كضيف.<br>سجّل دخولك لحفظ ذاكرتك بشكل دائم.</div></div>';return;}try{const r=await fetch('/get_memory');const d=await r.json();const items=[];if(d.name)items.push({k:'الاسم',v:d.name});if(d.lang)items.push({k:'اللغة',v:d.lang==='en'?'English':'العربية'});if(d.personality){const pMap={friendly:'ودود',concise:'مختصر',detailed:'مفصّل',formal:'رسمي',teacher:'معلّم',playful:'فرفوش'};items.push({k:'شخصية المساعد',v:pMap[d.personality]||d.personality});}if(d.email)items.push({k:'البريد الإلكتروني',v:d.email});let html='<div class="memory-card"><div class="memory-header"><span>الذاكرة</span></div>';if(items.length===0){html+='<div class="memory-empty">لا توجد معلومات محفوظة بعد.</div>';}else{items.forEach(i=>{html+='<div class="memory-item"><span class="memory-key">'+i.k+'</span><span class="memory-val">'+escapeHtml(i.v)+'</span></div>';});}html+='</div>';html+='<div class="memory-note">نبراس يستخدم هذي المعلومات لتخصيص ردوده.</div>';c.innerHTML=html;}catch(e){c.innerHTML='<div class="sp-note" style="text-align:center;">تعذر تحميل الذاكرة.</div>';}}
async function loadStorageInfo(){try{const r1=await fetch('/history');const d1=await r1.json();document.getElementById('sp-conv-count').textContent=(d1.conversations||[]).length;const r2=await fetch('/library/images');const d2=await r2.json();document.getElementById('sp-img-count').textContent=(d2.images||[]).length;}catch(e){}}
function saveGeneral(){const n=(document.getElementById('sp-name').value||'').trim();if(!n||n.length<2){showToast('اكتب اسم صحيح');return;}if(!IS_REGISTERED){showToast('سجّل دخولك أولاً');return;}fetch('/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,lang:userLang})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('تم الحفظ');closeSubPage();setTimeout(()=>location.reload(),500);}else{showToast(d.message||'فشل الحفظ');}}).catch(()=>showToast('تعذر الاتصال'));}
function saveVoice(){var lvlEl=document.querySelector('[data-vl].selected');var lvl=lvlEl?lvlEl.dataset.vl:'100';var gender=isMale?'male':'female';var speedEl=document.querySelector('[data-vs].selected');var speed=speedEl?parseFloat(speedEl.dataset.vs):1;voiceSpeed=speed;localStorage.setItem('nibras-voice-level',lvl);localStorage.setItem('nibras-voice-gender',gender);localStorage.setItem('nibras-voice-speed',speed);fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:gender})}).then(function(){showToast('تم حفظ الإعدادات');closeSubPage();}).catch(function(){showToast('تم الحفظ محلياً');closeSubPage();});}
function changePassword(){const o=document.getElementById('sp-old-pass').value;const n=document.getElementById('sp-new-pass').value;if(!o){showToast('اكتب كلمة المرور الحالية');return;}if(!n||n.length<8){showToast('كلمة المرور الجديدة 8 أحرف على الأقل');return;}fetch('/change_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:o,new_password:n})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('تم تغيير كلمة المرور');document.getElementById('sp-old-pass').value='';document.getElementById('sp-new-pass').value='';closeSubPage();}else{showToast(d.message||'فشل');}}).catch(()=>showToast('تعذر الاتصال'));}
function logoutAll(){if(confirm('خروج من كل الأجهزة؟')){fetch('/logout_all',{method:'POST'}).then(()=>window.location.href='/logout');}}
function clearCache(){if(!confirm('مسح الإعدادات المحلية؟'))return;localStorage.clear();sessionStorage.clear();document.documentElement.classList.remove('dark-mode');showToast('تم المسح');setTimeout(()=>location.reload(),900);}
function exportData(){window.location.href='/export_data';}
function saveAds(){showToast('تم حفظ التفضيلات');closeSubPage();}
function sendReport(){const d=document.getElementById('sp-report-desc').value;if(!d||d.trim().length<3){showToast('اكتب وصف');return;}fetch('/report_bug',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:document.getElementById('sp-report-type').value,description:d})}).then(r=>r.json()).then(res=>{if(res.status==='ok'){showToast('تم الإرسال');setTimeout(()=>closeSubPage(),800);}});}
async function loadPinned(){try{let pinned=[];if(IS_REGISTERED){const r=await fetch('/pinned_conversations');const d=await r.json();pinned=d.pinned||[];}else{const ids=getPinnedLocal();if(ids.length){const hr=await fetch('/history');const hd=await hr.json();pinned=(hd.conversations||[]).filter(c=>ids.includes(c.id));}}pl.innerHTML='';if(!pinned||pinned.length===0){pl.innerHTML='<div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;">لا توجد محادثات مثبتة</div>';return;}pinned.forEach(c=>{const btn=document.createElement('button');btn.className='conv-item pinned-item';btn.innerHTML='<span class="conv-title">'+c.title+'</span>';btn.onclick=()=>loadConversation(c.id);pl.appendChild(btn);});}catch(e){}}
async function loadHistory(){try{const r=await fetch('/history');const d=await r.json();hl.innerHTML='';const localPinned=getPinnedLocal();if(d.conversations&&d.conversations.length>0){d.conversations.forEach(c=>{const isPinned=IS_REGISTERED?c.pinned:localPinned.includes(c.id);const b=document.createElement('div');b.className='conv-item';b.style.cursor='pointer';b.innerHTML='<span class="conv-title">'+((c.title&&c.title.trim())?c.title:'محادثة')+'</span><button class="pin-btn '+(isPinned?'pinned':'')+'"><svg viewBox="0 0 24 24"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg></button>';b.onclick=(e)=>{if(e.target.closest('.pin-btn'))return;loadConversation(c.id);};b.querySelector('.pin-btn').onclick=async(e)=>{e.stopPropagation();await togglePin(c.id,isPinned,e.currentTarget);};hl.appendChild(b);});}else{const e=document.createElement('div');e.className='item';e.style.color='var(--text-secondary)';e.style.fontSize='13px';e.style.justifyContent='center';e.textContent='لا توجد محادثات';hl.appendChild(e);}}catch(e){}}
async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;d.messages.slice(-50).forEach(function(m){const s=m.role==='user'?'user':'bot';addMessage(m.content,s,!0)});dd.classList.remove('show')}}catch(e){}}
document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.classList.remove('show');ui.value=''});
document.querySelector('[data-action="share"]').addEventListener('click',function(e){e.stopPropagation();dd.classList.remove('show');const msgs=ch.slice(-20).map(function(m){return{r:m.role==='user'?'u':'b',c:String(m.content||'').slice(0,500)};}).filter(function(m){return m.c;});if(!msgs||msgs.length===0){showToast('لا توجد محادثة لمشاركتها');return;}const text='شوف محادثتي مع نبراس';if(IS_REGISTERED&&cid&&!String(cid).startsWith('guest_conv_')){const dbUrl=window.location.origin+'/share/'+cid;document.getElementById('shareWhatsapp').href='https://wa.me/?text='+encodeURIComponent(text+'\n'+dbUrl);document.getElementById('shareFacebook').href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(dbUrl);document.getElementById('shareTwitter').href='https://twitter.com/intent/tweet?url='+encodeURIComponent(dbUrl)+'&text='+encodeURIComponent(text);document.getElementById('shareCopy').onclick=function(){navigator.clipboard.writeText(dbUrl).then(function(){showToast('تم نسخ الرابط');}).catch(function(){showToast('فشل النسخ');});};sm.classList.add('show');}else{let url='';try{const json=JSON.stringify(msgs);const encoded=btoa(unescape(encodeURIComponent(json)));url=window.location.origin+'/share/view#d='+encodeURIComponent(encoded);}catch(err){showToast('تعذر تجهيز الرابط');return;}if(url.length>60000){showToast('المحادثة طويلة جداً');return;}if(navigator.share){navigator.share({title:'محادثة نبراس',text:text,url:url}).catch(function(){});}else{navigator.clipboard.writeText(url).then(function(){showToast('تم نسخ الرابط');}).catch(function(){showToast('فشل النسخ');});}}});
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function scrollMsgToTop(el){if(!el)return;requestAnimationFrame(function(){const r=el.getBoundingClientRect();const c=cb.getBoundingClientRect();cb.scrollTop=cb.scrollTop+(r.top-c.top)-8;});}
function isNearBottom(){return cb.scrollHeight-cb.scrollTop-cb.clientHeight<10;}
cb.addEventListener('scroll',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('touchmove',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('wheel',function(){stickBottom=isNearBottom();},{passive:true});
function attachBotActions(el,msgText){if(!el||el.querySelector('.msg-actions'))return;const actions=document.createElement('div');actions.className='msg-actions';actions.innerHTML='<button class="act-like" title="إعجاب"><svg viewBox="0 0 24 24"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg></button><button class="act-dislike" title="عدم إعجاب"><svg viewBox="0 0 24 24"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg></button><button class="act-copy" title="نسخ"><svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2.5" ry="2.5"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg></button><button class="act-speak" title="استماع"><svg viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg></button>';el.appendChild(actions);const likeBtn=actions.querySelector('.act-like');const dislikeBtn=actions.querySelector('.act-dislike');const copyBtn=actions.querySelector('.act-copy');const speakBtn=actions.querySelector('.act-speak');likeBtn.addEventListener('click',function(){const wasLiked=this.classList.contains('liked');this.classList.toggle('liked',!wasLiked);dislikeBtn.classList.remove('disliked');actions.classList.add('touched');fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasLiked?'unlike':'like',message:msgText,conv_id:cid})}).catch(function(){});showToast(wasLiked?'تم إلغاء الإعجاب':'شكراً لتقييمك');});dislikeBtn.addEventListener('click',function(){const wasDisliked=this.classList.contains('disliked');this.classList.toggle('disliked',!wasDisliked);likeBtn.classList.remove('liked');actions.classList.add('touched');fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasDisliked?'undislike':'dislike',message:msgText,conv_id:cid})}).catch(function(){});showToast(wasDisliked?'تم إلغاء التقييم':'رأيك مهم');});copyBtn.addEventListener('click',function(){navigator.clipboard.writeText(msgText).then(()=>{this.classList.add('copied');showToast('تم النسخ');const b=this;setTimeout(()=>b.classList.remove('copied'),1500);}).catch(()=>showToast('فشل النسخ'));});speakBtn.addEventListener('click',function(){const btn=this;if(btn.classList.contains('speaking')){stopAllAudio();document.querySelectorAll('.act-speak.speaking').forEach(function(b){b.classList.remove('speaking');});return;}stopAllAudio();document.querySelectorAll('.act-speak.speaking').forEach(function(b){b.classList.remove('speaking');});btn.classList.add('speaking');fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:msgText})}).then(r=>r.json()).then(v=>{if(v&&v.audio){playAudioWithSpeed(v.audio,function(){btn.classList.remove('speaking');});}else{btn.classList.remove('speaking');showToast('فشل التشغيل');}}).catch(function(){btn.classList.remove('speaking');showToast('فشل الاتصال');});});}
function renderInline(s){var placeholders=[];s=s.replace(/`([^`\n]+)`/g,function(m,c){var i=placeholders.length;placeholders.push('<code class="inline-code">'+escapeHtml(c)+'</code>');return '\u0000INLINE'+i+'\u0000';});s=escapeHtml(s);s=s.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');s=s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,'$1<em>$2</em>');s=s.replace(/~~([^~\n]+)~~/g,'<del>$1</del>');s=s.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g,'<a href="$2" target="_blank" rel="noopener" class="md-link">$1</a>');s=s.replace(/(^|[\s])(https?:\/\/[^\s<]+)/g,'$1<a href="$2" target="_blank" rel="noopener" class="md-link">$2</a>');s=s.replace(/\u0000INLINE(\d+)\u0000/g,function(m,i){return placeholders[+i];});return s;}
function parseMarkdown(text){var lines=text.split('\n');var html='';var inCode=false,codeLang='',codeContent=[];var inList=false,listType='ul',listItems=[];var inTable=false,tableRows=[];var i=0;
function flushList(){if(listItems.length===0)return;var tag=listType==='ol'?'ol':'ul';var cls=listType==='ol'?'md-ol':'md-list';html+='<'+tag+' class="'+cls+'">';listItems.forEach(function(item){html+='<li>'+renderInline(item)+'</li>';});html+='</'+tag+'>';listItems=[];inList=false;}
function flushTable(){if(tableRows.length===0)return;html+='<div class="md-table-wrap"><table class="md-table">';tableRows.forEach(function(row,ri){var cells=row.split('|').map(function(c){return c.trim();});if(cells[0]==='')cells.shift();if(cells[cells.length-1]==='')cells.pop();if(ri===1&&cells.every(function(c){return /^[-: ]+$/.test(c);}))return;var tag=ri===0?'th':'td';html+='<tr>';cells.forEach(function(c){html+='<'+tag+'>'+renderInline(c)+'</'+tag+'>';});html+='</tr>';});html+='</table></div>';tableRows=[];inTable=false;}
for(i=0;i<lines.length;i++){var line=lines[i];var fenceMatch=line.match(/^\s*```(\w*)\s*$/);if(fenceMatch){if(inCode){var codeStr=codeContent.join('\n');var idx=codeIndex++;var ci='<svg class="copy-icon-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';var chk='<svg class="copy-icon-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';html+='<div class="code-block"><div class="code-header"><span class="code-lang">'+escapeHtml(codeLang||'code')+'</span><button class="code-copy" onclick="copyCodeBlock(this,'+idx+')" type="button">'+ci+chk+'<span class="copy-label">Copy</span></button></div><pre><code>'+escapeHtml(codeStr)+'</code></pre></div>';window.__codeStore=window.__codeStore||{};window.__codeStore[idx]=codeStr;inCode=false;codeContent=[];codeLang='';}else{flushList();flushTable();inCode=true;codeLang=fenceMatch[1]||'';codeContent=[];}continue;}
if(inCode){codeContent.push(line);continue;}
var isTableLine=/^\s*\|.*\|\s*$/.test(line);if(isTableLine){flushList();inTable=true;tableRows.push(line.trim());continue;}else if(inTable){flushTable();}
if(line.trim()===''){flushList();continue;}
var h=line.match(/^(#{1,6})\s+(.+)$/);if(h){flushList();var level=h[1].length;html+='<div class="md-h'+level+'">'+renderInline(h[2].trim())+'</div>';continue;}
if(/^\s*(---|\*\*\*|___)\s*$/.test(line)){flushList();html+='<hr class="md-hr"/>';continue;}
var bq=line.match(/^\s*>\s?(.*)$/);if(bq){flushList();html+='<div class="md-blockquote">'+renderInline(bq[1])+'</div>';continue;}
var ul=line.match(/^\s*[-*+]\s+(.+)$/);if(ul){if(inList&&listType!=='ul')flushList();inList=true;listType='ul';listItems.push(ul[1].trim());continue;}
var ol=line.match(/^\s*\d+[.)]\s+(.+)$/);if(ol){if(inList&&listType!=='ol')flushList();inList=true;listType='ol';listItems.push(ol[1].trim());continue;}
flushList();html+=renderInline(line.trim());var nextLine=lines[i+1];if(nextLine!==undefined&&nextLine.trim()!==''&&!/^(#{1,6})\s|^\s*[-*+]\s|^\s*\d+[.)]\s|^\s*>|^\s*```|^\s*\|/.test(nextLine)&&!/^\s*(---|\*\*\*|___)\s*$/.test(nextLine)){html+='<br>';}}
flushList();flushTable();return html;}
var codeIndex=0;
function formatBotText(t){if(!t)return '';var parts=[];var regex=/```(\w*)\n?([\s\S]*?)```/g;var lastIndex=0;var m;codeIndex=0;while((m=regex.exec(t))!==null){if(m.index>lastIndex){parts.push({type:'text',content:t.slice(lastIndex,m.index)});}parts.push({type:'code',lang:(m[1]||'code').toLowerCase(),content:m[2].replace(/\n$/,'')});lastIndex=regex.lastIndex;}if(lastIndex<t.length){parts.push({type:'text',content:t.slice(lastIndex)});}if(parts.length===0)parts.push({type:'text',content:t});var html='';var ci2=0;parts.forEach(function(p){if(p.type==='code'){var idx=ci2++;var ci='<svg class="copy-icon-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>';var chk='<svg class="copy-icon-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';html+='<div class="code-block"><div class="code-header"><span class="code-lang">'+escapeHtml(p.lang)+'</span><button class="code-copy" onclick="copyCodeBlock(this,'+idx+')" type="button">'+ci+chk+'<span class="copy-label">Copy</span></button></div><pre><code>'+escapeHtml(p.content)+'</code></pre></div>';window.__codeStore=window.__codeStore||{};window.__codeStore[idx]=p.content;}else{html+=parseMarkdown(p.content);}});return html;}
function copyCodeBlock(btn,idx){var code=window.__codeStore&&window.__codeStore[idx]?window.__codeStore[idx]:'';if(!code)return;var done=function(){btn.classList.add('copied');var lbl=btn.querySelector('.copy-label');if(lbl){lbl.textContent='Copied';setTimeout(function(){lbl.textContent='Copy';btn.classList.remove('copied');},1500);}};var fallback=function(){var ta=document.createElement('textarea');ta.value=code;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();try{document.execCommand('copy');done();}catch(e){}document.body.removeChild(ta);};if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(code).then(done).catch(fallback);}else{fallback();}}
window.copyCodeBlock=copyCodeBlock;
function addMessage(t,s,isSys,img,imageUrl){s=s||'bot';isSys=isSys||false;const el=document.createElement('div');el.className='msg '+s;if(img){el.innerHTML='<img src="'+escapeHtml(img)+'" class="image-upload" />';cb.appendChild(el);if(stickBottom)cb.scrollTop=cb.scrollHeight;return el}let content=formatBotText(t);if(imageUrl){const safeUrl=escapeHtml(imageUrl);content+='<br><img src="'+safeUrl+'" class="generated-image" />';}el.innerHTML=content;if(s==='bot'&&!isSys){attachBotActions(el,t);}cb.appendChild(el);if(stickBottom)cb.scrollTop=cb.scrollHeight;return el;}
function showImagePreview(d){ip.src=d;ipc.classList.add('show');}
function clearPending(){pid=null;ipc.classList.remove('show');ip.src='';}
rib.addEventListener('click',clearPending);
ui.addEventListener('input',function(){this.style.height='auto';const maxH=150;this.style.height=Math.min(this.scrollHeight,maxH)+'px';this.style.overflowY=this.scrollHeight>maxH?'auto':'hidden';const ums=cb.querySelectorAll('.msg.user');if(ums.length)scrollMsgToTop(ums[ums.length-1]);});
let poOpen=false;
pb.addEventListener('click',function(){poOpen=!poOpen;po.classList.toggle('show',poOpen);this.classList.toggle('rotate',poOpen)});
document.addEventListener('click',function(e){if(!pb.contains(e.target)&&!po.contains(e.target)){po.classList.remove('show');poOpen=false;pb.classList.remove('rotate')}});
gb.addEventListener('click',function(){fi.click();po.classList.remove('show')});
fi.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];fi.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
cab.addEventListener('click',function(){ci.click();po.classList.remove('show')});
ci.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];ci.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
let myAssistants=[];let currentAssistantId=null;let currentAssistantData={name:'نبراس',color:'#4a6a8a'};let editingAssistantId=null;let selectedAsstColor='#4a6a8a';
async function loadAssistants(){if(!IS_REGISTERED)return;try{const r=await fetch('/my_assistants');const d=await r.json();myAssistants=d.assistants||[];renderAssistantMenu();const saved=localStorage.getItem('nibras_assistant_id');if(saved){const id=parseInt(saved);const found=myAssistants.find(a=>a.id===id);if(found){selectAssistant(id,false);}else{selectAssistant(null,false);}}else{selectAssistant(null,false);}}catch(e){console.error(e);}}
function toggleAssistantMenu(e){if(e)e.stopPropagation();const menu=document.getElementById('assistantMenu');if(menu.classList.contains('show')){menu.classList.remove('show');return;}renderAssistantMenu();const pill=document.getElementById('assistantPill');const rect=pill.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-260))+'px';menu.style.bottom=(window.innerHeight-rect.top+6)+'px';menu.classList.add('show');}
function renderAssistantMenu(){const menu=document.getElementById('assistantMenu');if(!menu)return;let html='';const isDefault=currentAssistantId===null;html+='<button class="assistant-menu-item'+(isDefault?' selected':'')+'" onclick="selectAssistant(null)"><span class="a-dot" style="background:#4a6a8a">ن</span><span class="a-name">نبراس</span><svg class="a-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></button>';if(myAssistants.length>0){html+='<div class="assistant-menu-sep"></div>';myAssistants.forEach(a=>{const sel=currentAssistantId===a.id;html+='<button class="assistant-menu-item'+(sel?' selected':'')+'" onclick="selectAssistant('+a.id+')"><span class="a-dot" style="background:'+a.color+'">'+escapeHtml(a.name.charAt(0))+'</span><span class="a-name">'+escapeHtml(a.name)+'</span><svg class="a-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></button>';});}html+='<div class="assistant-menu-sep"></div>';html+='<button class="assistant-menu-add" onclick="openNewAssistantForm()"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>إضافة مساعد جديد</button>';menu.innerHTML=html;}
function selectAssistant(id,closeMenu){currentAssistantId=id;if(id===null){currentAssistantData={name:'نبراس',color:'#4a6a8a'};localStorage.removeItem('nibras_assistant_id');}else{const a=myAssistants.find(x=>x.id===id);if(a){currentAssistantData={name:a.name,color:a.color};localStorage.setItem('nibras_assistant_id',String(id));}}const dot=document.getElementById('assistantPillDot');const name=document.getElementById('assistantPillName');if(dot){dot.style.background=currentAssistantData.color;dot.textContent=currentAssistantData.name.charAt(0);}if(name){name.textContent=currentAssistantData.name;}if(closeMenu!==false){document.getElementById('assistantMenu').classList.remove('show');}}
function openNewAssistantForm(){document.getElementById('assistantMenu').classList.remove('show');closeSettings();openAssistantForm(null);}
function openAssistantForm(id){editingAssistantId=id;const a=id?myAssistants.find(x=>x.id===id):null;selectedAsstColor=a?a.color:'#4a6a8a';const colors=['#4a6a8a','#1a1a1a','#10b981','#fbbf24','#ec4899','#f97316','#8b5cf6','#ef4444'];const colorDots=colors.map(c=>'<button type="button" class="assistant-color-dot'+(c===selectedAsstColor?' selected':'')+'" data-color="'+c+'" style="background:'+c+'" onclick="pickAssistantColor(\''+c+'\')"></button>').join('');const body=document.getElementById('subPageBody');document.getElementById('subPageTitle').textContent=id?'تعديل المساعد':'مساعد جديد';body.innerHTML='<div class="assistant-form-field"><label>اسم المساعد</label><input type="text" id="asst-name" placeholder="مثلاً: أستاذ الرياضيات" maxlength="40" value="'+(a?escapeHtml(a.name):'')+'"></div><div class="assistant-form-field"><label>وصف المساعد</label><textarea id="asst-persona" placeholder="اكتب كيف تريد المساعد يتصرف..." maxlength="1000">'+(a?escapeHtml(a.persona):'')+'</textarea></div><div class="assistant-form-field"><label>اللون</label><div class="assistant-color-picker">'+colorDots+'</div></div><div class="assistant-form-actions"><button type="button" class="btn-cancel" onclick="loadAssistantsPage()">إلغاء</button><button type="button" class="btn-save" id="asst-save-btn" onclick="saveAssistant()">حفظ</button></div>';document.getElementById('subPage').classList.add('show');currentSubKey=null;setTimeout(()=>{const inp=document.getElementById('asst-name');if(inp)inp.focus();},100);}
function pickAssistantColor(c){selectedAsstColor=c;document.querySelectorAll('.assistant-color-dot').forEach(el=>{el.classList.toggle('selected',el.dataset.color===c);});}
async function saveAssistant(){const nameEl=document.getElementById('asst-name');const personaEl=document.getElementById('asst-persona');const name=(nameEl.value||'').trim();const persona=(personaEl.value||'').trim();if(name.length<2){showToast('اسم المساعد قصير');return;}if(persona.length<10){showToast('اكتب وصفاً أطول');return;}const btn=document.getElementById('asst-save-btn');btn.disabled=true;btn.textContent='جاري الحفظ...';try{const url=editingAssistantId?'/update_assistant':'/create_assistant';const body={name,persona,color:selectedAsstColor};if(editingAssistantId)body.id=editingAssistantId;const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(d.status==='ok'){showToast(editingAssistantId?'تم التعديل':'تم الإنشاء');if(d.assistant&&!editingAssistantId){myAssistants.push(d.assistant);}else if(d.assistant&&editingAssistantId){const idx=myAssistants.findIndex(x=>x.id===editingAssistantId);if(idx>=0)myAssistants[idx]=d.assistant;}else{await loadAssistants();}renderAssistantMenu();loadAssistantsPage();}else{showToast(d.message||'فشل الحفظ');btn.disabled=false;btn.textContent='حفظ';}}catch(e){showToast('خطأ في الاتصال');btn.disabled=false;btn.textContent='حفظ';}}
async function deleteAssistant(id){if(!confirm('حذف هذا المساعد؟'))return;try{const r=await fetch('/delete_assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});const d=await r.json();if(d.status==='ok'){myAssistants=myAssistants.filter(x=>x.id!==id);if(currentAssistantId===id)selectAssistant(null,false);showToast('تم الحذف');renderAssistantMenu();loadAssistantsPage();}else{showToast('فشل الحذف');}}catch(e){showToast('خطأ في الاتصال');}}
function loadAssistantsPage(){currentSubKey='assistants';document.getElementById('subPageTitle').textContent='مساعدي الخاص';let html='';if(myAssistants.length===0){html='<div class="sp-note" style="text-align:center;padding:30px;">لا يوجد مساعدون حتى الآن.<br>أنشئ مساعداً خاصاً بك</div>';}else{html='<div class="assistants-list">';myAssistants.forEach(a=>{html+='<div class="assistant-card"><div class="a-dot" style="background:'+a.color+'">'+escapeHtml(a.name.charAt(0))+'</div><div class="assistant-card-info"><div class="assistant-card-name">'+escapeHtml(a.name)+'</div><div class="assistant-card-sub">'+escapeHtml(a.persona.substring(0,60))+(a.persona.length>60?'...':'')+'</div></div><button type="button" class="assistant-card-del" onclick="deleteAssistant('+a.id+')" title="حذف"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>';});html+='</div>';}html+='<button type="button" class="assistant-add-btn" onclick="openAssistantForm(null)"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>إنشاء مساعد جديد</button>';document.getElementById('subPageBody').innerHTML=html;document.getElementById('subPage').classList.add('show');}
document.addEventListener('click',function(e){const menu=document.getElementById('assistantMenu');const pill=document.getElementById('assistantPill');if(!menu||!pill)return;if(!menu.contains(e.target)&&!pill.contains(e.target)){menu.classList.remove('show');}});
if(IS_REGISTERED){document.getElementById('assistantBar').classList.add('show');setTimeout(loadAssistants,300);}
async function sendMessage(){if(iw)return;const msgText=ui.value.trim(),img=pid;if(!msgText&&!img)return;let userMsgEl=null;if(msgText){userMsgEl=addMessage(msgText,'user');ch.push({role:'user',content:msgText});}if(img){userMsgEl=addMessage('صورة مرفقة','user',false,img);ch.push({role:'user',content:'[صورة مرفقة]'});clearPending()}ui.value='';ui.style.height='auto';iw=true;const botEl=document.createElement('div');botEl.className='msg bot';botEl.innerHTML='<span class="typing-dots">'+tr('thinking')+'</span>';cb.appendChild(botEl);if(userMsgEl)scrollMsgToTop(userMsgEl);const payload={message:msgText||'مرفق',image:img||null,history:ch,conv_id:cid,lang:userLang,personality:userPersonality,assistant_id:currentAssistantId};let displayText='';let bufferText='';let streamDone=false;let typingTimer=null;function tick(){if(bufferText.length>0){displayText+=bufferText.slice(0,1);bufferText=bufferText.slice(1);botEl.innerHTML=formatBotText(displayText);}if(bufferText.length===0&&streamDone){clearInterval(typingTimer);typingTimer=null;botEl.innerHTML=formatBotText(displayText);if(displayText&&displayText.trim().length>0){attachBotActions(botEl,displayText);ch.push({role:'assistant',content:displayText});}iw=false;if(voiceOn===true&&displayText&&displayText.trim().length>10){fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:displayText})}).then(r=>r.json()).then(v=>{if(v&&v.audio){playAudioWithSpeed(v.audio,function(){});}}).catch(function(){});}}}typingTimer=setInterval(tick,15);try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){let errMsg='مشكلة';try{const d=await r.json();errMsg=d.error||d.message||'مشكلة';}catch(e){}clearInterval(typingTimer);botEl.remove();addMessage('خطأ: '+errMsg,'error');iw=false;return;}const reader=r.body.getReader();const decoder=new TextDecoder();let sseBuffer='';let firstToken=true;while(true){const {done,value}=await reader.read();if(done)break;sseBuffer+=decoder.decode(value,{stream:true});const parts=sseBuffer.split('\n\n');sseBuffer=parts.pop();for(const line of parts){if(!line.startsWith('data: '))continue;try{const data=JSON.parse(line.slice(6));if(data.token){if(firstToken){botEl.innerHTML='';firstToken=false;}bufferText+=data.token;}else if(data.done){if(data.conv_id)cid=data.conv_id;streamDone=true;}else if(data.error){bufferText+='\n\nخطأ: '+data.error;}}catch(e){}}}streamDone=true;}catch(e){clearInterval(typingTimer);if(botEl.parentNode)botEl.remove();addMessage('تعذر الاتصال','error');iw=false;}}
sb.addEventListener('click',sendMessage);
ui.addEventListener('keydown',function(e){if(e.key==='Enter'){const isMobile=/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);if(isMobile&&!e.shiftKey){return;}if(!isMobile&&!e.shiftKey){e.preventDefault();sendMessage();}}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
let recog=null;
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage(tr('micUnsupported'),'bot',true);return}if(this.classList.contains('listening')){this.classList.remove('listening');if(recog)recog.stop();return}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang=userLang==='en'?'en-US':'ar-SA';this.classList.add('listening');addMessage(tr('listening'),'bot',true);recog.onresult=function(e){const tr2=e.results[0][0].transcript;ui.value=tr2;mb.classList.remove('listening');setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove('listening')};recog.start()});
window.deleteMyAccount=function(){if(!confirm('حذف حسابك بالكامل؟'))return;fetch('/delete_my_account',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='success'){alert('تم الحذف');window.location.href='/'}});};
window.openSettings=openSettings;window.closeSettings=closeSettings;window.setTheme=setTheme;window.setAccentColor=setAccentColor;window.openSubPage=openSubPage;window.closeSubPage=closeSubPage;window.confirmSubPage=confirmSubPage;window.selectTheme=selectTheme;window.selectColor=selectColor;window.selectLanguage=selectLanguage;window.selectPersonality=selectPersonality;window.selectFontSize=selectFontSize;window.saveGeneral=saveGeneral;window.saveVoice=saveVoice;window.selectVoiceGender=selectVoiceGender;window.selectVoiceSpeed=selectVoiceSpeed;window.selectVoiceLevel=selectVoiceLevel;window.changePassword=changePassword;window.logoutAll=logoutAll;window.clearCache=clearCache;window.exportData=exportData;window.saveAds=saveAds;window.sendReport=sendReport;window.loadPinned=loadPinned;window.loadHistory=loadHistory;window.loadConversation=loadConversation;window.loadStorageInfo=loadStorageInfo;window.loadMemory=loadMemory;window.getContrastColor=getContrastColor;window.toggleAssistantMenu=toggleAssistantMenu;window.selectAssistant=selectAssistant;window.openNewAssistantForm=openNewAssistantForm;window.openAssistantForm=openAssistantForm;window.pickAssistantColor=pickAssistantColor;window.saveAssistant=saveAssistant;window.deleteAssistant=deleteAssistant;window.loadAssistantsPage=loadAssistantsPage;
applyLang();
(function initPersonality(){var map={friendly:'ودود',concise:'مختصر',detailed:'مفصّل',formal:'رسمي',teacher:'معلّم',playful:'فرفوش'};var lbl=document.getElementById('currentPersonalityLabel');if(lbl)lbl.textContent=map[userPersonality]||'ودود';})();
})();</script></body></html>"""

@app.route('/')
def index():
    user_name = None
    email = session.get('user_email')
    is_registered = bool(email) or bool(session.get('is_admin'))
    user_lang = ''
    if email and not session.get('is_admin'):
        p = get_user_profile(email)
        user_name = (p.get("display_name") or email.split("@")[0]) if p else email.split("@")[0]
        mem = get_user_memory(email)
        if mem.get('name'): user_name = mem['name']
        lang_from_mem = mem.get('lang')
        if lang_from_mem in ('ar', 'en'): user_lang = lang_from_mem
    elif session.get('is_admin'):
        user_name = "أدمن"
    return render_template_string(HT, user_name=user_name, is_registered=is_registered, user_lang=user_lang)

@app.route('/library')
def library_page():
    if not session.get('user_email') and not session.get('is_admin'): return redirect(url_for('login'))
    return render_template_string(LIBRARY_HTML)

@app.route('/library/images')
def library_images(): return jsonify({"images": get_user_images(get_user_id())})

@app.route('/library/upload', methods=['POST'])
def library_upload():
    try:
        if not session.get('user_email') and not session.get('is_admin'): return jsonify({"status": "error", "message": "يجب تسجيل الدخول"}), 401
        d = request.get_json(silent=True) or {}
        image_data = d.get('image_data') or ''
        if not isinstance(image_data, str) or len(image_data) > 7000000: return jsonify({"status": "error", "message": "الصورة كبيرة جداً"}), 413
        if not image_data: return jsonify({"status": "error", "message": "لا توجد صورة"}), 400
        if not re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+", image_data): return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة"}), 400
        try:
            if len(base64.b64decode(image_data.split(",", 1)[1], validate=True)) > 5 * 1024 * 1024: return jsonify({"status": "error", "message": "الصورة كبيرة جداً"}), 413
        except Exception: return jsonify({"status": "error", "message": "تعذر قراءة الصورة"}), 400
        title = d.get('title') if isinstance(d.get('title'), str) else "صورة"
        save_image_to_library(get_user_id(), image_data=image_data, title=title[:200] or "صورة", source="upload")
        return jsonify({"status": "ok"})
    except Exception as e: print("library_upload:", e); return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/library/delete', methods=['POST'])
def library_delete():
    try:
        d = request.get_json(silent=True) or {}
        ok = delete_user_image(get_user_id(), d.get('id'))
        return jsonify({"status": "ok"}), 200 if ok else (jsonify({"status": "error"}), 404)
    except Exception as e: print("library_delete:", e); return jsonify({"status": "error"}), 500

@app.route('/my_assistants')
def my_assistants():
    if not session.get('user_email') and not session.get('is_admin'): return jsonify({"assistants": []})
    uid = get_user_id()
    try:
        r = sb.table("custom_assistants").select("id,name,persona,color,created_at").eq("user_id", uid).order("created_at", desc=False).limit(50).execute()
        return jsonify({"assistants": r.data or []})
    except Exception as e: print("my_assistants:", e); return jsonify({"assistants": [], "error": str(e)})

@app.route('/create_assistant', methods=['POST'])
def create_assistant():
    if not session.get('user_email') and not session.get('is_admin'): return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()[:40]
    persona = (d.get('persona') or '').strip()[:1000]
    color = (d.get('color') or '#4a6a8a')[:20]
    if len(name) < 2 or len(persona) < 10: return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    uid = get_user_id()
    try:
        cnt = len((sb.table("custom_assistants").select("id").eq("user_id", uid).execute()).data or [])
        if cnt >= 5: return jsonify({"status": "error", "message": "وصلت للحد الأقصى (5)"}), 400
    except Exception as e: print("count error:", e)
    try:
        r = sb.table("custom_assistants").insert({"user_id": uid, "name": name, "persona": persona, "color": color}).execute()
        asst = r.data[0] if r and r.data else None
        return jsonify({"status": "ok", "assistant": asst})
    except Exception as e: print("create_assistant:", e); return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/update_assistant', methods=['POST'])
def update_assistant():
    if not session.get('user_email') and not session.get('is_admin'): return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    aid = d.get('id')
    name = (d.get('name') or '').strip()[:40]
    persona = (d.get('persona') or '').strip()[:1000]
    color = (d.get('color') or '#4a6a8a')[:20]
    if not aid or len(name) < 2 or len(persona) < 10: return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400
    uid = get_user_id()
    try:
        r = sb.table("custom_assistants").update({"name": name, "persona": persona, "color": color}).eq("id", aid).eq("user_id", uid).execute()
        asst = r.data[0] if r and r.data else None
        return jsonify({"status": "ok", "assistant": asst})
    except Exception as e: print("update_assistant:", e); return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/delete_assistant', methods=['POST'])
def delete_assistant():
    if not session.get('user_email') and not session.get('is_admin'): return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    aid = d.get('id')
    if not aid: return jsonify({"status": "error"}), 400
    uid = get_user_id()
    try:
        sb.table("custom_assistants").delete().eq("id", aid).eq("user_id", uid).execute()
        return jsonify({"status": "ok"})
    except Exception as e: print("delete_assistant:", e); return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/pinned_conversations')
def pinned_conversations():
    email = session.get('user_email')
    if not email: return jsonify({"pinned": []})
    pinned_ids = get_pinned_convs(email)
    if not pinned_ids: return jsonify({"pinned": []})
    all_convs = get_user_conversations(get_user_id())
    return jsonify({"pinned": [c for c in all_convs if c["id"] in pinned_ids]})

@app.route('/pin_conversation', methods=['POST'])
def pin_conversation():
    email = session.get('user_email')
    if not email: return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('conv_id')
    pinned = get_pinned_convs(email)
    if cid not in pinned: pinned.append(cid); save_pinned_convs(email, pinned)
    return jsonify({"status": "ok"})

@app.route('/unpin_conversation', methods=['POST'])
def unpin_conversation():
    email = session.get('user_email')
    if not email: return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('conv_id')
    pinned = get_pinned_convs(email)
    if cid in pinned: pinned.remove(cid); save_pinned_convs(email, pinned)
    return jsonify({"status": "ok"})

@app.route('/history')
def history():
    uid = get_user_id()
    cs = get_user_conversations(uid)
    email = session.get('user_email')
    pinned_ids = get_pinned_convs(email) if email else []
    return jsonify({"conversations": [{"id": c["id"], "title": c["title"], "pinned": c["id"] in pinned_ids} for c in cs]})

@app.route('/load_conversation/<cid>')
def load_conversation_route(cid):
    ms = load_conversation(get_user_id(), cid)
    return jsonify({"messages": ms}) if ms else (jsonify({"messages": None}), 404)

@app.route('/delete_message', methods=['POST'])
def delete_message():
    try:
        d = request.get_json(silent=True) or {}
        if not isinstance(d.get('conv_id'), str) or not isinstance(d.get('index'), int): return jsonify({"status": "error"}), 400
        ok = delete_message_row(get_user_id(), d.get('conv_id'), d.get('index'))
        return jsonify({"status": "ok"}), 200 if ok else (jsonify({"status": "error"}), 404)
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get_memory')
def get_memory_route():
    email = session.get('user_email')
    if not email: return jsonify({"status": "guest", "items": {}})
    try:
        mem = get_user_memory(email) or {}
        return jsonify({"name": mem.get('name', ''), "lang": mem.get('lang', 'ar'), "personality": mem.get('personality', 'friendly'), "email": email})
    except Exception as e: print("get_memory:", e); return jsonify({"status": "error"}), 500

@app.route('/delete_my_account', methods=['POST'])
def delete_my_account():
    email = session.get('user_email')
    if not email or session.get('is_admin'): return jsonify({"status": "error"}), 400
    uid = get_user_id()
    try:
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not service_key: return jsonify({"status": "error", "message": "غير مُعدّ"}), 503
        auth_user_id = None
        for page in range(1, 101):
            ar = requests.get(f"{SUPABASE_URL}/auth/v1/admin/users", headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}, params={"page": page, "per_page": 100}, timeout=15)
            ar.raise_for_status()
            users_payload = ar.json()
            auth_users = users_payload.get("users", []) if isinstance(users_payload, dict) else []
            for auth_user in auth_users:
                if (auth_user.get("email") or "").lower() == email.lower(): auth_user_id = auth_user.get("id"); break
            if auth_user_id or len(auth_users) < 100: break
        if not auth_user_id: return jsonify({"status": "error", "message": "لم يتم العثور"}), 404
        sb.table("assistant_chats").delete().eq("user_id", uid).execute()
        sb.table("assistant_usage").delete().eq("user_id", uid).execute()
        sb.table("image_library").delete().eq("user_id", uid).execute()
        sb.table("custom_assistants").delete().eq("user_id", uid).execute()
        sb.table("profiles").delete().eq("email", email.lower()).execute()
        requests.delete(f"{SUPABASE_URL}/auth/v1/admin/users/{auth_user_id}", headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}, timeout=15).raise_for_status()
    except Exception as e: print("delete_my_account:", e); return jsonify({"status": "error", "message": "تعذر"}), 500
    session.clear()
    return jsonify({"status": "success"}), 200

@app.route('/update_profile', methods=['POST'])
def update_profile():
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    lang = d.get('lang')
    if not name or len(name) < 2: return jsonify({"status": "error"}), 400
    email = session.get('user_email')
    if not email: return jsonify({"status": "error"}), 401
    save_user_profile(email, name=name)
    mem = get_user_memory(email) or {}
    mem['name'] = name
    if lang in ('ar', 'en'): mem['lang'] = lang
    save_user_memory(email, mem)
    return jsonify({"status": "ok"})

@app.route('/update_language', methods=['POST'])
def update_language():
    d = request.get_json(silent=True) or {}
    lang = d.get('lang')
    if lang not in ('ar', 'en'): return jsonify({"status": "error"}), 400
    email = session.get('user_email')
    if email:
        try:
            mem = get_user_memory(email) or {}
            mem['lang'] = lang
            save_user_memory(email, mem)
        except: pass
    return jsonify({"status": "ok"})

@app.route('/update_personality', methods=['POST'])
def update_personality():
    d = request.get_json(silent=True) or {}
    p = d.get('personality')
    if p not in PERSONALITY_INSTRUCTIONS: return jsonify({"status": "error"}), 400
    email = session.get('user_email')
    if email:
        try:
            mem = get_user_memory(email) or {}
            mem['personality'] = p
            save_user_memory(email, mem)
        except: pass
    return jsonify({"status": "ok"})

@app.route('/change_password', methods=['POST'])
def change_password():
    email = session.get('user_email')
    if not email: return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    oldp = d.get('old_password', '')
    newp = d.get('new_password', '')
    if not oldp: return jsonify({"status": "error", "message": "اكتب كلمة المرور الحالية"}), 400
    if not newp or len(newp) < 8: return jsonify({"status": "error", "message": "8 أحرف على الأقل"}), 400
    try: r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password", headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"}, json={"email": email, "password": oldp}, timeout=15)
    except Exception as e: return jsonify({"status": "error", "message": "تعذر الاتصال"}), 500
    if r.status_code != 200: return jsonify({"status": "error", "message": "كلمة المرور الحالية غير صحيحة"}), 400
    at = r.json().get('access_token')
    if not at: return jsonify({"status": "error", "message": "تعذر إنشاء الجلسة"}), 500
    try: r2 = requests.put(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {at}", "Content-Type": "application/json"}, json={"password": newp}, timeout=15)
    except Exception as e: return jsonify({"status": "error", "message": "تعذر التحديث"}), 500
    if r2.status_code == 200: return jsonify({"status": "ok"}), 200
    err_msg = "تعذر تغيير كلمة المرور"
    try:
        e2 = r2.json()
        err_msg = e2.get("msg") or e2.get("message") or e2.get("error_description") or err_msg
    except: pass
    return jsonify({"status": "error", "message": err_msg}), 400

@app.route('/export_data')
def export_data():
    email = session.get('user_email')
    if not email: return "يجب تسجيل الدخول", 401
    uid = get_user_id()
    data = {"user_email": email, "conversations": get_user_conversations(uid), "images_count": len(get_user_images(uid))}
    resp = jsonify(data)
    resp.headers['Content-Disposition'] = f'attachment; filename=nibras_data_{email}.json'
    return resp

@app.route('/report_bug', methods=['POST'])
def report_bug():
    try:
        d = request.get_json(silent=True) or {}
        desc = (d.get('description') or '').strip()
        if not desc or len(desc) < 3: return jsonify({"status": "error"}), 400
        sb.table("bug_reports").insert({"user_email": session.get('user_email', 'ضيف'), "user_role": session.get('user_role', 'guest'), "type": d.get('type', 'غير محدد'), "description": desc}).execute()
        return jsonify({"status": "ok"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/logout_all', methods=['POST'])
def logout_all(): session.clear(); return jsonify({"status": "ok"})

@app.route('/feedback', methods=['POST'])
def feedback():
    try:
        d = request.get_json(silent=True) or {}
        ftype = d.get('type')
        if ftype not in ('like', 'dislike', 'unlike', 'undislike'): return jsonify({"status": "error"}), 400
        sb.table("message_feedback").insert({"user_id": get_user_id(), "user_email": session.get('user_email', 'guest'), "conv_id": d.get('conv_id') or '', "message_text": (d.get('message') or '')[:1000], "feedback": ftype}).execute()
        return jsonify({"status": "ok"})
    except Exception as e: print("feedback:", e); return jsonify({"status": "error"}), 500

@app.route('/share/view')
def shared_view(): return render_template_string(SHARED_VIEW_HTML)

@app.route('/share/<cid>')
def shared_conversation(cid):
    rows = load_conversation_public(cid)
    if not rows: return "المحادثة غير موجودة.", 404
    msgs = []
    title = "محادثة نبراس"
    for i, row in enumerate(rows):
        if i == 0 and row.get("title"): title = row["title"]
        if row.get("message"): msgs.append({"role": "user", "content": row["message"]})
        if row.get("response"): msgs.append({"role": "assistant", "content": row["response"]})
    return render_template_string(SPH, messages=msgs, title=title)

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        e = request.form.get('email', '').strip().lower()
        p = request.form.get('password', '')
        ap = os.environ.get("ADMIN_PASSWORD")
        if not e or "@" not in e: return render_template_string(LH, error="بريد صحيح مطلوب.")
        if e == ADMIN_EMAIL.lower():
            if not ap or not secrets.compare_digest(p, ap): return render_template_string(LH, error="كلمة مرور الأدمن غير صحيحة.")
            session.clear(); session.permanent = True
            session['user_email'] = e; session['is_admin'] = True; session['user_role'] = 'admin'
            return redirect(url_for('index'))
        try: r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password", headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"}, json={"email": e, "password": p}, timeout=15)
        except Exception as ex: return render_template_string(LH, error="تعذر الاتصال.")
        if r.status_code != 200: return render_template_string(LH, error="البريد أو كلمة المرور غير صحيحة.")
        session.clear(); session.permanent = True
        session['user_email'] = e; session['is_admin'] = False; session['user_role'] = get_user_role(e)
        touch_user(e)
        return redirect(url_for('index'))
    return render_template_string(LH)

@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup():
    e = request.form.get('email', '').strip().lower()
    p = request.form.get('password', '')
    name = request.form.get('name', '').strip()
    if not e or "@" not in e or len(p) < 8: return render_template_string(LH, error="بيانات غير صحيحة.")
    if not name or len(name) < 2: return render_template_string(LH, error="الاسم مطلوب.")
    try:
        sb.auth.sign_up({"email": e, "password": p, "options": {"email_redirect_to": f"{request.host_url.rstrip('/')}/verified", "data": {"display_name": name}}})
        save_user_profile(e, name=name)
        save_user_memory(e, {"name": name})
        return render_template_string(LH, success="تم إنشاء حسابك! افتح بريدك للتأكيد.")
    except Exception as ex: return render_template_string(LH, error=f"فشل: {ex}")

@app.route('/verified')
def verified(): return """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><title>تم التحقق</title></head><body style="text-align:center;padding:50px;font-family:sans-serif;"><h2>تم تأكيد حسابك!</h2><a href="/login">تسجيل الدخول</a></body></html>"""

@app.route('/recover', methods=['POST'])
@limiter.limit("5 per hour")
def recover():
    e = request.form.get('email', '').strip().lower()
    if not e or "@" not in e: return render_template_string(LH, error="أدخل بريداً صحيحاً.")
    try:
        redirect_url = f"{request.host_url.rstrip('/')}/reset-password"
        requests.post(f"{SUPABASE_URL}/auth/v1/recover?redirect_to={redirect_url}", headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"}, json={"email": e}, timeout=15)
        return render_template_string(LH, success="تم إرسال رابط الاستعادة على بريدك.")
    except Exception as ex: return render_template_string(LH, error=f"فشل: {ex}")

@app.route('/reset-password')
def reset_password_page(): return render_template_string(RESET_HTML)

@app.route('/update_password', methods=['POST'])
def update_password():
    try:
        d = request.get_json(silent=True) or {}
        token = d.get('access_token', '')
        newp = d.get('new_password', '')
        if not token: return jsonify({"status": "error", "message": "الرابط غير صالح"}), 400
        if not newp or len(newp) < 8: return jsonify({"status": "error", "message": "8 أحرف على الأقل"}), 400
        r = requests.put(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json={"password": newp}, timeout=15)
        if r.status_code == 200: return jsonify({"status": "ok"})
        msg = "تعذر التحديث"
        try:
            e2 = r.json()
            msg = e2.get("msg") or e2.get("message") or e2.get("error_description") or msg
        except: pass
        return jsonify({"status": "error", "message": msg}), 400
    except Exception as e: return jsonify({"status": "error", "message": "خطأ داخلي"}), 500

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('index'))

ALLOWED_OAUTH_PROVIDERS = ("google",)
@app.route('/auth/<provider>')
def oauth_login(provider):
    if provider not in ALLOWED_OAUTH_PROVIDERS: return redirect(url_for('login'))
    callback = f"{request.host_url.rstrip('/')}/auth/callback"
    auth_url = f"{SUPABASE_URL}/auth/v1/authorize?provider={provider}&redirect_to={urllib.parse.quote(callback, safe='')}"
    return redirect(auth_url)

@app.route('/auth/callback')
def oauth_callback(): return render_template_string(OAUTH_CALLBACK_HTML)

@app.route('/auth/session', methods=['POST'])
@limiter.limit("20 per minute")
def oauth_session():
    try:
        d = request.get_json(silent=True) or {}
        at = d.get('access_token')
        if not at or not isinstance(at, str): return jsonify({"status": "error", "message": "توكن مفقود"}), 400
        r = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {at}"}, timeout=15)
        if r.status_code != 200: return jsonify({"status": "error", "message": "توكن غير صالح"}), 401
        u = r.json()
        email = (u.get('email') or '').lower().strip()
        if not email: return jsonify({"status": "error", "message": "بريد غير موجود"}), 400
        session.clear(); session.permanent = True
        session['user_email'] = email; session['is_admin'] = (email == ADMIN_EMAIL.lower()); session['user_role'] = get_user_role(email)
        try:
            meta = u.get('user_metadata') or {}
            name = (meta.get('full_name') or meta.get('name') or email.split('@')[0]).strip()
            if not get_user_profile(email):
                save_user_profile(email, name=name)
                save_user_memory(email, {"name": name})
            touch_user(email)
        except: pass
        return jsonify({"status": "ok"})
    except Exception as e: print("oauth_session:", e); return jsonify({"status": "error", "message": "خطأ داخلي"}), 500

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        p = request.form.get('password', '')
        ap = os.environ.get("ADMIN_PASSWORD")
        if ap and secrets.compare_digest(p, ap):
            session['is_admin'] = True; session.permanent = True
            return redirect(url_for('admin_dashboard'))
        return "<h2>كلمة مرور خاطئة</h2>"
    return """<body style='text-align:center;padding:50px;font-family:sans-serif;'><form method='POST'><h2>دخول الأدمن</h2><input type='password' name='password' required><br><br><button type='submit'>دخول</button></form></body>"""

@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    recent, users_list, reports_list, feedback_list = [], [], [], []
    try: recent = (sb.table("assistant_chats").select("user_id,title,created_at").order("created_at", desc=True).limit(10).execute()).data or []
    except: pass
    try: users_list = (sb.table("profiles").select("email,display_name,role").order("created_at", desc=True).limit(30).execute()).data or []
    except: pass
    try: reports_list = (sb.table("bug_reports").select("*").order("created_at", desc=True).limit(30).execute()).data or []
    except: pass
    try: feedback_list = (sb.table("message_feedback").select("*").order("created_at", desc=True).limit(100).execute()).data or []
    except: pass
    likes_count = sum(1 for f in feedback_list if f.get('feedback') == 'like')
    dislikes_count = sum(1 for f in feedback_list if f.get('feedback') == 'dislike')
    recent_html = "".join([f'<div class="conv-item"><b>{escape(str(r.get("title", "?")))}</b><small>{escape(str(r.get("user_id", ""))[:30])}</small></div>' for r in recent]) or "<p>لا توجد</p>"
    users_html = "".join([f'<div class="conv-item"><b>{escape(str(u.get("display_name", "?")))}</b><small>{escape(str(u.get("email", "")))}</small></div>' for u in users_list]) or "<p>لا يوجد</p>"
    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>لوحة الأدمن</title><style>body{{font-family:sans-serif;padding:16px;background:#f4f7fc;color:#1a2b3c;margin:0}}.container{{max-width:700px;margin:auto}}h1{{color:#4a6a8a;text-align:center}}.card{{background:#fff;padding:18px;margin:15px 0;border-radius:15px;box-shadow:0 4px 16px rgba(0,0,0,0.04)}}.stat{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eef1f6}}.stat:last-child{{border:none}}.num{{color:#4a6a8a;font-weight:bold}}.back{{display:block;text-align:center;color:#4a6a8a;text-decoration:none;margin-top:24px;font-weight:600;padding:12px;background:#fff;border-radius:12px}}</style></head><body><div class="container"><h1>لوحة تحكم نبراس</h1><div class="card"><div class="stat"><span>المستخدمون</span><span class="num">{len(users_list)}</span></div><div class="stat"><span>البلاغات</span><span class="num">{len(reports_list)}</span></div><div class="stat"><span>إعجابات</span><span class="num" style="color:#27ae60;">{likes_count}</span></div><div class="stat"><span>رفض</span><span class="num" style="color:#e74c3c;">{dislikes_count}</span></div></div><div class="card"><h3>المستخدمون</h3>{users_html}</div><div class="card"><h3>آخر المحادثات</h3>{recent_html}</div><a href="/" class="back">← العودة للرئيسية</a></div></body></html>"""

@app.route('/set_gender', methods=['POST'])
def set_gender():
    d = request.get_json(silent=True) or {}
    gender = d.get('gender', 'male')
    if gender not in ('male', 'female'): gender = 'male'
    session['voice_gender'] = gender
    return jsonify({"status": "ok"})

@app.route('/voice', methods=['POST'])
@limiter.limit("30 per minute")
def voice():
    try:
        d = request.get_json(silent=True) or {}
        text = (d.get('text') or "").strip()
        if not text or len(text) > 3000: return jsonify({"audio": None})
        return jsonify({"audio": generate_speech(text, session.get('voice_gender', 'male'))})
    except Exception as e: print(f"voice: {e}"); return jsonify({"audio": None})

@app.route('/chat', methods=['POST'])
@limiter.limit("20 per minute")
def chat():
    try:
        d = request.get_json(silent=True) or {}
        raw_message = d.get("message", "")
        if not isinstance(raw_message, str): return jsonify({"status": "error", "message": "نص غير صالح"}), 400
        um = raw_message.strip()
        cid = d.get("conv_id")
        img_data = d.get("image")
        assistant_id = d.get("assistant_id")
        if len(um) > 12000: return jsonify({"status": "error", "message": "الرسالة طويلة"}), 413
        if not um and not img_data: return jsonify({"reply": "اكتب شيء"})
        is_admin = bool(session.get('is_admin'))
        user_email = session.get('user_email', '')
        user_role = get_user_role(user_email) if user_email else 'guest'
        is_registered = is_admin or (bool(user_email) and user_role in ('user', 'admin'))
        uid = get_user_id()
        lang_from_payload = d.get("lang")
        if lang_from_payload in ('ar', 'en'): user_lang = lang_from_payload
        elif user_email: user_lang = get_user_language(user_email)
        else: user_lang = 'ar'
        assistant_persona_extra = ""
        if assistant_id and is_registered:
            try:
                ar = sb.table("custom_assistants").select("*").eq("id", assistant_id).eq("user_id", uid).limit(1).execute()
                if ar.data:
                    asst = ar.data[0]
                    assistant_persona_extra = f"\n\n**شخصيتك الحالية:**\nأنت الآن تجسّد '{asst['name']}'. {asst['persona']}\n\nالتزم بهذه الشخصية تماماً."
            except Exception as e: print(f"assistant load: {e}")
        usage, limits, can_chat, can_search, can_image = check_limits(uid, user_role if not is_admin else 'admin')
        if not can_chat:
            reply_limit = "وصل محادثاتك للحد اليومي المسموح به" if user_lang == 'ar' else "You've reached the daily limit."
            nid = save_message(uid, um, reply_limit, cid) if is_registered else cid
            def ls():
                yield f"data: {json.dumps({'token': reply_limit}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'conv_id': nid or cid or ''}, ensure_ascii=False)}\n\n"
            return Response(stream_with_context(ls()), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})
        if is_registered and user_email:
            try: touch_user(user_email)
            except: pass
        has_image = img_data is not None
        if has_image:
            if not isinstance(img_data, str) or len(img_data) > 7000000 or not re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+", img_data): return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة"}), 400
            try:
                if len(base64.b64decode(img_data.split(",", 1)[1], validate=True)) > 5 * 1024 * 1024: return jsonify({"status": "error", "message": "الصورة كبيرة"}), 413
            except: return jsonify({"status": "error", "message": "تعذر قراءة الصورة"}), 400
            if not is_registered: return jsonify({"reply": "تحليل الصور للمسجلين فقط.", "conv_id": cid})
            if not can_image:
                msg = "وصلت للحد اليومي للصور."
                nid = save_message(uid, um, msg, cid) if is_registered else cid
                inc_usage(uid, "chat_count")
                def lis():
                    yield f"data: {json.dumps({'token': msg}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'done': True, 'conv_id': nid or cid or ''}, ensure_ascii=False)}\n\n"
                return Response(stream_with_context(lis()), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})
        user_memory = get_user_memory(user_email) if user_email else {}
        memory_context = ""
        if user_memory.get('name'): memory_context = f"\n\n**معلومات المستخدم:**\nاسم المستخدم: {user_memory['name']}"
        if is_registered: server_hist = load_conversation(uid, cid) or []
        else:
            server_hist = []
            client_hist = d.get("history") or []
            if isinstance(client_hist, list):
                items = client_hist
                if items and isinstance(items[-1], dict) and items[-1].get("role") == "user": items = items[:-1]
                for h in items[-15:]:
                    if isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str):
                        server_hist.append({"role": h["role"], "content": h["content"][:2000]})
        if img_data and is_registered and can_image:
            server_hist.append({"role": "user", "content": [{"type": "text", "text": um or "حلل الصورة"}, {"type": "image_url", "image_url": {"url": img_data}}]})
        else: server_hist.append({"role": "user", "content": um})
        lang_inst = LANG_INSTRUCTION.get(user_lang, "")
        if user_email: personality = get_user_memory(user_email).get('personality', 'friendly')
        else: personality = d.get('personality', 'friendly')
        if personality not in PERSONALITY_INSTRUCTIONS: personality = 'friendly'
        personality_inst = PERSONALITY_INSTRUCTIONS.get(personality, "")
        msgs = [{"role": "system", "content": SP + memory_context + lang_inst + personality_inst + assistant_persona_extra}] + server_hist[-15:]
        if is_registered and can_search:
            inc_usage(uid, "search_count")
            try:
                sr = client.responses.create(model=OPENAI_MODEL, instructions="أنت محرك بحث.", input=f"ابحث: {um}", tools=[{"type": "web_search"}])
                res = ""
                if hasattr(sr, "output_text") and sr.output_text: res = sr.output_text.strip()
                elif getattr(sr, "output", None):
                    try: res = sr.output[0].content[0].text
                    except: res = ""
                if res: msgs.append({"role": "system", "content": f"نتائج البحث:\n\n{res}"})
            except Exception as e: print(f"فشل البحث: {e}")
        def generate():
            full_reply = ""
            try:
                stream = client.chat.completions.create(model=OPENAI_MODEL, messages=msgs, max_completion_tokens=8000, stream=True)
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        full_reply += token
                        yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
                cleaned = full_reply or "ما قدرت أجيب رد."
                nid = cid
                if is_registered: nid = save_message(uid, um or "[صورة مرفقة]", cleaned, cid)
                elif not nid: nid = "guest_conv_" + secrets.token_hex(5)
                inc_usage(uid, "chat_count")
                if has_image and is_registered and can_image: inc_usage(uid, "image_count")
                yield f"data: {json.dumps({'done': True, 'conv_id': nid})}\n\n"
            except Exception as e:
                print("stream error:", repr(e))
                yield f"data: {json.dumps({'error': 'تعذر إكمال الطلب.'}, ensure_ascii=False)}\n\n"
        return Response(stream_with_context(generate()), mimetype='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'})
    except Exception as e:
        print("chat request error:", repr(e))
        return jsonify({"status": "error", "message": "حدث خطأ داخلي"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
