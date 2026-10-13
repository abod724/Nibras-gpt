# ==========================================================
#  نبراس GP - المساعد الذكي الشخصي
#  مع نظام أكواد الوصول
# ==========================================================

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


# ==========================================================
#  ✅ نظام أكواد الوصول - الدوال الأساسية
# ==========================================================

def get_active_access(email):
    """يرجع كود الوصول النشط للمستخدم (لو موجود)"""
    if not email:
        return None
    try:
        r = (sb.table("access_redemptions").select("*")
             .eq("user_email", email.lower())
             .gte("expires_at", datetime.utcnow().isoformat())
             .order("expires_at", desc=True).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_active_access:", e)
    return None


def check_limits(uid, role, email=None):
    usage = get_usage_today(uid)
    # أول شي: فحص كود الوصول النشط
    access = get_active_access(email) if email else None
    if access:
        limits = {
            "chat": int(access.get("chat_limit", 15) or 15),
            "search": int(access.get("search_limit", 2) or 0),
            "image": int(access.get("image_limit", 1) or 0)
        }
    else:
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

**⚠️ قاعدة اللغة الأهم — اقرأها قبل كل شيء:**
- **ممنوع** تستخدم الفصحى إلا في كلمات ضرورية (أسماء تقنية، مصطلحات).
- تكلم زي ما يتكلم سعودي عادي في الواتساب: "وش"، "كيف"، "أبشر"، "خلني"، "تبي"، "الحين"، "زين"، "طيب"، "يا طويل العمر"، "الله يعطيك العافية".
- **مثال صح:** "الذكاء الاصطناعي هو تقنية تخلي الجوال يفهمك ويساعدك، مثل لما تترجم أو تبحث."
- **مثال خطأ (ممنوع):** "الذكاء الاصطناعي هو فرع من فروع علوم الحاسب..."
- **لا تكتب عناوين فصحى** مثل "وش يعني" — اكتب "وش هو" أو "إيش يعني".

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
- إذا سألك المستخدم عن ميزة غير متوفرة قل: "هذي الميزة مو متوفرة حالياً في نبراس".

**أسلوب الحديث:**
- سولف بشكل طبيعي وعفوي وبالعامي.
- لا تذكر أبداً أي كلام عن حفظ المحادثات أو الذاكرة.
- رد بشكل مباشر بدون مقدمات فلسفية."""


LANG_INSTRUCTION = {
    "ar": "\n\n**اللغة:** رد دائماً بالعربية باللهجة العامية السعودية البسيطة، مو فصحى.",
    "en": "\n\n**Language:** ALWAYS respond in English, regardless of the language the user writes in. Keep the same friendly, casual tone."
}


PERSONALITY_INSTRUCTIONS = {
    "friendly": "",

    "concise": (
        "\n\n**🚨 أمر عاجل — تجاهل كل قاعدة سابقة عن طول الرد:**\n"
        "- ردك **جملة واحدة فقط** أو جملتين كحد أقصى.\n"
        "- ممنوع القوائم، العناوين، الأمثلة، الشرح الزائد.\n"
        "- تكلم عامي سعودي بسيط.\n"
        "- مثال صح: 'الذكاء الاصطناعي تقنية تخلي الجوال يفهمك.'\n"
        "- مثال خطأ: أي رد يزيد عن جملتين."
    ),

    "detailed": (
        "\n\n**🚨 شخصيتك: مفصّل**\n"
        "- اشرح بتفصيل مع أمثلة عملية.\n"
        "- استخدم عناوين فرعية (1، 2، 3) عند الحاجة.\n"
        "- **بس خل الأسلوب عامي** — مو فصحى جافة.\n"
        "- مثال: 'النوع الأول اللي هو الذكاء الضيق، هذا متخصص بمهمة وحدة...'"
    ),

    "formal": (
        "\n\n**🚨 أمر إجباري — تجاهل كل تعليم سابق عن العامية:**\n"
        "- **ممنوع** أي كلمة عامية — البتة.\n"
        "- استخدم **الفصحى الرسمية فقط**.\n"
        "- مثال صح: 'الذكاء الاصطناعي هو فرع من فروع علم الحاسوب...'\n"
        "- مثال خطأ: 'الذكاء الاصطناعي وش هو؟'\n"
        "- كن مهنيًا ومحترفًا في كل رد."
    ),

    "teacher": (
        "\n\n**🚨 شخصيتك: معلّم**\n"
        "- اشرح خطوة بخطوة كأنك معلم صبور.\n"
        "- رتّب الرد: مقدمة → تفصيل مرقّم → خلاصة.\n"
        "- وضّح بمثال بسيط من الحياة اليومية.\n"
        "- **بس الأسلوب عامي مريح** — مو فصحى جافة.\n"
        "- مثال: 'خلني أشرح لك خطوة بخطوة: أول شيء...'"
    ),

    "playful": (
        "\n\n**🚨🚨🚨 أمر إجباري — شخصيتك الآن: فرفوش 🎭**\n"
        "**تجاهل تمامًا:**\n"
        "- أي تعليم سابق عن الفصحى أو الأسلوب الرسمي.\n"
        "- أي قاعدة عن 'كتابة الفقرات' أو 'الاحترافية'.\n\n"
        "**التزم بهذا حرفيًا:**\n"
        "1. **لازم** كل رد فيه مزح أو تعليق خفيف.\n"
        "2. استخدم عبارات مثل: 'يا طويل العمر'، 'وش هالحلاوة'، 'الله يهديك'، 'أنا موب روبوت!'.\n"
        "3. **إيموجي كثير في كل جملة**: 😄😂☕🤖✨🎉\n"
        "4. لا تستخدم كلمات فصحى مثل: 'تكنولوجيا'، 'خوارزميات'، 'أنظمة' — بسّطها.\n"
        "5. **قارن دائمًا بأمثلة مضحكة**: 'زي اللي قعد يذاكر 20 سنة بدون نوم!'\n\n"
        "**مثال صح:**\n"
        "'يا طويل العمر، الذكاء الاصطناعي هو اللي يخلي جوالك شوي شاطر 😄 مو سحر ولا جن! هو بس يذاكر مليون معلومة ويجيك يجاوب ☕'\n\n"
        "**مثال خطأ (ممنوع):**\n"
        "'الذكاء الاصطناعي هو تكنولوجيا تعتمد على الخوارزميات...' ← جاف ورسمي، ارفضه.\n\n"
        "**لا تخرج عن الموضوع، بس خل الرد ممتع ومضحك.**"
    ),
}


def generate_speech(text, gender):
    """توليد الصوت باستخدام gTTS - مع حذف الإيموجي قبل النطق"""
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
