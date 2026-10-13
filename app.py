# ==========================================================
#  نبراس GP - المساعد الذكي الشخصي
#  مع نظام أكواد الوصول + أخبار Google News المنسقة كبطاقات
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
from markupsafe import escape, Markup
import io
import urllib.parse
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from gtts import gTTS
# ✅ جديد: مكتبات تنسيق Markdown
import markdown
import bleach


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
    if not email:
        return None
    try:
        r = (sb.table("access_redemptions").select("*")
             .eq("user_email", email.lower().strip())
             .order("expires_at", desc=True)
             .limit(10)
             .execute())
        if not r or not r.data:
            return None
        from datetime import timezone
        now = datetime.now(timezone.utc)
        for row in r.data:
            exp_raw = row.get("expires_at")
            if not exp_raw:
                continue
            try:
                exp_str = str(exp_raw).replace('Z', '+00:00')
                exp_dt = datetime.fromisoformat(exp_str)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt > now:
                    return row
            except Exception as ex:
                print("get_active_access parse:", ex, exp_raw)
                continue
    except Exception as e:
        print("get_active_access:", e)
    return None


def check_limits(uid, role, email=None):
    usage = get_usage_today(uid)
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


# ==========================================================
#  ✅ جديد: دالة تحويل Markdown إلى HTML منسق (بطاقات إخبارية)
# ==========================================================
def format_nibras_response(text):
    """تحويل رد نبراس (Markdown) إلى HTML منسق وآمن."""
    if not isinstance(text, str):
        return ""

    text = text.strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # إزالة أسوار Markdown الخارجية إن وجدت
    text = re.sub(
        r"^\s*```(?:markdown|md)?\s*\n(.*?)\n```\s*$",
        r"\1",
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    # تحويل Markdown إلى HTML
    html = markdown.markdown(
        text,
        extensions=["extra", "sane_lists", "nl2br"]
    )

    # السماح بوسوم آمنة فقط
    allowed_tags = set(bleach.sanitizer.ALLOWED_TAGS).union({
        "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "br", "hr", "ul", "ol", "li",
        "strong", "em", "blockquote",
        "pre", "code", "table", "thead",
        "tbody", "tr", "th", "td", "img"
    })

    allowed_attributes = {
        "a": ["href", "title", "rel", "target"],
        "img": ["src", "alt", "title", "width", "height"],
        "code": ["class"],
        "pre": ["class"],
        "th": ["align"],
        "td": ["align"]
    }

    clean_html = bleach.clean(
        html,
        tags=allowed_tags,
        attributes=allowed_attributes,
        protocols={"http", "https", "mailto"},
        strip=True
    )

    # إضافة حماية للروابط الخارجية
    clean_html = re.sub(
        r'<a\s+href="(https?://[^"]*)"',
        r'<a href="\1" target="_blank" rel="noopener noreferrer"',
        clean_html
    )

    return Markup(clean_html)


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


# ==========================================================
#  📰 نظام الأخبار (Google News RSS) — منسق كبطاقات
# ==========================================================

_news_cache = {}
_NEWS_CACHE_TTL = 900


def fetch_news(query, limit=6):
    """يجيب أخبار من Google News RSS — مع cache"""
    if not query or len(query) < 2:
        return []
    query = query.strip()[:150]
    now = time.time()
    cached = _news_cache.get(query)
    if cached and (now - cached[0]) < _NEWS_CACHE_TTL:
        return cached[1]

    url = (
        "https://news.google.com/rss/search?q="
        + quote_plus(query)
        + "&hl=ar&gl=SA&ceid=SA:ar"
    )
    headers = {"User-Agent": "Mozilla/5.0 (NibrasGP/1.0)"}

    try:
        r = requests.get(url, headers=headers, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        articles = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            pub = item.findtext("pubDate", "").strip()
            src_el = item.find("source")
            source = (src_el.text.strip() if src_el is not None and src_el.text else "")
            if title and link:
                articles.append({
                    "title": title,
                    "link": link,
                    "published": pub,
                    "source": source,
                })
        if len(_news_cache) > 100:
            _news_cache.clear()
        _news_cache[query] = (now, articles)
        return articles
    except (requests.RequestException, ET.ParseError) as exc:
        print("News fetch failed:", type(exc).__name__, exc)
        return []


def detect_news_query(text):
    """يكتشف إذا المستخدم يبي أخبار ويرجع الكلمات المفتاحية"""
    if not text:
        return None
    t = text.strip()
    triggers = ["أخبار", "اخبار", "خبر", "آخر أخبار", "اخر اخبار", "news",
                "آخر الأنباء", "الجديد في", "وش صار في", "وش يصير في"]
    tl = t.lower()
    for kw in triggers:
        if kw in tl:
            clean = t
            for remove in ["أخبار", "اخبار", "آخر أخبار", "اخر اخبار",
                           "آخر الأنباء", "الجديد في", "وش صار في", "وش يصير في",
                           "news"]:
                clean = clean.replace(remove, "")
            clean = clean.strip(" ؟?.,،عن في من ")
            return clean if len(clean) >= 2 else t
    return None


# ✅ جديد: إخراج Markdown منسق بدلاً من نص عادي
def format_news_reply(articles, lang="ar"):
    """يحوّل الأخبار لرد منسق بصيغة Markdown (لعرضها كبطاقات)"""
    if not articles:
        return "ما لقيت أخبار جديدة عن الموضوع هذا." if lang == "ar" else "No recent news found."

    lines = []
    if lang == "ar":
        lines.append("## 📰 آخر الأخبار")
    else:
        lines.append("## 📰 Latest News")
    lines.append("")
    lines.append("تشي هذي القائمة بأحدث الأخبار المتعلقة بطلبك:")
    lines.append("")

    for i, a in enumerate(articles[:6], 1):
        title = (a.get("title") or "").strip()
        source = (a.get("source") or "").strip()
        link = (a.get("link") or "").strip()
        published = (a.get("published") or "").strip()

        lines.append("---")
        lines.append("")
        lines.append(f"### {i}. {title}")
        lines.append("")

        meta_parts = []
        if source:
            meta_parts.append(f"**المصدر:** {source}")
        if published:
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(published)
                date_str = dt.strftime("%d %B %Y")
                meta_parts.append(f"*{date_str}*")
            except Exception:
                pass
        if meta_parts:
            lines.append(" · ".join(meta_parts))
            lines.append("")

        if link:
            lines.append(f"[🔗 قراءة الخبر كاملاً]({link})")
            lines.append("")

    return "\n".join(lines)


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

LIBRARY_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.img-card .delete-btn:hover svg{stroke:#fff}.img-card .delete-btn svg{width:16px;height:16px;stroke:#ff4757;stroke-width:2;fill:none}.empty{text-align:center;padding:60px 20px;color:#8b949e}.empty svg{width:64px;height:64px;stroke:#dce1e8;stroke-width:1.5;fill:none;margin-bottom:16px}.empty h3{color:#5a6b7c;font-size:18px;margin-bottom:6px}.empty p{font-size:14px}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}@media(max-width:520px){.topbar h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.img-card .preview{height:150px}}</style></head><body><div class="container"><div class="topbar"><h1><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4a6a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.replaceChildren();if(!d.images||d.images.length===0){const empty=document.createElement('div');empty.className='empty';empty.style.gridColumn='1/-1';const h=document.createElement('h3');h.textContent='مكتبتك فاضية';const p=document.createElement('p');p.textContent='ارفع أول صورة';empty.append(h,p);grid.appendChild(empty);return;}d.images.forEach(img=>{const src=img.image_data||img.image_url||'';const card=document.createElement('div');card.className='img-card';const preview=document.createElement('img');preview.className='preview';preview.loading='lazy';if(typeof src==='string'&&(src.startsWith('data:image/')||src.startsWith('https://')))preview.src=src;preview.alt='صورة من المكتبة';const del=document.createElement('button');del.className='delete-btn';del.type='button';del.title='حذف';del.textContent='×';const info=document.createElement('div');info.className='info';const title=document.createElement('div');title.className='title';title.textContent=String(img.title||'صورة');const source=document.createElement('div');source.className='source';source.textContent=img.source==='generated'?'مولدة':'مرفوعة';info.append(title,source);card.append(preview,del,info);del.onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف هذه الصورة؟'))return;try{const dr=await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});const res=await dr.json();if(dr.ok&&res.status==='ok'){card.remove();showToast('تم الحذف');if(grid.children.length===0)loadImages();}else showToast('فشل الحذف');}catch(e){showToast('خطأ في الاتصال');}};grid.appendChild(card);});}catch(e){grid.replaceChildren();const msg=document.createElement('p');msg.className='empty';msg.textContent='تعذر تحميل الصور';grid.appendChild(msg);}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{const r=await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});const d=await r.json();if(d.status==='ok')showToast('تم رفع الصورة');else showToast(d.message||'فشل الرفع');}catch(e){showToast('خطأ في الاتصال');}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};zone.ondragover=(e)=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=(e)=>{e.preventDefault();zone.classList.remove('dragover');uploadFiles(e.dataTransfer.files);};loadImages();
</script></body></html>"""

LH = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif;-webkit-tap-highlight-color:transparent}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;position:relative;font-family:inherit;transition:color .2s}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}.field input::placeholder{color:#a5b0be}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit;transition:all .2s}button.submit:hover{background:#3a5a7a}button.submit:active{transform:scale(0.98)}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}a:hover{color:#3a5a7a}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider{margin:22px 0 0;padding-top:18px;border-top:1px solid #eef1f6}.privacy-link{font-size:12px;color:#a5b0be;margin-top:6px;text-decoration:underline;font-weight:500}
.divider-or{display:flex;align-items:center;gap:14px;margin:26px 0 18px;color:#a5b0be;font-size:13px;font-weight:500}
.divider-or::before,.divider-or::after{content:'';flex:1;height:1px;background:#e8ecf1}
.google-btn{display:flex;align-items:center;justify-content:center;gap:14px;padding:14px 24px;border:1.5px solid #dce1e8;border-radius:50px;background:#fff;color:#1a2b3c;font-size:15px;font-weight:600;text-decoration:none;cursor:pointer;transition:all .2s ease;font-family:inherit;-webkit-tap-highlight-color:transparent;width:100%;margin-top:0;box-sizing:border-box}
.google-btn:hover{background:#f8faff;border-color:#4285F4;box-shadow:0 4px 14px rgba(66,133,244,0.12);color:#1a2b3c}
.google-btn:active{transform:scale(0.99)}
.google-btn svg{width:22px;height:22px;flex-shrink:0}
.google-btn span{line-height:1}
@media(max-width:420px){.box{padding:34px 24px}h2{font-size:22px}}@media(prefers-color-scheme:dark){body{background:#0d1117}.box{background:#161b22}h2{color:#c9d1d9}.subtitle{color:#8b949e}.tabs{border-bottom-color:#30363d}.tabs button{color:#8b949e}.tabs button.active{color:#58a6ff}.tabs button.active::after{background:#58a6ff}.field input{background:#21262d;border-color:#30363d;color:#c9d1d9}.field input:focus{border-color:#58a6ff;background:#21262d;box-shadow:0 0 0 4px rgba(88,166,255,0.15)}button.submit{background:#238636}button.submit:hover{background:#2ea043}.divider{border-top-color:#30363d}.divider-or{color:#8b949e}.divider-or::before,.divider-or::after{background:#30363d}.google-btn{background:#21262d;border-color:#30363d;color:#c9d1d9}.google-btn:hover{background:#1a2332;border-color:#4285F4;color:#c9d1d9}.privacy-link{color:#6e7681}}</style></head><body><div class="box"><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg></div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div>
<div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form>
<div class="divider-or"><span>أو</span></div>
<a href="/auth/google" class="google-btn" aria-label="المتابعة باستخدام حساب Google">
<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
<span>المتابعة باستخدام حساب Google</span>
</a>
</div>
<div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form><div class="divider-or" style="margin-top:26px;"><span>أو</span></div><a href="/auth/google" class="google-btn" aria-label="المتابعة باستخدام حساب Google"><svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg><span>المتابعة باستخدام حساب Google</span></a></div>
<div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div class="divider" style="display:flex;flex-wrap:wrap;justify-content:center;align-items:center;gap:8px;"><a href="/" style="margin-top:0;">العودة للرئيسية</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" class="privacy-link" style="margin-top:0;">شروط الاستخدام</a><span style="color:#dce1e8;">|</span><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="privacy-link" style="margin-top:0;">سياسة الخصوصية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

OAUTH_CALLBACK_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>جاري تسجيل الدخول...</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:380px;text-align:center}.spinner{width:52px;height:52px;border:4px solid #e5e9ef;border-top-color:#4a6a8a;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px}@keyframes spin{to{transform:rotate(360deg)}}h2{font-size:19px;color:#1a2b3c;margin-bottom:8px;font-weight:700}p{color:#8b949e;font-size:14px;line-height:1.7}.err{color:#d63031}.ok{color:#00b894}@media(prefers-color-scheme:dark){body{background:#0d1117}.box{background:#161b22}h2{color:#c9d1d9}p{color:#8b949e}.spinner{border-color:#30363d;border-top-color:#58a6ff}}</style></head><body><div class="box"><div class="spinner" id="spin"></div><h2 id="title">جاري تسجيل الدخول</h2><p id="msg">لحظة من فضلك...</p></div><script>
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
        var errParam=params.get('error')||params.get('error_description');
        if(errParam){fail(decodeURIComponent(errParam).replace(/\\+/g,' '));return;}
        if(!at){fail('لم يتم استلام التوكن. حاول مرة أخرى.');return;}
        fetch('/auth/session',{
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({access_token:at,refresh_token:rt||''})
        }).then(function(r){return r.json();}).then(function(d){
            if(d&&d.status==='ok'){
                titleEl.textContent='تم تسجيل الدخول';
                titleEl.classList.add('ok');
                msgEl.textContent='جاري تحويلك...';
                setTimeout(function(){window.location.href='/';},500);
            } else {
                fail((d&&d.message)||'فشل إنشاء الجلسة');
            }
        }).catch(function(){fail('تعذر الاتصال بالسيرفر');});
    }catch(e){fail('خطأ في قراءة الرابط');}
})();
</script></body></html>"""

RESET_HTML = """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>تعيين كلمة مرور جديدة</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff}h2{font-size:22px;color:#1a2b3c;margin-bottom:8px}.subtitle{color:#8b949e;font-size:14px;margin-bottom:26px}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;font-family:inherit;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit}button.submit:hover{background:#3a5a7a}.msg{padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right;display:none}.msg.err{display:block;color:#d63031;background:#ffe8e8}.msg.ok{display:block;color:#00b894;background:#e6fff5}</style></head><body><div class="box"><div class="logo"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="width:30px;height:30px;"><circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/></svg></div><h2>كلمة مرور جديدة</h2><p class="subtitle">اكتب كلمة مرورك الجديدة</p><div id="msg" class="msg"></div><form id="resetForm"><div class="field"><input type="password" id="newPass" placeholder="كلمة المرور الجديدة (8 أحرف +)" minlength="8" required></div><div class="field"><input type="password" id="confirmPass" placeholder="تأكيد كلمة المرور" minlength="8" required></div><button type="submit" class="submit">حفظ كلمة المرور</button></form></div><script>
(function(){
    var msgEl=document.getElementById('msg');
    var formEl=document.getElementById('resetForm');
    var accessToken=null;
    try{
        var hash=window.location.hash.substring(1);
        var qs=window.location.search.substring(1);
        var params=new URLSearchParams(hash||qs);
        accessToken=params.get('access_token');
        if(!accessToken){
            msgEl.className='msg err';
            msgEl.textContent='الرابط غير صالح أو منتهي. اطلب رابط استعادة جديد.';
            formEl.style.display='none';
        }
    }catch(e){
        msgEl.className='msg err';
        msgEl.textContent='خطأ في قراءة الرابط.';
        formEl.style.display='none';
    }
    formEl.addEventListener('submit',async function(ev){
        ev.preventDefault();
        var p1=document.getElementById('newPass').value;
        var p2=document.getElementById('confirmPass').value;
        if(p1.length<8){
            msgEl.className='msg err';msgEl.textContent='كلمة المرور لازم 8 أحرف على الأقل';return;
        }
        if(p1!==p2){
            msgEl.className='msg err';msgEl.textContent='كلمتا المرور ما تتطابقان';return;
        }
        msgEl.className='msg';msgEl.textContent='جاري الحفظ...';
        try{
            var r=await fetch('/update_password',{
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({access_token:accessToken,new_password:p1})
            });
            var d=await r.json();
            if(d.status==='ok'){
                msgEl.className='msg ok';
                msgEl.textContent='تم تعيين كلمة المرور! جاري التحويل لتسجيل الدخول...';
                setTimeout(function(){window.location.href='/login';},1500);
            }else{
                msgEl.className='msg err';
                msgEl.textContent=(d.message||'فشل التحديث');
            }
        }catch(e){
            msgEl.className='msg err';msgEl.textContent='تعذر الاتصال بالسيرفر';
        }
    });
})();
</script></body></html>"""


# ✅ تمت إضافة CSS الخاص بـ .nibras-response داخل HT
HT = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><meta name="screen-orientation" content="portrait"><meta name="x5-orientation" content="portrait"><meta name="full-screen" content="no"><meta name="x5-fullscreen" content="false"><meta name="browsermode" content="application"><meta name="x5-page-mode" content="app"><title>نبراس GP | مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"><link rel="icon" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="180x180" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="192x192" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="512x512" href="/static/icon-512.png"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="نبراس"><meta name="theme-color" content="#ffffff"><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--border-input:#dce1e8;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--modal-bg:rgba(0,0,0,0.5);--accent-color:#4a6a8a;--font-size-base:16px;--font-size-small:14px}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#58a6ff;--border-input:#30363d;--send-bg:#238636;--send-hover:#2ea043;--modal-bg:rgba(0,0,0,0.7);--accent-color:#58a6ff}html[data-font="small"]{--font-size-base:14px;--font-size-small:12.5px}html[data-font="medium"]{--font-size-base:16px;--font-size-small:14px}html[data-font="large"]{--font-size-base:18px;--font-size-small:16px}html[data-font="xlarge"]{--font-size-base:20px;--font-size-small:18px}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif;-webkit-tap-highlight-color:transparent;-webkit-touch-callout:none}html{-webkit-tap-highlight-color:transparent}body{-webkit-tap-highlight-color:transparent}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s,opacity .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.icon-btn.voice-on{color:var(--primary-color);opacity:1}.icon-btn.voice-off{color:var(--text-secondary);opacity:0.7}.btn-group{display:flex;gap:8px;align-items:center}.btn{padding:7px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center;font-family:inherit;font-weight:600}.btn-outline{background:0 0;border:1.5px solid var(--primary-color);color:var(--primary-color);transition:all .2s}.btn-outline:hover{background:var(--primary-color);color:#fff}.user-badge{display:flex;align-items:center;gap:6px;background:var(--bg-hover);padding:6px 12px;border-radius:20px;font-size:13px;color:var(--text-primary);font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;border:none;font-family:inherit}.user-badge:hover{background:var(--border-color)}.user-badge svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}.dropdown{position:absolute;top:68px;left:12px;right:12px;background:var(--bg-dropdown);border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15),0 4px 12px rgba(0,0,0,0.08);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:78vh;overflow-y:auto;padding:10px;opacity:0;transform:translateY(-8px);transition:opacity .2s ease,transform .2s ease}.dropdown.show{display:flex;opacity:1;transform:translateY(0)}.dropdown::-webkit-scrollbar{width:4px}.dropdown::-webkit-scrollbar-thumb{background:var(--border-color);border-radius:4px}.dropdown .item{display:flex;align-items:center;gap:14px;padding:13px 16px;font-size:15px;color:var(--text-primary);background:transparent;border:none;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-weight:600;border-radius:14px;transition:background .15s ease,transform .1s ease;letter-spacing:-0.2px}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .item:active{transform:scale(0.98)}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0;stroke-linecap:round;stroke-linejoin:round;opacity:.85}.dropdown .section-title{padding:16px 16px 6px;font-size:11px;font-weight:700;color:var(--text-secondary);letter-spacing:.8px;text-transform:uppercase;opacity:.7}.dropdown .conv-item{display:flex;align-items:center;gap:8px;padding:11px 16px;border:none;background:transparent;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-size:14px;color:var(--text-primary);font-weight:500;border-radius:14px;transition:background .15s ease;letter-spacing:-0.1px;position:relative}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item .conv-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dropdown .conv-item::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--primary-color);opacity:.4;flex-shrink:0}.dropdown .conv-item .pin-btn{background:transparent;border:none;cursor:pointer;padding:4px;border-radius:8px;display:flex;align-items:center;justify-content:center;opacity:0.5;transition:opacity .2s,background .2s;flex-shrink:0}.dropdown .conv-item .pin-btn:hover{opacity:1;background:var(--bg-hover)}.dropdown .conv-item .pin-btn svg{width:16px;height:16px;stroke:var(--text-primary);stroke-width:2;fill:none}.dropdown .conv-item .pin-btn.pinned svg{fill:var(--primary-color);stroke:var(--primary-color)}.dropdown .pinned-item{padding:11px 16px;display:flex;align-items:center;gap:8px;border-radius:14px;transition:background .15s ease}.dropdown .pinned-item:hover{background:var(--bg-hover)}.gender-option{flex:1;padding:9px 12px;border-radius:12px;border:1px solid var(--border-color);background:transparent;font-size:13px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s ease;font-family:inherit}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color);box-shadow:0 4px 12px rgba(74,106,138,0.3)}.dropdown .item.danger{color:#d32f2f}.dropdown .item.danger svg{stroke:#d32f2f;opacity:1}.dropdown .item.danger:hover{background:rgba(211,47,47,0.08)}.settings-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:99999;display:none;flex-direction:column;overflow-y:auto}.settings-overlay.show{display:flex}.settings-page{max-width:500px;width:100%;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column;background:var(--bg-body)}.settings-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.settings-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.settings-body{padding:16px;display:flex;flex-direction:column;gap:14px}.settings-card{background:var(--bg-app);border-radius:18px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.settings-item{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.settings-item:last-child{border-bottom:none}.settings-item:hover{background:var(--bg-hover)}.settings-item .item-right{display:flex;align-items:center;gap:14px;color:var(--text-primary);font-size:15px;font-weight:600}.settings-item .item-right svg{width:22px;height:22px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0}.settings-item .chevron{width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none}.sub-page{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;display:none;align-items:center;justify-content:center;padding:20px}.sub-page.show{display:flex}.sub-page .modal-box{background:var(--bg-app);width:100%;max-width:420px;max-height:80vh;border-radius:22px;overflow:hidden;display:flex;flex-direction:column;animation:modalIn .25s ease;border:1px solid var(--border-color)}.sub-page-header{display:none}.sub-page-body{padding:20px;overflow-y:auto;flex:1}.sub-page-body::-webkit-scrollbar{width:4px}.sub-page-body::-webkit-scrollbar-thumb{background:var(--border-color);border-radius:4px}.modal-title{text-align:center;font-size:17px;font-weight:700;color:var(--text-primary);padding:18px 20px;border-bottom:1px solid var(--border-color)}.modal-confirm{width:100%;padding:16px;background:transparent;border:none;border-top:1px solid var(--border-color);font-size:16px;font-weight:700;color:var(--primary-color);cursor:pointer;font-family:inherit}.modal-confirm:active{background:var(--bg-hover)}@keyframes modalIn{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:scale(1)}}.info-box{background:var(--bg-hover);padding:16px;border-radius:14px;font-size:14px;color:var(--text-secondary);line-height:1.8}.option-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.option-row{padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.option-row:last-child{border-bottom:none}.option-row:active{background:var(--bg-hover)}.option-label{display:flex;justify-content:space-between;align-items:center;font-size:15px;color:var(--text-primary);font-weight:500}.check-icon{width:22px;height:22px;stroke:var(--primary-color);stroke-width:2.5;fill:none;opacity:0;transition:opacity .25s}.option-row.selected .check-icon{opacity:1}.color-grid{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.color-row{padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:background .2s}.color-row:last-child{border-bottom:none}.color-row:active{background:var(--bg-hover)}.color-row-left{display:flex;align-items:center;gap:14px;font-size:15px;color:var(--text-primary);font-weight:500}.color-circle{width:26px;height:26px;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.15);flex-shrink:0}.color-row .check-icon{opacity:0;transition:opacity .25s}.color-row.selected .check-icon{opacity:1}.lang-list{display:flex;flex-direction:column;gap:12px}.lang-card{display:flex;align-items:center;gap:16px;padding:18px 20px;background:var(--bg-app);border-radius:18px;cursor:pointer;border:2px solid var(--border-color);transition:all .25s cubic-bezier(.4,0,.2,1);box-shadow:0 1px 3px var(--shadow-color)}.lang-card:hover{border-color:var(--primary-color);transform:translateY(-2px);box-shadow:0 8px 24px rgba(74,106,138,0.15)}.lang-card.selected{border-color:var(--primary-color);background:linear-gradient(135deg,var(--bg-app) 0%,rgba(74,106,138,0.06) 100%);box-shadow:0 6px 20px rgba(74,106,138,0.18)}.lang-flag{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;flex-shrink:0;letter-spacing:-0.5px;box-shadow:0 2px 6px rgba(0,0,0,0.15);color:#fff}.lang-info{flex:1;display:flex;flex-direction:column;gap:3px}.lang-name{font-size:17px;font-weight:700;color:var(--text-primary);letter-spacing:-0.2px}.lang-sub{font-size:13px;color:var(--text-secondary)}.lang-check{width:26px;height:26px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;transition:opacity .3s ease,transform .35s cubic-bezier(.34,1.56,.64,1);flex-shrink:0;transform:scale(0.5)}.lang-card.selected .lang-check{opacity:1;transform:scale(1)}
.personality-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}
.personality-row{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}
.personality-row:last-child{border-bottom:none}
.personality-row:active{background:var(--bg-hover)}
.personality-text{display:flex;flex-direction:column;gap:3px;flex:1;min-width:0}
.personality-name{font-size:15px;color:var(--text-primary);font-weight:500;letter-spacing:-0.1px;transition:color .2s ease}
.personality-sub{font-size:12.5px;color:var(--text-secondary);letter-spacing:-0.1px}
.personality-row .check-icon{opacity:0;transition:opacity .25s ease;flex-shrink:0;margin-right:8px}
.personality-row.selected .personality-name{color:var(--primary-color);font-weight:700}
.personality-row.selected .check-icon{opacity:1}
.fontsize-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}
.fontsize-row{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}
.fontsize-row:last-child{border-bottom:none}
.fontsize-row:active{background:var(--bg-hover)}
.fontsize-row-left{display:flex;flex-direction:column;gap:4px}
.fontsize-label{font-size:15px;color:var(--text-primary);font-weight:500;transition:color .2s ease}
.fontsize-sample{color:var(--text-secondary);transition:color .2s ease}
.fontsize-row .check-icon{opacity:0;transition:opacity .25s ease;flex-shrink:0}
.fontsize-row.selected .fontsize-label{color:var(--primary-color);font-weight:700}
.fontsize-row.selected .check-icon{opacity:1}
.memory-card{background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color);margin-bottom:14px}
.memory-header{padding:14px 18px;background:var(--bg-hover);display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border-color)}
.memory-header svg{width:18px;height:18px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}
.memory-header span{font-size:14px;color:var(--text-primary);font-weight:700}
.memory-item{padding:14px 18px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.memory-item:last-child{border-bottom:none}
.memory-key{font-size:14px;color:var(--text-secondary);font-weight:500;flex-shrink:0}
.memory-val{font-size:14.5px;color:var(--text-primary);font-weight:600;text-align:left;word-wrap:break-word;overflow-wrap:anywhere;max-width:60%}
.memory-empty{padding:24px 18px;text-align:center;color:var(--text-secondary);font-size:14px;line-height:1.8}
.memory-note{padding:14px 18px;background:var(--bg-hover);font-size:13px;color:var(--text-secondary);line-height:1.8;border-radius:0 0 16px 16px;margin-top:-14px;margin-bottom:14px}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:var(--font-size-base);min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:var(--font-size-base);font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--msg-user-bg,var(--bg-user-msg));color:var(--msg-user-text,#111);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.5;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;font-size:16px;color:var(--text-secondary)}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}
.input-area{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:28px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative;transition:border-color .2s,box-shadow .2s,transform .2s}
.input-area:focus-within{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.08)}
.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:var(--font-size-base);font-weight:500;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow-y:hidden;min-height:22px;max-height:150px;font-family:inherit;line-height:1.5;width:100%}
.input-area textarea::placeholder{color:var(--placeholder-color)}
#imagePreviewContainer{display:none;width:100%;padding:8px 4px 4px;}
#imagePreviewContainer.show{display:block;}
.image-preview-wrapper{position:relative;display:inline-block;border-radius:14px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.15);animation:previewIn .25s cubic-bezier(.34,1.56,.64,1);}
@keyframes previewIn{from{opacity:0;transform:scale(.75);}to{opacity:1;transform:scale(1);}}
.image-preview-wrapper img{display:block;max-height:76px;max-width:120px;object-fit:cover;border-radius:14px;border:1px solid var(--border-color);}
.image-preview-wrapper .remove-img-btn{position:absolute;top:5px;left:5px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,0.65);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);transition:background .2s,transform .15s;box-shadow:0 2px 8px rgba(0,0,0,0.25);}
.image-preview-wrapper .remove-img-btn:hover{background:rgba(220,38,38,0.95);transform:scale(1.1);}
.image-preview-wrapper .remove-img-btn:active{transform:scale(.9);}
.image-preview-wrapper .remove-img-btn svg{width:11px;height:11px;stroke:#fff;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round;pointer-events:none;}
.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}
.input-area .btn-icon:hover{background:var(--bg-hover)}
.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.input-area .mic-btn{color:var(--primary-color)}
.input-area .mic-btn.listening{color:#c33;background:#fde8e8}
.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 14px rgba(74,106,138,0.35);transition:background .2s,transform .15s}
.input-area .send:hover{background:var(--send-hover);transform:scale(1.05)}
.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}
.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .3s}
.plus-btn:hover{background:var(--bg-hover)}
.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.plus-btn.rotate{transform:rotate(45deg)}
.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;flex-direction:row;border:1px solid var(--border-color);z-index:50}
.plus-options.show{display:flex}
.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}
.plus-options .option-btn:hover{background:var(--border-color)}
.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color)}.share-modal .box h3{font-size:20px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:14px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px;color:#fff;font-family:inherit}.share-modal .box .share-btn.whatsapp{background:#25D366}.share-modal .box .share-btn.facebook{background:#1877F2}.share-modal .box .share-btn.twitter{background:#000}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:15px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600;font-family:inherit}.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center;transition:opacity .2s}.copy-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center}.msg .actions .del-msg-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}.msg-actions{display:flex;gap:2px;margin-top:12px;align-items:center;opacity:0.5;transition:opacity .3s ease}.msg:hover .msg-actions,.msg-actions.touched{opacity:1}.msg-actions button{background:transparent;border:none;cursor:pointer;width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:background .2s ease,color .2s ease,transform .15s cubic-bezier(.4,0,.2,1)}.msg-actions button:hover{background:var(--bg-hover);color:var(--text-primary)}.msg-actions button:active{transform:scale(0.88)}.msg-actions button svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.9;fill:none;stroke-linecap:round;stroke-linejoin:round;transition:fill .2s ease,stroke .2s ease,transform .2s cubic-bezier(.34,1.56,.64,1)}.msg-actions button.liked{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.liked svg{fill:#10b981;stroke:#10b981;transform:scale(1.08)}.msg-actions button.disliked{color:#ef4444;background:rgba(239,68,68,0.1)}.msg-actions button.disliked svg{fill:#ef4444;stroke:#ef4444;transform:scale(1.08)}.msg-actions button.copied{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.copied svg{stroke:#10b981}.msg-actions button.speaking{color:var(--primary-color);background:var(--bg-hover)}.msg-actions button.speaking svg{fill:currentColor}.msg-actions button.speaking svg polygon{animation:speakerPulse 0.9s ease-in-out infinite}@keyframes speakerPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px}.input-area .btn-icon{width:32px;height:32px}.plus-btn{width:32px;height:32px}}#oauth-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:999999;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;text-align:center;padding:20px}#oauth-overlay.show{display:flex}#oauth-overlay .oauth-spinner{width:52px;height:52px;border:4px solid var(--border-color);border-top-color:var(--primary-color);border-radius:50%;animation:oauthSpin 1s linear infinite}@keyframes oauthSpin{to{transform:rotate(360deg)}}#oauth-overlay .oauth-title{font-size:19px;color:var(--text-primary);font-weight:700}#oauth-overlay .oauth-msg{font-size:14px;color:var(--text-secondary);line-height:1.7}#oauth-overlay .oauth-title.ok{color:#00b894}#oauth-overlay .oauth-title.err{color:#d63031}
.assistant-bar{padding:6px 14px 0;flex-shrink:0;display:none;justify-content:flex-start}
.assistant-bar.show{display:flex}
.assistant-pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px 6px 14px;background:var(--bg-input);border:1px solid var(--border-color);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--text-primary);cursor:pointer;font-family:inherit;transition:all .15s;-webkit-tap-highlight-color:transparent;max-width:200px}
.assistant-pill:hover{background:var(--bg-hover)}
.assistant-pill:active{transform:scale(0.97)}
.assistant-pill .a-dot{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;flex-shrink:0}
.assistant-pill .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.assistant-pill svg{width:11px;height:11px;stroke:var(--text-secondary);stroke-width:2.5;fill:none;flex-shrink:0}
.assistant-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:200;min-width:220px;max-width:260px;display:none;max-height:60vh;overflow-y:auto}
.assistant-menu.show{display:block;animation:modalIn .18s ease}
.assistant-menu-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:11px;cursor:pointer;font-size:14px;font-weight:600;color:var(--text-primary);border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .15s}
.assistant-menu-item:hover{background:var(--bg-hover)}
.assistant-menu-item .a-dot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;flex-shrink:0}
.assistant-menu-item .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.assistant-menu-item .a-check{width:15px;height:15px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;flex-shrink:0}
.assistant-menu-item.selected .a-check{opacity:1}
.assistant-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}
.assistant-menu-add{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:11px;cursor:pointer;font-size:13px;font-weight:600;color:var(--primary-color);border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .15s}
.assistant-menu-add:hover{background:var(--bg-hover)}
.assistant-menu-add svg{width:16px;height:16px;stroke:currentColor;stroke-width:2.5;fill:none;flex-shrink:0}
.assistants-list{display:flex;flex-direction:column;gap:10px}
.assistant-card{display:flex;align-items:center;gap:14px;padding:14px 16px;background:var(--bg-app);border-radius:16px;box-shadow:0 1px 3px var(--shadow-color);border:1px solid var(--border-color)}
.assistant-card .a-dot{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px;font-weight:700;flex-shrink:0}
.assistant-card-info{flex:1;min-width:0}
.assistant-card-name{font-size:15px;font-weight:700;color:var(--text-primary);margin-bottom:3px}
.assistant-card-sub{font-size:12.5px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.5}
.assistant-card-del{background:transparent;border:none;cursor:pointer;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);flex-shrink:0;padding:0;transition:color .2s}
.assistant-card-del:hover{color:#ef4444}
.assistant-card-del svg{width:16px;height:16px;stroke:currentColor;stroke-width:2;fill:none}
.assistant-add-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;background:var(--bg-app);border:1.5px dashed var(--border-color);border-radius:16px;cursor:pointer;font-size:14px;font-weight:600;color:var(--primary-color);font-family:inherit;transition:all .2s;margin-top:12px;width:100%}
.assistant-add-btn:hover{border-color:var(--primary-color);background:var(--bg-hover)}
.assistant-add-btn svg{width:18px;height:18px;stroke:currentColor;stroke-width:2.5;fill:none}
.assistant-form-field{margin-bottom:18px}
.assistant-form-field label{display:block;font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:8px;text-align:right}
.assistant-form-field input,.assistant-form-field textarea{width:100%;padding:13px 16px;border:1.5px solid var(--border-input);border-radius:14px;font-size:14.5px;background:var(--bg-input);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;resize:none;font-weight:500}
.assistant-form-field input:focus,.assistant-form-field textarea:focus{border-color:var(--primary-color);background:var(--bg-app);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.assistant-form-field textarea{min-height:110px;line-height:1.7}
.assistant-form-hint{font-size:11.5px;color:var(--text-secondary);margin-top:6px;text-align:right;line-height:1.6}
.assistant-color-picker{display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-start}
.assistant-color-dot{width:38px;height:38px;border-radius:50%;border:2px solid transparent;cursor:pointer;transition:all .15s;padding:0;position:relative}
.assistant-color-dot.selected{border-color:var(--text-primary);transform:scale(1.08)}
.assistant-form-actions{display:flex;gap:10px;margin-top:22px}
.assistant-form-actions button{flex:1;padding:13px;border-radius:14px;border:none;font-size:14.5px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .15s}
.assistant-form-actions .btn-cancel{background:var(--bg-hover);color:var(--text-primary)}
.assistant-form-actions .btn-save{background:var(--primary-color);color:#fff}
.assistant-form-actions .btn-save:disabled{opacity:0.6;cursor:not-allowed}
.sp-input{width:100%;padding:14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background:var(--bg-app);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;font-weight:500}
.sp-input:focus{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.sp-input::placeholder{color:var(--placeholder-color)}
.sp-input:disabled{opacity:0.55;cursor:not-allowed}
.sp-select{width:100%;padding:14px 44px 14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background-color:var(--bg-app);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;font-weight:500;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%235a6b7c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:left 14px center;background-size:18px;cursor:pointer}
.sp-select:focus{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.sp-field{margin-bottom:16px}
.sp-field:last-child{margin-bottom:0}
.sp-label{display:block;font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-align:right}
.sp-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;border:none;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .15s;width:100%;-webkit-tap-highlight-color:transparent;outline:none}
.sp-btn:active{transform:scale(0.98)}
.sp-btn-primary{background:var(--primary-color);color:#fff}
.sp-btn-primary:hover{filter:brightness(1.08)}
.sp-btn-danger{background:rgba(211,47,47,0.08);color:#d32f2f}
.sp-btn-danger:hover{background:rgba(211,47,47,0.15)}
html.dark-mode .sp-btn-danger{background:rgba(248,81,73,0.12);color:#f85149}
html.dark-mode .sp-btn-danger:hover{background:rgba(248,81,73,0.2)}
.sp-btn-row{display:flex;gap:10px}
.sp-btn-row .sp-btn{flex:1}
.sp-link-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;background:var(--bg-app);color:var(--text-primary);text-decoration:none;font-size:15px;font-weight:600;border:1.5px solid var(--border-color);transition:all .15s;text-align:center;width:100%;box-sizing:border-box}
.sp-link-btn:hover{background:var(--bg-hover);border-color:var(--primary-color);color:var(--primary-color)}
.sp-note{font-size:14.5px;color:var(--text-secondary);line-height:1.9}
.sp-note b{color:var(--text-primary);font-weight:700;display:block;margin-bottom:6px;font-size:15px}
.sp-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:14px;border:1px solid var(--border-color);overflow:hidden}
.sp-list-item{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--border-color);font-size:15px}
.sp-list-item:last-child{border-bottom:none}
.sp-list-key{color:var(--text-secondary);font-weight:500}
.sp-list-val{color:var(--text-primary);font-weight:700;text-align:left;max-width:60%;word-wrap:break-word}
.sp-hero{display:flex;align-items:center;gap:14px;padding:16px;background:var(--bg-app);border-radius:16px;border:1px solid var(--border-color);margin-bottom:16px}
.sp-hero-icon{width:46px;height:46px;border-radius:13px;background:var(--bg-hover);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--primary-color)}
.sp-hero-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}
.sp-hero-title{font-size:15.5px;font-weight:700;color:var(--text-primary);margin:0 0 3px}
.sp-hero-sub{font-size:12.5px;color:var(--text-secondary);margin:0;line-height:1.5}
.user-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:300;min-width:220px;display:none}
.user-menu.show{display:block;animation:modalIn .18s ease}
.user-menu-item{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:11px;cursor:pointer;font-size:14px;font-weight:600;color:var(--text-primary);border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .15s}
.user-menu-item:hover{background:var(--bg-hover)}
.user-menu-item svg{width:18px;height:18px;stroke:currentColor;stroke-width:2;fill:none;flex-shrink:0}
.user-menu-item.danger{color:#d32f2f}
.user-menu-item.danger:hover{background:rgba(211,47,47,0.08)}
.user-menu-item.danger svg{stroke:#d32f2f}
.user-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}
/* ✅ جديد: تنسيق بطاقات الأخبار (nibras-response) */
.nibras-response{font-size:var(--font-size-base);line-height:1.9;color:var(--text-primary);max-width:100%}
.nibras-response h2{font-size:1.25em;font-weight:800;color:var(--primary-color);margin:4px 0 16px;padding-bottom:10px;border-bottom:2px solid var(--border-color);line-height:1.5}
.nibras-response h3{font-size:1.05em;font-weight:750;margin:16px 0 8px;background:var(--bg-hover);padding:10px 14px;border-right:4px solid var(--primary-color);border-radius:8px;color:var(--text-primary);line-height:1.5}
.nibras-response p{margin:0 0 10px;color:var(--text-primary)}
.nibras-response em{color:var(--text-secondary);font-size:0.9em;display:inline-block;margin-bottom:6px;font-style:normal}
.nibras-response hr{border:0;height:1px;background:var(--border-color);margin:18px 0}
.nibras-response strong{font-weight:800;color:var(--text-primary)}
.nibras-response a{color:var(--primary-color);text-decoration:none;font-weight:600;display:inline-block;padding:4px 0}
.nibras-response a:hover{text-decoration:underline}
.nibras-response ul,.nibras-response ol{padding-right:22px;padding-left:0;margin:8px 0 14px}
.nibras-response li{margin-bottom:8px}
.nibras-response blockquote{border-right:4px solid var(--primary-color);margin:10px 0;padding:8px 14px;background:var(--bg-hover);border-radius:8px}
.nibras-response img{display:block;max-width:100%;height:auto;border-radius:12px;margin:10px 0;border:1px solid var(--border-color)}
</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="icon-btn voice-off" id="voiceToggle" title="تشغيل/إيقاف الصوت"><svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg></button><button class="icon-btn" id="menuToggle" title="القائمة"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}{% if user_name %}<button type="button" class="user-badge" id="userBadge" onclick="toggleUserMenu(event)" title="{{ session.get('user_email') }}"><svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{{ user_name }}</button>{% endif %}<a href="/logout" class="btn btn-outline">خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div>

