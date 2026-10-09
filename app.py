# ==========================================================
#  نبراس GP - المساعد الذكي الشخصي
# ==========================================================

from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, send_from_directory
)
import openai, os, secrets, json, asyncio, base64, re, requests, edge_tts
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from pywebpush import webpush, WebPushException
from concurrent.futures import ThreadPoolExecutor


app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True
)

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "abdullaha0569361@gmail.com")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود!")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise Exception("OPENAI_MODEL غير موجود!")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("SUPABASE_URL و SUPABASE_KEY مطلوبان!")
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", f"mailto:{ADMIN_EMAIL}")

LIMITS = {
    "guest": {"chat": 15,  "search": 0,   "image": 0},
    "user":  {"chat": 15,  "search": 2,   "image": 1},
    "admin": {"chat": 9999, "search": 9999, "image": 9999},
}

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["500 per day", "300 per hour"]
)
limiter.init_app(app)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    allowed = [
        'https://abod724.github.io',
        'https://nibras-al.onrender.com',
        'https://test-bot-001.onrender.com'
    ]
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/robots.txt')
def serve_robots():
    return send_from_directory('static', 'robots.txt')

@app.route('/sitemap.xml')
def serve_sitemap():
    return send_from_directory('static', 'sitemap.xml')

@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):
    return send_from_directory('.well-known', filename)

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')


# ==========================================================
#  دوال Supabase
# ==========================================================

def get_user_role(email):
    if not email:
        return 'guest'
    if email.lower() == ADMIN_EMAIL.lower():
        return 'admin'
    try:
        r = (sb.table("profiles").select("role")
             .eq("email", email.lower()).limit(1).execute())
        if r and r.data and r.data[0].get("role"):
            return r.data[0]["role"]
    except Exception as e:
        print("get_user_role:", e)
    return 'user'


def get_user_profile(email):
    if not email:
        return None
    try:
        r = (sb.table("profiles").select("*")
             .eq("email", email.lower().strip()).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_user_profile:", e)
    return None


def save_user_profile(email, name=None, avatar=None):
    if not email:
        return
    try:
        data = {"email": email.lower().strip()}
        if name is not None:
            data["display_name"] = name
        if avatar is not None:
            data["avatar_url"] = avatar
        sb.table("profiles").upsert(data, on_conflict="email").execute()
    except Exception as e:
        print("save_user_profile:", e)


def touch_user(email):
    if not email:
        return
    try:
        sb.table("profiles").update(
            {"last_seen": datetime.utcnow().isoformat()}
        ).eq("email", email.lower().strip()).execute()
    except Exception as e:
        print("touch_user:", e)


def get_user_memory(email):
    if not email:
        return {}
    try:
        r = (sb.table("profiles").select("memory")
             .eq("email", email.lower().strip()).limit(1).execute())
        if r and r.data and r.data[0].get("memory"):
            return r.data[0]["memory"] or {}
    except Exception as e:
        print("get_user_memory:", e)
    return {}


def save_user_memory(email, memory_dict):
    if not email:
        return
    try:
        sb.table("profiles").update(
            {"memory": memory_dict}
        ).eq("email", email.lower().strip()).execute()
    except Exception as e:
        print("save_user_memory:", e)


def get_pinned_convs(email):
    if not email:
        return []
    try:
        r = (sb.table("profiles").select("pinned_convs")
             .eq("email", email.lower().strip()).limit(1).execute())
        if r and r.data and r.data[0].get("pinned_convs"):
            return r.data[0]["pinned_convs"] or []
    except Exception as e:
        print("get_pinned_convs:", e)
    return []


def save_pinned_convs(email, pinned_list):
    if not email:
        return
    try:
        sb.table("profiles").update(
            {"pinned_convs": pinned_list}
        ).eq("email", email.lower().strip()).execute()
    except Exception as e:
        print("save_pinned_convs:", e)


def get_recent_summaries(uid, limit=5):
    try:
        r = (sb.table("assistant_chats")
             .select("conv_id,summary,title,created_at")
             .eq("user_id", uid)
             .not_.is_("summary", "null")
             .order("created_at", desc=True)
             .limit(50)
             .execute())
        rows = r.data or []
    except Exception as e:
        print("get_recent_summaries:", e)
        return []
    seen = {}
    for row in rows:
        cid = row.get("conv_id")
        if cid and cid not in seen and row.get("summary"):
            seen[cid] = {
                "conv_id": cid,
                "summary": row["summary"],
                "title": row.get("title")
            }
        if len(seen) >= limit:
            break
    return list(seen.values())


def summarize_old_conversation(uid, cid):
    if not cid:
        return
    try:
        existing = (sb.table("assistant_chats").select("summary")
                    .eq("user_id", uid).eq("conv_id", cid).limit(1).execute())
        if existing and existing.data and existing.data[0].get("summary"):
            return
        msgs = load_conversation(uid, cid)
        if not msgs or len(msgs) < 2:
            return
        convo_text = ""
        for m in msgs[:20]:
            role = "المستخدم" if m["role"] == "user" else "نبراس"
            convo_text += f"{role}: {m['content'][:300]}\n"
        try:
            r = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "لخّص المحادثة التالية في 2-3 جمل قصيرة بالعربية."},
                    {"role": "user", "content": convo_text}
                ],
                max_completion_tokens=300
            )
            summary = r.choices[0].message.content.strip()
        except Exception as e:
            print("summarize generation:", e)
            return
        if not summary:
            return
        sb.table("assistant_chats").update({"summary": summary}) \
            .eq("user_id", uid).eq("conv_id", cid).execute()
    except Exception as e:
        print("summarize_old_conversation:", e)


