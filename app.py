# ==========================================================
#  نبراس GP - المساعد الذكي الشخصي
# ==========================================================

from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, send_from_directory,
    Response, stream_with_context
)
import openai, os, secrets, json, asyncio, base64, re, requests, edge_tts
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from pywebpush import webpush, WebPushException
from concurrent.futures import ThreadPoolExecutor
from markupsafe import escape


# ==========================================================
# إعداد التطبيق
# ==========================================================

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError("يجب ضبط SECRET_KEY كمتغير بيئة ثابت بطول 32 حرفًا على الأقل")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True
)


# ==========================================================
#  متغيرات البيئة
# ==========================================================

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


# ==========================================================
# الحدود والـ Rate Limiter
# ==========================================================

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


# ==========================================================
#  بعد كل طلب - CORS
# ==========================================================

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


# ==========================================================
#  ملفات ثابتة
# ==========================================================

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


def get_user_language(email):
    if not email:
        return 'ar'
    mem = get_user_memory(email)
    lang = mem.get('lang')
    if lang in ('ar', 'en'):
        return lang
    return 'ar'


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
        session.permanent = True
        return "admin_page"
    if session.get('user_email'):
        session.permanent = True
        return "user_" + session['user_email']
    if 'guest_id' not in session:
        session['guest_id'] = "guest_" + secrets.token_hex(8)
    session.permanent = True
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
             .select("message,response,title,created_at,user_id")
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
        return 0
    sent_count = 0
    try:
        subs = sb.table("push_subscriptions").select("*").eq("user_id", user_id).execute()
        for sub in (subs.data or []):
            try:
                webpush(
                    subscription_info={
                        "endpoint": sub["endpoint"],
                        "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}
                    },
                    data=json.dumps({"title": title, "body": body, "url": url}),
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": VAPID_SUBJECT}
                )
                sent_count += 1
                print(f"✅ إشعار Push أُرسل لـ {user_id}")
            except WebPushException as ex:
                if ex.response and ex.response.status_code in (404, 410):
                    sb.table("push_subscriptions").delete().eq("id", sub["id"]).execute()
                    print("🗑️ حذف اشتراك منتهي")
                else:
                    print(f"❌ فشل إرسال Push: {ex}")
    except Exception as e:
        print("send_push_to_user:", e)
    return sent_count


def send_push_to_all(user_ids, title, body):
    if not user_ids:
        return 0
    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            return sum(executor.map(lambda uid: send_push_to_user(uid, title, body), user_ids))
    except Exception as e:
        print("send_push_to_all:", e)
        return 0


# ==========================================================
#  ملف المعرفة + System Prompt
# ==========================================================

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


# ==========================================================
#  تعليمات اللغة (تُضاف للـ System Prompt)
# ==========================================================

LANG_INSTRUCTION = {
    "ar": "\n\n**⚠️ اللغة:** رد دائماً بالعربية، بأسلوبك العامي المعتاد.",
    "en": "\n\n**⚠️ Language:** ALWAYS respond in English, regardless of the language the user writes in. Keep the same friendly, casual tone."
}


# ==========================================================
#  تحويل النص إلى كلام
# ==========================================================

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


# ==========================================================
#  قوالب HTML
# ==========================================================