<div class="user-menu" id="userMenu">
    <button class="user-menu-item" onclick="openSubPage('general');toggleUserMenu(null)">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="8" r="3"/><path d="M6.5 20a5.5 5.5 0 0 1 11 0"/></svg>
        <span>حسابي</span>
    </button>
    <button class="user-menu-item" onclick="openRedeemCode();toggleUserMenu(null)">
        <svg viewBox="0 0 24 24"><path d="m15 7 4 4-4 4"/><path d="M19 11H5"/><rect x="2" y="4" width="20" height="16" rx="2"/></svg>
        <span>تفعيل كود وصول</span>
    </button>
    <div class="user-menu-sep"></div>
    <button class="user-menu-item danger" onclick="deleteMyAccount();toggleUserMenu(null)">
        <svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg>
        <span>حذف حسابي</span>
    </button>
    <button class="user-menu-item danger" onclick="window.location.href='/logout'">
        <svg viewBox="0 0 24 24"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        <span>تسجيل الخروج</span>
    </button>
</div>

<div class="dropdown" id="dropdown">
    <button class="item" data-action="new"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>محادثة جديدة</button>
    <button class="item" onclick="window.location.href='/library'"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>مكتبتي</button>
    <button class="item" data-action="share"><svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>مشاركة المحادثة</button>
    <button class="item" onclick="openSettings()"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>الإعدادات</button>
    <div class="section-title">مثبت</div>
    <div id="pinnedList"><div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;font-weight:500;">لا توجد محادثات مثبتة</div></div>
    <div class="section-title">المحادثات الأخيرة</div>
    <div id="historyList"></div>