def get_user_id():
    if session.get('is_admin'):
        return "admin_page"
    if session.get('user_email'):
        return "user_" + session['user_email']
    if 'guest_id' not in session:
        session['guest_id'] = "guest_" + secrets.token_hex(8)
    return session['guest_id']


def get_usage_today(uid):
    today = _date.today().isoformat()
    try:
        r = (sb.table("assistant_usage").select("*")
             .eq("user_id", uid).eq("date", today).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_usage_today select:", e)
    new_row = {"user_id": uid, "date": today, "chat_count": 0, "image_count": 0, "search_count": 0}
    try:
        r = sb.table("assistant_usage").insert(new_row).execute()
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_usage_today insert:", e)
    return new_row


def inc_usage(uid, field):
    today = _date.today().isoformat()
    row = get_usage_today(uid)
    current = int(row.get(field, 0) or 0) + 1
    try:
        sb.table("assistant_usage").update({field: current}) \
            .eq("user_id", uid).eq("date", today).execute()
    except Exception as e:
        print("inc_usage:", e)
    return current


def check_limits(uid, role):
    usage = get_usage_today(uid)
    limits = LIMITS.get(role, LIMITS["guest"])
    can_chat = int(usage.get("chat_count", 0) or 0) < limits["chat"]
    can_search = int(usage.get("search_count", 0) or 0) < limits["search"]
    can_image = int(usage.get("image_count", 0) or 0) < limits["image"]
    return usage, limits, can_chat, can_search, can_image


def get_user_conversations(uid):
    try:
        r = (sb.table("assistant_chats")
             .select("conv_id,title,created_at")
             .eq("user_id", uid)
             .order("created_at", desc=True)
             .limit(200)
             .execute())
        rows = r.data or []
    except Exception as e:
        print("get_user_conversations:", e)
        return []
    seen = {}
    for row in rows:
        cid = row.get("conv_id")
        if cid and cid not in seen:
            title = (row.get("title") or "").strip() or "محادثة"
            seen[cid] = {
                "id": cid,
                "conv_id": cid,
                "title": title,
                "timestamp": row.get("created_at")
            }
    return list(seen.values())


def save_message(uid, msg, resp, cid=None):
    if not cid:
        cid = secrets.token_hex(5)
    try:
        ex = (sb.table("assistant_chats").select("id")
              .eq("user_id", uid).eq("conv_id", cid).limit(1).execute())
        has_prev = bool(ex.data)
        title = None
        if not has_prev:
            clean_msg = (msg or "").strip()
            clean_msg = re.sub(r'[^\w\s\u0600-\u06FF]', '', clean_msg).strip()
            if clean_msg:
                title = clean_msg[:30]
                if len(clean_msg) > 30:
                    title += "..."
            else:
                title = "محادثة جديدة"
        sb.table("assistant_chats").insert({
            "user_id": uid,
            "conv_id": cid,
            "message": msg,
            "response": resp,
            "title": title
        }).execute()
    except Exception as e:
        print("save_message:", e)
    return cid


def load_conversation(uid, cid):
    try:
        r = (sb.table("assistant_chats")
             .select("message,response,created_at")
             .eq("user_id", uid).eq("conv_id", cid)
             .order("created_at").execute())
        rows = r.data or []
    except Exception as e:
        print("load_conversation:", e)
        return None
    if not rows:
        return None
    msgs = []
    for row in rows:
        if row.get("message"):
            msgs.append({"role": "user", "content": row["message"]})
        if row.get("response"):
            msgs.append({"role": "assistant", "content": row["response"]})
    return msgs


def load_conversation_public(cid):
    try:
        r = (sb.table("assistant_chats")
             .select("message,response,title,created_at")
             .eq("conv_id", cid).order("created_at").execute())
        return r.data or []
    except Exception as e:
        print("load_conversation_public:", e)
        return []


def delete_message_row(uid, cid, index):
    try:
        r = (sb.table("assistant_chats")
             .select("id,message,response")
             .eq("user_id", uid).eq("conv_id", cid)
             .order("created_at").execute())
        rows = r.data or []
        if index < 0 or index >= len(rows):
            return False
        row_idx = index // 2
        if row_idx >= len(rows):
            return False
        sb.table("assistant_chats").delete().eq("id", rows[row_idx]["id"]).execute()
        return True
    except Exception as e:
        print("delete_message_row:", e)
        return False


def save_image_to_library(uid, image_url=None, image_data=None, title="", source="upload"):
    try:
        row = {"user_id": uid, "title": title or "صورة", "source": source}
        if image_url:
            row["image_url"] = image_url
        if image_data:
            row["image_data"] = image_data
        r = sb.table("image_library").insert(row).execute()
        return r.data[0] if r and r.data else None
    except Exception as e:
        print("save_image_to_library:", e)
        return None


def get_user_images(uid):
    try:
        r = (sb.table("image_library").select("*")
             .eq("user_id", uid).order("created_at", desc=True).limit(200).execute())
        return r.data or []
    except Exception as e:
        print("get_user_images:", e)
        return []


def delete_user_image(uid, image_id):
    try:
        sb.table("image_library").delete().eq("id", image_id).eq("user_id", uid).execute()
        return True
    except Exception as e:
        print("delete_user_image:", e)
        return False


def send_push_to_user(user_id, title, body, url="/"):
    if not VAPID_PRIVATE_KEY or not VAPID_SUBJECT:
        print("⚠️ VAPID غير مُعَد")
        return
    try:
        subs = sb.table("push_subscriptions").select("*").eq("user_id", user_id).execute()
        for s in (subs.data or []):
            try:
                webpush(
                    subscription_info={
                        "endpoint": s["endpoint"],
                        "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}
                    },
                    data=json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT}
                )
                print(f"✅ إشعار Push أُرسل لـ {user_id}")
            except WebPushException as ex:
                if ex.response and ex.response.status_code in (404, 410):
                    sb.table("push_subscriptions").delete().eq("id", s["id"]).execute()
                    print(f"🗑️ حذف اشتراك منتهي")
                else:
                    print(f"❌ فشل إرسال Push: {ex}")
    except Exception as e:
        print("send_push_to_user:", e)