SHARED_VIEW_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:flex-start;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px;margin-top:20px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px;font-weight:600}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word;white-space:pre-wrap}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}.error{background:#ffe8e8;color:#c33;padding:20px;border-radius:14px;text-align:center;font-weight:600}</style></head><body><div class="container"><div class="header"><h1>محادثة نبراس</h1><a href="/">الرئيسية</a></div><div id="content"><div class="error">جاري التحميل...</div></div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div><script>
(function(){
    var container=document.getElementById('content');
    try{
        var hash=window.location.hash||'';
        var m=hash.match(/[#&]d=([^&]+)/);
        if(!m){container.innerHTML='<div class="error">الرابط غير صالح أو ناقص.</div>';return;}
        var encoded=decodeURIComponent(m[1]);
        var json=decodeURIComponent(escape(atob(encoded)));
        var msgs=JSON.parse(json);
        if(!Array.isArray(msgs)||msgs.length===0){container.innerHTML='<div class="error">المحادثة فاضية.</div>';return;}
        container.innerHTML='';
        msgs.forEach(function(msg){
            var div=document.createElement('div');
            div.className='msg '+(msg.r==='u'?'user':'bot');
            var av=document.createElement('div');av.className='avatar';av.textContent=msg.r==='u'?'👤':'🤖';
            var ct=document.createElement('div');ct.className='content';ct.textContent=msg.c||'';
            div.appendChild(av);div.appendChild(ct);
            container.appendChild(div);
        });
        if(msgs[0]&&msgs[0].c){document.title=String(msgs[0].c).slice(0,30);}
    }catch(e){
        console.error(e);
        container.innerHTML='<div class="error">تعذر قراءة المحادثة من الرابط.</div>';
    }
})();
</script></body></html>"""

SPH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>{{ (title or 'محادثة نبراس')|e }}</h1><a href="/">الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class="content">{{ msg.content|e|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

LIBRARY_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.img-card .delete-btn:hover svg{stroke:#fff}.img-card .delete-btn svg{width:16px;height:16px;stroke:#ff4757;stroke-width:2;fill:none}.empty{text-align:center;padding:60px 20px;color:#8b949e}.empty svg{width:64px;height:64px;stroke:#dce1e8;stroke-width:1.5;fill:none;margin-bottom:16px}.empty h3{color:#5a6b7c;font-size:18px;margin-bottom:6px}.empty p{font-size:14px}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}@media(max-width:520px){.topbar h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.img-card .preview{height:150px}}</style></head><body><div class="container"><div class="topbar"><h1><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4a6a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.replaceChildren();if(!d.images||d.images.length===0){const empty=document.createElement('div');empty.className='empty';empty.style.gridColumn='1/-1';const h=document.createElement('h3');h.textContent='مكتبتك فاضية';const p=document.createElement('p');p.textContent='ارفع أول صورة';empty.append(h,p);grid.appendChild(empty);return;}d.images.forEach(img=>{const src=img.image_data||img.image_url||'';const card=document.createElement('div');card.className='img-card';const preview=document.createElement('img');preview.className='preview';preview.loading='lazy';if(typeof src==='string'&&(src.startsWith('data:image/')||src.startsWith('https://')))preview.src=src;preview.alt='صورة من المكتبة';const del=document.createElement('button');del.className='delete-btn';del.type='button';del.title='حذف';del.textContent='×';const info=document.createElement('div');info.className='info';const title=document.createElement('div');title.className='title';title.textContent=String(img.title||'صورة');const source=document.createElement('div');source.className='source';source.textContent=img.source==='generated'?'مولدة':'مرفوعة';info.append(title,source);card.append(preview,del,info);del.onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف هذه الصورة؟'))return;try{const dr=await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});const res=await dr.json();if(dr.ok&&res.status==='ok'){card.remove();showToast('تم الحذف');if(grid.children.length===0)loadImages();}else showToast('فشل الحذف');}catch(e){showToast('خطأ في الاتصال');}};grid.appendChild(card);});}catch(e){grid.replaceChildren();const msg=document.createElement('p');msg.className='empty';msg.textContent='تعذر تحميل الصور';grid.appendChild(msg);}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{const r=await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});const d=await r.json();if(d.status==='ok')showToast('تم رفع الصورة');else showToast(d.message||'فشل الرفع');}catch(e){showToast('خطأ في الاتصال');}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};zone.ondragover=(e)=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=(e)=>{e.preventDefault();zone.classList.remove('dragover');uploadFiles(e.dataTransfer.files);};loadImages();
</script></body></html>"""

LH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff;font-size:26px;font-weight:700}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;position:relative;font-family:inherit;transition:color .2s}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}.field input::placeholder{color:#a5b0be}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit;transition:all .2s}button.submit:hover{background:#3a5a7a}button.submit:active{transform:scale(0.98)}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}a:hover{color:#3a5a7a}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider{margin:22px 0 0;padding-top:18px;border-top:1px solid #eef1f6}.privacy-link{font-size:12px;color:#a5b0be;margin-top:6px;text-decoration:underline;font-weight:500}@media(max-width:420px){.box{padding:34px 24px}h2{font-size:22px}}</style></head><body><div class="box"><div class="logo">🔐</div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div class="divider" style="display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:8px;"><a href="/" style="margin-top:0;">العودة للرئيسية</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" class="privacy-link" style="margin-top:0;">شروط الاستخدام</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="privacy-link" style="margin-top:0;">سياسة الخصوصية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""


HT = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><title>نبراس GP | مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"><link rel="icon" href="/static/icon-192.png"><meta name="theme-color" content="#ffffff"><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--border-input:#dce1e8;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--modal-bg:rgba(0,0,0,0.5);--accent-color:#4a6a8a}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#58a6ff;--border-input:#30363d;--send-bg:#238636;--send-hover:#2ea043;--modal-bg:rgba(0,0,0,0.7);--accent-color:#58a6ff}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-color);flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s,opacity .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.icon-btn.voice-on{color:var(--primary-color);opacity:1}.icon-btn.voice-off{color:var(--primary-color);opacity:0.85}.btn-group{display:flex;gap:8px;align-items:center}.btn{padding:7px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center;font-family:inherit;font-weight:600}.btn-outline{background:0 0;border:1.5px solid var(--primary-color);color:var(--primary-color);transition:all .2s}.btn-outline:hover{background:var(--primary-color);color:#fff}.user-badge{display:flex;align-items:center;gap:6px;background:var(--bg-hover);padding:6px 12px;border-radius:20px;font-size:13px;color:var(--text-primary);font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user-badge svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}.dropdown{position:absolute;top:68px;left:12px;right:12px;background:var(--bg-dropdown);border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15),0 4px 12px rgba(0,0,0,0.08);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:78vh;overflow-y:auto;padding:10px;opacity:0;transform:translateY(-8px);transition:opacity .2s ease,transform .2s ease}.dropdown.show{display:flex;opacity:1;transform:translateY(0)}.dropdown::-webkit-scrollbar{width:4px}.dropdown::-webkit-scrollbar-thumb{background:var(--border-color);border-radius:4px}.dropdown .item{display:flex;align-items:center;gap:14px;padding:13px 16px;font-size:15px;color:var(--text-primary);background:transparent;border:none;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-weight:600;border-radius:14px;transition:background .15s ease,transform .1s ease;letter-spacing:-0.2px}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .item:active{transform:scale(0.98)}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0;stroke-linecap:round;stroke-linejoin:round;opacity:.85}.dropdown .section-title{padding:16px 16px 6px;font-size:11px;font-weight:700;color:var(--text-secondary);letter-spacing:.8px;text-transform:uppercase;opacity:.7}.dropdown .conv-item{display:flex;align-items:center;gap:8px;padding:11px 16px;border:none;background:transparent;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-size:14px;color:var(--text-primary);font-weight:500;border-radius:14px;transition:background .15s ease;letter-spacing:-0.1px;position:relative}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item .conv-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dropdown .conv-item::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--primary-color);opacity:.4;flex-shrink:0}.dropdown .conv-item .pin-btn{background:transparent;border:none;cursor:pointer;padding:4px;border-radius:8px;display:flex;align-items:center;justify-content:center;opacity:0.5;transition:opacity .2s,background .2s;flex-shrink:0}.dropdown .conv-item .pin-btn:hover{opacity:1;background:var(--bg-hover)}.dropdown .conv-item .pin-btn svg{width:16px;height:16px;stroke:var(--text-primary);stroke-width:2;fill:none}.dropdown .conv-item .pin-btn.pinned svg{fill:var(--primary-color);stroke:var(--primary-color)}.dropdown .pinned-item{padding:11px 16px;display:flex;align-items:center;gap:8px;border-radius:14px;transition:background .15s ease}.dropdown .pinned-item:hover{background:var(--bg-hover)}.gender-option{flex:1;padding:9px 12px;border-radius:12px;border:1px solid var(--border-color);background:transparent;font-size:13px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s ease;font-family:inherit}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color);box-shadow:0 4px 12px rgba(74,106,138,0.3)}.dropdown .item.danger{color:#d32f2f}.dropdown .item.danger svg{stroke:#d32f2f;opacity:1}.dropdown .item.danger:hover{background:rgba(211,47,47,0.08)}.settings-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:99999;display:none;flex-direction:column;overflow-y:auto}.settings-overlay.show{display:flex}.settings-page{max-width:500px;width:100%;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column;background:var(--bg-body)}.settings-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.settings-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.settings-body{padding:16px;display:flex;flex-direction:column;gap:14px}.settings-card{background:var(--bg-app);border-radius:18px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.settings-item{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.settings-item:last-child{border-bottom:none}.settings-item:hover{background:var(--bg-hover)}.settings-item .item-right{display:flex;align-items:center;gap:14px;color:var(--text-primary);font-size:15px;font-weight:600}.settings-item .item-right svg{width:22px;height:22px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0}.settings-item .chevron{width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none}.sub-page{position:fixed;inset:0;background:var(--bg-body);z-index:100000;display:none;flex-direction:column;overflow-y:auto}.sub-page.show{display:flex}.sub-page-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.sub-page-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.sub-page-body{padding:20px;display:flex;flex-direction:column;gap:16px;max-width:500px;margin:0 auto;width:100%}.sub-page-body .field{display:flex;flex-direction:column;gap:8px}.sub-page-body .field label{font-size:14px;color:var(--text-secondary);font-weight:600}.sub-page-body .field input,.sub-page-body .field select{padding:12px 16px;border-radius:12px;border:1px solid var(--border-color);background:var(--bg-input);color:var(--text-primary);font-size:15px;font-family:inherit;outline:none}.sub-page-body .save-btn{padding:14px;border-radius:14px;background:var(--primary-color);color:#fff;border:none;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:8px}.info-box{background:var(--bg-hover);padding:16px;border-radius:14px;font-size:14px;color:var(--text-secondary);line-height:1.8}.option-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.option-row{padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.option-row:last-child{border-bottom:none}.option-row:active{background:var(--bg-hover)}.option-label{display:flex;justify-content:space-between;align-items:center;font-size:15px;color:var(--text-primary);font-weight:500}.check-icon{width:22px;height:22px;stroke:var(--primary-color);stroke-width:2.5;fill:none;opacity:0;transition:opacity .25s}.option-row.selected .check-icon{opacity:1}.color-grid{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.color-row{padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:background .2s}.color-row:last-child{border-bottom:none}.color-row:active{background:var(--bg-hover)}.color-row-left{display:flex;align-items:center;gap:14px;font-size:15px;color:var(--text-primary);font-weight:500}.color-circle{width:26px;height:26px;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.15);flex-shrink:0}.color-row .check-icon{opacity:0;transition:opacity .25s}.color-row.selected .check-icon{opacity:1}.lang-list{display:flex;flex-direction:column;gap:12px}.lang-card{display:flex;align-items:center;gap:16px;padding:18px 20px;background:var(--bg-app);border-radius:18px;cursor:pointer;border:2px solid var(--border-color);transition:all .25s cubic-bezier(.4,0,.2,1);box-shadow:0 1px 3px var(--shadow-color)}.lang-card:hover{border-color:var(--primary-color);transform:translateY(-2px);box-shadow:0 8px 24px rgba(74,106,138,0.15)}.lang-card.selected{border-color:var(--primary-color);background:linear-gradient(135deg,var(--bg-app) 0%,rgba(74,106,138,0.06) 100%);box-shadow:0 6px 20px rgba(74,106,138,0.18)}.lang-flag{font-size:34px;line-height:1;flex-shrink:0;filter:drop-shadow(0 2px 4px rgba(0,0,0,0.1))}.lang-info{flex:1;display:flex;flex-direction:column;gap:3px}.lang-name{font-size:17px;font-weight:700;color:var(--text-primary);letter-spacing:-0.2px}.lang-sub{font-size:13px;color:var(--text-secondary)}.lang-check{width:26px;height:26px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;transition:opacity .3s ease,transform .35s cubic-bezier(.34,1.56,.64,1);flex-shrink:0;transform:scale(0.5)}.lang-card.selected .lang-check{opacity:1;transform:scale(1)}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:16px;min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:16px;font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--msg-user-bg,var(--bg-user-msg));color:var(--msg-user-text,#111);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.5;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;font-size:16px;color:var(--text-secondary)}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}#imagePreviewContainer{display:none;padding:6px 18px;align-items:center;gap:10px;background:var(--bg-input);margin:0 14px;border-radius:20px 20px 0 0;border:1px solid var(--border-color);border-bottom:none;flex-wrap:wrap;flex-shrink:0}#imagePreviewContainer img{max-height:60px;border-radius:8px;border:1px solid var(--border-color)}#imagePreviewContainer .label{font-size:13px;color:var(--text-secondary)}#removeImageBtn{background:0 0;border:none;color:var(--danger-color);font-size:13px;cursor:pointer;padding:4px 10px;border-radius:10px;font-family:inherit;font-weight:600}.input-area{display:flex;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:40px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:16px;font-weight:500;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow:hidden;min-height:22px;max-height:80px;font-family:inherit;line-height:1.4}.input-area textarea::placeholder{color:var(--placeholder-color)}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}.input-area .btn-icon:hover{background:var(--bg-hover)}.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.input-area .mic-btn{color:var(--primary-color)}.input-area .mic-btn.listening{color:#c33;background:#fde8e8}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 14px rgba(74,106,138,0.35);transition:background .2s,transform .15s}.input-area .send:hover{background:var(--send-hover);transform:scale(1.05)}.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .3s}.plus-btn:hover{background:var(--bg-hover)}.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}.plus-options .option-btn:hover{background:var(--border-color)}.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color)}.share-modal .box h3{font-size:20px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:14px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px;color:#fff;font-family:inherit}.share-modal .box .share-btn.whatsapp{background:#25D366}.share-modal .box .share-btn.facebook{background:#1877F2}.share-modal .box .share-btn.twitter{background:#000}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:15px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600;font-family:inherit}.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center;transition:opacity .2s}.copy-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center}.msg .actions .del-msg-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}.msg-actions{display:flex;gap:2px;margin-top:12px;align-items:center;opacity:0.5;transition:opacity .3s ease}.msg:hover .msg-actions,.msg-actions.touched{opacity:1}.msg-actions button{background:transparent;border:none;cursor:pointer;width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:background .2s ease,color .2s ease,transform .15s cubic-bezier(.4,0,.2,1)}.msg-actions button:hover{background:var(--bg-hover);color:var(--text-primary)}.msg-actions button:active{transform:scale(0.88)}.msg-actions button svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.9;fill:none;stroke-linecap:round;stroke-linejoin:round;transition:fill .2s ease,stroke .2s ease,transform .2s cubic-bezier(.34,1.56,.64,1)}.msg-actions button.liked{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.liked svg{fill:#10b981;stroke:#10b981;transform:scale(1.08)}.msg-actions button.disliked{color:#ef4444;background:rgba(239,68,68,0.1)}.msg-actions button.disliked svg{fill:#ef4444;stroke:#ef4444;transform:scale(1.08)}.msg-actions button.copied{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.copied svg{stroke:#10b981}.msg-actions button.speaking{color:var(--primary-color);background:var(--bg-hover)}.msg-actions button.speaking svg{fill:currentColor}.msg-actions button.speaking svg polygon{animation:speakerPulse 0.9s ease-in-out infinite}@keyframes speakerPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px}.input-area .btn-icon{width:32px;height:32px}.plus-btn{width:32px;height:32px}}</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="icon-btn voice-off" id="voiceToggle" title="تشغيل/إيقاف الصوت"><svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg></button><button class="icon-btn" id="menuToggle" title="القائمة"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}{% if user_name %}<div class="user-badge" title="{{ session.get('user_email') }}"><svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{{ user_name }}</div>{% endif %}<a href="/logout" class="btn btn-outline">خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div>

<div class="dropdown" id="dropdown">
    <button class="item" data-action="new"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>محادثة جديدة</button>
    <button class="item" onclick="window.location.href='/library'"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>مكتبتي</button>
    <button class="item" data-action="share"><svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>مشاركة المحادثة</button>
    <button class="item" onclick="openSettings()"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>الإعدادات</button>
    <div class="section-title">مثبت</div>
    <div id="pinnedList"><div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;font-weight:500;">لا توجد محادثات مثبتة</div></div>
    <div class="section-title">المحادثات الأخيرة</div>
    <div id="historyList"></div>
    {% if session.get('user_email') and not session.get('is_admin') %}<button class="item danger" onclick="deleteMyAccount()"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg>حذف حسابي</button>{% endif %}
</div>

<div id="settingsModal" class="settings-overlay">
    <div class="settings-page">
        <div class="settings-header"><button class="icon-btn" onclick="closeSettings()"><svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></button><h2>الإعدادات</h2><div style="width:32px;"></div></div>
        <div class="settings-body">
            <div class="settings-card">
                <div class="settings-item" onclick="openSubPage('theme')">
                    <div class="item-right">
                        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
                        <span>المظهر</span>
                    </div>
                    <svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
                </div>
                <div class="settings-item" onclick="openSubPage('color')">
                    <div class="item-right">
                        <svg viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg>
                        <span>لون التمييز</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span id="currentColorLabel" style="font-size:14px;color:var(--text-secondary);">أزرق داكن</span>
                        <span id="currentColorDot" style="width:14px;height:14px;border-radius:50%;background:#4a6a8a;display:inline-block;"></span>
                        <svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
                    </div>
                </div>
                <div class="settings-item" onclick="openSubPage('language')">
                    <div class="item-right">
                        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                        <span>اللغة / Language</span>
                    </div>
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span id="currentLangLabel" style="font-size:14px;color:var(--text-secondary);">العربية</span>
                        <svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
                    </div>
                </div>
            </div>
            <div class="settings-card">
                <div class="settings-item" onclick="openSubPage('general')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span>عام</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('notifications')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg><span>الإشعارات</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('voice')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg><span>الصوت</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('safety')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg><span>السلامة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('security')"><div class="item-right"><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg><span>الأمان وتسجيل الدخول</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('remote')"><div class="item-right"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg><span>التحكم عن بُعد</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
            </div>
            <div class="settings-card">
                <div class="settings-item" onclick="openSubPage('storage')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg><span>التخزين</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('privacy')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg><span>مركز الخصوصية</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('data')"><div class="item-right"><svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg><span>التحكم في البيانات</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('ads')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M3 11l18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg><span>التحكم في الإعلانات</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('report')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg><span>الإبلاغ عن خطأ</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('about')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg><span>حول</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
            </div>
            {% if session.get('user_email') and not session.get('is_admin') %}
            <div class="settings-card">
                <div class="settings-item" onclick="deleteMyAccount()"><div class="item-right"><svg viewBox="0 0 24 24" style="stroke:#d32f2f;"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg><span style="color:#d32f2f;">حذف حسابي</span></div></div>
            </div>
            {% endif %}
            <div class="settings-card" onclick="window.location.href='/logout'">
                <div class="settings-item" style="justify-content:center;">
                    <div class="item-right" style="justify-content:center;width:100%;">
                        <span style="color:#d32f2f;font-weight:bold;">تسجيل الخروج</span>
                        <svg viewBox="0 0 24 24" style="stroke:#d32f2f;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<div id="subPage" class="sub-page">
    <div class="sub-page-header"><button class="icon-btn" onclick="closeSubPage()"><svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></button><h2 id="subPageTitle">عام</h2><div style="width:32px;"></div></div>
    <div class="sub-page-body" id="subPageBody"></div>
</div>

<div id="chat"></div><div id="imagePreviewContainer"><img id="imagePreview" src=""/><span class="label">صورة معلقة</span><button id="removeImageBtn">إزالة</button></div><div class="input-area"><button class="btn-icon mic-btn" id="micBtn" title="صوت"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button><button class="plus-btn" id="plusBtn" title="إضافة"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button><div class="plus-options" id="plusOptions"><button class="option-btn" id="cameraBtn" title="كاميرا"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></button><button class="option-btn" id="galleryBtn" title="صور"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></button></div><textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea><button class="send" id="sendBtn" title="إرسال"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button></div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/></div>

<div class="share-modal" id="shareModal">
    <div class="box">
        <h3>مشاركة المحادثة</h3>
        <div class="share-grid">
            <a class="share-btn whatsapp" id="shareWhatsapp" target="_blank" rel="noopener">واتساب</a>
            <a class="share-btn facebook" id="shareFacebook" target="_blank" rel="noopener">فيسبوك</a>
            <a class="share-btn twitter" id="shareTwitter" target="_blank" rel="noopener">تويتر</a>
            <button class="share-btn snapchat" id="shareSnapchat">نسخ الرابط</button>
        </div>
        <button class="close-btn" onclick="document.getElementById('shareModal').classList.remove('show')">إغلاق</button>
    </div>
</div>

<script>(function(){const IS_REGISTERED={{ 'true' if is_registered else 'false' }};const SERVER_LANG='{{ user_lang }}';let userLang=SERVER_LANG||localStorage.getItem('nibras-lang')||'ar';try{localStorage.setItem('nibras-lang',userLang);}catch(e){}let isMale=(localStorage.getItem('nibras-voice-gender')||'male')==='male';let ch=[],pid=null,iw=!1,cid=null,ca=null,voiceOn=false,stickBottom=true;const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),pl=document.getElementById('pinnedList'),sm=document.getElementById('shareModal'),vt=document.getElementById('voiceToggle');
const SVG_SPK_ON='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
const SVG_SPK_OFF='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';
function tr(key){const d={thinking:{ar:'جاري التفكير',en:'Thinking'},listening:{ar:'جاري الاستماع...',en:'Listening...'},inputPlaceholder:{ar:'اكتب رسالتك...',en:'Type your message...'},micUnsupported:{ar:'المتصفح لا يدعم التعرف على الصوت.',en:'Browser does not support voice recognition.'}};return (d[key]||{})[userLang]||(d[key]||{}).ar||key;}
function applyLang(){ui.placeholder=tr('inputPlaceholder');document.documentElement.lang=userLang==='en'?'en':'ar';const lbl=document.getElementById('currentLangLabel');if(lbl)lbl.textContent=userLang==='en'?'English':'العربية';}
vt.addEventListener('click',function(){voiceOn=!voiceOn;if(voiceOn){vt.classList.remove('voice-off');vt.classList.add('voice-on');vt.innerHTML=SVG_SPK_ON;showToast(userLang==='en'?'Sound ON':'الصوت مفعّل');}else{vt.classList.remove('voice-on');vt.classList.add('voice-off');vt.innerHTML=SVG_SPK_OFF;if(ca){ca.pause();ca.currentTime=0;ca=null;}showToast(userLang==='en'?'Sound OFF':'الصوت مغلق');}});
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
function getPinnedLocal(){try{return JSON.parse(localStorage.getItem('nibras_pinned')||'[]');}catch(e){return [];}}
function savePinnedLocal(arr){try{localStorage.setItem('nibras_pinned',JSON.stringify(arr));}catch(e){}}
async function togglePin(cid,wasPinned,btnEl){if(IS_REGISTERED){const url=wasPinned?'/unpin_conversation':'/pin_conversation';try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conv_id:cid})});if(r.ok){btnEl.classList.toggle('pinned',!wasPinned);showToast(wasPinned?(userLang==='en'?'Unpinned':'تم إلغاء التثبيت'):(userLang==='en'?'📌 Pinned':'📌 تم التثبيت'));loadPinned();}}catch(e){showToast(userLang==='en'?'Connection failed':'فشل الاتصال');}}else{let arr=getPinnedLocal();if(wasPinned){arr=arr.filter(x=>x!==cid);showToast(userLang==='en'?'Unpinned':'تم إلغاء التثبيت');}else{if(!arr.includes(cid))arr.push(cid);showToast(userLang==='en'?'📌 Pinned locally':'📌 تم التثبيت محلياً');}savePinnedLocal(arr);btnEl.classList.toggle('pinned',!wasPinned);loadPinned();}}
mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();loadPinned();}});
function openSettings(){document.getElementById('settingsModal').classList.add('show');document.getElementById('dropdown').classList.remove('show');}
function closeSettings(){document.getElementById('settingsModal').classList.remove('show');}
function setTheme(t){const h=document.documentElement;if(t==='dark'){h.classList.add('dark-mode');localStorage.setItem('nibras-theme','dark')}else{h.classList.remove('dark-mode');localStorage.setItem('nibras-theme','light')}}
function getContrastColor(hex){try{const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);const lum=(0.299*r+0.587*g+0.114*b)/255;return lum>0.6?'#111111':'#ffffff';}catch(e){return '#111111';}}
function setAccentColor(color,name){const h=document.documentElement;h.style.setProperty('--primary-color',color);h.style.setProperty('--accent-color',color);h.style.setProperty('--send-bg',color);h.style.setProperty('--send-hover',color);h.style.setProperty('--primary-hover',color);h.style.setProperty('--icon-color',color);h.style.setProperty('--send-shadow',color+'33');h.style.setProperty('--msg-user-bg',color);h.style.setProperty('--msg-user-text',getContrastColor(color));const lbl=document.getElementById('currentColorLabel');if(lbl)lbl.textContent=name;const dot=document.getElementById('currentColorDot');if(dot)dot.style.background=color;localStorage.setItem('nibras-accent',color);localStorage.setItem('nibras-accent-name',name);}
(function initTheme(){const mode=localStorage.getItem('nibras-theme-mode')||'system';if(mode==='system'){const prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;setTheme(prefersDark?'dark':'light');}else{setTheme(mode);}})();
const savedAccent=localStorage.getItem('nibras-accent');const savedAccentName=localStorage.getItem('nibras-accent-name');
if(savedAccent){setAccentColor(savedAccent,savedAccentName||'مخصص');}
const subPagesContent={
    theme:'<div class="option-list"><div class="option-row" data-theme="system" onclick="selectTheme(\'system\')"><div class="option-label"><span>النظام (افتراضي)</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="option-row" data-theme="light" onclick="selectTheme(\'light\')"><div class="option-label"><span>فاتح</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div><div class="option-row" data-theme="dark" onclick="selectTheme(\'dark\')"><div class="option-label"><span>داكن</span><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div>',
    color:'<div class="color-grid"><div class="color-row" data-color="#4a6a8a" onclick="selectColor(\'#4a6a8a\',\'أزرق داكن\')"><div class="color-row-left"><div class="color-circle" style="background:#4a6a8a;"></div><span>أزرق داكن (افتراضي)</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#1a1a1a" onclick="selectColor(\'#1a1a1a\',\'أسود\')"><div class="color-row-left"><div class="color-circle" style="background:#1a1a1a;"></div><span>أسود</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#10b981" onclick="selectColor(\'#10b981\',\'أخضر\')"><div class="color-row-left"><div class="color-circle" style="background:#10b981;"></div><span>أخضر</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#fbbf24" onclick="selectColor(\'#fbbf24\',\'أصفر\')"><div class="color-row-left"><div class="color-circle" style="background:#fbbf24;"></div><span>أصفر</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#ec4899" onclick="selectColor(\'#ec4899\',\'وردي\')"><div class="color-row-left"><div class="color-circle" style="background:#ec4899;"></div><span>وردي</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#f97316" onclick="selectColor(\'#f97316\',\'برتقالي\')"><div class="color-row-left"><div class="color-circle" style="background:#f97316;"></div><span>برتقالي</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="color-row" data-color="#8b5cf6" onclick="selectColor(\'#8b5cf6\',\'أرجواني\')"><div class="color-row-left"><div class="color-circle" style="background:#8b5cf6;"></div><span>أرجواني</span></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    language:'<div class="lang-list"><div class="lang-card" data-lang="ar" onclick="selectLanguage(\'ar\')"><div class="lang-flag">🇸🇦</div><div class="lang-info"><div class="lang-name">العربية</div><div class="lang-sub">Arabic</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="lang-card" data-lang="en" onclick="selectLanguage(\'en\')"><div class="lang-flag">🇬🇧</div><div class="lang-info"><div class="lang-name">English</div><div class="lang-sub">الإنجليزية</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    general:'<div class="field"><label>الاسم الكامل</label><input type="text" id="sp-name" value="{{ user_name or '' }}" placeholder="اكتب اسمك"></div><button class="save-btn" onclick="saveGeneral()">حفظ</button>',
    notifications:'<div class="info-box">الإشعارات تسمح لك بتلقي تنبيهات فورية عند وصول ردود جديدة من نبراس.</div><button class="save-btn" onclick="requestNotifications()">تفعيل الإشعارات</button><button class="save-btn" style="background:#d32f2f;margin-top:8px;" onclick="unsubscribeFromPush()">إلغاء الإشعارات</button>',
    voice:'<div class="field"><label>🎙️ جنس الصوت</label><div style="display:flex;gap:10px;"><button type="button" id="voice-male-btn" class="gender-option" data-gender="male" onclick="pickVoiceGender(\'male\')" style="padding:14px 12px;font-size:14px;">👨 ذكر (حامد)</button><button type="button" id="voice-female-btn" class="gender-option" data-gender="female" onclick="pickVoiceGender(\'female\')" style="padding:14px 12px;font-size:14px;">👩 أنثى (زارية)</button></div></div><div class="field"><label>🔊 مستوى الصوت: <span id="sp-voice-val" style="color:var(--primary-color);font-weight:700;">100%</span></label><input type="range" id="sp-voice-level" min="0" max="100" value="100" step="5" oninput="document.getElementById(\'sp-voice-val\').textContent=this.value+\'%\'" style="width:100%;padding:8px 0;background:transparent;border:none;cursor:pointer;"></div><button class="save-btn" onclick="saveVoice()">💾 حفظ الإعدادات</button>',
    safety:'<div class="info-box"><b>إرشادات السلامة:</b><br>• لا تشارك معلوماتك الشخصية الحساسة.<br>• نبراس مساعد ذكي، وليس بديلاً عن الاستشارة المتخصصة.<br>• أبلغ عن أي محتوى غير لائق.</div>',
    security:'<div class="field"><label>البريد الإلكتروني</label><input type="email" value="{{ session.get('user_email','') }}" disabled></div><div class="field"><label>كلمة المرور الحالية</label><input type="password" id="sp-old-pass" placeholder="••••••••"></div><div class="field"><label>كلمة المرور الجديدة</label><input type="password" id="sp-new-pass" placeholder="••••••••"></div><button class="save-btn" onclick="changePassword()">تغيير كلمة المرور</button>',
    remote:'<div class="info-box"><b>الأجهزة المتصلة:</b><br>هذا الجهاز (المتصفح الحالي) - الآن<br><br>لتسجيل الخروج من جميع الأجهزة، اضغط الزر أدناه.</div><button class="save-btn" onclick="logoutAll()">تسجيل الخروج من كل الأجهزة</button>',
    storage:'<div class="info-box"><b>التخزين المستخدم:</b><br>المحادثات: <span id="sp-conv-count">0</span><br>الصور: <span id="sp-img-count">0</span><br><br>لتفريغ الكاش المحلي:</div><button class="save-btn" onclick="clearCache()">مسح الكاش</button>',
    privacy:'<div class="info-box"><b>سياسة الخصوصية:</b><br>• نحتفظ بمحادثاتك لتقديم خدمة أفضل.<br>• لا نشارك بياناتك مع أطراف ثالثة.<br>• يمكنك حذف بياناتك في أي وقت من "التحكم في البيانات".<br><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:block; padding:12px; background:var(--primary-color); color:#fff; text-decoration:none; border-radius:10px; font-weight:600; text-align:center;">📄 قراءة سياسة الخصوصية كاملة</a></div>',
    data:'<div class="info-box">يمكنك تصدير جميع بياناتك أو حذفها نهائياً.</div><button class="save-btn" onclick="exportData()">تصدير البيانات (JSON)</button><button class="save-btn" style="background:#d32f2f;" onclick="deleteMyAccount()">حذف كل البيانات</button>',
    ads:'<div class="field"><label>تخصيص الإعلانات</label><select id="sp-ads"><option value="personalized">مخصصة</option><option value="non-personalized">غير مخصصة</option></select></div><button class="save-btn" onclick="saveAds()">حفظ</button>',
    report:'<div class="field"><label>نوع المشكلة</label><select id="sp-report-type"><option>خطأ تقني</option><option>محتوى غير لائق</option><option>اقتراح</option><option>أخرى</option></select></div><div class="field"><label>الوصف</label><input type="text" id="sp-report-desc" placeholder="اشرح المشكلة..."></div><button class="save-btn" onclick="sendReport()">إرسال البلاغ</button>',
    about:'<div class="info-box"><b>نبراس GP</b><br>الإصدار 1.0<br><br>مساعد ذكي شخصي باللهجة العربية العامية.<br><br>© 2026 جميع الحقوق محفوظة.</div><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" style="display:flex;align-items:center;justify-content:center;gap:10px;padding:14px;background:linear-gradient(135deg,var(--primary-color) 0%,var(--primary-hover) 100%);color:#fff;text-decoration:none;border-radius:50px;font-weight:600;text-align:center;margin-top:14px;box-shadow:0 6px 18px rgba(74,106,138,0.25);font-size:14px;">📜 شروط الاستخدام</a><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:flex;align-items:center;justify-content:center;gap:10px;padding:14px;background:linear-gradient(135deg,var(--primary-color) 0%,var(--primary-hover) 100%);color:#fff;text-decoration:none;border-radius:50px;font-weight:600;text-align:center;margin-top:10px;box-shadow:0 6px 18px rgba(74,106,138,0.25);font-size:14px;">🔒 سياسة الخصوصية</a>'
};
function pickVoiceGender(g){isMale=(g==='male');const mBtn=document.getElementById('voice-male-btn');const fBtn=document.getElementById('voice-female-btn');if(mBtn)mBtn.classList.toggle('active',isMale);if(fBtn)fBtn.classList.toggle('active',!isMale);}
function selectLanguage(lang){userLang=lang;try{localStorage.setItem('nibras-lang',userLang);}catch(e){}applyLang();fetch('/update_language',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lang:userLang})}).catch(()=>{});document.querySelectorAll('.lang-card').forEach(c=>{c.classList.toggle('selected',c.dataset.lang===userLang);});const lbl=document.getElementById('currentLangLabel');if(lbl)lbl.textContent=userLang==='en'?'English':'العربية';showToast(userLang==='en'?'✅ Language: English':'✅ اللغة: العربية');}
function selectTheme(t){if(t==='system'){const prefersDark=window.matchMedia('(prefers-color-scheme: dark)').matches;setTheme(prefersDark?'dark':'light');}else{setTheme(t);}localStorage.setItem('nibras-theme-mode',t);markSelectedTheme(t);showToast('✅');}
function markSelectedTheme(t){document.querySelectorAll('.option-row').forEach(el=>{if(el.dataset.theme===t)el.classList.add('selected');else el.classList.remove('selected');});}
function selectColor(color,name){setAccentColor(color,name);markSelectedColor(color);showToast('✅ '+name);}
function markSelectedColor(color){document.querySelectorAll('.color-row').forEach(el=>{if(el.dataset.color===color)el.classList.add('selected');else el.classList.remove('selected');});}
function openSubPage(key){const titleMap={general:'عام',notifications:'الإشعارات',voice:'الصوت',safety:'السلامة',security:'الأمان وتسجيل الدخول',remote:'التحكم عن بُعد',storage:'التخزين',privacy:'مركز الخصوصية',data:'التحكم في البيانات',ads:'التحكم في الإعلانات',report:'الإبلاغ عن خطأ',about:'حول',theme:'المظهر',color:'لون التمييز',language:'اللغة / Language'};document.getElementById('subPageTitle').textContent=titleMap[key]||'إعدادات';document.getElementById('subPageBody').innerHTML=subPagesContent[key]||'<div class="info-box">قريباً</div>';document.getElementById('subPage').classList.add('show');if(key==='storage')loadStorageInfo();if(key==='color'){const c=localStorage.getItem('nibras-accent')||'#4a6a8a';setTimeout(()=>markSelectedColor(c),50);}if(key==='theme'){const t=localStorage.getItem('nibras-theme-mode')||'system';setTimeout(()=>markSelectedTheme(t),50);}if(key==='language'){setTimeout(()=>{document.querySelectorAll('.lang-card').forEach(c=>{c.classList.toggle('selected',c.dataset.lang===userLang);});},50);}if(key==='voice'){setTimeout(()=>{pickVoiceGender(isMale?'male':'female');const lvlInput=document.getElementById('sp-voice-level');if(lvlInput){const savedLvl=localStorage.getItem('nibras-voice-level')||'100';lvlInput.value=savedLvl;const span=document.getElementById('sp-voice-val');if(span)span.textContent=savedLvl+'%';}},50);}}
function closeSubPage(){document.getElementById('subPage').classList.remove('show');}
async function loadStorageInfo(){try{const r1=await fetch('/history');const d1=await r1.json();document.getElementById('sp-conv-count').textContent=(d1.conversations||[]).length;const r2=await fetch('/library/images');const d2=await r2.json();document.getElementById('sp-img-count').textContent=(d2.images||[]).length;}catch(e){}}
function saveGeneral(){const n=(document.getElementById('sp-name').value||'').trim();if(!n||n.length<2){showToast('اكتب اسم صحيح');return;}fetch('/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,lang:userLang})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('✅ تم الحفظ');closeSubPage();setTimeout(()=>location.reload(),500);}else showToast('فشل');});}
function urlBase64ToUint8Array(s){const p='='.repeat((4-s.length%4)%4);const b=(s+p).replace(/-/g,'+').replace(/_/g,'/');const r=window.atob(b);return Uint8Array.from([...r].map(c=>c.charCodeAt(0)));}
async function subscribeToPush(){if(!('serviceWorker' in navigator)||!('PushManager' in window)){showToast('المتصفح لا يدعم الإشعارات');return;}try{const reg=await navigator.serviceWorker.register('/service-worker.js');const perm=await Notification.requestPermission();if(perm!=='granted'){showToast('تم رفض الإشعارات');return;}const sub=await reg.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array('BLHwJhdfs5Gv_sPwVbbdct2kqOXF5uJo7CiCPawCs2GwaKf9P2-1pHvFfzCjmK4PEaqaE9OA5c_LyRhKtfpQ3q8')});const res=await fetch('/save_push_subscription',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sub)});if(res.ok)showToast('✅ تم تفعيل الإشعارات');else showToast('فشل الحفظ');}catch(err){console.error(err);showToast('فشل: '+err.message);}}
async function unsubscribeFromPush(){if(!('serviceWorker' in navigator)){showToast('المتصفح ما يدعم الإشعارات');return;}try{const reg=await navigator.serviceWorker.getRegistration('/service-worker.js');if(reg){const sub=await reg.pushManager.getSubscription();if(sub)await sub.unsubscribe();}await fetch('/remove_push_subscription',{method:'POST'});showToast('✅ تم إلغاء الإشعارات');}catch(err){console.error(err);showToast('فشل الإلغاء');}}
function requestNotifications(){subscribeToPush();}
function saveVoice(){const lvl=document.getElementById('sp-voice-level').value;const gender=isMale?'male':'female';localStorage.setItem('nibras-voice-level',lvl);localStorage.setItem('nibras-voice-gender',gender);fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:gender})}).then(()=>{showToast('✅ تم حفظ الإعدادات');closeSubPage();}).catch(()=>{showToast('✅ تم الحفظ محلياً');closeSubPage();});}
function changePassword(){const o=document.getElementById('sp-old-pass').value;const n=document.getElementById('sp-new-pass').value;if(!o){showToast('اكتب كلمة المرور الحالية');return;}if(!n||n.length<8){showToast('كلمة المرور الجديدة 8 أحرف على الأقل');return;}fetch('/change_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:o,new_password:n})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('✅ تم تغيير كلمة المرور');document.getElementById('sp-old-pass').value='';document.getElementById('sp-new-pass').value='';closeSubPage();}else{showToast('❌ '+(d.message||'فشل تغيير كلمة المرور'));}}).catch(()=>showToast('❌ تعذر الاتصال بالسيرفر'));}
function logoutAll(){if(confirm('خروج من كل الأجهزة؟')){fetch('/logout_all',{method:'POST'}).then(()=>window.location.href='/logout');}}
function clearCache(){if(!confirm('مسح الإعدادات المحلية؟'))return;localStorage.clear();sessionStorage.clear();document.documentElement.classList.remove('dark-mode');showToast('✅ تم المسح');setTimeout(()=>location.reload(),900);}
function exportData(){window.location.href='/export_data';}
function saveAds(){showToast('تم حفظ التفضيلات');closeSubPage();}
function sendReport(){const d=document.getElementById('sp-report-desc').value;if(!d||d.trim().length<3){showToast('اكتب وصف');return;}fetch('/report_bug',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:document.getElementById('sp-report-type').value,description:d})}).then(r=>r.json()).then(res=>{if(res.status==='ok'){showToast('✅ تم الإرسال');setTimeout(()=>closeSubPage(),800);}});}
async function loadPinned(){try{let pinned=[];if(IS_REGISTERED){const r=await fetch('/pinned_conversations');const d=await r.json();pinned=d.pinned||[];}else{const ids=getPinnedLocal();if(ids.length){const hr=await fetch('/history');const hd=await hr.json();pinned=(hd.conversations||[]).filter(c=>ids.includes(c.id));}}pl.innerHTML='';if(!pinned||pinned.length===0){pl.innerHTML='<div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;">'+(userLang==='en'?'No pinned conversations':'لا توجد محادثات مثبتة')+'</div>';if(!IS_REGISTERED){const hint=document.createElement('div');hint.style.cssText='padding:8px 16px 12px;font-size:12px;color:var(--text-secondary);text-align:center;line-height:1.6;';hint.innerHTML=userLang==='en'?'💡 <a href="/login" style="color:var(--primary-color);font-weight:600;text-decoration:none;">Sign in</a> to save pins permanently':'💡 <a href="/login" style="color:var(--primary-color);font-weight:600;text-decoration:none;">سجّل دخولك</a> لحفظ التثبيتات بشكل دائم';pl.appendChild(hint);}return;}pinned.forEach(c=>{const btn=document.createElement('button');btn.className='conv-item pinned-item';btn.innerHTML='<span class="conv-title">'+c.title+'</span>';btn.onclick=()=>loadConversation(c.id);pl.appendChild(btn);});}catch(e){}}
async function loadHistory(){try{const r=await fetch('/history');const d=await r.json();hl.innerHTML='';const localPinned=getPinnedLocal();if(d.conversations&&d.conversations.length>0){d.conversations.forEach(c=>{const isPinned=IS_REGISTERED?c.pinned:localPinned.includes(c.id);const b=document.createElement('div');b.className='conv-item';b.style.cursor='pointer';b.innerHTML='<span class="conv-title">'+((c.title&&c.title.trim())?c.title:'محادثة')+'</span><button class="pin-btn '+(isPinned?'pinned':'')+'" title="'+(isPinned?'إلغاء التثبيت':'تثبيت')+'"><svg viewBox="0 0 24 24"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg></button>';b.onclick=(e)=>{if(e.target.closest('.pin-btn'))return;loadConversation(c.id);};b.querySelector('.pin-btn').onclick=async(e)=>{e.stopPropagation();await togglePin(c.id,isPinned,e.currentTarget);};hl.appendChild(b);});}else{const e=document.createElement('div');e.className='item';e.style.color='var(--text-secondary)';e.style.fontSize='13px';e.style.justifyContent='center';e.textContent=userLang==='en'?'No conversations':'لا توجد محادثات';hl.appendChild(e);}}catch(e){}}
async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;d.messages.slice(-50).forEach(function(m){const s=m.role==='user'?'user':'bot';addMessage(m.content,s,!0)});dd.classList.remove('show')}}catch(e){}}
document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.style.display='none';ui.value=''});
document.querySelector('[data-action="share"]').addEventListener('click',function(e){
    e.stopPropagation();
    dd.classList.remove('show');
    const msgs = ch.slice(-20).map(function(m){
        return {r: m.role==='user'?'u':'b', c: String(m.content||'').slice(0,500)};
    }).filter(function(m){ return m.c; });
    if(!msgs || msgs.length===0){
        showToast(userLang==='en'?'No conversation to share':'لا توجد محادثة لمشاركتها');
        return;
    }
    const text = userLang==='en'?'Check out my conversation with Nibras':'شوف محادثتي مع نبراس';
    if(IS_REGISTERED && cid && !String(cid).startsWith('guest_conv_')){
        const dbUrl = window.location.origin + '/share/' + cid;
        document.getElementById('shareWhatsapp').href = 'https://wa.me/?text=' + encodeURIComponent(text + '\n' + dbUrl);
        document.getElementById('shareFacebook').href = 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(dbUrl);
        document.getElementById('shareTwitter').href  = 'https://twitter.com/intent/tweet?url=' + encodeURIComponent(dbUrl) + '&text=' + encodeURIComponent(text);
        document.getElementById('shareSnapchat').onclick = function(){
            navigator.clipboard.writeText(dbUrl).then(function(){ showToast(userLang==='en'?'✅ Link copied':'✅ تم نسخ الرابط'); }).catch(function(){ showToast(userLang==='en'?'Copy failed':'فشل النسخ'); });
        };
        sm.classList.add('show');
    } else {
        let url = '';
        try {
            const json = JSON.stringify(msgs);
            const encoded = btoa(unescape(encodeURIComponent(json)));
            url = window.location.origin + '/share/view#d=' + encodeURIComponent(encoded);
        } catch(err){
            showToast(userLang==='en'?'Failed to prepare link':'تعذر تجهيز الرابط');
            return;
        }
        if(url.length > 60000){
            showToast(userLang==='en'?'Conversation too long to share':'المحادثة طويلة جداً للمشاركة');
            return;
        }
        if(navigator.share){
            navigator.share({ title: userLang==='en'?'Nibras Conversation':'محادثة نبراس', text: text, url: url }).catch(function(){});
        } else {
            navigator.clipboard.writeText(url).then(function(){ showToast(userLang==='en'?'✅ Link copied':'✅ تم نسخ الرابط'); }).catch(function(){ showToast(userLang==='en'?'Copy failed':'فشل النسخ'); });
        }
    }
});
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function formatBotText(t){let s=escapeHtml(t);return s.split(/\n\s*\n/).map(p=>p.replace(/[\r\n]+/g,' ').trim()).filter(p=>p.length>0).join('<br><br>');}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function scrollToBottomSmooth(){if(!stickBottom)return;cb.scrollTop=cb.scrollHeight;}
function scrollMsgToTop(el){if(!el)return;requestAnimationFrame(function(){const r=el.getBoundingClientRect();const c=cb.getBoundingClientRect();cb.scrollTop=cb.scrollTop+(r.top-c.top)-8;});}
function isNearBottom(){return cb.scrollHeight-cb.scrollTop-cb.clientHeight<10;}
cb.addEventListener('scroll',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('touchmove',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('wheel',function(){stickBottom=isNearBottom();},{passive:true});
function attachBotActions(el,msgText){
    if(!el||el.querySelector('.msg-actions'))return;
    const actions=document.createElement('div');actions.className='msg-actions';
    actions.innerHTML=
        '<button class="act-like" title="إعجاب"><svg viewBox="0 0 24 24"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg></button>'+
        '<button class="act-dislike" title="عدم إعجاب"><svg viewBox="0 0 24 24"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg></button>'+
        '<button class="act-copy" title="نسخ"><svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2.5" ry="2.5"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg></button>'+
        '<button class="act-speak" title="استماع"><svg viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg></button>';
    el.appendChild(actions);
    const likeBtn=actions.querySelector('.act-like');
    const dislikeBtn=actions.querySelector('.act-dislike');
    const copyBtn=actions.querySelector('.act-copy');
    const speakBtn=actions.querySelector('.act-speak');
    likeBtn.addEventListener('click',function(){
        const wasLiked=this.classList.contains('liked');
        this.classList.toggle('liked',!wasLiked);
        dislikeBtn.classList.remove('disliked');
        actions.classList.add('touched');
        fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasLiked?'unlike':'like',message:msgText,conv_id:cid})}).catch(function(){});
        showToast(wasLiked?(userLang==='en'?'Like removed':'تم إلغاء الإعجاب'):(userLang==='en'?'👍 Thanks!':'👍 شكراً لتقييمك'));
    });
    dislikeBtn.addEventListener('click',function(){
        const wasDisliked=this.classList.contains('disliked');
        this.classList.toggle('disliked',!wasDisliked);
        likeBtn.classList.remove('liked');
        actions.classList.add('touched');
        fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasDisliked?'undislike':'dislike',message:msgText,conv_id:cid})}).catch(function(){});
        showToast(wasDisliked?(userLang==='en'?'Rating removed':'تم إلغاء التقييم'):(userLang==='en'?'👎 We will improve':'👎 رأيك مهم، بنتحسن'));
    });
    copyBtn.addEventListener('click',function(){
        navigator.clipboard.writeText(msgText).then(()=>{
            this.classList.add('copied');
            showToast(userLang==='en'?'✅ Copied':'✅ تم النسخ');
            const b=this;setTimeout(()=>b.classList.remove('copied'),1500);
        }).catch(()=>showToast(userLang==='en'?'Copy failed':'فشل النسخ'));
    });
    speakBtn.addEventListener('click',function(){
        const btn=this;
        if(btn.classList.contains('speaking')){
            if(ca){ca.pause();ca.currentTime=0;ca=null;}
            btn.classList.remove('speaking');
            return;
        }
        if(ca){ca.pause();ca.currentTime=0;ca=null;}
        btn.classList.add('speaking');
        fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:msgText})}).then(r=>r.json()).then(v=>{
            if(v.audio){
                const src='data:audio/mp3;base64,'+v.audio;
                ca=new Audio(src);
                ca.onended=function(){ca=null;btn.classList.remove('speaking');};
                ca.onerror=function(){btn.classList.remove('speaking');};
                const savedLvl=localStorage.getItem('nibras-voice-level');
                if(savedLvl)ca.volume=savedLvl/100;
                ca.play().catch(()=>btn.classList.remove('speaking'));
            }else{
                btn.classList.remove('speaking');
                showToast(userLang==='en'?'Playback failed':'فشل التشغيل');
            }
        }).catch(()=>{btn.classList.remove('speaking');showToast(userLang==='en'?'Connection failed':'فشل الاتصال');});
    });
}
function addMessage(t,s,isSys,img,imageUrl){
    s=s||'bot';isSys=isSys||false;
    const el=document.createElement('div');el.className='msg '+s;
    if(img){el.innerHTML='<img src="'+escapeHtml(img)+'" class="image-upload" />';cb.appendChild(el);if(stickBottom)cb.scrollTop=cb.scrollHeight;return el}
    let content=formatBotText(t);
    if(imageUrl){const safeUrl=escapeHtml(imageUrl);content+='<br><img src="'+safeUrl+'" class="generated-image" />';}
    el.innerHTML=content;
    if(s==='bot'&&!isSys){attachBotActions(el,t);}
    cb.appendChild(el);
    if(stickBottom)cb.scrollTop=cb.scrollHeight;
    return el;
}
function showImagePreview(d){ip.src=d;ipc.style.display='flex'}
function clearPending(){pid=null;ipc.style.display='none';ip.src=''}
rib.addEventListener('click',clearPending);
ui.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,80)+'px';const ums=cb.querySelectorAll('.msg.user');if(ums.length)scrollMsgToTop(ums[ums.length-1]);});
let poOpen=false;
pb.addEventListener('click',function(){poOpen=!poOpen;po.classList.toggle('show',poOpen);this.classList.toggle('rotate',poOpen)});
document.addEventListener('click',function(e){if(!pb.contains(e.target)&&!po.contains(e.target)){po.classList.remove('show');poOpen=false;pb.classList.remove('rotate')}});
gb.addEventListener('click',function(){fi.click();po.classList.remove('show')});
fi.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];fi.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
cab.addEventListener('click',function(){ci.click();po.classList.remove('show')});
ci.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];ci.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
async function sendMessage(){if(iw)return;const msgText=ui.value.trim(),img=pid;if(!msgText&&!img)return;let userMsgEl=null;if(msgText){userMsgEl=addMessage(msgText,'user');ch.push({role:'user',content:msgText});}if(img){userMsgEl=addMessage(userLang==='en'?'Image attached':'صورة مرفقة','user',false,img);ch.push({role:'user',content:userLang==='en'?'[Image attached]':'[صورة مرفقة]'});clearPending()}ui.value='';ui.style.height='auto';iw=true;const botEl=document.createElement('div');botEl.className='msg bot';botEl.innerHTML='<span class="typing-dots">'+tr('thinking')+'</span>';cb.appendChild(botEl);if(userMsgEl)scrollMsgToTop(userMsgEl);const payload={message:msgText||"مرفق",image:img||null,history:ch,conv_id:cid,lang:userLang};let displayText='';let bufferText='';let streamDone=false;let typingTimer=null;function tick(){if(bufferText.length>0){displayText+=bufferText.slice(0,1);bufferText=bufferText.slice(1);botEl.innerHTML=formatBotText(displayText);}if(bufferText.length===0&&streamDone){clearInterval(typingTimer);typingTimer=null;botEl.innerHTML=formatBotText(displayText);if(displayText&&displayText.trim().length>0){attachBotActions(botEl,displayText);ch.push({role:'assistant',content:displayText});}iw=false;if(voiceOn&&displayText&&displayText.length<1500){fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:displayText})}).then(r=>r.json()).then(v=>{if(v.audio){if(ca){ca.pause();ca.currentTime=0;}const src='data:audio/mp3;base64,'+v.audio;ca=new Audio(src);ca.onended=function(){ca=null;};const savedLvl=localStorage.getItem('nibras-voice-level');if(savedLvl)ca.volume=savedLvl/100;ca.play();}}).catch(()=>{});}}}typingTimer=setInterval(tick,15);try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){let errMsg='مشكلة';try{const d=await r.json();errMsg=d.error||d.message||'مشكلة';}catch(e){}clearInterval(typingTimer);botEl.remove();addMessage('خطأ: '+errMsg,'error');iw=false;return;}const reader=r.body.getReader();const decoder=new TextDecoder();let sseBuffer='';let firstToken=true;while(true){const {done,value}=await reader.read();if(done)break;sseBuffer+=decoder.decode(value,{stream:true});const parts=sseBuffer.split('\n\n');sseBuffer=parts.pop();for(const line of parts){if(!line.startsWith('data: '))continue;try{const data=JSON.parse(line.slice(6));if(data.token){if(firstToken){botEl.innerHTML='';firstToken=false;}bufferText+=data.token;}else if(data.done){if(data.conv_id)cid=data.conv_id;streamDone=true;}else if(data.error){bufferText+='\n\nخطأ: '+data.error;}}catch(e){}}}streamDone=true;}catch(e){clearInterval(typingTimer);if(botEl.parentNode)botEl.remove();addMessage(userLang==='en'?'Connection failed':'تعذر الاتصال','error');iw=false;}}
sb.addEventListener('click',sendMessage);
ui.addEventListener('keypress',function(e){if(e.key==='Enter'){e.preventDefault();sendMessage()}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
let recog=null;
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage(tr('micUnsupported'),'bot',true);return}if(this.classList.contains('listening')){this.classList.remove('listening');if(recog)recog.stop();return}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang=userLang==='en'?'en-US':'ar-SA';this.classList.add('listening');addMessage(tr('listening'),'bot',true);recog.onresult=function(e){const tr2=e.results[0][0].transcript;ui.value=tr2;mb.classList.remove('listening');setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove('listening')};recog.start()});
window.deleteMyAccount=function(){if(!confirm('حذف حسابك بالكامل؟'))return;fetch('/delete_my_account',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='success'){alert('تم الحذف');window.location.href='/'}});};
window.openSettings=openSettings;window.closeSettings=closeSettings;window.setTheme=setTheme;window.setAccentColor=setAccentColor;window.openSubPage=openSubPage;window.closeSubPage=closeSubPage;window.selectTheme=selectTheme;window.selectColor=selectColor;window.selectLanguage=selectLanguage;window.saveGeneral=saveGeneral;window.requestNotifications=requestNotifications;window.subscribeToPush=subscribeToPush;window.unsubscribeFromPush=unsubscribeFromPush;window.saveVoice=saveVoice;window.pickVoiceGender=pickVoiceGender;window.changePassword=changePassword;window.logoutAll=logoutAll;window.clearCache=clearCache;window.exportData=exportData;window.saveAds=saveAds;window.sendReport=sendReport;window.loadPinned=loadPinned;window.loadHistory=loadHistory;window.loadConversation=loadConversation;window.loadStorageInfo=loadStorageInfo;window.getContrastColor=getContrastColor;
applyLang();
})();</script></body></html>"""


# ==========================================================
#  Routes - الصفحات الرئيسية
# ==========================================================

@app.route('/')
def index():
    user_name = None
    email = session.get('user_email')
    is_registered = bool(email) or bool(session.get('is_admin'))
    user_lang = ''
    if email and not session.get('is_admin'):
        p = get_user_profile(email)
        if p:
            user_name = p.get("display_name") or email.split("@")[0]
        else:
            user_name = email.split("@")[0]
        mem = get_user_memory(email)
        if mem.get('name'):
            user_name = mem['name']
        lang_from_mem = mem.get('lang')
        if lang_from_mem in ('ar', 'en'):
            user_lang = lang_from_mem
    elif session.get('is_admin'):
        user_name = "أدمن"
    return render_template_string(HT, user_name=user_name, is_registered=is_registered, user_lang=user_lang)


@app.route('/library')
def library_page():
    if not session.get('user_email') and not session.get('is_admin'):
        return redirect(url_for('login'))
    return render_template_string(LIBRARY_HTML)


# ==========================================================
#  Routes - المكتبة
# ==========================================================

@app.route('/library/images')
def library_images():
    return jsonify({"images": get_user_images(get_user_id())})


@app.route('/library/upload', methods=['POST'])
def library_upload():
    try:
        if not session.get('user_email') and not session.get('is_admin'):
            return jsonify({"status": "error", "message": "يجب تسجيل الدخول"}), 401
        d = request.get_json(silent=True) or {}
        if not isinstance(d, dict):
            return jsonify({"status": "error", "message": "صيغة الطلب غير صحيحة"}), 400
        image_data = d.get('image_data') or ''
        if not isinstance(image_data, str) or len(image_data) > 7000000:
            return jsonify({"status": "error", "message": "الصورة كبيرة جداً (الحد 5MB)"}), 413
        if not image_data:
            return jsonify({"status": "error", "message": "لا توجد صورة"}), 400
        if not re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+", image_data):
            return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة"}), 400
        try:
            if len(base64.b64decode(image_data.split(",", 1)[1], validate=True)) > 5 * 1024 * 1024:
                return jsonify({"status": "error", "message": "الصورة كبيرة جداً (الحد 5MB)"}), 413
        except Exception:
            return jsonify({"status": "error", "message": "تعذر قراءة بيانات الصورة"}), 400
        title = d.get('title') if isinstance(d.get('title'), str) else "صورة"
        save_image_to_library(get_user_id(), image_data=image_data, title=title[:200] or "صورة", source="upload")
        return jsonify({"status": "ok"})
    except Exception as e:
        print("library_upload:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/library/delete', methods=['POST'])
def library_delete():
    try:
        d = request.get_json(silent=True) or {}
        ok = delete_user_image(get_user_id(), d.get('id'))
        if ok:
            return jsonify({"status": "ok"}), 200
        return jsonify({"status": "error"}), 404
    except Exception as e:
        print("library_delete:", e)
        return jsonify({"status": "error", "message": "حدث خطأ داخلي"}), 500


# ==========================================================
#  Routes - Push Notifications
# ==========================================================

@app.route('/save_push_subscription', methods=['POST'])
def save_push_subscription():
    try:
        sub = request.get_json(silent=True) or {}
        uid = get_user_id()
        sb.table("push_subscriptions").upsert({
            "user_id": uid,
            "endpoint": sub["endpoint"],
            "p256dh": sub["keys"]["p256dh"],
            "auth": sub["keys"]["auth"]
        }, on_conflict="endpoint").execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        print("save_push_subscription:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/remove_push_subscription', methods=['POST'])
def remove_push_subscription():
    try:
        uid = get_user_id()
        sb.table("push_subscriptions").delete().eq("user_id", uid).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        print("remove_push_subscription:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================================
#  Routes - المحادثات المثبتة
# ==========================================================

@app.route('/pinned_conversations')
def pinned_conversations():
    email = session.get('user_email')
    if not email:
        return jsonify({"pinned": []})
    pinned_ids = get_pinned_convs(email)
    if not pinned_ids:
        return jsonify({"pinned": []})
    all_convs = get_user_conversations(get_user_id())
    return jsonify({"pinned": [c for c in all_convs if c["id"] in pinned_ids]})


@app.route('/pin_conversation', methods=['POST'])
def pin_conversation():
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('conv_id')
    pinned = get_pinned_convs(email)
    if cid not in pinned:
        pinned.append(cid)
        save_pinned_convs(email, pinned)
    return jsonify({"status": "ok"})


@app.route('/unpin_conversation', methods=['POST'])
def unpin_conversation():
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('conv_id')
    pinned = get_pinned_convs(email)
    if cid in pinned:
        pinned.remove(cid)
        save_pinned_convs(email, pinned)
    return jsonify({"status": "ok"})


# ==========================================================
#  Routes - المحادثات
# ==========================================================

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
        if not isinstance(d, dict) or not isinstance(d.get('conv_id'), str) or not isinstance(d.get('index'), int):
            return jsonify({"status": "error", "message": "بيانات الحذف غير صحيحة"}), 400
        ok = delete_message_row(get_user_id(), d.get('conv_id'), d.get('index'))
        if ok:
            return jsonify({"status": "ok"}), 200
        return jsonify({"status": "error"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================================
#  Routes - الحساب
# ==========================================================

@app.route('/delete_my_account', methods=['POST'])
def delete_my_account():
    email = session.get('user_email')
    if not email or session.get('is_admin'):
        return jsonify({"status": "error"}), 400
    uid = get_user_id()
    try:
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not service_key:
            return jsonify({"status": "error", "message": "حذف الحساب الكامل غير مُعدّ على الخادم. تواصل مع الإدارة."}), 503
        auth_user_id = None
        for page in range(1, 101):
            ar = requests.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                params={"page": page, "per_page": 100}, timeout=15
            )
            ar.raise_for_status()
            users_payload = ar.json()
            auth_users = users_payload.get("users", []) if isinstance(users_payload, dict) else []
            for auth_user in auth_users:
                if (auth_user.get("email") or "").lower() == email.lower():
                    auth_user_id = auth_user.get("id")
                    break
            if auth_user_id or len(auth_users) < 100:
                break
        if not auth_user_id:
            return jsonify({"status": "error", "message": "لم يتم العثور على حساب المصادقة؛ لم تُحذف البيانات."}), 404
        sb.table("assistant_chats").delete().eq("user_id", uid).execute()
        sb.table("assistant_usage").delete().eq("user_id", uid).execute()
        sb.table("image_library").delete().eq("user_id", uid).execute()
        sb.table("push_subscriptions").delete().eq("user_id", uid).execute()
        sb.table("profiles").delete().eq("email", email.lower()).execute()
        dr = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{auth_user_id}",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}, timeout=15
        )
        dr.raise_for_status()
    except Exception as e:
        print("delete_my_account:", e)
        return jsonify({"status": "error", "message": "تعذر إكمال حذف الحساب. راجع سجلات الخادم."}), 500
    session.clear()
    return jsonify({"status": "success"}), 200


@app.route('/update_profile', methods=['POST'])
def update_profile():
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    lang = d.get('lang')
    if not name or len(name) < 2:
        return jsonify({"status": "error"}), 400
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401
    save_user_profile(email, name=name)
    mem = get_user_memory(email) or {}
    mem['name'] = name
    if lang in ('ar', 'en'):
        mem['lang'] = lang
    save_user_memory(email, mem)
    return jsonify({"status": "ok"})


@app.route('/update_language', methods=['POST'])
def update_language():
    d = request.get_json(silent=True) or {}
    lang = d.get('lang')
    if lang not in ('ar', 'en'):
        return jsonify({"status": "error"}), 400
    email = session.get('user_email')
    if email:
        try:
            mem = get_user_memory(email) or {}
            mem['lang'] = lang
            save_user_memory(email, mem)
        except Exception as e:
            print("update_language:", e)
    return jsonify({"status": "ok"})


@app.route('/change_password', methods=['POST'])
def change_password():
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401
    d = request.get_json(silent=True) or {}
    oldp = d.get('old_password', '')
    newp = d.get('new_password', '')
    if not oldp:
        return jsonify({"status": "error", "message": "اكتب كلمة المرور الحالية"}), 400
    if not newp or len(newp) < 8:
        return jsonify({"status": "error", "message": "كلمة المرور الجديدة لازم 8 أحرف على الأقل"}), 400

    print(f"change_password: user={email} old_len={len(oldp)} new_len={len(newp)}")

    try:
        r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": oldp}, timeout=15)
    except Exception as e:
        print(f"change_password: login request error: {e}")
        return jsonify({"status": "error", "message": "تعذر الاتصال بخدمة المصادقة"}), 500

    print(f"change_password: login status={r.status_code} body={r.text[:300]}")

    if r.status_code != 200:
        msg = "كلمة المرور الحالية غير صحيحة"
        try:
            err = r.json()
            raw = err.get("error_description") or err.get("msg") or err.get("error") or ""
            rl = str(raw).lower()
            if "rate" in rl or "too many" in rl:
                msg = "حاولت عدة مرات — انتظر دقيقة ثم أعد المحاولة"
            elif "email" in rl and "confirm" in rl:
                msg = "حسابك غير مؤكد — افتح إيميلك واضغط رابط التأكيد"
            elif "invalid" in rl and "grant" in rl:
                msg = "البريد أو كلمة المرور الحالية غير صحيحة"
            elif raw:
                msg = str(raw)
        except Exception:
            pass
        return jsonify({"status": "error", "message": msg}), 400

    at = r.json().get('access_token')
    if not at:
        return jsonify({"status": "error", "message": "تعذر إنشاء الجلسة"}), 500

    try:
        r2 = requests.put(f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {at}",
                "Content-Type": "application/json"
            },
            json={"password": newp}, timeout=15)
        print(f"change_password: update status={r2.status_code} body={r2.text[:300]}")
    except Exception as e:
        print(f"change_password: update request error: {e}")
        return jsonify({"status": "error", "message": "تعذر تحديث كلمة المرور"}), 500

    if r2.status_code == 200:
        return jsonify({"status": "ok"}), 200

    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if service_key:
        try:
            auth_user_id = None
            for page in range(1, 11):
                ar = requests.get(
                    f"{SUPABASE_URL}/auth/v1/admin/users",
                    headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                    params={"page": page, "per_page": 100}, timeout=15
                )
                if ar.status_code != 200:
                    break
                payload = ar.json()
                users = payload.get("users", []) if isinstance(payload, dict) else []
                for u in users:
                    if (u.get("email") or "").lower() == email.lower():
                        auth_user_id = u.get("id")
                        break
                if auth_user_id or len(users) < 100:
                    break

            if auth_user_id:
                ur = requests.put(
                    f"{SUPABASE_URL}/auth/v1/admin/users/{auth_user_id}",
                    headers={"apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Type": "application/json"},
                    json={"password": newp}, timeout=15
                )
                print(f"change_password: admin update status={ur.status_code} body={ur.text[:300]}")
                if ur.status_code == 200:
                    return jsonify({"status": "ok"}), 200
        except Exception as e:
            print(f"change_password: admin fallback error: {e}")

    err_msg = "تعذر تغيير كلمة المرور"
    try:
        e2 = r2.json()
        err_msg = e2.get("msg") or e2.get("message") or e2.get("error_description") or err_msg
    except Exception:
        pass
    return jsonify({"status": "error", "message": err_msg}), 400


@app.route('/export_data')
def export_data():
    email = session.get('user_email')
    if not email:
        return "يجب تسجيل الدخول", 401
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
        if not desc or len(desc) < 3:
            return jsonify({"status": "error"}), 400
        sb.table("bug_reports").insert({
            "user_email": session.get('user_email', 'ضيف'),
            "user_role": session.get('user_role', 'guest'),
            "type": d.get('type', 'غير محدد'),
            "description": desc
        }).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/logout_all', methods=['POST'])
def logout_all():
    session.clear()
    return jsonify({"status": "ok"})


# ==========================================================
#  Routes - تقييمات الردود
# ==========================================================

@app.route('/feedback', methods=['POST'])
def feedback():
    try:
        d = request.get_json(silent=True) or {}
        ftype = d.get('type')
        if ftype not in ('like', 'dislike', 'unlike', 'undislike'):
            return jsonify({"status": "error"}), 400
        sb.table("message_feedback").insert({
            "user_id": get_user_id(),
            "user_email": session.get('user_email', 'guest'),
            "conv_id": d.get('conv_id') or '',
            "message_text": (d.get('message') or '')[:1000],
            "feedback": ftype
        }).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        print("feedback:", e)
        return jsonify({"status": "error"}), 500


# ==========================================================
#  Routes - المشاركة
# ==========================================================

@app.route('/share/view')
def shared_view():
    return render_template_string(SHARED_VIEW_HTML)


@app.route('/share/<cid>')
def shared_conversation(cid):
    rows = load_conversation_public(cid)
    if not rows:
        return "المحادثة غير موجودة.", 404
    msgs = []
    title = "محادثة نبراس"
    for i, row in enumerate(rows):
        if i == 0 and row.get("title"):
            title = row["title"]
        if row.get("message"):
            msgs.append({"role": "user", "content": row["message"]})
        if row.get("response"):
            msgs.append({"role": "assistant", "content": row["response"]})
    return render_template_string(SPH, messages=msgs, title=title)


# ==========================================================
#  Routes - المصادقة
# ==========================================================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'POST':
        e = request.form.get('email', '').strip().lower()
        p = request.form.get('password', '')
        ap = os.environ.get("ADMIN_PASSWORD")
        if not e or "@" not in e:
            return render_template_string(LH, error="بريد صحيح مطلوب.")
        if e == ADMIN_EMAIL.lower():
            if not ap or not secrets.compare_digest(p, ap):
                return render_template_string(LH, error="كلمة مرور الأدمن غير صحيحة.")
            session.clear()
            session.permanent = True
            session['user_email'] = e
            session['is_admin'] = True
            session['user_role'] = 'admin'
            return redirect(url_for('index'))
        try:
            r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
                json={"email": e, "password": p}, timeout=15)
        except:
            return render_template_string(LH, error="تعذر الاتصال.")
        if r.status_code != 200:
            return render_template_string(LH, error="البريد أو كلمة المرور غير صحيحة.")
        data = r.json()
        session.clear()
        session.permanent = True
        session['user_email'] = e
        session['is_admin'] = False
        session['access_token'] = data.get('access_token')
        session['refresh_token'] = data.get('refresh_token')
        session['user_role'] = get_user_role(e)
        touch_user(e)
        return redirect(url_for('index'))
    return render_template_string(LH)


@app.route('/signup', methods=['POST'])
@limiter.limit("5 per hour")
def signup():
    e = request.form.get('email', '').strip().lower()
    p = request.form.get('password', '')
    name = request.form.get('name', '').strip()
    if not e or "@" not in e or len(p) < 8:
        return render_template_string(LH, error="بيانات غير صحيحة.")
    if not name or len(name) < 2:
        return render_template_string(LH, error="الاسم مطلوب.")
    try:
        sb.auth.sign_up({"email": e, "password": p, "options": {"email_redirect_to": f"{request.host_url.rstrip('/')}/verified", "data": {"display_name": name}}})
        save_user_profile(e, name=name)
        save_user_memory(e, {"name": name})
        return render_template_string(LH, success="تم إنشاء حسابك! افتح بريدك للتأكيد.")
    except Exception as ex:
        return render_template_string(LH, error=f"فشل: {ex}")


@app.route('/verified')
def verified():
    return """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><title>تم التحقق</title></head><body style="text-align:center;padding:50px;font-family:sans-serif;"><h2>تم تأكيد حسابك!</h2><a href="/login">تسجيل الدخول</a></body></html>"""


@app.route('/recover', methods=['POST'])
@limiter.limit("5 per hour")
def recover():
    e = request.form.get('email', '').strip().lower()
    if not e or "@" not in e:
        return render_template_string(LH, error="أدخل بريداً صحيحاً.")
    try:
        requests.post(f"{SUPABASE_URL}/auth/v1/recover", headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"}, json={"email": e}, timeout=15)
        return render_template_string(LH, success="تم إرسال رابط الاستعادة.")
    except Exception as ex:
        return render_template_string(LH, error=f"فشل: {ex}")


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ==========================================================
#  Routes - الأدمن
# ==========================================================

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        p = request.form.get('password', '')
        ap = os.environ.get("ADMIN_PASSWORD")
        if ap and secrets.compare_digest(p, ap):
            session['is_admin'] = True
            session.permanent = True
            return redirect(url_for('admin_dashboard'))
        return "<h2>كلمة مرور خاطئة</h2>"
    return """<body style='text-align:center;padding:50px;font-family:sans-serif;'><form method='POST'><h2>دخول الأدمن</h2><input type='password' name='password' required><br><br><button type='submit'>دخول</button></form></body>"""


@app.route('/admin/send_notification', methods=['POST'])
def admin_send_notification():
    if not session.get('is_admin'):
        return jsonify({"status": "error", "message": "غير مصرح"}), 401
    try:
        d = request.get_json(silent=True) or {}
        if not isinstance(d, dict):
            return jsonify({"status": "error", "message": "صيغة الطلب غير صحيحة"}), 400
        title = (d.get('title') if isinstance(d.get('title'), str) else 'نبراس').strip()[:120]
        body = (d.get('body') if isinstance(d.get('body'), str) else '').strip()[:2000]
        if not body:
            return jsonify({"status": "error", "message": "الرسالة فاضية"}), 400
        subs = sb.table("push_subscriptions").select("user_id").execute()
        user_ids = list({s["user_id"] for s in (subs.data or [])})
        sent = send_push_to_all(user_ids, title, body)
        total = len((sb.table("push_subscriptions").select("id").execute()).data or [])
        return jsonify({"status": "ok", "sent": sent, "total": total})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    try:
        recent = (sb.table("assistant_chats").select("user_id,title,created_at").order("created_at", desc=True).limit(10).execute()).data or []
        users_list = (sb.table("profiles").select("email,display_name,role").order("created_at", desc=True).limit(30).execute()).data or []
        reports_list = (sb.table("bug_reports").select("*").order("created_at", desc=True).limit(30).execute()).data or []
        subs_count = len((sb.table("push_subscriptions").select("id").execute()).data or [])
        feedback_list = (sb.table("message_feedback").select("*").order("created_at", desc=True).limit(100).execute()).data or []
    except:
        recent, users_list, reports_list, subs_count, feedback_list = [], [], [], 0, []

    likes_count = sum(1 for f in feedback_list if f.get('feedback') == 'like')
    dislikes_count = sum(1 for f in feedback_list if f.get('feedback') == 'dislike')

    recent_html = "".join([f'<div class="conv-item"><b>{escape(str(r.get("title", "?")))}</b><small>{escape(str(r.get("user_id", ""))[:30])}</small></div>' for r in recent]) or "<p style='color:#8b949e;'>لا توجد</p>"
    users_html = "".join([f'<div class="conv-item"><b>{escape(str(u.get("display_name", "?")))}</b><small>{escape(str(u.get("email", "")))} ({escape(str(u.get("role", "user")))})</small></div>' for u in users_list]) or "<p style='color:#8b949e;'>لا يوجد</p>"
    reports_html = "".join([f'<div style="border-right:3px solid #e74c3c;padding:10px;margin:8px 0;background:#fff5f5;border-radius:8px;"><b>[{escape(str(r.get("type", "?")))}]</b> {escape(str(r.get("user_email", "?")))}<br><small>{escape(str(r.get("description", "")))}</small></div>' for r in reports_list]) or "<p style='color:#8b949e;'>لا توجد</p>"

    feedback_html = "".join([
        f'<div style="border-right:4px solid {"#27ae60" if f.get("feedback")=="like" else "#e74c3c"};padding:12px;margin:10px 0;background:{"#f0fdf4" if f.get("feedback")=="like" else "#fef2f2"};border-radius:10px;">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
        f'<b style="color:{"#27ae60" if f.get("feedback")=="like" else "#e74c3c"};font-size:14px;">'
        f'{"👍 إعجاب" if f.get("feedback")=="like" else "👎 رفض"}</b>'
        f'<small style="color:#8b949e;font-size:11px;">{escape(str(f.get("created_at",""))[:16])}</small>'
        f'</div>'
        f'<div style="font-size:12px;color:#5a6b7c;margin-bottom:6px;">'
        f'👤 {escape(str(f.get("user_email","?")))}'
        f'</div>'
        f'<div style="font-size:13px;color:#1a2b3c;background:#fff;padding:8px 10px;border-radius:6px;line-height:1.6;">'
        f'{escape(str(f.get("message_text",""))[:250])}'
        f'</div>'
        f'</div>'
        for f in feedback_list if f.get('feedback') in ('like', 'dislike')
    ]) or "<p style='color:#8b949e;text-align:center;padding:20px;'>لا توجد تقييمات بعد</p>"

    return f"""<!DOCTYPE html><html dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>لوحة الأدمن</title><style>
    *{{box-sizing:border-box}}
    body{{font-family:'Segoe UI',Tahoma,sans-serif;padding:16px;background:#f4f7fc;color:#1a2b3c;margin:0}}
    .container{{max-width:700px;margin:auto}}
    h1{{color:#4a6a8a;text-align:center;font-size:22px}}
    h3{{color:#1a2b3c;font-size:16px;margin:0 0 12px}}
    .card{{background:#fff;padding:18px;margin:15px 0;border-radius:15px;box-shadow:0 4px 16px rgba(0,0,0,0.04)}}
    .stat{{display:flex;justify-content:space-between;padding:10px 0;border-bottom:1px solid #eef1f6}}
    .stat:last-child{{border:none}}
    .num{{color:#4a6a8a;font-weight:bold;font-size:18px}}
    .conv-item{{padding:10px 0;border-bottom:1px solid #eef1f6}}
    .conv-item:last-child{{border:none}}
    .conv-item b{{font-size:14px}}
    .conv-item small{{color:#8b949e;display:block;font-size:12px;margin-top:2px}}
    .back{{display:block;text-align:center;color:#4a6a8a;text-decoration:none;margin-top:24px;font-weight:600;padding:12px;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.05)}}
    .notif-input{{width:100%;padding:12px;margin:6px 0;border:1px solid #dce1e8;border-radius:10px;font-family:inherit;font-size:14px;outline:none}}
    .notif-input:focus{{border-color:#4a6a8a}}
    .notif-btn{{background:#4a6a8a;color:#fff;border:none;padding:12px 30px;border-radius:10px;cursor:pointer;font-weight:600;font-family:inherit;font-size:15px}}
    .notif-btn:hover{{background:#3a5a7a}}
    </style></head><body><div class="container">

    <h1>🎛️ لوحة تحكم نبراس</h1>

    <div class="card">
        <h3>📢 إرسال إشعار يدوي</h3>
        <input type="text" id="notif-title" class="notif-input" placeholder="العنوان" value="نبراس">
        <textarea id="notif-body" class="notif-input" placeholder="اكتب الرسالة..." style="min-height:80px;"></textarea>
        <button onclick="sendNotif()" class="notif-btn">📤 إرسال للجميع</button>
        <div id="notif-result" style="margin-top:10px;font-size:13px;"></div>
    </div>

    <div class="card">
        <div class="stat"><span>👥 المستخدمون</span><span class="num">{len(users_list)}</span></div>
        <div class="stat"><span>🔔 المشتركون بالإشعارات</span><span class="num">{subs_count}</span></div>
        <div class="stat"><span>📩 البلاغات</span><span class="num">{len(reports_list)}</span></div>
        <div class="stat"><span>👍 إعجابات</span><span class="num" style="color:#27ae60;">{likes_count}</span></div>
        <div class="stat"><span>👎 رفض</span><span class="num" style="color:#e74c3c;">{dislikes_count}</span></div>
    </div>

    <div class="card"><h3>📊 تقييمات الردود ({likes_count + dislikes_count})</h3>{feedback_html}</div>
    <div class="card"><h3>📩 البلاغات</h3>{reports_html}</div>
    <div class="card"><h3>👥 المستخدمون</h3>{users_html}</div>
    <div class="card"><h3>💬 آخر المحادثات</h3>{recent_html}</div>

    <a href="/" class="back">← العودة للرئيسية</a>
    </div>

    <script>
    async function sendNotif(){{
        const title = document.getElementById('notif-title').value.trim() || 'نبراس';
        const body = document.getElementById('notif-body').value.trim();
        if(!body){{ alert('اكتب الرسالة أول'); return; }}
        if(!confirm('إرسال الإشعار لكل المشتركين؟')) return;
        const res = document.getElementById('notif-result');
        res.textContent = '⏳ جاري الإرسال...';
        res.style.color = '#4a6a8a';
        try{{
            const r = await fetch('/admin/send_notification', {{
                method:'POST',
                headers:{{'Content-Type':'application/json'}},
                body: JSON.stringify({{title: title, body: body}})
            }});
            const d = await r.json();
            if(d.status === 'ok'){{
                res.textContent = '✅ تم الإرسال لـ ' + d.sent + ' من ' + d.total;
                res.style.color = '#27ae60';
                document.getElementById('notif-body').value = '';
            }} else {{
                res.textContent = '❌ ' + (d.message || 'فشل');
                res.style.color = '#e74c3c';
            }}
        }}catch(e){{
            res.textContent = '❌ خطأ في الاتصال';
            res.style.color = '#e74c3c';
        }}
    }}
    </script>
    </body></html>"""


# ==========================================================
#  Routes - الصوت والمحادثة
# ==========================================================

@app.route('/set_gender', methods=['POST'])
def set_gender():
    session['voice_gender'] = request.get_json(silent=True) or {}.get('gender', 'male')
    return jsonify({"status": "ok"})


@app.route('/voice', methods=['POST'])
@limiter.limit("30 per minute")
def voice():
    try:
        d = request.get_json(silent=True) or {}
        text = (d.get('text') or "").strip()
        if not text or len(text) > 3000:
            return jsonify({"audio": None})
        return jsonify({"audio": generate_speech(text, session.get('voice_gender', 'male'))})
    except Exception as e:
        print(f"voice: {e}")
        return jsonify({"audio": None})


@app.route('/chat', methods=['POST'])
@limiter.limit("20 per minute")
def chat():
    try:
        d = request.get_json(silent=True) or {}
        if not isinstance(d, dict):
            return jsonify({"status": "error", "message": "صيغة الطلب غير صحيحة"}), 400
        raw_message = d.get("message", "")
        if not isinstance(raw_message, str):
            return jsonify({"status": "error", "message": "نص الرسالة غير صالح"}), 400
        um = raw_message.strip()
        cid = d.get("conv_id")
        img_data = d.get("image")
        if len(um) > 12000:
            return jsonify({"status": "error", "message": "الرسالة طويلة جدًا (الحد 12000 حرف)"}), 413
        if not um and not img_data:
            return jsonify({"reply": "اكتب شيء أساعدك فيه أو أرفق صورة"})
        is_admin = bool(session.get('is_admin'))
        user_email = session.get('user_email', '')
        user_role = get_user_role(user_email) if user_email else 'guest'
        is_registered = is_admin or (bool(user_email) and user_role in ('user', 'admin'))
        uid = get_user_id()

        lang_from_payload = d.get("lang")
        if lang_from_payload in ('ar', 'en'):
            user_lang = lang_from_payload
        elif user_email:
            user_lang = get_user_language(user_email)
        else:
            user_lang = 'ar'

        usage, limits, can_chat, can_search, can_image = check_limits(uid, user_role if not is_admin else 'admin')
        if not can_chat:
            reply_limit = "وصل محادثاتك للحد اليومي المسموح به، شكراً لك، غداً نلتقي 🌹" if user_lang == 'ar' else "You've reached the daily limit. Thank you, see you tomorrow 🌹"
            nid = save_message(uid, um, reply_limit, cid) if is_registered else cid
            def limit_stream():
                yield f"data: {json.dumps({'token': reply_limit}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'done': True, 'conv_id': nid or cid or ''}, ensure_ascii=False)}\n\n"
            return Response(
                stream_with_context(limit_stream()),
                mimetype='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
            )
        if is_registered and user_email:
            try: touch_user(user_email)
            except: pass
        has_image = img_data is not None
        if has_image:
            if not isinstance(img_data, str) or len(img_data) > 7000000 or not re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+", img_data):
                return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة أو حجمها كبير"}), 400
            try:
                encoded = img_data.split(",", 1)[1]
                if len(base64.b64decode(encoded, validate=True)) > 5 * 1024 * 1024:
                    return jsonify({"status": "error", "message": "حجم الصورة يتجاوز 5MB"}), 413
            except Exception:
                return jsonify({"status": "error", "message": "تعذر قراءة بيانات الصورة"}), 400
            if not is_registered:
                msg = "تحليل الصور للمسجلين فقط." if user_lang == 'ar' else "Image analysis is for registered users only."
                return jsonify({"reply": msg, "conv_id": cid})
            if not can_image:
                msg = "وصلت للحد اليومي للصور." if user_lang == 'ar' else "You've reached the daily image limit."
                nid = save_message(uid, um, msg, cid)
                inc_usage(uid, "chat_count")
                return jsonify({"reply": msg, "conv_id": nid})
        user_memory = get_user_memory(user_email) if user_email else {}
        memory_context = ""
        if user_memory.get('name'):
            memory_context = f"\n\n**معلومات المستخدم:**\nاسم المستخدم: {user_memory['name']}"

        if is_registered:
            server_hist = load_conversation(uid, cid) or []
        else:
            server_hist = []
            client_hist = d.get("history") or []
            if isinstance(client_hist, list):
                items = client_hist
                if items and isinstance(items[-1], dict) and items[-1].get("role") == "user":
                    items = items[:-1]
                for h in items[-15:]:
                    if (isinstance(h, dict)
                        and h.get("role") in ("user", "assistant")
                        and isinstance(h.get("content"), str)):
                        server_hist.append({
                            "role": h["role"],
                            "content": h["content"][:2000]
                        })

        if img_data and is_registered and can_image:
            user_content = [
                {"type": "text", "text": um or "حلل الصورة"},
                {"type": "image_url", "image_url": {"url": img_data}}
            ]
            server_hist.append({"role": "user", "content": user_content})
        else:
            server_hist.append({"role": "user", "content": um})

        lang_inst = LANG_INSTRUCTION.get(user_lang, "")
        msgs = [{"role": "system", "content": SP + memory_context + lang_inst}] + server_hist[-15:]

        if is_registered and can_search:
            inc_usage(uid, "search_count")
            try:
                sr = client.responses.create(model=OPENAI_MODEL, instructions=SP, input=f"ابحث عن أحدث المعلومات: {um}", tools=[{"type": "web_search"}])
                res = ""
                if hasattr(sr, "output_text") and sr.output_text:
                    res = sr.output_text.strip()
                elif getattr(sr, "output", None):
                    try: res = sr.output[0].content[0].text
                    except: res = ""
                if res:
                    msgs.append({"role": "user", "content": f"نتيجة البحث:\n{res}"})
                    print(f"✅ بحث ناجح - {len(res)} حرف")
            except Exception as e:
                print(f"❌ فشل البحث ({type(e).__name__}): {e}")

        def generate():
            full_reply = ""
            try:
                stream = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=msgs,
                    max_completion_tokens=8000,
                    stream=True
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        token = chunk.choices[0].delta.content
                        full_reply += token
                        yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"

                cleaned = '\n\n'.join([
                    ' '.join(l.strip() for l in block.split('\n') if l.strip())
                    for block in full_reply.split('\n\n') if block.strip()
                ]) or ("ما قدرت أجيب رد." if user_lang == 'ar' else "I couldn't generate a response.")

                nid = cid
                if is_registered:
                    nid = save_message(uid, um or "[صورة مرفقة]", cleaned, cid)
                    if not is_admin:
                        try: send_push_to_user(uid, "نبراس - رد جديد", cleaned[:120])
                        except Exception as pe: print("push send:", pe)
                else:
                    if not nid:
                        nid = "guest_conv_" + secrets.token_hex(5)
                inc_usage(uid, "chat_count")
                if has_image and is_registered and can_image:
                    inc_usage(uid, "image_count")

                yield f"data: {json.dumps({'done': True, 'conv_id': nid})}\n\n"
            except Exception as e:
                print("stream error:", repr(e))
                safe_error = "تعذر إكمال الطلب. حاول مرة أخرى." if user_lang == "ar" else "The request failed. Please try again."
                yield f"data: {json.dumps({'error': safe_error}, ensure_ascii=False)}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )
    except Exception as e:
        print("chat request error:", repr(e))
        return jsonify({"status": "error", "message": "حدث خطأ داخلي أثناء معالجة الطلب"}), 500


# ==========================================================
#  تشغيل التطبيق
# ==========================================================

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