</div>

<div id="settingsModal" class="settings-overlay">
    <div class="settings-page">
        <div class="settings-header"><button class="icon-btn" onclick="closeSettings()"><svg viewBox="0 0 24 24"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg></button><h2>الإعدادات</h2><div style="width:32px;"></div></div>
        <div class="settings-body">
            <div class="settings-card">
                <div class="settings-item" onclick="openSubPage('theme')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg><span>المظهر</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('color')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/></svg><span>لون التمييز</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentColorLabel" style="font-size:14px;color:var(--text-secondary);">أزرق داكن</span><span id="currentColorDot" style="width:14px;height:14px;border-radius:50%;background:#4a6a8a;display:inline-block;"></span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
                <div class="settings-item" onclick="openSubPage('fontSize')"><div class="item-right"><svg viewBox="0 0 24 24"><polyline points="4 7 4 4 20 4 20 7"/><line x1="9" y1="20" x2="15" y2="20"/><line x1="12" y1="4" x2="12" y2="20"/></svg><span>حجم الخط</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentFontSizeLabel" style="font-size:14px;color:var(--text-secondary);">متوسط</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
                <div class="settings-item" onclick="openSubPage('personality')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg><span>شخصية المساعد</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentPersonalityLabel" style="font-size:14px;color:var(--text-secondary);">ودود</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
                <div class="settings-item" onclick="openSubPage('language')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg><span>اللغة / Language</span></div><div style="display:flex;align-items:center;gap:8px;"><span id="currentLangLabel" style="font-size:14px;color:var(--text-secondary);">العربية</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div>
            </div>
            <div class="settings-card">
                <div class="settings-item" onclick="openSubPage('general')"><div class="item-right"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg><span>عام</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('memory')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/><path d="M12 8v8"/><path d="M8 12h8"/></svg><span>الذاكرة</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
                <div class="settings-item" onclick="openSubPage('assistants')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg><span>مساعدي الخاص</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>
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

