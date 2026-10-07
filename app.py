from flask import Flask,request,jsonify,render_template_string,session,redirect,url_for,send_from_directory
import openai,os,secrets,json,asyncio,base64,re,requests,edge_tts
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client

app=Flask(__name__,static_folder='static')
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(32))
app.permanent_session_lifetime=timedelta(days=30)
app.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE='Lax',SESSION_COOKIE_SECURE=True)

ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL","abdullaha0569361@gmail.com")

OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:raise Exception("OPENAI_API_KEY غير موجود!")
OPENAI_MODEL=os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL:raise Exception("OPENAI_MODEL غير موجود!")

client=openai.OpenAI(api_key=OPENAI_API_KEY)

SUPABASE_URL=os.environ.get("SUPABASE_URL")
SUPABASE_KEY=os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("SUPABASE_URL و SUPABASE_KEY مطلوبان!")
sb=create_client(SUPABASE_URL,SUPABASE_KEY)

LIMITS={
    "guest":  {"chat":15,"search":0,   "image":0},
    "user":   {"chat":2, "search":999, "image":1},
    "admin":  {"chat":9999,"search":9999,"image":9999},
}

limiter=Limiter(key_func=get_remote_address,default_limits=["500 per day","300 per hour"])
limiter.init_app(app)

@app.after_request
def add_cors_headers(response):
    origin=request.headers.get('Origin','')
    allowed=['https://abod724.github.io','https://nibras-al.onrender.com','https://test-bot-001.onrender.com']
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin']=origin
        response.headers['Access-Control-Allow-Methods']='POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers']='Content-Type'
    return response

@app.route('/robots.txt')
def serve_robots():return send_from_directory('static','robots.txt')
@app.route('/sitemap.xml')
def serve_sitemap():return send_from_directory('static','sitemap.xml')
@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):return send_from_directory('.well-known',filename)

# ==================== دوال Supabase ====================

def get_user_role(email):
    if not email:return 'guest'
    if email.lower()==ADMIN_EMAIL.lower():return 'admin'
    try:
        r=(sb.table("profiles").select("role").eq("email",email.lower()).limit(1).execute())
        if r and r.data and r.data[0].get("role"):
            return r.data[0]["role"]
    except Exception as e:
        print("get_user_role:",e)
    return 'user'

