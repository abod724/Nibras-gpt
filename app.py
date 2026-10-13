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