<div id="subPage" class="sub-page" onclick="if(event.target===this)closeSubPage()">
    <div class="modal-box">
        <div class="modal-title" id="subPageTitle">إعدادات</div>
        <div class="sub-page-body" id="subPageBody"></div>
        <button class="modal-confirm" onclick="confirmSubPage()">تأكيد</button>
    </div>
</div>

<div id="chat"></div>
<div class="assistant-bar" id="assistantBar">
  <button class="assistant-pill" id="assistantPill" type="button" onclick="toggleAssistantMenu(event)">
    <span class="a-dot" id="assistantPillDot" style="background:#4a6a8a">ن</span>
    <span class="a-name" id="assistantPillName">نبراس</span>
    <svg viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg>
  </button>
</div>
<div class="assistant-menu" id="assistantMenu"></div>
<div class="input-area" id="inputArea">
    <div id="imagePreviewContainer"><div class="image-preview-wrapper"><img id="imagePreview" src="" alt=""/><button class="remove-img-btn" id="removeImageBtn" title="إزالة" aria-label="إزالة الصورة"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div></div>
    <button class="btn-icon mic-btn" id="micBtn" title="صوت"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button>
    <button class="plus-btn" id="plusBtn" title="إضافة"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button>
    <div class="plus-options" id="plusOptions"><button class="option-btn" id="cameraBtn" title="كاميرا"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></button><button class="option-btn" id="galleryBtn" title="صور"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></button></div>
    <textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea>
    <button class="send" id="sendBtn" title="إرسال"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button>
</div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/></div>

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