def send_push_to_all(user_ids, title, body):
    if not user_ids:
        return 0
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(lambda u: send_push_to_user(u, title, body), user_ids))
    except Exception as e:
        print("send_push_to_all:", e)
    return len(user_ids)


kc = ""
for fn in ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]:
    if os.path.exists(fn):
        try:
            with open(fn, "r", encoding="utf-8") as f:
                kc = f.read()
                break
        except:
            pass
if not kc:
    kc = "أنت نبراس، مساعد ذكي."

SP = f"""أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه).
2. **معرفتك العامة**.
3. **البحث بالويب** عند الحاجة.

**ملف المعرفة:**
{kc}

**⚠️ قاعدة التنسيق:**
- اكتب ردودك في فقرات متصلة (2-4 جمل).
- لا تضع كل جملة في سطر منفصل.
- الفاصل الوحيد هو سطر فارغ بين الفقرات.

**⚠️ أسلوب الحديث:**
- سولف بشكل طبيعي وعفوي.
- لا تذكر أبداً أي كلام عن حفظ المحادثات أو الذاكرة.
- رد بشكل مباشر بدون مقدمات فلسفية."""


async def _generate_speech_async(text, voice):
    communicate = edge_tts.Communicate(text, voice)
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return audio_data


def generate_speech(text, gender):
    try:
        voice = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariahNeural"
        audio = asyncio.run(_generate_speech_async(text, voice))
        return base64.b64encode(audio).decode('utf-8')
    except Exception as e:
        print(f"صوت: {e}")
        return None


