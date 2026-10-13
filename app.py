# ═══════════════════════════════════════════════════════════
#  القسم 1/8 — Imports + إعدادات Flask
# ═══════════════════════════════════════════════════════════

from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, send_from_directory,
    Response, stream_with_context
)
import openai, os, secrets, json, asyncio, base64, re, requests, time
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from markupsafe import escape
import io
import urllib.parse
from gtts import gTTS


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
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_NAME='nibras_session',
    SESSION_COOKIE_DOMAIN=None
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
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


LIMITS = {
    "guest": {"chat": 15,  "search": 0,   "image": 0},
    "user":  {"chat": 15,  "search": 2,   "image": 1},
    "admin": {"chat": 9999, "search": 9999, "image": 9999},
}


def get_user_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return get_remote_address()


limiter = Limiter(
    key_func=get_user_ip,
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

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 1
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 2/8 — دوال المستخدم الأساسية
# ═══════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 2
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 3/8 — نظام أكواد الوصول
# ═══════════════════════════════════════════════════════════

def get_active_access(email):
    """يرجع كود الوصول النشط للمستخدم (مع فحص يدوي للتاريخ)"""
    if not email:
        return None
    try:
        r = (sb.table("access_redemptions").select("*")
             .eq("user_email", email.lower())
             .order("expires_at", desc=True).limit(1).execute())
        if r and r.data:
            row = r.data[0]
            expires = row.get('expires_at')
            if expires:
                try:
                    exp_str = str(expires).replace('Z', '').replace('+00:00', '')
                    if '.' in exp_str:
                        exp_str = exp_str.split('.')[0]
                    exp = datetime.fromisoformat(exp_str)
                    if exp >= datetime.utcnow():
                        return row
                    else:
                        print(f"⚠️ Access expired for {email}: {exp}")
                        return None
                except Exception as ex:
                    print(f"⚠️ Date parse error: {ex}, raw: {expires}")
                    return None
            return row
    except Exception as e:
        print("get_active_access:", e)
    return None


def check_limits(uid, role, email=None):
    usage = get_usage_today(uid)
    access = get_active_access(email) if email else None
    if access:
        limits = {
            "chat": int(access.get("chat_limit", 15) or 15),
            "search": int(access.get("search_limit", 2) or 2),
            "image": int(access.get("image_limit", 1) or 1)
        }
    else:
        limits = LIMITS.get(role, LIMITS["guest"])
    can_chat = int(usage.get("chat_count", 0) or 0) < limits["chat"]
    can_search = int(usage.get("search_count", 0) or 0) < limits["search"]
    can_image = int(usage.get("image_count", 0) or 0) < limits["image"]
    return usage, limits, can_chat, can_search, can_image

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 3
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 4/8 — دوال المحادثات والصور
# ═══════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 4
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 5/8 — SP + الشخصيات + الصوت
# ═══════════════════════════════════════════════════════════

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


SP = f"""أنت "نبراس"، مساعد شخصي سعودي تتكلم **عامي سعودي بسيط** — مو فصحى أبدًا.

**⚠️ قاعدة اللغة الأهم:**
- **ممنوع** تستخدم الفصحى إلا في كلمات ضرورية (أسماء تقنية).
- تكلم زي ما يتكلم سعودي عادي في الواتساب: "وش"، "كيف"، "أبشر"، "خلني"، "تبي"، "الحين"، "زين"، "طيب".
- **مثال صح:** "الذكاء الاصطناعي تقنية تخلي الجوال يفهمك."
- **مثال خطأ:** "الذكاء الاصطناعي هو فرع من فروع علوم الحاسب..."

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه).
2. **معرفتك العامة**.
3. **البحث بالويب** عند الحاجة.

**ملف المعرفة:**
{kc}

**قاعدة التنسيق:**
- اكتب فقرات متصلة (2-4 جمل).
- الفاصل الوحيد سطر فارغ بين الفقرات.

**قاعدة صوتية:**
- استخدم الإيموجي مباشرة بدون وصفها بالكلام.

**قواعد الهوية:**
- أنت "نبراس" فقط. لا تذكر أي شركة أو تطبيق آخر.
- إذا سُئلت "من صنعك؟" رد: "أنا نبراس، مساعدك الشخصي".

**أسلوب الحديث:**
- سولف بعفوية وبالعامي.
- لا تذكر حفظ المحادثات أو الذاكرة.
- رد مباشر بدون مقدمات فلسفية."""


LANG_INSTRUCTION = {
    "ar": "\n\n**اللغة:** رد دائماً بالعربية بالعامية السعودية البسيطة.",
    "en": "\n\n**Language:** ALWAYS respond in English, regardless of the language the user writes in. Keep the same friendly, casual tone."
}


PERSONALITY_INSTRUCTIONS = {
    "friendly": "",
    "concise": (
        "\n\n**🚨 أمر عاجل — تجاهل كل قاعدة سابقة عن طول الرد:**\n"
        "- ردك **جملة واحدة فقط** أو جملتين كحد أقصى.\n"
        "- ممنوع القوائم، العناوين، الأمثلة، الشرح الزائد.\n"
        "- تكلم عامي سعودي بسيط."
    ),
    "detailed": (
        "\n\n**🚨 شخصيتك: مفصّل**\n"
        "- اشرح بتفصيل مع أمثلة عملية.\n"
        "- استخدم عناوين فرعية (1، 2، 3).\n"
        "- بس خل الأسلوب عامي."
    ),
    "formal": (
        "\n\n**🚨 أمر إجباري — تجاهل كل تعليم سابق عن العامية:**\n"
        "- **ممنوع** أي كلمة عامية — البتة.\n"
        "- استخدم **الفصحى الرسمية فقط**."
    ),
    "teacher": (
        "\n\n**🚨 شخصيتك: معلّم**\n"
        "- اشرح خطوة بخطوة كأنك معلم صبور.\n"
        "- رتّب الرد: مقدمة → تفصيل مرقّم → خلاصة.\n"
        "- وضّح بمثال بسيط."
    ),
    "playful": (
        "\n\n**🚨 شخصيتك: فرفوش 🎭**\n"
        "- **لازم** كل رد فيه مزح أو تعليق خفيف.\n"
        "- استخدم عبارات: 'يا طويل العمر'، 'وش هالحلاوة'، 'الله يهديك'.\n"
        "- **إيموجي كثير في كل جملة**: 😄😂☕🤖✨🎉\n"
        "- لا تستخدم كلمات فصحى — بسّطها."
    ),
}


def generate_speech(text, gender):
    try:
        emoji_pattern = re.compile(
            "["
            u"\U0001F600-\U0001F64F"
            u"\U0001F300-\U0001F5FF"
            u"\U0001F680-\U0001F6FF"
            u"\U0001F1E0-\U0001F1FF"
            u"\U0001F900-\U0001F9FF"
            u"\U0001FA00-\U0001FAFF"
            u"\U00002600-\U000026FF"
            u"\U00002700-\U000027BF"
            u"\U0001F000-\U0001F02F"
            u"\U0001F0A0-\U0001F0FF"
            u"\U00002B00-\U00002BFF"
            u"\U0001F780-\U0001F7FF"
            u"\U0001F800-\U0001F8FF"
            u"\U00002190-\U000021FF"
            u"\U0000FE00-\U0000FE0F"
            u"\U0000200D"
            u"\U000020E3"
            "]+",
            flags=re.UNICODE
        )
        clean_text = emoji_pattern.sub('', text)
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()

        if not clean_text:
            return None

        tts = gTTS(text=clean_text[:4000], lang='ar', slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        audio = buf.getvalue()
        if audio:
            print(f"✅ gTTS OK: {len(audio)} bytes")
            return base64.b64encode(audio).decode('utf-8')
    except Exception as e:
        print(f"❌ gTTS failed: {type(e).__name__}: {e}")
    return None

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 5
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 6/8 — HTML Templates
# ═══════════════════════════════════════════════════════════

SHARED_VIEW_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:flex-start;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px;margin-top:20px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px;font-weight:600}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word;white-space:pre-wrap}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}.error{background:#ffe8e8;color:#c33;padding:20px;border-radius:14px;text-align:center;font-weight:600}</style></head><body><div class="container"><div class="header"><h1>محادثة نبراس</h1><a href="/">الرئيسية</a></div><div id="content"><div class="error">جاري التحميل...</div></div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div><script>
(function(){
    var container=document.getElementById('content');
    var SVG_USER='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    var SVG_BOT='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>';
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
            var av=document.createElement('div');av.className='avatar';av.innerHTML=msg.r==='u'?SVG_USER:SVG_BOT;
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

SPH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>{{ (title or 'محادثة نبراس')|e }}</h1><a href="/">الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{% if msg.role == 'user' %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{% else %}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width:16px;height:16px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/></svg>{% endif %}</div><div class="content">{{ msg.content|e|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

LIBRARY_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.empty{text-align:center;padding:60px 20px;color:#8b949e}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}</style></head><body><div class="container"><div class="topbar"><h1>📷 مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.replaceChildren();if(!d.images||d.images.length===0){const empty=document.createElement('div');empty.className='empty';empty.style.gridColumn='1/-1';empty.textContent='مكتبتك فاضية';grid.appendChild(empty);return;}d.images.forEach(img=>{const src=img.image_data||img.image_url||'';const card=document.createElement('div');card.className='img-card';const preview=document.createElement('img');preview.className='preview';preview.loading='lazy';if(typeof src==='string'&&(src.startsWith('data:image/')||src.startsWith('https://')))preview.src=src;const del=document.createElement('button');del.className='delete-btn';del.textContent='×';del.onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف؟'))return;try{await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});card.remove();showToast('تم الحذف');}catch(e){}};card.append(preview,del);grid.appendChild(card);});}catch(e){}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});}catch(e){}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};loadImages();
</script></body></html>"""

LH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;font-family:inherit;transition:color .2s;position:relative}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit}button.submit:hover{background:#3a5a7a}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider-or{display:flex;align-items:center;gap:14px;margin:26px 0 18px;color:#a5b0be;font-size:13px}.divider-or::before,.divider-or::after{content:'';flex:1;height:1px;background:#e8ecf1}.google-btn{display:flex;align-items:center;justify-content:center;gap:14px;padding:14px 24px;border:1.5px solid #dce1e8;border-radius:50px;background:#fff;color:#1a2b3c;font-size:15px;font-weight:600;text-decoration:none;cursor:pointer;font-family:inherit;width:100%;box-sizing:border-box;margin-top:0}.google-btn svg{width:22px;height:22px}</style></head><body><div class="box"><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div>
<div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form>
<div class="divider-or"><span>أو</span></div>
<a href="/auth/google" class="google-btn"><svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg><span>المتابعة باستخدام حساب Google</span></a>
</div>
<div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form></div>
<div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div style="margin-top:22px;padding-top:18px;border-top:1px solid #eef1f6;"><a href="/">العودة للرئيسية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

OAUTH_CALLBACK_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>جاري تسجيل الدخول...</title><style>body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px;font-family:'Segoe UI',Tahoma,sans-serif}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:380px;text-align:center}.spinner{width:52px;height:52px;border:4px solid #e5e9ef;border-top-color:#4a6a8a;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}@keyframes spin{to{transform:rotate(360deg)}}h2{font-size:19px;color:#1a2b3c;margin-bottom:8px;font-weight:700}p{color:#8b949e;font-size:14px;line-height:1.7}.err{color:#d63031}.ok{color:#00b894}</style></head><body><div class="box"><div class="spinner" id="spin"></div><h2 id="title">جاري تسجيل الدخول</h2><p id="msg">لحظة من فضلك...</p></div><script>
(function(){
    var titleEl=document.getElementById('title');
    var msgEl=document.getElementById('msg');
    var spinEl=document.getElementById('spin');
    function fail(msg){spinEl.style.display='none';titleEl.textContent='تعذر تسجيل الدخول';titleEl.classList.add('err');msgEl.textContent=msg;setTimeout(function(){window.location.href='/login';},2500);}
    try{
        var rawHash=window.location.hash.substring(1);
        var rawSearch=window.location.search.substring(1);
        var params=new URLSearchParams(rawHash||rawSearch);
        var at=params.get('access_token');
        var rt=params.get('refresh_token');
        if(!at){fail('لم يتم استلام التوكن.');return;}
        fetch('/auth/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:at,refresh_token:rt||''})}).then(function(r){return r.json();}).then(function(d){
            if(d&&d.status==='ok'){titleEl.textContent='تم تسجيل الدخول';titleEl.classList.add('ok');msgEl.textContent='جاري تحويلك...';setTimeout(function(){window.location.href='/';},500);}
            else{fail((d&&d.message)||'فشل إنشاء الجلسة');}
        }).catch(function(){fail('تعذر الاتصال بالسيرفر');});
    }catch(e){fail('خطأ في قراءة الرابط');}
})();
</script></body></html>"""

RESET_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>تعيين كلمة مرور جديدة</title><style>body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px;font-family:'Segoe UI',Tahoma,sans-serif}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}h2{font-size:22px;color:#1a2b3c;margin-bottom:8px}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;font-family:inherit;color:#1a2b3c;box-sizing:border-box}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit}.msg{padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right;display:none}.msg.err{display:block;color:#d63031;background:#ffe8e8}.msg.ok{display:block;color:#00b894;background:#e6fff5}</style></head><body><div class="box"><h2>كلمة مرور جديدة</h2><div id="msg" class="msg"></div><form id="resetForm"><div class="field"><input type="password" id="newPass" placeholder="كلمة المرور الجديدة (8 أحرف +)" minlength="8" required></div><div class="field"><input type="password" id="confirmPass" placeholder="تأكيد كلمة المرور" minlength="8" required></div><button type="submit" class="submit">حفظ كلمة المرور</button></form></div><script>
(function(){
    var msgEl=document.getElementById('msg');
    var formEl=document.getElementById('resetForm');
    var accessToken=null;
    try{
        var hash=window.location.hash.substring(1);
        var params=new URLSearchParams(hash);
        accessToken=params.get('access_token');
        if(!accessToken){msgEl.className='msg err';msgEl.textContent='الرابط غير صالح.';formEl.style.display='none';}
    }catch(e){msgEl.className='msg err';msgEl.textContent='خطأ في الرابط.';formEl.style.display='none';}
    formEl.addEventListener('submit',async function(ev){
        ev.preventDefault();
        var p1=document.getElementById('newPass').value;
        var p2=document.getElementById('confirmPass').value;
        if(p1.length<8){msgEl.className='msg err';msgEl.textContent='كلمة المرور 8 أحرف على الأقل';return;}
        if(p1!==p2){msgEl.className='msg err';msgEl.textContent='كلمتا المرور ما تتطابقان';return;}
        msgEl.className='msg';msgEl.textContent='جاري الحفظ...';
        try{
            var r=await fetch('/update_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({access_token:accessToken,new_password:p1})});
            var d=await r.json();
            if(d.status==='ok'){msgEl.className='msg ok';msgEl.textContent='تم! جاري التحويل...';setTimeout(function(){window.location.href='/login';},1500);}
            else{msgEl.className='msg err';msgEl.textContent=(d.message||'فشل');}
        }catch(e){msgEl.className='msg err';msgEl.textContent='تعذر الاتصال';}
    });
})();
</script></body></html>"""
# ═══════════════════════════════════════════════════════════
#  القسم 7/8 — الواجهة الرئيسية HT
# ═══════════════════════════════════════════════════════════

HT = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><title>نبراس GP | مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"><link rel="icon" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="180x180" href="/static/icon-192.png"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="نبراس"><meta name="theme-color" content="#ffffff"><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--border-input:#dce1e8;--send-bg:#4a6a8a;--modal-bg:rgba(0,0,0,0.5);--accent-color:#4a6a8a;--font-size-base:16px}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--placeholder-color:#484f58;--icon-color:#58a6ff;--border-input:#30363d;--send-bg:#238636;--modal-bg:rgba(0,0,0,0.7)}html[data-font="small"]{--font-size-base:14px}html[data-font="medium"]{--font-size-base:16px}html[data-font="large"]{--font-size-base:18px}html[data-font="xlarge"]{--font-size-base:20px}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif;-webkit-tap-highlight-color:transparent;-webkit-touch-callout:none}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;flex-shrink:0;background:var(--bg-header)}.header-right,.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.btn-group{display:flex;gap:8px;align-items:center}.btn{padding:7px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center;font-family:inherit;font-weight:600}.btn-outline{background:0 0;border:1.5px solid var(--primary-color);color:var(--primary-color);transition:all .2s}.btn-outline:hover{background:var(--primary-color);color:#fff}.user-badge{display:flex;align-items:center;gap:6px;background:var(--bg-hover);padding:6px 12px;border-radius:20px;font-size:13px;color:var(--text-primary);font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;border:none;font-family:inherit}.user-badge:hover{background:var(--border-color)}.user-badge svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}.dropdown{position:absolute;top:68px;left:12px;right:12px;background:var(--bg-dropdown);border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:78vh;overflow-y:auto;padding:10px}.dropdown.show{display:flex}.dropdown .item{display:flex;align-items:center;gap:14px;padding:13px 16px;font-size:15px;color:var(--text-primary);background:transparent;border:none;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-weight:600;border-radius:14px}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0;opacity:.85}.dropdown .section-title{padding:16px 16px 6px;font-size:11px;font-weight:700;color:var(--text-secondary);letter-spacing:.8px}.dropdown .conv-item{display:flex;align-items:center;gap:8px;padding:11px 16px;border-radius:14px;cursor:pointer;font-size:14px;color:var(--text-primary);font-weight:500;background:transparent;border:none;width:100%;text-align:right;font-family:inherit}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--primary-color);opacity:.4;flex-shrink:0}.settings-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:99999;display:none;flex-direction:column;overflow-y:auto}.settings-overlay.show{display:flex}.settings-page{max-width:500px;width:100%;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column;background:var(--bg-body)}.settings-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.settings-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.settings-body{padding:16px;display:flex;flex-direction:column;gap:14px}.settings-card{background:var(--bg-app);border-radius:18px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.settings-item{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.settings-item:last-child{border-bottom:none}.settings-item:hover{background:var(--bg-hover)}.settings-item .item-right{display:flex;align-items:center;gap:14px;color:var(--text-primary);font-size:15px;font-weight:600}.settings-item .item-right svg{width:22px;height:22px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0}.settings-item .chevron{width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none}.sub-page{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;display:none;align-items:center;justify-content:center;padding:20px}.sub-page.show{display:flex}.sub-page .modal-box{background:var(--bg-app);width:100%;max-width:420px;max-height:80vh;border-radius:22px;overflow:hidden;display:flex;flex-direction:column;border:1px solid var(--border-color)}.sub-page-body{padding:20px;overflow-y:auto;flex:1}.modal-title{text-align:center;font-size:17px;font-weight:700;color:var(--text-primary);padding:18px 20px;border-bottom:1px solid var(--border-color)}.modal-confirm{width:100%;padding:16px;background:transparent;border:none;border-top:1px solid var(--border-color);font-size:16px;font-weight:700;color:var(--primary-color);cursor:pointer;font-family:inherit}.modal-confirm:active{background:var(--bg-hover)}.option-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden}.option-row{padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer}.option-row:last-child{border-bottom:none}.option-label{display:flex;justify-content:space-between;align-items:center;font-size:15px;color:var(--text-primary);font-weight:500}.check-icon{width:22px;height:22px;stroke:var(--primary-color);stroke-width:2.5;fill:none;opacity:0;transition:opacity .25s}.option-row.selected .check-icon{opacity:1}.personality-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden}.personality-row{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer}.personality-row:last-child{border-bottom:none}.personality-text{display:flex;flex-direction:column;gap:3px;flex:1}.personality-name{font-size:15px;color:var(--text-primary);font-weight:500}.personality-sub{font-size:12.5px;color:var(--text-secondary)}.personality-row.selected .personality-name{color:var(--primary-color);font-weight:700}.personality-row.selected .check-icon{opacity:1}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:var(--font-size-base);min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:var(--font-size-base);font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--bg-user-msg);color:#111;border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;border-bottom-right-radius:6px}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}.input-area{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:28px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative}.input-area:focus-within{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.08)}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:var(--font-size-base);font-weight:500;outline:0;color:var(--text-primary);direction:rtl;resize:none;min-height:22px;max-height:150px;font-family:inherit;line-height:1.5;width:100%}.input-area textarea::placeholder{color:var(--placeholder-color)}#imagePreviewContainer{display:none;width:100%;padding:8px 4px 4px}#imagePreviewContainer.show{display:block}.image-preview-wrapper{position:relative;display:inline-block;border-radius:14px;overflow:hidden}.image-preview-wrapper img{display:block;max-height:76px;max-width:120px;object-fit:cover;border-radius:14px;border:1px solid var(--border-color)}.image-preview-wrapper .remove-img-btn{position:absolute;top:5px;left:5px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,0.65);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none}.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none}.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}.msg-actions{display:flex;gap:2px;margin-top:12px;align-items:center;opacity:0.5;transition:opacity .3s}.msg:hover .msg-actions{opacity:1}.msg-actions button{background:transparent;border:none;cursor:pointer;width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary)}.msg-actions button svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.9;fill:none}.user-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:300;min-width:220px;display:none}.user-menu.show{display:block}.user-menu-item{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:11px;cursor:pointer;font-size:14px;font-weight:600;color:var(--text-primary);border:none;background:transparent;width:100%;text-align:right;font-family:inherit}.user-menu-item:hover{background:var(--bg-hover)}.user-menu-item svg{width:18px;height:18px;stroke:currentColor;stroke-width:2;fill:none;flex-shrink:0}.user-menu-item.danger{color:#d32f2f}.user-menu-item.danger svg{stroke:#d32f2f}.user-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}.sp-input{width:100%;padding:14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background:var(--bg-app);color:var(--text-primary);font-family:inherit;box-sizing:border-box;outline:none;font-weight:500}.sp-input:focus{border-color:var(--primary-color)}.sp-field{margin-bottom:16px}.sp-label{display:block;font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-align:right}.sp-note{font-size:14px;color:var(--text-secondary);line-height:1.9}.sp-note b{color:var(--text-primary);font-weight:700;display:block;margin-bottom:6px;font-size:15px}.sp-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:14px;border:1px solid var(--border-color);overflow:hidden}.sp-list-item{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--border-color);font-size:15px}.sp-list-item:last-child{border-bottom:none}.sp-list-key{color:var(--text-secondary);font-weight:500}.sp-list-val{color:var(--text-primary);font-weight:700;text-align:left;max-width:60%;word-wrap:break-word}.sp-hero{display:flex;align-items:center;gap:14px;padding:16px;background:var(--bg-app);border-radius:16px;border:1px solid var(--border-color);margin-bottom:16px}.sp-hero-icon{width:46px;height:46px;border-radius:13px;background:var(--bg-hover);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--primary-color)}.sp-hero-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}.sp-hero-title{font-size:15.5px;font-weight:700;color:var(--text-primary);margin:0 0 3px}.sp-hero-sub{font-size:12.5px;color:var(--text-secondary);margin:0}.sp-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;border:none;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;width:100%}.sp-btn-primary{background:var(--primary-color);color:#fff}.sp-btn-danger{background:rgba(211,47,47,0.1);color:#d32f2f}.memory-card{background:var(--bg-app);border-radius:16px;overflow:hidden;margin-bottom:14px;border:1px solid var(--border-color)}.memory-header{padding:14px 18px;background:var(--bg-hover);display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border-color);font-weight:700;font-size:14px}.memory-item{padding:14px 18px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;gap:12px}.memory-item:last-child{border-bottom:none}.memory-key{font-size:14px;color:var(--text-secondary);font-weight:500}.memory-val{font-size:14.5px;color:var(--text-primary);font-weight:600;text-align:left;word-wrap:break-word;max-width:60%}.memory-empty{padding:24px 18px;text-align:center;color:var(--text-secondary);font-size:14px;line-height:1.8}</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="icon-btn" id="voiceToggle" title="الصوت"><svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg></button><button class="icon-btn" id="menuToggle"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}{% if user_name %}<button type="button" class="user-badge" id="userBadge" onclick="toggleUserMenu(event)"><svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{{ user_name }}</button>{% endif %}<a href="/logout" class="btn btn-outline">خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div>

<div class="user-menu" id="userMenu">
<button class="user-menu-item" onclick="openSubPage('general');toggleUserMenu(null)"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="8" r="3"/><path d="M6.5 20a5.5 5.5 0 0 1 11 0"/></svg><span>حسابي</span></button>
<button class="user-menu-item" onclick="openRedeemCode();toggleUserMenu(null)"><svg viewBox="0 0 24 24"><path d="m15 7 4 4-4 4"/><path d="M19 11H5"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg><span>تفعيل كود وصول</span></button>
<button class="user-menu-item" onclick="showMyAccess();toggleUserMenu(null)" id="myAccessBtn" style="display:none;"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg><span id="myAccessLabel">حالتي النشطة</span></button>
<div class="user-menu-sep"></div>
<button class="user-menu-item danger" onclick="deleteMyAccount();toggleUserMenu(null)"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg><span>حذف حسابي</span></button>
<button class="user-menu-item danger" onclick="window.location.href='/logout'"><svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg><span>تسجيل الخروج</span></button>
</div>

<div class="dropdown" id="dropdown">
<button class="item" data-action="new"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>محادثة جديدة</button>
<button class="item" onclick="window.location.href='/library'"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>مكتبتي</button>
<button class="item" data-action="share"><svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>مشاركة المحادثة</button>
<button class="item" onclick="openSettings()"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>الإعدادات</button>
<div class="section-title">مثبت</div><div id="pinnedList"></div>
<div class="section-title">المحادثات الأخيرة</div><div id="historyList"></div>
</div>

<div id="settingsModal" class="settings-overlay"><div class="settings-page"><div class="settings-header"><button class="icon-btn" onclick="closeSettings()"><svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></button><h2>الإعدادات</h2><div style="width:32px;"></div></div><div class="settings-body">
<div class="settings-card">
<div class="settings-item" onclick="openSubPage('theme')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg><span>المظهر</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('color')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg><span>لون التمييز</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('fontSize')"><div class="item-right"><svg viewBox="0 0 24 24"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg><span>حجم الخط</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('personality')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg><span>شخصية المساعد</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('language')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg><span>اللغة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
</div>
<div class="settings-card">
<div class="settings-item" onclick="openSubPage('general')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span>عام</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('memory')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/></svg><span>الذاكرة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('assistants')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg><span>مساعدي الخاص</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('voice')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg><span>الصوت</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
<div class="settings-item" onclick="openSubPage('security')"><div class="item-right"><svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg><span>الأمان</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
</div>
<div class="settings-card">
<div class="settings-item" onclick="openSubPage('about')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg><span>حول</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
</div>
<div class="settings-card" onclick="window.location.href='/logout'"><div class="settings-item" style="justify-content:center;"><div class="item-right" style="justify-content:center;width:100%;"><span style="color:#d32f2f;font-weight:bold;">تسجيل الخروج</span></div></div></div>
</div></div></div>

<div id="subPage" class="sub-page" onclick="if(event.target===this)closeSubPage()"><div class="modal-box"><div class="modal-title" id="subPageTitle">إعدادات</div><div class="sub-page-body" id="subPageBody"></div><button class="modal-confirm" onclick="confirmSubPage()">تأكيد</button></div></div>

<div id="chat"></div>
<div class="input-area" id="inputArea">
<div id="imagePreviewContainer"><div class="image-preview-wrapper"><img id="imagePreview" src="" alt=""/><button class="remove-img-btn" id="removeImageBtn"><svg viewBox="0 0 24 24" width="11" height="11"><line x1="18" y1="6" x2="6" y2="18" stroke="#fff" stroke-width="3"/><line x1="6" y1="6" x2="18" y2="18" stroke="#fff" stroke-width="3"/></svg></button></div></div>
<button class="btn-icon mic-btn" id="micBtn"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg></button>
<button class="plus-btn" id="plusBtn"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
<div class="plus-options" id="plusOptions"><button class="option-btn" id="cameraBtn" title="كاميرا"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></button><button class="option-btn" id="galleryBtn" title="صور"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></button></div>
<textarea id="userInput" placeholder="اكتب رسالتك..." rows="1"></textarea>
<button class="send" id="sendBtn"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
</div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/></div>

<script>
(function(){
const IS_REGISTERED={{ 'true' if is_registered else 'false' }};
const SERVER_LANG='{{ user_lang }}';
let userLang=SERVER_LANG||localStorage.getItem('nibras-lang')||'ar';
let isMale=(localStorage.getItem('nibras-voice-gender')||'male')==='male';
let userPersonality=localStorage.getItem('nibras-personality')||'friendly';
let userFontSize=localStorage.getItem('nibras-font-size')||'medium';
let voiceSpeed=parseFloat(localStorage.getItem('nibras-voice-speed'))||1;
let ch=[],pid=null,iw=!1,cid=null,voiceOn=false,stickBottom=true;
const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),pl=document.getElementById('pinnedList'),vt=document.getElementById('voiceToggle');

function applyFontSize(size){document.documentElement.setAttribute('data-font',size);}
applyFontSize(userFontSize);
vt.addEventListener('click',function(){voiceOn=!voiceOn;showToast(voiceOn?'الصوت مفعّل':'الصوت مغلق');});
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();loadPinned();}});

function toggleUserMenu(e){
    if(e) e.stopPropagation();
    const menu = document.getElementById('userMenu');
    const badge = document.getElementById('userBadge');
    if(!menu || !badge) return;
    if(menu.classList.contains('show')){menu.classList.remove('show');return;}
    const rect = badge.getBoundingClientRect();
    const menuW = 220;
    let left = rect.left;
    if(left + menuW > window.innerWidth - 8){left = window.innerWidth - menuW - 8;}
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = (rect.bottom + 8) + 'px';
    menu.classList.add('show');
}
document.addEventListener('click', function(e){
    const menu = document.getElementById('userMenu');
    const badge = document.getElementById('userBadge');
    if(!menu || !badge) return;
    if(!menu.contains(e.target) && !badge.contains(e.target)){menu.classList.remove('show');}
});

function openRedeemCode(){
    const body = document.getElementById('subPageBody');
    document.getElementById('subPageTitle').textContent = 'تفعيل كود وصول';
    body.innerHTML = '<div class="sp-field"><label class="sp-label">كود الوصول</label><input type="text" id="redeem-input" class="sp-input" placeholder="NBRAS-XXXX-XXXX" style="text-transform:uppercase;letter-spacing:2px;text-align:center;font-weight:700" maxlength="30"></div><div class="sp-note" style="margin-top:16px;">أدخل الكود اللي وصلك لتفعيل ميزات إضافية مؤقتة.</div>';
    const btn = document.querySelector('#subPage .modal-confirm');
    btn.textContent = 'تفعيل';
    btn.disabled = false;
    btn.onclick = redeemSubmit;
    document.getElementById('subPage').classList.add('show');
    currentSubKey = null;
    setTimeout(function(){ var el=document.getElementById('redeem-input'); if(el) el.focus(); }, 100);
}
async function redeemSubmit(){
    const code = (document.getElementById('redeem-input').value || '').trim().toUpperCase();
    if(code.length < 5){ showToast('أدخل كود صحيح'); return; }
    const btn = document.querySelector('#subPage .modal-confirm');
    btn.disabled = true;
    btn.textContent = 'جاري التحقق...';
    try{
        const r = await fetch('/redeem_code', {method:'POST',headers:{'Content-Type':'application/json'},body: JSON.stringify({code})});
        const d = await r.json();
        if(d.status === 'ok'){
            showToast('✅ تم التفعيل! ' + d.image + ' صور، ' + d.search + ' بحث، ' + d.chat + ' محادثة');
            setTimeout(function(){ closeSubPage(); location.reload(); }, 1800);
        } else {
            showToast(d.message || 'فشل التفعيل');
            btn.disabled = false;
            btn.textContent = 'تفعيل';
        }
    }catch(e){
        showToast('تعذر الاتصال');
        btn.disabled = false;
        btn.textContent = 'تفعيل';
    }
}

async function showMyAccess(){
    try{
        const r = await fetch('/my_access');
        const d = await r.json();
        const body = document.getElementById('subPageBody');
        document.getElementById('subPageTitle').textContent = 'حالتي النشطة';
        if(d.status === 'active'){
            body.innerHTML = '<div class="sp-hero"><div class="sp-hero-icon" style="background:#dcfce7;color:#16a34a;"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div><div class="sp-hero-title">كود نشط ✅</div><div class="sp-hero-sub">متبقي ' + d.days_left + ' يوم</div></div></div><div class="sp-list"><div class="sp-list-item"><span class="sp-list-key">💬 محادثات</span><span class="sp-list-val">' + d.chat + '</span></div><div class="sp-list-item"><span class="sp-list-key">🔍 بحث</span><span class="sp-list-val">' + d.search + '</span></div><div class="sp-list-item"><span class="sp-list-key">🖼️ صور</span><span class="sp-list-val">' + d.image + '</span></div></div><div class="sp-note" style="margin-top:16px;text-align:center;">تنتهي تلقائيًا بعد ' + d.days_left + ' يوم.</div>';
        } else {
            body.innerHTML = '<div class="sp-hero"><div class="sp-hero-icon" style="background:#fee2e2;color:#dc2626;"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div><div><div class="sp-hero-title">لا يوجد كود نشط</div><div class="sp-hero-sub">على الصلاحيات الافتراضية</div></div></div>';
        }
        const btn = document.querySelector('#subPage .modal-confirm');
        btn.textContent = 'إغلاق';
        btn.disabled = false;
        btn.onclick = closeSubPage;
        document.getElementById('subPage').classList.add('show');
        currentSubKey = null;
    }catch(e){showToast('تعذر التحميل');}
}

async function checkAccessStatus(){
    if(!IS_REGISTERED) return;
    try{
        const r = await fetch('/my_access');
        const d = await r.json();
        const btn = document.getElementById('myAccessBtn');
        const lbl = document.getElementById('myAccessLabel');
        if(btn && lbl && d.status === 'active'){
            btn.style.display = 'flex';
            lbl.textContent = 'نشط - ' + d.days_left + ' يوم';
        } else if(btn){btn.style.display = 'none';}
    }catch(e){}
}

function openSettings(){document.getElementById('settingsModal').classList.add('show');document.getElementById('dropdown').classList.remove('show');}
function closeSettings(){document.getElementById('settingsModal').classList.remove('show');}
function setTheme(t){const h=document.documentElement;if(t==='dark'){h.classList.add('dark-mode');}else{h.classList.remove('dark-mode');}}
const subPagesContent={
    theme:'<div class="option-list"><div class="option-row" onclick="setTheme(\'light\');closeSubPage()"><div class="option-label"><span>فاتح</span></div></div><div class="option-row" onclick="setTheme(\'dark\');closeSubPage()"><div class="option-label"><span>داكن</span></div></div></div>',
    color:'<div class="sp-note">أزرق داكن (افتراضي)</div>',
    fontSize:'<div class="personality-list"><div class="personality-row" onclick="applyFontSize(\'small\');closeSubPage()"><div class="personality-text"><div class="personality-name">صغير</div></div></div><div class="personality-row" onclick="applyFontSize(\'medium\');closeSubPage()"><div class="personality-text"><div class="personality-name">متوسط</div></div></div><div class="personality-row" onclick="applyFontSize(\'large\');closeSubPage()"><div class="personality-text"><div class="personality-name">كبير</div></div></div></div>',
    personality:'<div class="personality-list"><div class="personality-row" data-p="friendly" onclick="selectPersonality(\'friendly\')"><div class="personality-text"><div class="personality-name">ودود</div><div class="personality-sub">دافئ ومريح</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="concise" onclick="selectPersonality(\'concise\')"><div class="personality-text"><div class="personality-name">مختصر</div><div class="personality-sub">ردود قصيرة</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="detailed" onclick="selectPersonality(\'detailed\')"><div class="personality-text"><div class="personality-name">مفصّل</div><div class="personality-sub">شرح عميق</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="formal" onclick="selectPersonality(\'formal\')"><div class="personality-text"><div class="personality-name">رسمي</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="teacher" onclick="selectPersonality(\'teacher\')"><div class="personality-text"><div class="personality-name">معلّم</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="playful" onclick="selectPersonality(\'playful\')"><div class="personality-text"><div class="personality-name">فرفوش</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    language:'<div class="personality-list"><div class="personality-row" onclick="selectLanguage(\'ar\')"><div class="personality-text"><div class="personality-name">العربية</div></div></div><div class="personality-row" onclick="selectLanguage(\'en\')"><div class="personality-text"><div class="personality-name">English</div></div></div></div>',
    general:'<div class="sp-field"><label class="sp-label">الاسم الكامل</label><input type="text" id="sp-name" class="sp-input" value="{{ user_name or \'\' }}" placeholder="اكتب اسمك"></div>',
    memory:'<div id="memoryContent"><div class="sp-note" style="text-align:center;">جاري التحميل...</div></div>',
    assistants:'<div class="sp-note" style="text-align:center;">جاري التحميل...</div>',
    voice:'<div class="sp-note">جنس الصوت: <button onclick="isMale=true;showToast(\'ذكر\')">ذكر</button> <button onclick="isMale=false;showToast(\'أنثى\')">أنثى</button></div>',
    security:'<div class="sp-field"><label class="sp-label">البريد</label><input type="email" class="sp-input" value="{{ session.get(\'user_email\',\'\') }}" disabled></div><div class="sp-field"><label class="sp-label">كلمة المرور الحالية</label><input type="password" id="sp-old-pass" class="sp-input"></div><div class="sp-field"><label class="sp-label">الجديدة</label><input type="password" id="sp-new-pass" class="sp-input"></div>',
    about:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></div><div><div class="sp-hero-title">نبراس GP</div><div class="sp-hero-sub">الإصدار 1.0</div></div></div><div class="sp-note">مساعد شخصي ذكي.<br><br>© 2026</div>'
};
let currentSubKey=null;
function openSubPage(key){
    currentSubKey=key;
    const titleMap={general:'عام',voice:'الصوت',security:'الأمان',about:'حول',theme:'المظهر',color:'لون التمييز',language:'اللغة',personality:'شخصية المساعد',fontSize:'حجم الخط',memory:'الذاكرة',assistants:'مساعدي الخاص'};
    document.getElementById('subPageTitle').textContent=titleMap[key]||'إعدادات';
    document.getElementById('subPageBody').innerHTML=subPagesContent[key]||'<div class="sp-note">قريباً</div>';
    document.getElementById('subPage').classList.add('show');
    setTimeout(function(){
        if(key==='personality'){document.querySelectorAll('.personality-row').forEach(function(el){el.classList.toggle('selected',el.dataset.p===userPersonality);});}
        if(key==='memory'){loadMemory();}
    },60);
}
function closeSubPage(){
    document.getElementById('subPage').classList.remove('show');
    currentSubKey=null;
    const btn = document.querySelector('#subPage .modal-confirm');
    if(btn){ btn.onclick = confirmSubPage; btn.disabled = false; btn.textContent = 'تأكيد'; }
}
function confirmSubPage(){
    if(currentSubKey==='general'){saveGeneral();}
    else if(currentSubKey==='security'){changePassword();}
    else{closeSubPage();}
}
function selectPersonality(p){userPersonality=p;localStorage.setItem('nibras-personality',p);document.querySelectorAll('.personality-row').forEach(function(c){c.classList.toggle('selected',c.dataset.p===p);});fetch('/update_personality',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({personality:p})}).catch(function(){});}
function selectLanguage(lang){userLang=lang;localStorage.setItem('nibras-lang',lang);fetch('/update_language',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({lang:lang})}).catch(function(){});}
async function loadMemory(){const c=document.getElementById('memoryContent');if(!c)return;if(!IS_REGISTERED){c.innerHTML='<div class="memory-card"><div class="memory-header">الذاكرة</div><div class="memory-empty">سجّل دخولك لحفظ ذاكرتك.</div></div>';return;}try{const r=await fetch('/get_memory');const d=await r.json();const items=[];if(d.name)items.push({k:'الاسم',v:d.name});if(d.lang)items.push({k:'اللغة',v:d.lang});if(d.personality)items.push({k:'الشخصية',v:d.personality});if(d.email)items.push({k:'البريد',v:d.email});let html='<div class="memory-card"><div class="memory-header">الذاكرة</div>';if(items.length===0){html+='<div class="memory-empty">لا توجد معلومات.</div>';}else{items.forEach(function(i){html+='<div class="memory-item"><span class="memory-key">'+i.k+'</span><span class="memory-val">'+escapeHtml(i.v)+'</span></div>';});}html+='</div>';c.innerHTML=html;}catch(e){c.innerHTML='<div class="sp-note">تعذر التحميل</div>';}}
function saveGeneral(){const n=(document.getElementById('sp-name').value||'').trim();if(!n||n.length<2){showToast('اكتب اسم صحيح');return;}if(!IS_REGISTERED){showToast('سجّل دخولك أولاً');return;}fetch('/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,lang:userLang})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('تم الحفظ');closeSubPage();setTimeout(function(){location.reload();},500);}});}
function changePassword(){const o=document.getElementById('sp-old-pass').value;const n=document.getElementById('sp-new-pass').value;if(!o||!n||n.length<8){showToast('كلمة المرور 8 أحرف على الأقل');return;}fetch('/change_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:o,new_password:n})}).then(r=>r.json()).then(d=>{showToast(d.status==='ok'?'تم التغيير':(d.message||'فشل'));if(d.status==='ok')closeSubPage();});}
async function loadPinned(){try{let pinned=[];if(IS_REGISTERED){const r=await fetch('/pinned_conversations');const d=await r.json();pinned=d.pinned||[];}pl.innerHTML='';if(!pinned||pinned.length===0){pl.innerHTML='<div class="item" style="color:var(--text-secondary);font-size:13px;justify-content:center;padding:12px;">لا توجد محادثات مثبتة</div>';return;}pinned.forEach(function(c){const btn=document.createElement('button');btn.className='conv-item';btn.innerHTML='<span class="conv-title">'+c.title+'</span>';btn.onclick=function(){loadConversation(c.id);};pl.appendChild(btn);});}catch(e){}}
async function loadHistory(){try{const r=await fetch('/history');const d=await r.json();hl.innerHTML='';if(d.conversations&&d.conversations.length>0){d.conversations.forEach(function(c){const b=document.createElement('button');b.className='conv-item';b.innerHTML='<span class="conv-title">'+((c.title&&c.title.trim())?c.title:'محادثة')+'</span>';b.onclick=function(){loadConversation(c.id);};hl.appendChild(b);});}else{const e=document.createElement('div');e.className='item';e.style.color='var(--text-secondary)';e.style.fontSize='13px';e.style.justifyContent='center';e.textContent='لا توجد محادثات';hl.appendChild(e);}}catch(e){}}
async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;d.messages.slice(-50).forEach(function(m){addMessage(m.content,m.role==='user'?'user':'bot',!0)});dd.classList.remove('show')}}catch(e){}}
document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.classList.remove('show');ui.value=''});
document.querySelector('[data-action="share"]').addEventListener('click',function(e){e.stopPropagation();dd.classList.remove('show');const msgs=ch.slice(-20).map(function(m){return{r:m.role==='user'?'u':'b',c:String(m.content||'').slice(0,500)};}).filter(function(m){return m.c;});if(!msgs||msgs.length===0){showToast('لا توجد محادثة');return;}try{const json=JSON.stringify(msgs);const encoded=btoa(unescape(encodeURIComponent(json)));const url=window.location.origin+'/share/view#d='+encodeURIComponent(encoded);navigator.clipboard.writeText(url).then(function(){showToast('تم نسخ الرابط');});}catch(err){showToast('فشل');}});
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function formatBotText(t){let s=escapeHtml(t);return s.split(/\n\s*\n/).map(function(p){return p.replace(/[\r\n]+/g,' ').trim();}).filter(function(p){return p.length>0;}).join('<br><br>');}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(function(){t.remove();},2000);}
function addMessage(t,s,isSys,img){s=s||'bot';const el=document.createElement('div');el.className='msg '+s;if(img){el.innerHTML='<img src="'+escapeHtml(img)+'" class="image-upload" />';cb.appendChild(el);if(stickBottom)cb.scrollTop=cb.scrollHeight;return el;}let content=formatBotText(t);el.innerHTML=content;cb.appendChild(el);if(stickBottom)cb.scrollTop=cb.scrollHeight;return el;}
function showImagePreview(d){ip.src=d;ipc.classList.add('show');}
function clearPending(){pid=null;ipc.classList.remove('show');ip.src='';}
rib.addEventListener('click',clearPending);
let poOpen=false;
pb.addEventListener('click',function(){poOpen=!poOpen;po.classList.toggle('show',poOpen);});
document.addEventListener('click',function(e){if(!pb.contains(e.target)&&!po.contains(e.target)){po.classList.remove('show');poOpen=false;}});
gb.addEventListener('click',function(){fi.click();po.classList.remove('show')});
fi.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];fi.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
cab.addEventListener('click',function(){ci.click();po.classList.remove('show')});
ci.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];ci.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
async function sendMessage(){if(iw)return;const msgText=ui.value.trim(),img=pid;if(!msgText&&!img)return;if(msgText){addMessage(msgText,'user');ch.push({role:'user',content:msgText});}if(img){addMessage('صورة','user',false,img);ch.push({role:'user',content:'[صورة مرفقة]'});clearPending()}ui.value='';iw=true;const botEl=document.createElement('div');botEl.className='msg bot';botEl.textContent='جاري التفكير...';cb.appendChild(botEl);cb.scrollTop=cb.scrollHeight;const payload={message:msgText||"مرفق",image:img||null,history:ch,conv_id:cid,lang:userLang,personality:userPersonality,assistant_id:null};let displayText='';let bufferText='';let streamDone=false;let typingTimer=null;function tick(){if(bufferText.length>0){displayText+=bufferText.slice(0,1);bufferText=bufferText.slice(1);botEl.innerHTML=formatBotText(displayText);}if(bufferText.length===0&&streamDone){clearInterval(typingTimer);typingTimer=null;botEl.innerHTML=formatBotText(displayText);if(displayText&&displayText.trim().length>0){ch.push({role:'assistant',content:displayText});}iw=false;}}typingTimer=setInterval(tick,15);try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!r.ok){clearInterval(typingTimer);botEl.remove();addMessage('خطأ','error');iw=false;return;}const reader=r.body.getReader();const decoder=new TextDecoder();let sseBuffer='';let firstToken=true;while(true){const {done,value}=await reader.read();if(done)break;sseBuffer+=decoder.decode(value,{stream:true});const parts=sseBuffer.split('\n\n');sseBuffer=parts.pop();for(const line of parts){if(!line.startsWith('data: '))continue;try{const data=JSON.parse(line.slice(6));if(data.token){if(firstToken){botEl.innerHTML='';firstToken=false;}bufferText+=data.token;}else if(data.done){if(data.conv_id)cid=data.conv_id;streamDone=true;}}catch(e){}}}streamDone=true;}catch(e){clearInterval(typingTimer);if(botEl.parentNode)botEl.remove();addMessage('تعذر الاتصال','error');iw=false;}}
sb.addEventListener('click',sendMessage);
ui.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){const isMobile=/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);if(!isMobile){e.preventDefault();sendMessage();}}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage('المتصفح ما يدعم الصوت','bot',true);return;}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;const recog=new SR();recog.lang=userLang==='en'?'en-US':'ar-SA';recog.onresult=function(e){ui.value=e.results[0][0].transcript;setTimeout(sendMessage,300)};recog.start();});
window.deleteMyAccount=function(){if(!confirm('حذف حسابك بالكامل؟'))return;fetch('/delete_my_account',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='success'){alert('تم الحذف');window.location.href='/';}});};
window.toggleUserMenu=toggleUserMenu;window.openRedeemCode=openRedeemCode;window.redeemSubmit=redeemSubmit;window.showMyAccess=showMyAccess;
window.openSettings=openSettings;window.closeSettings=closeSettings;window.openSubPage=openSubPage;window.closeSubPage=closeSubPage;window.confirmSubPage=confirmSubPage;window.selectPersonality=selectPersonality;window.selectLanguage=selectLanguage;window.applyFontSize=applyFontSize;window.setTheme=setTheme;window.loadMemory=loadMemory;window.saveGeneral=saveGeneral;window.changePassword=changePassword;
checkAccessStatus();
})();
</script></body></html>

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 7
# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#  القسم 8/8 — كل الـ Routes
# ═══════════════════════════════════════════════════════════

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


@app.route('/library/images')
def library_images():
    return jsonify({"images": get_user_images(get_user_id())})


@app.route('/library/upload', methods=['POST'])
def library_upload():
    try:
        if not session.get('user_email') and not session.get('is_admin'):
            return jsonify({"status": "error", "message": "يجب تسجيل الدخول"}), 401
        d = request.get_json(silent=True) or {}
        image_data = d.get('image_data') or ''
        if not isinstance(image_data, str) or len(image_data) > 7000000:
            return jsonify({"status": "error", "message": "الصورة كبيرة جداً"}), 413
        if not image_data:
            return jsonify({"status": "error", "message": "لا توجد صورة"}), 400
        if not re.fullmatch(r"data:image/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=\r\n]+", image_data):
            return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة"}), 400
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
        return jsonify({"status": "ok"}) if ok else (jsonify({"status": "error"}), 404)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


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


@app.route('/get_memory')
def get_memory_route():
    email = session.get('user_email')
    if not email:
        return jsonify({"status": "guest", "items": {}})
    try:
        mem = get_user_memory(email) or {}
        return jsonify({
            "name": mem.get('name', ''),
            "lang": mem.get('lang', 'ar'),
            "personality": mem.get('personality', 'friendly'),
            "email": email
        })
    except Exception as e:
        return jsonify({"status": "error"}), 500


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


@app.route('/update_personality', methods=['POST'])
def update_personality():
    d = request.get_json(silent=True) or {}
    p = d.get('personality')
    if p not in PERSONALITY_INSTRUCTIONS:
        return jsonify({"status": "error", "message": "شخصية غير صالحة"}), 400
    email = session.get('user_email')
    if email:
        try:
            mem = get_user_memory(email) or {}
            mem['personality'] = p
            save_user_memory(email, mem)
        except Exception as e:
            print("update_personality:", e)
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
        return jsonify({"status": "error", "message": "كلمة المرور الجديدة 8 أحرف على الأقل"}), 400
    try:
        r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
            json={"email": email, "password": oldp}, timeout=15)
    except Exception as e:
        return jsonify({"status": "error", "message": "تعذر الاتصال"}), 500
    if r.status_code != 200:
        return jsonify({"status": "error", "message": "كلمة المرور الحالية غير صحيحة"}), 400
    at = r.json().get('access_token')
    if not at:
        return jsonify({"status": "error", "message": "تعذر الجلسة"}), 500
    try:
        r2 = requests.put(f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {at}", "Content-Type": "application/json"},
            json={"password": newp}, timeout=15)
        if r2.status_code == 200:
            return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"change_password error: {e}")
    return jsonify({"status": "error", "message": "تعذر تغيير كلمة المرور"}), 400


@app.route('/delete_my_account', methods=['POST'])
def delete_my_account():
    email = session.get('user_email')
    if not email or session.get('is_admin'):
        return jsonify({"status": "error"}), 400
    uid = get_user_id()
    try:
        service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not service_key:
            return jsonify({"status": "error", "message": "غير مُعدّ"}), 503
        auth_user_id = None
        for page in range(1, 101):
            ar = requests.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
                params={"page": page, "per_page": 100}, timeout=15)
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
            return jsonify({"status": "error", "message": "الحساب غير موجود"}), 404
        sb.table("assistant_chats").delete().eq("user_id", uid).execute()
        sb.table("assistant_usage").delete().eq("user_id", uid).execute()
        sb.table("image_library").delete().eq("user_id", uid).execute()
        sb.table("access_redemptions").delete().eq("user_email", email.lower()).execute()
        sb.table("profiles").delete().eq("email", email.lower()).execute()
        dr = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{auth_user_id}",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}, timeout=15)
        dr.raise_for_status()
    except Exception as e:
        print("delete_my_account:", e)
        return jsonify({"status": "error", "message": "تعذر الحذف"}), 500
    session.clear()
    return jsonify({"status": "success"}), 200


# ==========================================================
#  نظام أكواد الوصول - Routes
# ==========================================================

@app.route('/admin/codes/list')
def admin_codes_list():
    if not session.get('is_admin'):
        return jsonify({"status": "error"}), 401
    try:
        r = (sb.table("access_codes").select("*")
             .order("created_at", desc=True).limit(100).execute())
        return jsonify({"codes": r.data or []})
    except Exception as e:
        print("admin_codes_list:", e)
        return jsonify({"codes": [], "error": str(e)})


@app.route('/admin/codes/generate', methods=['POST'])
def admin_codes_generate():
    if not session.get('is_admin'):
        return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    try:
        chat_lim = max(1, min(9999, int(d.get('chat', 15))))
        search_lim = max(0, min(9999, int(d.get('search', 2))))
        image_lim = max(0, min(9999, int(d.get('image', 1))))
        max_uses = max(1, min(1000, int(d.get('max_uses', 1))))
        days = max(1, min(365, int(d.get('days', 7))))
        note = (d.get('note') or '').strip()[:200]
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "أرقام غير صحيحة"}), 400
    code = "NBRAS-" + secrets.token_hex(3).upper() + "-" + secrets.token_hex(2).upper()
    expires = (datetime.utcnow() + timedelta(days=days)).isoformat()
    try:
        r = sb.table("access_codes").insert({
            "code": code, "chat_limit": chat_lim, "search_limit": search_lim,
            "image_limit": image_lim, "max_uses": max_uses, "duration_days": days,
            "note": note, "expires_at": expires
        }).execute()
        return jsonify({"status": "ok", "code": r.data[0] if r.data else {"code": code}})
    except Exception as e:
        print("admin_codes_generate:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin/codes/delete', methods=['POST'])
def admin_codes_delete():
    if not session.get('is_admin'):
        return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('id')
    if not cid:
        return jsonify({"status": "error"}), 400
    try:
        sb.table("access_codes").delete().eq("id", cid).execute()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/admin/codes/toggle', methods=['POST'])
def admin_codes_toggle():
    if not session.get('is_admin'):
        return jsonify({"status": "error"}), 401
    d = request.get_json(silent=True) or {}
    cid = d.get('id')
    if not cid:
        return jsonify({"status": "error"}), 400
    try:
        r = sb.table("access_codes").select("active").eq("id", cid).limit(1).execute()
        if not r.data:
            return jsonify({"status": "error", "message": "الكود غير موجود"}), 404
        new_state = not r.data[0].get("active", True)
        sb.table("access_codes").update({"active": new_state}).eq("id", cid).execute()
        return jsonify({"status": "ok", "active": new_state})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/redeem_code', methods=['POST'])
@limiter.limit("20 per hour")
def redeem_code():
    try:
        email = session.get('user_email')
        if not email:
            return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401
        d = request.get_json(silent=True) or {}
        code = (d.get('code') or '').strip().upper()
        if not code or len(code) < 5:
            return jsonify({"status": "error", "message": "أدخل كود صحيح"}), 400

        try:
            r = (sb.table("access_codes").select("*")
                 .eq("code", code).limit(1).execute())
        except Exception as e:
            print(f"redeem search error: {e}")
            return jsonify({"status": "error", "message": "خطأ في البحث"}), 500

        if not r.data:
            return jsonify({"status": "error", "message": "الكود غير موجود"}), 404

        row = r.data[0]

        if not row.get('active', True):
            return jsonify({"status": "error", "message": "هذا الكود موقوف حاليًا"}), 400

        expires_code = row.get('expires_at')
        if expires_code:
            try:
                exp_str = str(expires_code).replace('Z', '').replace('+00:00', '')
                if '.' in exp_str:
                    exp_str = exp_str.split('.')[0]
                exp = datetime.fromisoformat(exp_str)
                if exp < datetime.utcnow():
                    return jsonify({"status": "error", "message": "انتهت صلاحية الكود"}), 400
            except Exception as ex:
                print(f"code exp check: {ex}")

        used = int(row.get('used_count', 0) or 0)
        max_u = int(row.get('max_uses', 1) or 1)
        if used >= max_u:
            return jsonify({"status": "error", "message": f"الكود استُنفد ({used}/{max_u})"}), 400

        try:
            ex_r = (sb.table("access_redemptions").select("id")
                    .eq("code", code).eq("user_email", email.lower()).limit(1).execute())
            if ex_r.data:
                return jsonify({"status": "error", "message": "سبق أن فعّلت هذا الكود"}), 400
        except Exception as ex:
            print(f"dup check: {ex}")

        expires_user = (datetime.utcnow() + timedelta(days=int(row.get('duration_days', 7) or 7))).isoformat()
        try:
            sb.table("access_redemptions").insert({
                "code": code,
                "user_email": email.lower(),
                "chat_limit": int(row.get('chat_limit', 15) or 15),
                "search_limit": int(row.get('search_limit', 2) or 2),
                "image_limit": int(row.get('image_limit', 1) or 1),
                "expires_at": expires_user
            }).execute()
            sb.table("access_codes").update({
                "used_count": used + 1
            }).eq("id", row['id']).execute()
        except Exception as ex:
            print(f"redeem insert error: {ex}")
            return jsonify({"status": "error", "message": "تعذر تفعيل الكود"}), 500

        print(f"✅ Code redeemed: {code} → {email}")
        return jsonify({
            "status": "ok",
            "chat": row.get('chat_limit', 15),
            "search": row.get('search_limit', 2),
            "image": row.get('image_limit', 1),
            "expires_at": expires_user
        })
    except Exception as e:
        print(f"redeem_code error: {e}")
        return jsonify({"status": "error", "message": "خطأ غير متوقع"}), 500


@app.route('/my_access')
def my_access():
    email = session.get('user_email')
    if not email:
        return jsonify({"access": None, "status": "guest"})
    access = get_active_access(email)
    if access:
        try:
            exp_str = str(access.get('expires_at', '')).replace('Z', '').replace('+00:00', '')
            if '.' in exp_str:
                exp_str = exp_str.split('.')[0]
            exp = datetime.fromisoformat(exp_str)
            days_left = max(0, (exp - datetime.utcnow()).days)
        except Exception:
            days_left = 0
        return jsonify({
            "access": access, "status": "active", "days_left": days_left,
            "chat": access.get('chat_limit'),
            "search": access.get('search_limit'),
            "image": access.get('image_limit')
        })
    return jsonify({"access": None, "status": "none"})


# ==========================================================
#  Feedback / Reports
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
#  Share
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
#  Auth Routes
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
        except Exception as ex:
            print(f"LOGIN_EXCEPTION: {ex}")
            return render_template_string(LH, error="تعذر الاتصال.")
        if r.status_code != 200:
            return render_template_string(LH, error="البريد أو كلمة المرور غير صحيحة.")
        session.clear()
        session.permanent = True
        session['user_email'] = e
        session['is_admin'] = False
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
        print(f"SIGNUP_ERROR: {ex}")
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
        redirect_url = f"{request.host_url.rstrip('/')}/reset-password"
        requests.post(
            f"{SUPABASE_URL}/auth/v1/recover?redirect_to={redirect_url}",
            headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
            json={"email": e}, timeout=15)
        return render_template_string(LH, success="تم إرسال رابط الاستعادة على بريدك.")
    except Exception as ex:
        return render_template_string(LH, error=f"فشل: {ex}")


@app.route('/reset-password')
def reset_password_page():
    return render_template_string(RESET_HTML)


@app.route('/update_password', methods=['POST'])
def update_password():
    try:
        d = request.get_json(silent=True) or {}
        token = d.get('access_token', '')
        newp = d.get('new_password', '')
        if not token:
            return jsonify({"status": "error", "message": "الرابط غير صالح"}), 400
        if not newp or len(newp) < 8:
            return jsonify({"status": "error", "message": "8 أحرف على الأقل"}), 400
        r = requests.put(f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"password": newp}, timeout=15)
        return jsonify({"status": "ok"}) if r.status_code == 200 else (jsonify({"status": "error", "message": "فشل"}), 400)
    except Exception as e:
        return jsonify({"status": "error", "message": "خطأ"}), 500


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


ALLOWED_OAUTH_PROVIDERS = ("google",)

@app.route('/auth/<provider>')
def oauth_login(provider):
    if provider not in ALLOWED_OAUTH_PROVIDERS:
        return redirect(url_for('login'))
    callback = f"{request.host_url.rstrip('/')}/auth/callback"
    auth_url = (f"{SUPABASE_URL}/auth/v1/authorize?provider={provider}&redirect_to={urllib.parse.quote(callback, safe='')}")
    return redirect(auth_url)


@app.route('/auth/callback')
def oauth_callback():
    return render_template_string(OAUTH_CALLBACK_HTML)


@app.route('/auth/session', methods=['POST'])
@limiter.limit("20 per minute")
def oauth_session():
    try:
        d = request.get_json(silent=True) or {}
        at = d.get('access_token')
        if not at or not isinstance(at, str):
            return jsonify({"status": "error", "message": "توكن مفقود"}), 400
        r = requests.get(f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {at}"}, timeout=15)
        if r.status_code != 200:
            return jsonify({"status": "error", "message": "توكن غير صالح"}), 401
        u = r.json()
        email = (u.get('email') or '').lower().strip()
        if not email:
            return jsonify({"status": "error", "message": "بريد غير موجود"}), 400
        session.clear()
        session.permanent = True
        session['user_email'] = email
        session['is_admin'] = (email == ADMIN_EMAIL.lower())
        session['user_role'] = get_user_role(email)
        try:
            meta = u.get('user_metadata') or {}
            name = (meta.get('full_name') or meta.get('name') or email.split('@')[0]).strip()
            if not get_user_profile(email):
                save_user_profile(email, name=name)
                save_user_memory(email, {"name": name})
            touch_user(email)
        except Exception as e:
            print("oauth_session profile:", e)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": "خطأ داخلي"}), 500


# ==========================================================
#  Admin Routes
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


@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    recent, users_list = [], []
    try:
        recent = (sb.table("assistant_chats").select("user_id,title,created_at").order("created_at", desc=True).limit(10).execute()).data or []
    except Exception as e:
        print(f"admin recent error: {e}")
    try:
        users_list = (sb.table("profiles").select("email,display_name,role").order("created_at", desc=True).limit(30).execute()).data or []
    except Exception as e:
        print(f"admin users error: {e}")
    recent_html = "".join([f'<div class="conv-item"><b>{escape(str(r.get("title", "?")))}</b><small>{escape(str(r.get("user_id", ""))[:30])}</small></div>' for r in recent]) or "<p style='color:#8b949e;'>لا توجد</p>"
    users_html = "".join([f'<div class="conv-item"><b>{escape(str(u.get("display_name", "?")))}</b><small>{escape(str(u.get("email", "")))} ({escape(str(u.get("role", "user")))})</small></div>' for u in users_list]) or "<p style='color:#8b949e;'>لا يوجد</p>"
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
    </style></head><body><div class="container">
    <h1>لوحة تحكم نبراس</h1>
    <div class="card">
        <div class="stat"><span>المستخدمون</span><span class="num">{len(users_list)}</span></div>
    </div>

    <div class="card">
        <h3>🎟️ توليد كود وصول</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">
            <label style="font-size:13px;">محادثات
                <input type="number" id="code-chat" value="4" min="1" max="9999" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
            <label style="font-size:13px;">بحث
                <input type="number" id="code-search" value="4" min="0" max="9999" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
            <label style="font-size:13px;">صور
                <input type="number" id="code-image" value="4" min="0" max="9999" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
            <label style="font-size:13px;">عدد المستخدمين
                <input type="number" id="code-uses" value="1" min="1" max="1000" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
            <label style="font-size:13px;">المدة (أيام)
                <input type="number" id="code-days" value="7" min="1" max="365" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
            <label style="font-size:13px;">ملاحظة
                <input type="text" id="code-note" placeholder="مثلاً: لأختي" maxlength="200" style="width:100%;padding:10px;border:1px solid #dce1e8;border-radius:10px;margin-top:4px;box-sizing:border-box;">
            </label>
        </div>
        <button onclick="generateCode()" style="width:100%;padding:14px;background:#4a6a8a;color:#fff;border:none;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;">توليد الكود</button>
        <div id="generated-code" style="margin-top:14px;display:none;padding:14px;background:#f0fdf4;border-radius:12px;text-align:center;border:1px solid #86efac;">
            <div style="font-size:12px;color:#166534;margin-bottom:6px;">✅ الكود الجديد — اضغط للنسخ:</div>
            <div id="generated-code-text" onclick="navigator.clipboard.writeText(this.textContent);this.style.background='#bbf7d0';setTimeout(()=>this.style.background='transparent',300);" style="font-size:22px;font-weight:800;letter-spacing:3px;color:#166534;cursor:pointer;padding:8px;border-radius:8px;user-select:all;transition:background .2s;"></div>
        </div>
    </div>

    <div class="card">
        <h3>📋 الأكواد السابقة</h3>
        <div id="codes-list"><p style="color:#8b949e;">جاري التحميل...</p></div>
    </div>

    <script>
    async function generateCode(){{
        const body = {{
            chat: parseInt(document.getElementById('code-chat').value) || 15,
            search: parseInt(document.getElementById('code-search').value) || 2,
            image: parseInt(document.getElementById('code-image').value) || 1,
            max_uses: parseInt(document.getElementById('code-uses').value) || 1,
            days: parseInt(document.getElementById('code-days').value) || 7,
            note: document.getElementById('code-note').value || ''
        }};
        try{{
            const r = await fetch('/admin/codes/generate', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}});
            const d = await r.json();
            if(d.status === 'ok'){{
                const codeData = d.code;
                document.getElementById('generated-code-text').textContent = codeData.code || codeData;
                document.getElementById('generated-code').style.display = 'block';
                loadCodes();
            }} else {{
                alert(d.message || 'فشل التوليد');
            }}
        }}catch(e){{ alert('خطأ في الاتصال'); }}
    }}
    async function loadCodes(){{
        const list = document.getElementById('codes-list');
        try{{
            const r = await fetch('/admin/codes/list');
            const d = await r.json();
            if(!d.codes || d.codes.length === 0){{
                list.innerHTML = '<p style="color:#8b949e;">لا توجد أكواد بعد</p>';
                return;
            }}
            list.innerHTML = d.codes.map(c => {{
                const expired = c.expires_at && new Date(c.expires_at) < new Date();
                const status = !c.active ? 'موقوف' : (expired ? 'منتهي' : 'نشط');
                const statusColor = !c.active ? '#8b949e' : (expired ? '#e74c3c' : '#16a34a');
                return '<div style="padding:12px;border:1px solid #eef1f6;border-radius:10px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">'
                    +'<div><b style="letter-spacing:1px;font-size:14px;">'+c.code+'</b>'
                    +'<span style="color:'+statusColor+';font-size:12px;margin-right:6px;">● '+status+'</span>'
                    +'<div style="font-size:11px;color:#666;margin-top:4px;">'+c.chat_limit+' محادثة · '+c.search_limit+' بحث · '+c.image_limit+' صورة · استُخدم '+c.used_count+'/'+c.max_uses+(c.note ? ' · '+c.note : '')+'</div></div>'
                    +'<div style="display:flex;gap:6px;flex-wrap:wrap;">'
                    +'<button onclick="navigator.clipboard.writeText(\\''+c.code+'\\');this.textContent=\\'✓\\';setTimeout(()=>this.textContent=\\'نسخ\\',800);" style="padding:6px 10px;border:1px solid #4a6a8a;background:#fff;color:#4a6a8a;border-radius:8px;cursor:pointer;font-size:12px;">نسخ</button>'
                    +'<button onclick="toggleCode('+c.id+')" style="padding:6px 10px;border:1px solid #f59e0b;background:#fff;color:#f59e0b;border-radius:8px;cursor:pointer;font-size:12px;">'+(c.active?'إيقاف':'تشغيل')+'</button>'
                    +'<button onclick="deleteCode('+c.id+')" style="padding:6px 10px;border:1px solid #e74c3c;background:#fff;color:#e74c3c;border-radius:8px;cursor:pointer;font-size:12px;">حذف</button>'
                    +'</div></div>';
            }}).join('');
        }}catch(e){{ list.innerHTML = '<p style="color:#e74c3c;">تعذر التحميل</p>'; }}
    }}
    async function toggleCode(id){{
        await fetch('/admin/codes/toggle', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{id}})}});
        loadCodes();
    }}
    async function deleteCode(id){{
        if(!confirm('حذف الكود؟')) return;
        await fetch('/admin/codes/delete', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{id}})}});
        loadCodes();
    }}
    loadCodes();
    </script>

    <div class="card"><h3>المستخدمون</h3>{users_html}</div>
    <div class="card"><h3>آخر المحادثات</h3>{recent_html}</div>
    <a href="/" class="back">← العودة للرئيسية</a>
    </div>
    </body></html>"""


# ==========================================================
#  Voice + Chat
# ==========================================================

@app.route('/set_gender', methods=['POST'])
def set_gender():
    d = request.get_json(silent=True) or {}
    gender = d.get('gender', 'male')
    if gender not in ('male', 'female'):
        gender = 'male'
    session['voice_gender'] = gender
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
        assistant_id = d.get("assistant_id")
        if len(um) > 12000:
            return jsonify({"status": "error", "message": "الرسالة طويلة جدًا"}), 413
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

        assistant_persona_extra = ""
        if assistant_id and is_registered:
            try:
                ar = sb.table("custom_assistants").select("*").eq("id", assistant_id).eq("user_id", uid).limit(1).execute()
                if ar.data:
                    asst = ar.data[0]
                    assistant_persona_extra = (
                        f"\n\n**شخصيتك الحالية:**\n"
                        f"أنت الآن تجسّد '{asst['name']}'. {asst['persona']}\n\n"
                        f"من الآن وصاعداً، التزم بهذه الشخصية تماماً."
                    )
            except Exception as e:
                print(f"assistant load: {e}")

        usage, limits, can_chat, can_search, can_image = check_limits(
            uid,
            user_role if not is_admin else 'admin',
            email=user_email or None
        )
        if not can_chat:
            reply_limit = (
                "وصل محادثاتك للحد اليومي المسموح به 🙏\n\n"
                "💡 تبغى تستمتع بمحادثات إضافية؟\n"
                "اضغط على اسمك فوق → تفعيل كود وصول\n"
                "أو جرب بكرة إن شاء الله ☀️"
            ) if user_lang == 'ar' else (
                "You've reached your daily limit 🙏\n\n"
                "💡 Tap your name → Redeem access code\n"
                "Or try again tomorrow ☀️"
            )
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
                return jsonify({"status": "error", "message": "صيغة الصورة غير صالحة"}), 400
            if not is_registered:
                msg = "تحليل الصور للمسجلين فقط." if user_lang == 'ar' else "Image analysis for registered users only."
                return jsonify({"reply": msg, "conv_id": cid})
            if not can_image:
                msg = "وصلت للحد اليومي للصور." if user_lang == 'ar' else "Daily image limit reached."
                nid = save_message(uid, um, msg, cid) if is_registered else cid
                inc_usage(uid, "chat_count")
                def limit_img_stream():
                    yield f"data: {json.dumps({'token': msg}, ensure_ascii=False)}\n\n"
                    yield f"data: {json.dumps({'done': True, 'conv_id': nid or cid or ''}, ensure_ascii=False)}\n\n"
                return Response(
                    stream_with_context(limit_img_stream()),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
                )
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
                    if (isinstance(h, dict) and h.get("role") in ("user", "assistant") and isinstance(h.get("content"), str)):
                        server_hist.append({"role": h["role"], "content": h["content"][:2000]})
        if img_data and is_registered and can_image:
            user_content = [
                {"type": "text", "text": um or "حلل الصورة"},
                {"type": "image_url", "image_url": {"url": img_data}}
            ]
            server_hist.append({"role": "user", "content": user_content})
        else:
            server_hist.append({"role": "user", "content": um})
        lang_inst = LANG_INSTRUCTION.get(user_lang, "")
        if user_email:
            personality = get_user_memory(user_email).get('personality', 'friendly')
        else:
            personality = d.get('personality', 'friendly')
        if personality not in PERSONALITY_INSTRUCTIONS:
            personality = 'friendly'
        personality_inst = PERSONALITY_INSTRUCTIONS.get(personality, "")
        msgs = [{"role": "system", "content": 
            personality_inst + "\n\n" + SP + memory_context + lang_inst + assistant_persona_extra + "\n\n" + personality_inst
        }] + server_hist[-15:]
        if is_registered and can_search:
            inc_usage(uid, "search_count")
            try:
                sr = client.responses.create(
                    model=OPENAI_MODEL,
                    instructions="أنت محرك بحث. ارجع النتائج كما هي مع الروابط والمصادر والتواريخ.",
                    input=f"ابحث عن أحدث المعلومات: {um}",
                    tools=[{"type": "web_search"}]
                )
                res = ""
                if hasattr(sr, "output_text") and sr.output_text:
                    res = sr.output_text.strip()
                elif getattr(sr, "output", None):
                    try: res = sr.output[0].content[0].text
                    except: res = ""
                if res:
                    msgs.append({"role": "system", "content": f"نتائج البحث الفعلية من الويب (بيانات داخلية مو رسالة من المستخدم):\n\n{res}"})
            except Exception as e:
                print(f"فشل البحث ({type(e).__name__}): {e}")
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
                else:
                    if not nid:
                        nid = "guest_conv_" + secrets.token_hex(5)
                inc_usage(uid, "chat_count")
                if has_image and is_registered and can_image:
                    inc_usage(uid, "image_count")
                yield f"data: {json.dumps({'done': True, 'conv_id': nid})}\n\n"
            except Exception as e:
                print("stream error:", repr(e))
                safe_error = "تعذر إكمال الطلب. حاول مرة أخرى." if user_lang == "ar" else "The request failed."
                yield f"data: {json.dumps({'error': safe_error}, ensure_ascii=False)}\n\n"
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'}
        )
    except Exception as e:
        print("chat request error:", repr(e))
        return jsonify({"status": "error", "message": "حدث خطأ داخلي"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 8 — نهاية الملف
# ═══════════════════════════════════════════════════════════