def get_user_profile(email):
    if not email: return None
    try:
        r=(sb.table("profiles").select("*").eq("email",email.lower()).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_user_profile:",e)
    return None

def save_user_profile(email, name=None, avatar=None):
    if not email: return
    try:
        data={"email":email.lower()}
        if name is not None: data["display_name"]=name
        if avatar is not None: data["avatar_url"]=avatar
        sb.table("profiles").upsert(data, on_conflict="email").execute()
    except Exception as e:
        print("save_user_profile:",e)

def touch_user(email):
    if not email: return
    try:
        sb.table("profiles").update({"last_seen":datetime.utcnow().isoformat()}).eq("email",email.lower()).execute()
    except Exception as e:
        print("touch_user:",e)

def get_user_id():
    if session.get('is_admin'):return "admin_page"
    if session.get('user_email'):return "user_"+session['user_email']
    if 'guest_id' not in session:
        session['guest_id']="guest_"+secrets.token_hex(8)
    return session['guest_id']

def get_usage_today(uid):
    today=_date.today().isoformat()
    try:
        r=(sb.table("assistant_usage").select("*").eq("user_id",uid).eq("date",today).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_usage_today select:",e)
    new_row={"user_id":uid,"date":today,"chat_count":0,"image_count":0,"search_count":0}
    try:
        r=sb.table("assistant_usage").insert(new_row).execute()
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_usage_today insert:",e)
    return new_row

def inc_usage(uid,field):
    today=_date.today().isoformat()
    row=get_usage_today(uid)
    current=int(row.get(field,0) or 0)+1
    try:
        sb.table("assistant_usage").update({field:current}).eq("user_id",uid).eq("date",today).execute()
    except Exception as e:
        print("inc_usage:",e)
    return current

def check_limits(uid,role):
    usage=get_usage_today(uid)
    limits=LIMITS.get(role,LIMITS["guest"])
    can_chat=int(usage.get("chat_count",0) or 0)<limits["chat"]
    return usage,limits,can_chat

def get_user_conversations(uid):
    try:
        r=(sb.table("assistant_chats").select("conv_id,title,created_at").eq("user_id",uid).order("created_at",desc=True).limit(200).execute())
        rows=r.data or []
    except Exception as e:
        print("get_user_conversations:",e)
        return []
    seen={}
    for row in rows:
        cid=row.get("conv_id")
        if cid and cid not in seen:
            seen[cid]={"id":cid,"conv_id":cid,"title":row.get("title") or "محادثة","timestamp":row.get("created_at")}
    return list(seen.values())

def save_message(uid,msg,resp,cid=None):
    if not cid:cid=secrets.token_hex(5)
    try:
        ex=(sb.table("assistant_chats").select("id").eq("user_id",uid).eq("conv_id",cid).limit(1).execute())
        has_prev=bool(ex.data)
        title=None
        if not has_prev:
            title=(msg or "").strip()[:30] or "محادثة"
            if len((msg or "").strip())>30:title+="..."
        sb.table("assistant_chats").insert({"user_id":uid,"conv_id":cid,"message":msg,"response":resp,"title":title}).execute()
    except Exception as e:
        print("save_message:",e)
    return cid

def load_conversation(uid,cid):
    try:
        r=(sb.table("assistant_chats").select("message,response,created_at").eq("user_id",uid).eq("conv_id",cid).order("created_at").execute())
        rows=r.data or []
    except Exception as e:
        print("load_conversation:",e)
        return None
    if not rows:return None
    msgs=[]
    for row in rows:
        if row.get("message"):msgs.append({"role":"user","content":row["message"]})
        if row.get("response"):msgs.append({"role":"assistant","content":row["response"]})
    return msgs

def load_conversation_public(cid):
    try:
        r=(sb.table("assistant_chats").select("message,response,title,created_at").eq("conv_id",cid).order("created_at").execute())
        return r.data or []
    except Exception as e:
        print("load_conversation_public:",e)
        return []

def delete_message_row(uid,cid,index):
    try:
        r=(sb.table("assistant_chats").select("id,message,response").eq("user_id",uid).eq("conv_id",cid).order("created_at").execute())
        rows=r.data or []
        if index<0 or index>=len(rows):return False
        row_idx=index//2
        if row_idx>=len(rows):return False
        sb.table("assistant_chats").delete().eq("id",rows[row_idx]["id"]).execute()
        return True
    except Exception as e:
        print("delete_message_row:",e)
        return False

def save_image_to_library(uid, image_url=None, image_data=None, title="", source="upload"):
    try:
        row={"user_id":uid,"title":title or "صورة","source":source}
        if image_url: row["image_url"]=image_url
        if image_data: row["image_data"]=image_data
        r=sb.table("image_library").insert(row).execute()
        return r.data[0] if r and r.data else None
    except Exception as e:
        print("save_image_to_library:",e)
        return None

def get_user_images(uid):
    try:
        r=(sb.table("image_library").select("*").eq("user_id",uid).order("created_at",desc=True).limit(200).execute())
        return r.data or []
    except Exception as e:
        print("get_user_images:",e)
        return []

def delete_user_image(uid, image_id):
    try:
        sb.table("image_library").delete().eq("id",image_id).eq("user_id",uid).execute()
        return True
    except Exception as e:
        print("delete_user_image:",e)
        return False

# ==================== نهاية دوال Supabase ====================

kc=""
for fn in ["Knowledge.md","knowledge.md","معرفة.md","README.md","ملف_المعرفة.md"]:
    if os.path.exists(fn):
        try:
            with open(fn,"r",encoding="utf-8") as f:kc=f.read();break
        except:pass
if not kc:kc="أنت نبراس، مساعد ذكي."

SP=f"""أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

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

def generate_image(prompt):
    try:
        api_key=os.environ.get("PEXELS_API_KEY")
        if not api_key:return "ERROR: PEXELS_API_KEY غير موجود"
        query=requests.utils.quote(prompt);url=f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape";headers={"Authorization":api_key};response=requests.get(url,headers=headers,timeout=10);data=response.json()
        if response.status_code==200 and data.get("photos") and len(data["photos"])>0:return data["photos"][0]["src"]["large"]
        else:return f"ERROR: {data.get('error','لم أجد صورة')}"
    except Exception as e:return f"ERROR: {str(e)}"

def search_video(prompt):
    try:
        api_key=os.environ.get("PEXELS_API_KEY")
        if not api_key:return "ERROR: PEXELS_API_KEY غير موجود"
        query=requests.utils.quote(prompt);url=f"https://api.pexels.com/videos/search?query={query}&per_page=1";headers={"Authorization":api_key};response=requests.get(url,headers=headers,timeout=10);data=response.json()
        if response.status_code==200 and data.get("videos") and len(data["videos"])>0:
            video_files=data["videos"][0]["video_files"]
            for vf in video_files:
                if vf.get("quality")=="hd" and vf.get("link"):return vf["link"]
            if video_files and video_files[0].get("link"):return video_files[0]["link"]
            return "ERROR: ما لقيت رابط فيديو"
        else:return f"ERROR: {data.get('error','لم أجد فيديو')}"
    except Exception as e:return f"ERROR: {str(e)}"

async def _generate_speech_async(text, voice):
    communicate=edge_tts.Communicate(text, voice);audio_data=b""
    async for chunk in communicate.stream():
        if chunk["type"]=="audio":audio_data+=chunk["data"]
    return audio_data

def generate_speech(text, gender):
    try:
        voice="ar-SA-HamedNeural" if gender=="male" else "ar-SA-ZariyahNeural"
        audio=asyncio.run(_generate_speech_async(text, voice))
        return base64.b64encode(audio).decode('utf-8')
    except Exception as e:print(f"صوت: {e}");return None

# ==================== قوالب HTML ====================