SPH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>{{ title or 'محادثة نبراس' }}</h1><a href="/">الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class="content">{{ msg.content|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

LIBRARY_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.img-card .delete-btn:hover svg{stroke:#fff}.img-card .delete-btn svg{width:16px;height:16px;stroke:#ff4757;stroke-width:2;fill:none}.empty{text-align:center;padding:60px 20px;color:#8b949e}.empty svg{width:64px;height:64px;stroke:#dce1e8;stroke-width:1.5;fill:none;margin-bottom:16px}.empty h3{color:#5a6b7c;font-size:18px;margin-bottom:6px}.empty p{font-size:14px}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}@media(max-width:520px){.topbar h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.img-card .preview{height:150px}}</style></head><body><div class="container"><div class="topbar"><h1><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4a6a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.innerHTML='';if(!d.images||d.images.length===0){grid.innerHTML='<div class="empty" style="grid-column:1/-1"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><h3>مكتبتك فاضية</h3><p>ارفع أول صورة</p></div>';return;}d.images.forEach(img=>{const src=img.image_data||img.image_url;const card=document.createElement('div');card.className='img-card';card.innerHTML='<img class="preview" src="'+src+'" loading="lazy"/><button class="delete-btn" title="حذف"><svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg></button><div class="info"><div class="title">'+(img.title||'صورة')+'</div><div class="source">'+(img.source==='generated'?'مولدة':'مرفوعة')+'</div></div>';card.querySelector('.delete-btn').onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف هذه الصورة؟'))return;const r=await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});const res=await r.json();if(res.status==='ok'){card.remove();showToast('تم الحذف');if(grid.children.length===0)loadImages();}else showToast('فشل الحذف');};grid.appendChild(card);});}catch(e){grid.innerHTML='<div class="empty" style="grid-column:1/-1"><h3>خطأ</h3><p>تعذر تحميل الصور</p></div>';}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{const r=await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});const d=await r.json();if(d.status==='ok')showToast('تم رفع الصورة');else showToast(d.message||'فشل الرفع');}catch(e){showToast('خطأ في الاتصال');}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};zone.ondragover=(e)=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=(e)=>{e.preventDefault();zone.classList.remove('dragover');uploadFiles(e.dataTransfer.files);};loadImages();
</script></body></html>"""

LH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff;font-size:26px;font-weight:700}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;position:relative;font-family:inherit;transition:color .2s}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}.field input::placeholder{color:#a5b0be}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit;transition:all .2s}button.submit:hover{background:#3a5a7a}button.submit:active{transform:scale(0.98)}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}a:hover{color:#3a5a7a}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider{margin:22px 0 0;padding-top:18px;border-top:1px solid #eef1f6}.privacy-link{font-size:12px;color:#a5b0be;margin-top:6px;text-decoration:underline;font-weight:500}@media(max-width:420px){.box{padding:34px 24px}h2{font-size:22px}}</style></head><body><div class="box"><div class="logo">🔐</div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div class="divider"><a href="/">العودة للرئيسية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""