<script>
(function(){
    try{
        var hash = window.location.hash || '';
        var search = window.location.search || '';
        if(hash.indexOf('type=recovery') !== -1 && hash.indexOf('access_token=') !== -1){
            window.location.replace('/reset-password' + hash);
            return;
        }
        if(search.indexOf('type=recovery') !== -1 && search.indexOf('code=') !== -1){
            window.location.replace('/reset-password' + search);
            return;
        }
        var params = new URLSearchParams(hash.replace(/^#/, ''));
        var at = params.get('access_token');
        var codeP = new URLSearchParams(search).get('code');
        if(at || codeP){
            var rt = params.get('refresh_token') || '';
            try{ history.replaceState(null, '', window.location.pathname); }catch(e){}
            var overlay = document.createElement('div');
            overlay.id = 'oauth-overlay';
            overlay.classList.add('show');
            overlay.innerHTML = '<div class="oauth-spinner" id="oauth-spin"></div><div class="oauth-title" id="oauth-title">جاري تسجيل الدخول</div><div class="oauth-msg" id="oauth-msg">لحظة من فضلك...</div>';
            document.body.appendChild(overlay);
            function done(msg, isOk){
                var spin = document.getElementById('oauth-spin');
                var title = document.getElementById('oauth-title');
                var msgEl = document.getElementById('oauth-msg');
                if(spin) spin.style.display = 'none';
                if(title){ title.textContent = isOk ? 'تم تسجيل الدخول' : 'تعذر تسجيل الدخول'; title.classList.add(isOk ? 'ok' : 'err'); }
                if(msgEl) msgEl.textContent = msg;
                setTimeout(function(){ window.location.replace(isOk ? '/' : '/login'); }, isOk ? 700 : 2500);
            }
            fetch('/auth/session', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify({access_token: at || '', refresh_token: rt, code: codeP || ''})
            }).then(function(r){return r.json();}).then(function(d){
                if(d && d.status === 'ok'){ done('جاري تحويلك...', true); }
                else { done((d && d.message) || 'فشل إنشاء الجلسة', false); }
            }).catch(function(){ done('تعذر الاتصال بالسيرفر', false); });
            return;
        }
    }catch(e){}
})();
(function(){const IS_REGISTERED={{ 'true' if is_registered else 'false' }};const SERVER_LANG='{{ user_lang }}';let userLang=SERVER_LANG||localStorage.getItem('nibras-lang')||'ar';try{localStorage.setItem('nibras-lang',userLang);}catch(e){}let isMale=(localStorage.getItem('nibras-voice-gender')||'male')==='male';let userPersonality=localStorage.getItem('nibras-personality')||'friendly';let userFontSize=localStorage.getItem('nibras-font-size')||'medium';let voiceSpeed=parseFloat(localStorage.getItem('nibras-voice-speed'))||1;let ch=[],pid=null,iw=!1,cid=null,voiceOn=false,stickBottom=true;const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),pl=document.getElementById('pinnedList'),sm=document.getElementById('shareModal'),vt=document.getElementById('voiceToggle');
const SVG_SPK_ON='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
const SVG_SPK_OFF='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';

let audioCtx = null;
let allSources = [];
let ca = null;
let voiceSessionId = 0;
function getAudioContext(){ if(!audioCtx){ audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } if(audioCtx.state === 'suspended'){ audioCtx.resume(); } return audioCtx; }
function stopAllAudio(){ allSources.forEach(function(src){ try{ src.stop(0); }catch(e){} }); allSources = []; ca = null; voiceSessionId++; }
function playAudioWithSpeed(base64Audio, onEnd){ try{ stopAllAudio(); const mySession = voiceSessionId; const ctx = getAudioContext(); const binary = atob(base64Audio); const bytes = new Uint8Array(binary.length); for(let i = 0; i < binary.length; i++){ bytes[i] = binary.charCodeAt(i); } ctx.decodeAudioData(bytes.buffer, function(buffer){ if(mySession !== voiceSessionId){ if(typeof onEnd === 'function') onEnd(); return; } const source = ctx.createBufferSource(); source.buffer = buffer; source.playbackRate.value = voiceSpeed; const gainNode = ctx.createGain(); const savedLvl = localStorage.getItem('nibras-voice-level'); gainNode.gain.value = savedLvl ? savedLvl/100 : 1; source.connect(gainNode); gainNode.connect(ctx.destination); source.onended = function(){ const idx = allSources.indexOf(source); if(idx >= 0) allSources.splice(idx, 1); if(typeof onEnd === 'function') onEnd(); }; source.start(0); allSources.push(source); ca = { pause: function(){ try{source.stop(0);}catch(e){} }, currentTime: 0 }; }, function(err){ console.error('Audio decode error:', err); if(typeof onEnd === 'function') onEnd(); }); }catch(e){ console.error('Web Audio API error:', e); if(typeof onEnd === 'function') onEnd(); } }

function tr(key){const d={thinking:{ar:'جاري التفكير',en:'Thinking'},listening:{ar:'جاري الاستماع...',en:'Listening...'},inputPlaceholder:{ar:'اكتب رسالتك...',en:'Type your message...'},micUnsupported:{ar:'المتصفح لا يدعم التعرف على الصوت.',en:'Browser does not support voice recognition.'}};return (d[key]||{})[userLang]||(d[key]||{}).ar||key;}
function applyLang(){ui.placeholder=tr('inputPlaceholder');document.documentElement.lang=userLang==='en'?'en':'ar';const lbl=document.getElementById('currentLangLabel');if(lbl)lbl.textContent=userLang==='en'?'English':'العربية';}
function applyFontSize(size){document.documentElement.setAttribute('data-font',size);const map={small:'صغير',medium:'متوسط',large:'كبير',xlarge:'ضخم'};const lbl=document.getElementById('currentFontSizeLabel');if(lbl)lbl.textContent=map[size]||'متوسط';}
applyFontSize(userFontSize);
vt.addEventListener('click',function(){voiceOn=!voiceOn;if(voiceOn){vt.classList.remove('voice-off');vt.classList.add('voice-on');vt.innerHTML=SVG_SPK_ON;showToast(userLang==='en'?'Sound ON':'الصوت مفعّل');}else{vt.classList.remove('voice-on');vt.classList.add('voice-off');vt.innerHTML=SVG_SPK_OFF;stopAllAudio();showToast(userLang==='en'?'Sound OFF':'الصوت مغلق');}});
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
function getPinnedLocal(){try{return JSON.parse(localStorage.getItem('nibras_pinned')||'[]');}catch(e){return [];}}
function savePinnedLocal(arr){try{localStorage.setItem('nibras_pinned',JSON.stringify(arr));}catch(e){}}
async function togglePin(cid,wasPinned,btnEl){if(IS_REGISTERED){const url=wasPinned?'/unpin_conversation':'/pin_conversation';try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conv_id:cid})});if(r.ok){btnEl.classList.toggle('pinned',!wasPinned);showToast(wasPinned?(userLang==='en'?'Unpinned':'تم إلغاء التثبيت'):(userLang==='en'?'Pinned':'تم التثبيت'));loadPinned();}}catch(e){showToast(userLang==='en'?'Connection failed':'فشل الاتصال');}}else{let arr=getPinnedLocal();if(wasPinned){arr=arr.filter(x=>x!==cid);showToast(userLang==='en'?'Unpinned':'تم إلغاء التثبيت');}else{if(!arr.includes(cid))arr.push(cid);showToast(userLang==='en'?'Pinned locally':'تم التثبيت محلياً');}savePinnedLocal(arr);btnEl.classList.toggle('pinned',!wasPinned);loadPinned();}}
mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();loadPinned();}});

function toggleUserMenu(e){
    if(e) e.stopPropagation();
    const menu = document.getElementById('userMenu');
    const badge = document.getElementById('userBadge');
    if(!menu || !badge) return;
    if(menu.classList.contains('show')){
        menu.classList.remove('show');
        return;
    }
    const rect = badge.getBoundingClientRect();
    const menuW = 220;
    let left = rect.left;
    if(left + menuW > window.innerWidth - 8){
        left = window.innerWidth - menuW - 8;
    }
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = (rect.bottom + 8) + 'px';
    menu.classList.add('show');
}
document.addEventListener('click', function(e){
    const menu = document.getElementById('userMenu');
    const badge = document.getElementById('userBadge');
    if(!menu || !badge) return;
    if(!menu.contains(e.target) && !badge.contains(e.target)){
        menu.classList.remove('show');
    }
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
        const r = await fetch('/redeem_code', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({code})
        });
        const d = await r.json();
        if(d.status === 'ok'){
            showToast('✅ تم التفعيل! ' + d.image + ' صور، ' + d.search + ' بحث، ' + d.chat + ' محادثة');
            setTimeout(function(){ closeSubPage(); location.reload(); }, 1500);
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
    fontSize:'<div class="fontsize-list"><div class="fontsize-row" data-fs="small" onclick="selectFontSize(\'small\',\'صغير\')"><div class="fontsize-row-left"><div class="fontsize-label">صغير</div><div class="fontsize-sample" style="font-size:13px;">نموذج من الخط الصغير</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="medium" onclick="selectFontSize(\'medium\',\'متوسط\')"><div class="fontsize-row-left"><div class="fontsize-label">متوسط</div><div class="fontsize-sample" style="font-size:15px;">نموذج من الخط المتوسط</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="large" onclick="selectFontSize(\'large\',\'كبير\')"><div class="fontsize-row-left"><div class="fontsize-label">كبير</div><div class="fontsize-sample" style="font-size:17px;">نموذج من الخط الكبير</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="fontsize-row" data-fs="xlarge" onclick="selectFontSize(\'xlarge\',\'ضخم\')"><div class="fontsize-row-left"><div class="fontsize-label">ضخم</div><div class="fontsize-sample" style="font-size:19px;">نموذج من الخط الضخم</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    personality:'<div class="personality-list"><div class="personality-row" data-p="friendly" onclick="selectPersonality(\'friendly\',\'ودود\')"><div class="personality-text"><div class="personality-name">ودود</div><div class="personality-sub">دافئ ومريح</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="concise" onclick="selectPersonality(\'concise\',\'مختصر\')"><div class="personality-text"><div class="personality-name">مختصر</div><div class="personality-sub">ردود قصيرة</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="detailed" onclick="selectPersonality(\'detailed\',\'مفصّل\')"><div class="personality-text"><div class="personality-name">مفصّل</div><div class="personality-sub">شرح عميق</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="formal" onclick="selectPersonality(\'formal\',\'رسمي\')"><div class="personality-text"><div class="personality-name">رسمي</div><div class="personality-sub">احترافي ومهني</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="teacher" onclick="selectPersonality(\'teacher\',\'معلّم\')"><div class="personality-text"><div class="personality-name">معلّم</div><div class="personality-sub">يشرح خطوة بخطوة</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-p="playful" onclick="selectPersonality(\'playful\',\'فرفوش\')"><div class="personality-text"><div class="personality-name">فرفوش</div><div class="personality-sub">مرح ومزح خفيف</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    language:'<div class="lang-list"><div class="lang-card" data-lang="ar" onclick="selectLanguage(\'ar\')"><div class="lang-flag" style="background:linear-gradient(135deg,#2d6a4f 0%,#40916c 100%);">ع</div><div class="lang-info"><div class="lang-name">العربية</div><div class="lang-sub">Arabic</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="lang-card" data-lang="en" onclick="selectLanguage(\'en\')"><div class="lang-flag" style="background:linear-gradient(135deg,#1e3a8a 0%,#3b82f6 100%);">EN</div><div class="lang-info"><div class="lang-name">English</div><div class="lang-sub">الإنجليزية</div></div><svg class="lang-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div>',
    general:'<div class="sp-field"><label class="sp-label">الاسم الكامل</label><input type="text" id="sp-name" class="sp-input" value="{{ user_name or '' }}" placeholder="اكتب اسمك"></div>',
    memory:'<div id="memoryContent"><div class="sp-note" style="text-align:center;">جاري تحميل الذاكرة...</div></div>',
    assistants:'<div class="sp-note" style="text-align:center;">جاري التحميل...</div>',
    voice:'<div style="display:flex;flex-direction:column;gap:16px;"><div><div class="sp-label" style="padding:0 4px 8px;letter-spacing:.5px;">جنس الصوت</div><div class="personality-list"><div class="personality-row" data-vg="male" onclick="selectVoiceGender(\'male\')"><div class="personality-text"><div class="personality-name">ذكر</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vg="female" onclick="selectVoiceGender(\'female\')"><div class="personality-text"><div class="personality-name">أنثى</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div><div><div class="sp-label" style="padding:0 4px 8px;letter-spacing:.5px;">سرعة الصوت</div><div class="personality-list"><div class="personality-row" data-vs="0.75" onclick="selectVoiceSpeed(0.75)"><div class="personality-text"><div class="personality-name">بطيء</div><div class="personality-sub">0.75×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1" onclick="selectVoiceSpeed(1)"><div class="personality-text"><div class="personality-name">عادي</div><div class="personality-sub">1×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1.25" onclick="selectVoiceSpeed(1.25)"><div class="personality-text"><div class="personality-name">سريع</div><div class="personality-sub">1.25×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vs="1.5" onclick="selectVoiceSpeed(1.5)"><div class="personality-text"><div class="personality-name">سريع جداً</div><div class="personality-sub">1.5×</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div><div><div class="sp-label" style="padding:0 4px 8px;letter-spacing:.5px;">مستوى الصوت</div><div class="personality-list"><div class="personality-row" data-vl="25" onclick="selectVoiceLevel(25)"><div class="personality-text"><div class="personality-name">هادئ</div><div class="personality-sub">25%</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="50" onclick="selectVoiceLevel(50)"><div class="personality-text"><div class="personality-name">متوسط</div><div class="personality-sub">50%</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="75" onclick="selectVoiceLevel(75)"><div class="personality-text"><div class="personality-name">عالي</div><div class="personality-sub">75%</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><div class="personality-row" data-vl="100" onclick="selectVoiceLevel(100)"><div class="personality-text"><div class="personality-name">كامل</div><div class="personality-sub">100%</div></div><svg class="check-icon" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div></div></div></div>',
    safety:'<div class="sp-note"><b>إرشادات السلامة</b>• لا تشارك معلوماتك الشخصية الحساسة.<br>• نبراس مساعد ذكي، وليس بديلاً عن الاستشارة المتخصصة.<br>• أبلغ عن أي محتوى غير لائق.</div>',
    security:'<div class="sp-field"><label class="sp-label">البريد الإلكتروني</label><input type="email" class="sp-input" value="{{ session.get('user_email','') }}" disabled></div><div class="sp-field"><label class="sp-label">كلمة المرور الحالية</label><input type="password" id="sp-old-pass" class="sp-input" placeholder="••••••••"></div><div class="sp-field"><label class="sp-label">كلمة المرور الجديدة</label><input type="password" id="sp-new-pass" class="sp-input" placeholder="••••••••"></div>',
    remote:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg></div><div><div class="sp-hero-title">إدارة الجلسات</div><div class="sp-hero-sub">تحكم بالأجهزة المتصلة بحسابك</div></div></div><div class="sp-list"><div class="sp-list-item"><span class="sp-list-key">هذا الجهاز (المتصفح الحالي)</span><span class="sp-list-val" style="color:var(--primary-color);font-size:13px;">نشط الآن</span></div></div><div style="margin-top:16px;"><button class="sp-btn sp-btn-danger" onclick="logoutAll()">تسجيل الخروج من كل الأجهزة</button></div>',
    storage:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg></div><div><div class="sp-hero-title">التخزين</div><div class="sp-hero-sub">إحصائيات البيانات المحفوظة</div></div></div><div class="sp-list"><div class="sp-list-item"><span class="sp-list-key">المحادثات</span><span class="sp-list-val" id="sp-conv-count">0</span></div><div class="sp-list-item"><span class="sp-list-key">الصور</span><span class="sp-list-val" id="sp-img-count">0</span></div></div><div style="margin-top:16px;"><button class="sp-btn sp-btn-danger" onclick="clearCache()">مسح الكاش المحلي</button></div>',
    privacy:'<div class="sp-note"><b>سياسة الخصوصية</b>• نحتفظ بمحادثاتك لتقديم خدمة أفضل.<br>• لا نشارك بياناتك مع أطراف ثالثة.<br>• يمكنك حذف بياناتك في أي وقت من التحكم في البيانات.</div><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="sp-link-btn" style="margin-top:16px;">قراءة السياسة كاملة</a>',
    data:'<div class="sp-note">يمكنك تصدير جميع بياناتك أو حذفها نهائياً.</div><div class="sp-btn-row" style="margin-top:16px;"><button class="sp-btn sp-btn-primary" onclick="exportData()">تصدير البيانات</button><button class="sp-btn sp-btn-danger" onclick="deleteMyAccount()">حذف</button></div>',
    ads:'<div class="sp-field"><label class="sp-label">تخصيص الإعلانات</label><select id="sp-ads" class="sp-select"><option value="personalized">مخصصة</option><option value="non-personalized">غير مخصصة</option></select></div>',
    report:'<div class="sp-field"><label class="sp-label">نوع المشكلة</label><select id="sp-report-type" class="sp-select"><option>خطأ تقني</option><option>محتوى غير لائق</option><option>اقتراح</option><option>أخرى</option></select></div><div class="sp-field"><label class="sp-label">الوصف</label><input type="text" id="sp-report-desc" class="sp-input" placeholder="اشرح المشكلة..."></div>',
    about:'<div class="sp-hero"><div class="sp-hero-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg></div><div><div class="sp-hero-title">نبراس GP</div><div class="sp-hero-sub">الإصدار 1.0 · مساعد ذكي شخصي</div></div></div><div class="sp-note">مساعد شخصي باللهجة العربية العامية.<br><br>© 2026 جميع الحقوق محفوظة.</div><a href="https://abod724.github.io/nibras-privacy/terms.html" target="_blank" class="sp-link-btn" style="margin-top:16px;">شروط الاستخدام</a><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="sp-link-btn" style="margin-top:10px;">سياسة الخصوصية</a>'
};
let currentSubKey=null;
function openSubPage(key){
    currentSubKey=key;
    const titleMap={general:'عام',voice:'الصوت',safety:'السلامة',security:'الأمان وتسجيل الدخول',remote:'التحكم عن بُعد',storage:'التخزين',privacy:'مركز الخصوصية',data:'التحكم في البيانات',ads:'التحكم في الإعلانات',report:'الإبلاغ عن خطأ',about:'حول',theme:'المظهر',color:'لون التمييز',language:'اللغة / Language',personality:'شخصية المساعد',fontSize:'حجم الخط',memory:'الذاكرة',assistants:'مساعدي الخاص'};
    document.getElementById('subPageTitle').textContent=titleMap[key]||'إعدادات';
    document.getElementById('subPageBody').innerHTML=subPagesContent[key]||'<div class="sp-note">قريباً</div>';
    document.getElementById('subPage').classList.add('show');
    setTimeout(function(){
        if(key==='theme'){const t=localStorage.getItem('nibras-theme-mode')||'system';markSelectedTheme(t);}
        if(key==='color'){const c=localStorage.getItem('nibras-accent')||'#4a6a8a';markSelectedColor(c);}
        if(key==='fontSize'){document.querySelectorAll('.fontsize-row').forEach(function(el){el.classList.toggle('selected',el.dataset.fs===userFontSize);});}
        if(key==='personality'){document.querySelectorAll('.personality-row').forEach(function(el){el.classList.toggle('selected',el.dataset.p===userPersonality);});}
        if(key==='language'){document.querySelectorAll('.lang-card').forEach(function(el){el.classList.toggle('selected',el.dataset.lang===userLang);});}
        if(key==='voice'){markVoiceSelections();}
        if(key==='memory'){loadMemory();}
        if(key==='assistants'){loadAssistants().then(loadAssistantsPage);}
        if(key==='storage'){loadStorageInfo();}
    },60);
}
function closeSubPage(){
    document.getElementById('subPage').classList.remove('show');
    currentSubKey=null;
    const btn = document.querySelector('#subPage .modal-confirm');
    if(btn){ btn.onclick = confirmSubPage; btn.disabled = false; btn.textContent = 'تأكيد'; }
}
function confirmSubPage(){
    if(currentSubKey==='voice'){saveVoice();}
    else if(currentSubKey==='general'){saveGeneral();}
    else if(currentSubKey==='security'){changePassword();}
    else if(currentSubKey==='ads'){saveAds();}
    else if(currentSubKey==='report'){sendReport();}
    else{closeSubPage();}
}
function pickVoiceGender(g){isMale=(g==='male');}
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
async function loadMemory(){const c=document.getElementById('memoryContent');if(!c)return;if(!IS_REGISTERED){c.innerHTML='<div class="memory-card"><div class="memory-header"><svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/></svg><span>الذاكرة</span></div><div class="memory-empty">أنت تستخدم التطبيق كضيف.<br>سجّل دخولك لحفظ ذاكرتك بشكل دائم.</div></div>';return;}try{const r=await fetch('/get_memory');const d=await r.json();const items=[];if(d.name)items.push({k:'الاسم',v:d.name});if(d.lang)items.push({k:'اللغة',v:d.lang==='en'?'English':'العربية'});if(d.personality){const pMap={friendly:'ودود',concise:'مختصر',detailed:'مفصّل',formal:'رسمي',teacher:'معلّم',playful:'فرفوش'};items.push({k:'شخصية المساعد',v:pMap[d.personality]||d.personality});}if(d.email)items.push({k:'البريد الإلكتروني',v:d.email});let html='<div class="memory-card"><div class="memory-header"><svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/></svg><span>الذاكرة</span></div>';if(items.length===0){html+='<div class="memory-empty">لا توجد معلومات محفوظة بعد.</div>';}else{items.forEach(i=>{html+='<div class="memory-item"><span class="memory-key">'+i.k+'</span><span class="memory-val">'+escapeHtml(i.v)+'</span></div>';});}html+='</div>';html+='<div class="memory-note">نبراس يستخدم هذي المعلومات لتخصيص ردوده. لا يشاركها مع أي طرف ثالث.</div>';c.innerHTML=html;}catch(e){c.innerHTML='<div class="sp-note" style="text-align:center;">تعذر تحميل الذاكرة.</div>';}}
async function loadStorageInfo(){try{const r1=await fetch('/history');const d1=await r1.json();document.getElementById('sp-conv-count').textContent=(d1.conversations||[]).length;const r2=await fetch('/library/images');const d2=await r2.json();document.getElementById('sp-img-count').textContent=(d2.images||[]).length;}catch(e){}}
function saveGeneral(){const n=(document.getElementById('sp-name').value||'').trim();if(!n||n.length<2){showToast('اكتب اسم صحيح');return;}if(!IS_REGISTERED){showToast('سجّل دخولك أولاً');return;}fetch('/update_profile',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,lang:userLang})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('تم الحفظ');closeSubPage();setTimeout(()=>location.reload(),500);}else{showToast(d.message||'فشل الحفظ');}}).catch(()=>showToast('تعذر الاتصال بالسيرفر'));}
function saveVoice(){var lvlEl=document.querySelector('[data-vl].selected');var lvl=lvlEl?lvlEl.dataset.vl:'100';var gender=isMale?'male':'female';var speedEl=document.querySelector('[data-vs].selected');var speed=speedEl?parseFloat(speedEl.dataset.vs):1;voiceSpeed=speed;localStorage.setItem('nibras-voice-level',lvl);localStorage.setItem('nibras-voice-gender',gender);localStorage.setItem('nibras-voice-speed',speed);fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:gender})}).then(function(){showToast('تم حفظ الإعدادات');closeSubPage();}).catch(function(){showToast('تم الحفظ محلياً');closeSubPage();});}
function changePassword(){const o=document.getElementById('sp-old-pass').value;const n=document.getElementById('sp-new-pass').value;if(!o){showToast('اكتب كلمة المرور الحالية');return;}if(!n||n.length<8){showToast('كلمة المرور الجديدة 8 أحرف على الأقل');return;}fetch('/change_password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({old_password:o,new_password:n})}).then(r=>r.json()).then(d=>{if(d.status==='ok'){showToast('تم تغيير كلمة المرور');document.getElementById('sp-old-pass').value='';document.getElementById('sp-new-pass').value='';closeSubPage();}else{showToast((d.message||'فشل تغيير كلمة المرور'));}}).catch(()=>showToast('تعذر الاتصال بالسيرفر'));}
function logoutAll(){if(confirm('خروج من كل الأجهزة؟')){fetch('/logout_all',{method:'POST'}).then(()=>window.location.href='/logout');}}
function clearCache(){if(!confirm('مسح الإعدادات المحلية؟'))return;localStorage.clear();sessionStorage.clear();document.documentElement.classList.remove('dark-mode');showToast('تم المسح');setTimeout(()=>location.reload(),900);}
function exportData(){window.location.href='/export_data';}
function saveAds(){showToast('تم حفظ التفضيلات');closeSubPage();}
function sendReport(){const d=document.getElementById('sp-report-desc').value;if(!d||d.trim().length<3){showToast('اكتب وصف');return;}fetch('/report_bug',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:document.getElementById('sp-report-type').value,description:d})}).then(r=>r.json()).then(res=>{if(res.status==='ok'){showToast('تم الإرسال');setTimeout(()=>closeSubPage(),800);}});}
async function loadPinned(){try{let pinned=[];if(IS_REGISTERED){const r=await fetch('/pinned_conversations');const d=await r.json();pinned=d.pinned||[];}else{const ids=getPinnedLocal();if(ids.length){const hr=await fetch('/history');const hd=await hr.json();pinned=(hd.conversations||[]).filter(c=>ids.includes(c.id));}}pl.innerHTML='';if(!pinned||pinned.length===0){pl.innerHTML='<div class="item" style="color:var(--text-secondary);font-size:13px;cursor:default;justify-content:center;padding:12px;">'+(userLang==='en'?'No pinned conversations':'لا توجد محادثات مثبتة')+'</div>';if(!IS_REGISTERED){const hint=document.createElement('div');hint.style.cssText='padding:8px 16px 12px;font-size:12px;color:var(--text-secondary);text-align:center;line-height:1.6;';hint.innerHTML=userLang==='en'?'Sign in to save pins permanently':'سجّل دخولك لحفظ التثبيتات بشكل دائم';pl.appendChild(hint);}return;}pinned.forEach(c=>{const btn=document.createElement('button');btn.className='conv-item pinned-item';btn.innerHTML='<span class="conv-title">'+c.title+'</span>';btn.onclick=()=>loadConversation(c.id);pl.appendChild(btn);});}catch(e){}}
async function loadHistory(){try{const r=await fetch('/history');const d=await r.json();hl.innerHTML='';const localPinned=getPinnedLocal();if(d.conversations&&d.conversations.length>0){d.conversations.forEach(c=>{const isPinned=IS_REGISTERED?c.pinned:localPinned.includes(c.id);const b=document.createElement('div');b.className='conv-item';b.style.cursor='pointer';b.innerHTML='<span class="conv-title">'+((c.title&&c.title.trim())?c.title:'محادثة')+'</span><button class="pin-btn '+(isPinned?'pinned':'')+'" title="'+(isPinned?'إلغاء التثبيت':'تثبيت')+'"><svg viewBox="0 0 24 24"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg></button>';b.onclick=(e)=>{if(e.target.closest('.pin-btn'))return;loadConversation(c.id);};b.querySelector('.pin-btn').onclick=async(e)=>{e.stopPropagation();await togglePin(c.id,isPinned,e.currentTarget);};hl.appendChild(b);});}else{const e=document.createElement('div');e.className='item';e.style.color='var(--text-secondary)';e.style.fontSize='13px';e.style.justifyContent='center';e.textContent=userLang==='en'?'No conversations':'لا توجد محادثات';hl.appendChild(e);}}catch(e){}}
async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;d.messages.slice(-50).forEach(function(m){const s=m.role==='user'?'user':'bot';addMessage(m.content,s,!0)});dd.classList.remove('show')}}catch(e){}}
document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.classList.remove('show');ui.value=''});
document.querySelector('[data-action="share"]').addEventListener('click',function(e){e.stopPropagation();dd.classList.remove('show');const msgs=ch.slice(-20).map(function(m){return{r:m.role==='user'?'u':'b',c:String(m.content||'').slice(0,500)};}).filter(function(m){return m.c;});if(!msgs||msgs.length===0){showToast(userLang==='en'?'No conversation to share':'لا توجد محادثة لمشاركتها');return;}const text=userLang==='en'?'Check out my conversation with Nibras':'شوف محادثتي مع نبراس';if(IS_REGISTERED&&cid&&!String(cid).startsWith('guest_conv_')){const dbUrl=window.location.origin+'/share/'+cid;document.getElementById('shareWhatsapp').href='https://wa.me/?text='+encodeURIComponent(text+'\n'+dbUrl);document.getElementById('shareFacebook').href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(dbUrl);document.getElementById('shareTwitter').href='https://twitter.com/intent/tweet?url='+encodeURIComponent(dbUrl)+'&text='+encodeURIComponent(text);document.getElementById('shareSnapchat').onclick=function(){navigator.clipboard.writeText(dbUrl).then(function(){showToast(userLang==='en'?'Link copied':'تم نسخ الرابط');}).catch(function(){showToast(userLang==='en'?'Copy failed':'فشل النسخ');});};sm.classList.add('show');}else{let url='';try{const json=JSON.stringify(msgs);const encoded=btoa(unescape(encodeURIComponent(json)));url=window.location.origin+'/share/view#d='+encodeURIComponent(encoded);}catch(err){showToast(userLang==='en'?'Failed to prepare link':'تعذر تجهيز الرابط');return;}if(url.length>60000){showToast(userLang==='en'?'Conversation too long to share':'المحادثة طويلة جداً للمشاركة');return;}if(navigator.share){navigator.share({title:userLang==='en'?'Nibras Conversation':'محادثة نبراس',text:text,url:url}).catch(function(){});}else{navigator.clipboard.writeText(url).then(function(){showToast(userLang==='en'?'Link copied':'تم نسخ الرابط');}).catch(function(){showToast(userLang==='en'?'Copy failed':'فشل النسخ');});}}});
function escapeHtml(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
function formatBotText(t){let s=escapeHtml(t);return s.split(/\n\s*\n/).map(p=>p.replace(/[\r\n]+/g,' ').trim()).filter(p=>p.length>0).join('<br><br>');}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2000);}
function scrollMsgToTop(el){if(!el)return;requestAnimationFrame(function(){const r=el.getBoundingClientRect();const c=cb.getBoundingClientRect();cb.scrollTop=cb.scrollTop+(r.top-c.top)-8;});}
function isNearBottom(){return cb.scrollHeight-cb.scrollTop-cb.clientHeight<10;}
cb.addEventListener('scroll',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('touchmove',function(){stickBottom=isNearBottom();},{passive:true});
cb.addEventListener('wheel',function(){stickBottom=isNearBottom();},{passive:true});
function attachBotActions(el,msgText){if(!el||el.querySelector('.msg-actions'))return;const actions=document.createElement('div');actions.className='msg-actions';actions.innerHTML='<button class="act-like" title="إعجاب"><svg viewBox="0 0 24 24"><path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z"/></svg></button><button class="act-dislike" title="عدم إعجاب"><svg viewBox="0 0 24 24"><path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z"/></svg></button><button class="act-copy" title="نسخ"><svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2.5" ry="2.5"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg></button><button class="act-speak" title="استماع"><svg viewBox="0 0 24 24"><path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg></button>';el.appendChild(actions);const likeBtn=actions.querySelector('.act-like');const dislikeBtn=actions.querySelector('.act-dislike');const copyBtn=actions.querySelector('.act-copy');const speakBtn=actions.querySelector('.act-speak');likeBtn.addEventListener('click',function(){const wasLiked=this.classList.contains('liked');this.classList.toggle('liked',!wasLiked);dislikeBtn.classList.remove('disliked');actions.classList.add('touched');fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasLiked?'unlike':'like',message:msgText,conv_id:cid})}).catch(function(){});showToast(wasLiked?(userLang==='en'?'Like removed':'تم إلغاء الإعجاب'):(userLang==='en'?'Thanks!':'شكراً لتقييمك'));});dislikeBtn.addEventListener('click',function(){const wasDisliked=this.classList.contains('disliked');this.classList.toggle('disliked',!wasDisliked);likeBtn.classList.remove('liked');actions.classList.add('touched');fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:wasDisliked?'undislike':'dislike',message:msgText,conv_id:cid})}).catch(function(){});showToast(wasDisliked?(userLang==='en'?'Rating removed':'تم إلغاء التقييم'):(userLang==='en'?'We will improve':'رأيك مهم، بنتحسن'));});copyBtn.addEventListener('click',function(){navigator.clipboard.writeText(msgText).then(()=>{this.classList.add('copied');showToast(userLang==='en'?'Copied':'تم النسخ');const b=this;setTimeout(()=>b.classList.remove('copied'),1500);}).catch(()=>showToast(userLang==='en'?'Copy failed':'فشل النسخ'));});speakBtn.addEventListener('click',function(){const btn=this;if(btn.classList.contains('speaking')){stopAllAudio();document.querySelectorAll('.act-speak.speaking').forEach(function(b){ b.classList.remove('speaking'); });return;}stopAllAudio();document.querySelectorAll('.act-speak.speaking').forEach(function(b){ b.classList.remove('speaking'); });btn.classList.add('speaking');fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:msgText})}).then(r=>r.json()).then(v=>{if(v && v.audio){playAudioWithSpeed(v.audio, function(){btn.classList.remove('speaking');});}else{btn.classList.remove('speaking');showToast(userLang==='en'?'Playback failed':'فشل التشغيل');}}).catch(function(){btn.classList.remove('speaking');showToast(userLang==='en'?'Connection failed':'فشل الاتصال');});});}
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
let myAssistants=[];
let currentAssistantId=null;
let currentAssistantData={name:'نبراس',color:'#4a6a8a'};
let editingAssistantId=null;
let selectedAsstColor='#4a6a8a';
async function loadAssistants(){if(!IS_REGISTERED)return;try{const r=await fetch('/my_assistants');const d=await r.json();myAssistants=d.assistants||[];renderAssistantMenu();const saved=localStorage.getItem('nibras_assistant_id');if(saved){const id=parseInt(saved);const found=myAssistants.find(a=>a.id===id);if(found){selectAssistant(id,false);}else{selectAssistant(null,false);}}else{selectAssistant(null,false);}}catch(e){console.error(e);}}
function toggleAssistantMenu(e){if(e)e.stopPropagation();const menu=document.getElementById('assistantMenu');if(menu.classList.contains('show')){menu.classList.remove('show');return;}renderAssistantMenu();const pill=document.getElementById('assistantPill');const rect=pill.getBoundingClientRect();menu.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-260))+'px';menu.style.bottom=(window.innerHeight-rect.top+6)+'px';menu.classList.add('show');}
function renderAssistantMenu(){const menu=document.getElementById('assistantMenu');if(!menu)return;let html='';const isDefault=currentAssistantId===null;html+='<button class="assistant-menu-item'+(isDefault?' selected':'')+'" onclick="selectAssistant(null)"><span class="a-dot" style="background:#4a6a8a">ن</span><span class="a-name">نبراس</span><svg class="a-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></button>';if(myAssistants.length>0){html+='<div class="assistant-menu-sep"></div>';myAssistants.forEach(a=>{const sel=currentAssistantId===a.id;html+='<button class="assistant-menu-item'+(sel?' selected':'')+'" onclick="selectAssistant('+a.id+')"><span class="a-dot" style="background:'+a.color+'">'+escapeHtml(a.name.charAt(0))+'</span><span class="a-name">'+escapeHtml(a.name)+'</span><svg class="a-check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></button>';});}html+='<div class="assistant-menu-sep"></div>';html+='<button class="assistant-menu-add" onclick="openNewAssistantForm()"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>إضافة مساعد جديد</button>';menu.innerHTML=html;}
function selectAssistant(id,closeMenu){currentAssistantId=id;if(id===null){currentAssistantData={name:'نبراس',color:'#4a6a8a'};localStorage.removeItem('nibras_assistant_id');}else{const a=myAssistants.find(x=>x.id===id);if(a){currentAssistantData={name:a.name,color:a.color};localStorage.setItem('nibras_assistant_id',String(id));}}const dot=document.getElementById('assistantPillDot');const name=document.getElementById('assistantPillName');if(dot){dot.style.background=currentAssistantData.color;dot.textContent=currentAssistantData.name.charAt(0);}if(name){name.textContent=currentAssistantData.name;}if(closeMenu!==false){document.getElementById('assistantMenu').classList.remove('show');}}
function openNewAssistantForm(){document.getElementById('assistantMenu').classList.remove('show');closeSettings();openAssistantForm(null);}
function openAssistantForm(id){editingAssistantId=id;const a=id?myAssistants.find(x=>x.id===id):null;selectedAsstColor=a?a.color:'#4a6a8a';const colors=['#4a6a8a','#1a1a1a','#10b981','#fbbf24','#ec4899','#f97316','#8b5cf6','#ef4444'];const colorDots=colors.map(c=>'<button type="button" class="assistant-color-dot'+(c===selectedAsstColor?' selected':'')+'" data-color="'+c+'" style="background:'+c+'" onclick="pickAssistantColor(\''+c+'\')"></button>').join('');const body=document.getElementById('subPageBody');document.getElementById('subPageTitle').textContent=id?'تعديل المساعد':'مساعد جديد';body.innerHTML='<div class="assistant-form-field"><label>اسم المساعد</label><input type="text" id="asst-name" placeholder="مثلاً: أستاذ الرياضيات" maxlength="40" value="'+(a?escapeHtml(a.name):'')+'"></div><div class="assistant-form-field"><label>وصف المساعد وأسلوبه</label><textarea id="asst-persona" placeholder="اكتب كيف تريد المساعد يتصرف..." maxlength="1000">'+(a?escapeHtml(a.persona):'')+'</textarea><div class="assistant-form-hint">هذا الوصف يحدد شخصية المساعد وطريقة ردوده</div></div><div class="assistant-form-field"><label>اللون</label><div class="assistant-color-picker">'+colorDots+'</div></div><div class="assistant-form-actions"><button type="button" class="btn-cancel" onclick="loadAssistantsPage()">إلغاء</button><button type="button" class="btn-save" id="asst-save-btn" onclick="saveAssistant()">حفظ</button></div>';document.getElementById('subPage').classList.add('show');currentSubKey=null;setTimeout(()=>{const inp=document.getElementById('asst-name');if(inp)inp.focus();},100);}
function pickAssistantColor(c){selectedAsstColor=c;document.querySelectorAll('.assistant-color-dot').forEach(el=>{el.classList.toggle('selected',el.dataset.color===c);});}
async function saveAssistant(){const nameEl=document.getElementById('asst-name');const personaEl=document.getElementById('asst-persona');const name=(nameEl.value||'').trim();const persona=(personaEl.value||'').trim();if(name.length<2){showToast('اسم المساعد قصير جداً');return;}if(persona.length<10){showToast('اكتب وصفاً أطول للمساعد');return;}const btn=document.getElementById('asst-save-btn');btn.disabled=true;btn.textContent='جاري الحفظ...';try{const url=editingAssistantId?'/update_assistant':'/create_assistant';const body={name,persona,color:selectedAsstColor};if(editingAssistantId)body.id=editingAssistantId;const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(d.status==='ok'){showToast(editingAssistantId?'تم التعديل':'تم إنشاء المساعد');if(d.assistant&&!editingAssistantId){myAssistants.push(d.assistant);}else if(d.assistant&&editingAssistantId){const idx=myAssistants.findIndex(x=>x.id===editingAssistantId);if(idx>=0)myAssistants[idx]=d.assistant;}else{await loadAssistants();}renderAssistantMenu();loadAssistantsPage();}else{showToast(d.message||'فشل الحفظ');btn.disabled=false;btn.textContent='حفظ';}}catch(e){showToast('خطأ في الاتصال');btn.disabled=false;btn.textContent='حفظ';}}
async function deleteAssistant(id){if(!confirm('حذف هذا المساعد؟'))return;try{const r=await fetch('/delete_assistant',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});const d=await r.json();if(d.status==='ok'){myAssistants=myAssistants.filter(x=>x.id!==id);if(currentAssistantId===id)selectAssistant(null,false);showToast('تم الحذف');renderAssistantMenu();loadAssistantsPage();}else{showToast('فشل الحذف');}}catch(e){showToast('خطأ في الاتصال');}}
function loadAssistantsPage(){currentSubKey='assistants';document.getElementById('subPageTitle').textContent='مساعدي الخاص';let html='';if(myAssistants.length===0){html='<div class="sp-note" style="text-align:center;padding:30px;font-size:14px;">لا يوجد مساعدون حتى الآن.<br>أنشئ مساعداً خاصاً بك</div>';}else{html='<div class="assistants-list">';myAssistants.forEach(a=>{html+='<div class="assistant-card"><div class="a-dot" style="background:'+a.color+'">'+escapeHtml(a.name.charAt(0))+'</div><div class="assistant-card-info"><div class="assistant-card-name">'+escapeHtml(a.name)+'</div><div class="assistant-card-sub">'+escapeHtml(a.persona.substring(0,60))+(a.persona.length>60?'...':'')+'</div></div><button type="button" class="assistant-card-del" onclick="deleteAssistant('+a.id+')" title="حذف"><svg viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button></div>';});html+='</div>';}html+='<button type="button" class="assistant-add-btn" onclick="openAssistantForm(null)"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>إنشاء مساعد جديد</button>';document.getElementById('subPageBody').innerHTML=html;document.getElementById('subPage').classList.add('show');}
document.addEventListener('click',function(e){const menu=document.getElementById('assistantMenu');const pill=document.getElementById('assistantPill');if(!menu||!pill)return;if(!menu.contains(e.target)&&!pill.contains(e.target)){menu.classList.remove('show');}});
if(IS_REGISTERED){document.getElementById('assistantBar').classList.add('show');setTimeout(loadAssistants,300);}

// ✅ تم تعديل دالة sendMessage لدعم عرض HTML المنسق للأخبار
async function sendMessage(){
    if(iw)return;
    const msgText=ui.value.trim(),img=pid;
    if(!msgText&&!img)return;
    let userMsgEl=null;
    if(msgText){userMsgEl=addMessage(msgText,'user');ch.push({role:'user',content:msgText});}
    if(img){userMsgEl=addMessage(userLang==='en'?'Image attached':'صورة مرفقة','user',false,img);ch.push({role:'user',content:userLang==='en'?'[Image attached]':'[صورة مرفقة]'});clearPending()}
    ui.value='';ui.style.height='auto';iw=true;
    const botEl=document.createElement('div');
    botEl.className='msg bot';
    botEl.innerHTML='<span class="typing-dots">'+tr('thinking')+'</span>';
    cb.appendChild(botEl);
    if(userMsgEl)scrollMsgToTop(userMsgEl);
    const payload={message:msgText||"مرفق",image:img||null,history:ch,conv_id:cid,lang:userLang,personality:userPersonality,assistant_id:currentAssistantId};
    let displayText='';
    let bufferText='';
    let streamDone=false;
    let isFormatted=false;
    let typingTimer=null;
    function tick(){
        if(isFormatted)return;
        if(bufferText.length>0){
            displayText+=bufferText.slice(0,1);
            bufferText=bufferText.slice(1);
            botEl.innerHTML=formatBotText(displayText);
        }
        if(bufferText.length===0&&streamDone){
            clearInterval(typingTimer);
            typingTimer=null;
            botEl.innerHTML=formatBotText(displayText);
            if(displayText&&displayText.trim().length>0){
                attachBotActions(botEl,displayText);
                ch.push({role:'assistant',content:displayText});
            }
            iw=false;
            if(voiceOn===true && displayText && displayText.trim().length>10){
                fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:displayText})}).then(r=>r.json()).then(v=>{if(v && v.audio){playAudioWithSpeed(v.audio, function(){});}}).catch(function(){});
            }
        }
    }
    typingTimer=setInterval(tick,15);
    try{
        const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        if(!r.ok){
            let errMsg='مشكلة';
            try{const d=await r.json();errMsg=d.error||d.message||'مشكلة';}catch(e){}
            clearInterval(typingTimer);
            botEl.remove();
            addMessage('خطأ: '+errMsg,'error');
            iw=false;
            return;
        }
        const reader=r.body.getReader();
        const decoder=new TextDecoder();
        let sseBuffer='';
        let firstToken=true;
        while(true){
            const {done,value}=await reader.read();
            if(done)break;
            sseBuffer+=decoder.decode(value,{stream:true});
            const parts=sseBuffer.split('\n\n');
            sseBuffer=parts.pop();
            for(const line of parts){
                if(!line.startsWith('data: '))continue;
                try{
                    const data=JSON.parse(line.slice(6));
                    // ✅ جديد: التحقق من وجود HTML منسق
                    if(data.formatted_html){
                        isFormatted=true;
                        clearInterval(typingTimer);
                        typingTimer=null;
                        if(firstToken){botEl.innerHTML='';firstToken=false;}
                        botEl.classList.add('nibras-response');
                        botEl.innerHTML=data.formatted_html;
                        displayText='[تم عرض الأخبار]';
                        streamDone=true;
                        iw=false;
                    } else if(data.token){
                        if(!isFormatted){
                            if(firstToken){botEl.innerHTML='';firstToken=false;}
                            bufferText+=data.token;
                        }
                    } else if(data.done){
                        if(data.conv_id)cid=data.conv_id;
                        streamDone=true;
                    } else if(data.error){
                        bufferText+='\n\nخطأ: '+data.error;
                    }
                }catch(e){}
            }
        }
        streamDone=true;
    }catch(e){
        clearInterval(typingTimer);
        if(botEl.parentNode)botEl.remove();
        addMessage(userLang==='en'?'Connection failed':'تعذر الاتصال','error');
        iw=false;
    }
}
sb.addEventListener('click',sendMessage);
ui.addEventListener('keydown',function(e){if(e.key==='Enter'){const isMobile=/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);if(isMobile && !e.shiftKey){return;}if(!isMobile && !e.shiftKey){e.preventDefault();sendMessage();}}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
let recog=null;
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage(tr('micUnsupported'),'bot',true);return}if(this.classList.contains('listening')){this.classList.remove('listening');if(recog)recog.stop();return}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang=userLang==='en'?'en-US':'ar-SA';this.classList.add('listening');addMessage(tr('listening'),'bot',true);recog.onresult=function(e){const tr2=e.results[0][0].transcript;ui.value=tr2;mb.classList.remove('listening');setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove('listening')};recog.start()});
window.deleteMyAccount=function(){if(!confirm('حذف حسابك بالكامل؟'))return;fetch('/delete_my_account',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.status==='success'){alert('تم الحذف');window.location.href='/'}});};
window.toggleUserMenu=toggleUserMenu;window.openRedeemCode=openRedeemCode;window.redeemSubmit=redeemSubmit;
window.openSettings=openSettings;window.closeSettings=closeSettings;window.setTheme=setTheme;window.setAccentColor=setAccentColor;window.openSubPage=openSubPage;window.closeSubPage=closeSubPage;window.confirmSubPage=confirmSubPage;window.selectTheme=selectTheme;window.selectColor=selectColor;window.selectLanguage=selectLanguage;window.selectPersonality=selectPersonality;window.selectFontSize=selectFontSize;window.saveGeneral=saveGeneral;window.saveVoice=saveVoice;window.pickVoiceGender=pickVoiceGender;window.selectVoiceGender=selectVoiceGender;window.selectVoiceSpeed=selectVoiceSpeed;window.selectVoiceLevel=selectVoiceLevel;window.changePassword=changePassword;window.logoutAll=logoutAll;window.clearCache=clearCache;window.exportData=exportData;window.saveAds=saveAds;window.sendReport=sendReport;window.loadPinned=loadPinned;window.loadHistory=loadHistory;window.loadConversation=loadConversation;window.loadStorageInfo=loadStorageInfo;window.loadMemory=loadMemory;window.getContrastColor=getContrastColor;window.toggleAssistantMenu=toggleAssistantMenu;window.selectAssistant=selectAssistant;window.openNewAssistantForm=openNewAssistantForm;window.openAssistantForm=openAssistantForm;window.pickAssistantColor=pickAssistantColor;window.saveAssistant=saveAssistant;window.deleteAssistant=deleteAssistant;window.loadAssistantsPage=loadAssistantsPage;
applyLang();
(function initPersonality(){var map={friendly:'ودود',concise:'مختصر',detailed:'مفصّل',formal:'رسمي',teacher:'معلّم',playful:'فرفوش'};var lbl=document.getElementById('currentPersonalityLabel');if(lbl)lbl.textContent=map[userPersonality]||'ودود';})();
})();</script></body></html>"""
