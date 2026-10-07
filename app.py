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

# ========== Supabase ==========
SUPABASE_URL=os.environ.get("SUPABASE_URL")
SUPABASE_KEY=os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("SUPABASE_URL و SUPABASE_KEY مطلوبان!")
sb=create_client(SUPABASE_URL,SUPABASE_KEY)

# ========== الحدود ==========
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
    allowed=['https://abod724.github.io','https://nibras-al.onrender.com']
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
    """يرجع دور المستخدم: admin / user / guest"""
    if not email:return 'guest'
    if email.lower()==ADMIN_EMAIL.lower():return 'admin'
    try:
        r=(sb.table("profiles")
             .select("role")
             .eq("email",email.lower())
             .limit(1)
             .execute())
        if r and r.data and r.data[0].get("role"):
            return r.data[0]["role"]
    except Exception as e:
        print("get_user_role:",e)
    return 'user'

def get_user_id():
    """يرجع معرف المستخدم الحالي (email أو guest_<token>)"""
    if session.get('is_admin'):return "admin_page"
    if session.get('user_email'):return "user_"+session['user_email']
    if 'guest_id' not in session:
        session['guest_id']="guest_"+secrets.token_hex(8)
    return session['guest_id']

def get_usage_today(uid):
    """يرجع صف الاستخدام لليوم أو ينشئ واحداً"""
    today=_date.today().isoformat()
    try:
        r=(sb.table("assistant_usage")
             .select("*")
             .eq("user_id",uid)
             .eq("date",today)
             .limit(1)
             .execute())
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
    """يزيد عدّاد اليوم لعمود معين"""
    today=_date.today().isoformat()
    row=get_usage_today(uid)
    current=int(row.get(field,0) or 0)+1
    try:
        sb.table("assistant_usage") \
          .update({field:current}) \
          .eq("user_id",uid) \
          .eq("date",today) \
          .execute()
    except Exception as e:
        print("inc_usage:",e)
    return current

def check_limits(uid,role):
    """يرجع (usage, limits, can_chat:bool)"""
    usage=get_usage_today(uid)
    limits=LIMITS.get(role,LIMITS["guest"])
    can_chat=int(usage.get("chat_count",0) or 0)<limits["chat"]
    return usage,limits,can_chat

def get_user_conversations(uid):
    """يرجع قائمة محادثات فريدة (conv_id + title + time)"""
    try:
        r=(sb.table("assistant_chats")
             .select("conv_id,title,created_at")
             .eq("user_id",uid)
             .order("created_at",desc=True)
             .limit(200)
             .execute())
        rows=r.data or []
    except Exception as e:
        print("get_user_conversations:",e)
        return []
    seen={}
    for row in rows:
        cid=row.get("conv_id")
        if cid and cid not in seen:
            seen[cid]={
                "id":cid,
                "conv_id":cid,
                "title":row.get("title") or "محادثة",
                "timestamp":row.get("created_at"),
            }
    return list(seen.values())

def save_message(uid,msg,resp,cid=None):
    """يحفظ رسالة+رد. ينشئ conv_id جديد إذا ما فيه."""
    if not cid:
        cid=secrets.token_hex(5)  # 10 أحرف مثل السابق
    try:
        # هل فيه صفوف سابقة؟
        ex=(sb.table("assistant_chats")
              .select("id")
              .eq("user_id",uid)
              .eq("conv_id",cid)
              .limit(1)
              .execute())
        has_prev=bool(ex.data)
        title=None
        if not has_prev:
            title=(msg or "").strip()[:30] or "محادثة"
            if len((msg or "").strip())>30:title+="..."
        sb.table("assistant_chats").insert({
            "user_id":uid,
            "conv_id":cid,
            "message":msg,
            "response":resp,
            "title":title,
        }).execute()
    except Exception as e:
        print("save_message:",e)
    return cid

def load_conversation(uid,cid):
    """يرجع كل رسائل محادثة معينة كـ list of {role,content}"""
    try:
        r=(sb.table("assistant_chats")
             .select("message,response,created_at")
             .eq("user_id",uid)
             .eq("conv_id",cid)
             .order("created_at")
             .execute())
        rows=r.data or []
    except Exception as e:
        print("load_conversation:",e)
        return None
    if not rows:return None
    msgs=[]
    for row in rows:
        if row.get("message"):
            msgs.append({"role":"user","content":row["message"]})
        if row.get("response"):
            msgs.append({"role":"assistant","content":row["response"]})
    return msgs

def load_conversation_public(cid):
    """للرابط العام /share/<cid>"""
    try:
        r=(sb.table("assistant_chats")
             .select("message,response,title,created_at")
             .eq("conv_id",cid)
             .order("created_at")
             .execute())
        return r.data or []
    except Exception as e:
        print("load_conversation_public:",e)
        return []

def delete_message_row(uid,cid,index):
    """يحذف رسالة واحدة (بالترتيب) من محادثة"""
    try:
        r=(sb.table("assistant_chats")
             .select("id,message,response")
             .eq("user_id",uid)
             .eq("conv_id",cid)
             .order("created_at")
             .execute())
        rows=r.data or []
        if index<0 or index>=len(rows):return False
        # كل صف = رسالتان (user + assistant)، لذا نحوّل الـ index
        row_idx=index//2
        if row_idx>=len(rows):return False
        sb.table("assistant_chats").delete().eq("id",rows[row_idx]["id"]).execute()
        return True
    except Exception as e:
        print("delete_message_row:",e)
        return False

# ==================== نهاية دوال Supabase ====================

sm={}
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
    except Exception as e:print(f"❌ صوت: {e}");return None

# ==================== HTML (نفس السابق بدون تغيير) ====================
# ملاحظة: كل قوالب HTML (SPH, TOOLS_HTML, LH, HT) تبقى كما هي.
# لكن LH يُستبدل بالقالب الجديد أدناه (بدون access_code).

LH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:40px 30px;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;max-width:400px;text-align:center}h2{font-size:26px;color:#1a2b3c;margin-bottom:25px}input{width:100%;padding:14px 16px;margin:10px 0;border:1px solid #dce1e8;border-radius:12px;font-size:16px;background:#fafbfc;box-sizing:border-box}input:focus{outline:0;border-color:#4a6a8a;background:#fff}button{width:100%;padding:16px;background:#4a6a8a;color:#fff;border:none;border-radius:12px;font-size:18px;font-weight:700;cursor:pointer;margin-top:15px}button:hover{background:#3a5a7a}button.alt{background:#eaeef2;color:#1a2b3c}button.alt:hover{background:#dce1e8}a{color:#4a6a8a;text-decoration:none;font-size:15px;display:inline-block;margin-top:20px}.error{color:#d9534f;background:#fde8e8;padding:12px;border-radius:10px;margin-bottom:15px;font-size:14px}.success{color:#1a7f37;background:#e6f4ea;padding:12px;border-radius:10px;margin-bottom:15px;font-size:14px}.tabs{display:flex;gap:8px;margin-bottom:20px}.tabs button{flex:1;padding:12px;font-size:15px;border-radius:12px;background:#eaeef2;color:#1a2b3c}.tabs button.active{background:#4a6a8a;color:#fff}.section{display:none}.section.active{display:block}</style></head><body><div class="box"><h2>🔐 نبراس</h2>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور" required><button type="submit">دخول</button></form></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور (6 أحرف +)" minlength="6" required><button type="submit">إنشاء حساب</button></form></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><input type="email" name="email" placeholder="البريد الإلكتروني" required><button type="submit">إرسال رابط الاستعادة</button></form></div><a href="/">⬅ العودة للرئيسية</a><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:inline-block;margin-top:5px;font-size:12px;text-decoration:underline;">سياسة الخصوصية</a></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

@app.route('/')
def index():return render_template_string(HT)

@app.route('/tools')
def tools_page():return render_template_string(TOOLS_HTML)

@app.route('/share/<cid>')
def shared_conversation(cid):
    rows=load_conversation_public(cid)
    if not rows:return "⚠️ المحادثة غير موجودة.",404
    msgs=[]
    title="محادثة نبراس"
    for i,row in enumerate(rows):
        if i==0 and row.get("title"):title=row["title"]
        if row.get("message"):msgs.append({"role":"user","content":row["message"]})
        if row.get("response"):msgs.append({"role":"assistant","content":row["response"]})
    return render_template_string(SPH,messages=msgs,title=title)

# ==================== تسجيل الدخول ====================

@app.route('/login',methods=['GET','POST'])
@limiter.limit("10 per minute")
def login():
    if request.method=='POST':
        e=request.form.get('email','').strip().lower()
        p=request.form.get('password','')
        ap=os.environ.get("ADMIN_PASSWORD")

        if not e or "@" not in e:
            return render_template_string(LH,error="يرجى إدخال بريد صحيح.")

        # أدمن
        if e==ADMIN_EMAIL.lower():
            if not ap:return render_template_string(LH,error="لم يتم إعداد كلمة مرور الأدمن.")
            if secrets.compare_digest(p,ap):
                session.clear();session.permanent=True
                session['user_email']=e;session['is_admin']=True
                session['user_role']='admin'
                return redirect(url_for('index'))
            return render_template_string(LH,error="كلمة مرور الأدمن غير صحيحة.")

        # مستخدم عادي عبر Supabase Auth
        try:
            r=requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},
                json={"email":e,"password":p},
                timeout=15,
            )
        except Exception as ex:
            return render_template_string(LH,error=f"تعذر الاتصال بخدمة الدخول.")

        if r.status_code!=200:
            return render_template_string(LH,error="البريد الإلكتروني أو كلمة المرور غير صحيحة.")

        data=r.json()
        session.clear();session.permanent=True
        session['user_email']=e
        session['is_admin']=False
        session['access_token']=data.get('access_token')
        session['refresh_token']=data.get('refresh_token')
        session['user_role']=get_user_role(e)
        return redirect(url_for('index'))

    return render_template_string(LH)

@app.route('/signup',methods=['POST'])
@limiter.limit("5 per hour")
def signup():
    e=request.form.get('email','').strip().lower()
    p=request.form.get('password','')
    if not e or "@" not in e or len(p)<6:
        return render_template_string(LH,error="بريد صحيح وكلمة مرور 6 أحرف على الأقل مطلوبة.")
    try:
        sb.auth.sign_up({"email":e,"password":p})
        return render_template_string(LH,success="✅ تم إنشاء حسابك! تحقق من بريدك للتأكيد ثم سجّل الدخول.")
    except Exception as ex:
        return render_template_string(LH,error=f"فشل إنشاء الحساب: {ex}")

@app.route('/recover',methods=['POST'])
@limiter.limit("5 per hour")
def recover():
    e=request.form.get('email','').strip().lower()
    if not e or "@" not in e:
        return render_template_string(LH,error="أدخل بريداً صحيحاً.")
    try:
        requests.post(
            f"{SUPABASE_URL}/auth/v1/recover",
            headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},
            json={"email":e},
            timeout=15,
        )
        return render_template_string(LH,success="✅ تم إرسال رابط استعادة كلمة المرور إلى بريدك.")
    except Exception as ex:
        return render_template_string(LH,error=f"تعذر إرسال الرابط: {ex}")

@app.route('/logout')
def logout():session.clear();return redirect(url_for('index'))

# ==================== المحادثات ====================

@app.route('/history')
def history():
    uid=get_user_id();cs=get_user_conversations(uid)
    return jsonify({"conversations":[{"id":c["id"],"title":c["title"]} for c in cs]})

@app.route('/load_conversation/<cid>')
def load_conversation_route(cid):
    uid=get_user_id();ms=load_conversation(uid,cid)
    return jsonify({"messages":ms}) if ms else (jsonify({"messages":None}),404)

@app.route('/delete_message',methods=['POST'])
def delete_message():
    try:
        d=request.get_json();cid=d.get('conv_id');idx=d.get('index');uid=get_user_id()
        if not cid or idx is None:return jsonify({"status":"error","message":"بيانات ناقصة"}),400
        ok=delete_message_row(uid,cid,idx)
        if ok:return jsonify({"status":"ok"})
        return jsonify({"status":"error","message":"غير موجودة"}),404
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),500

@app.route('/delete_my_account',methods=['POST'])
def delete_my_account():
    email=session.get('user_email')
    is_admin=session.get('is_admin')
    if not email or is_admin:
        return jsonify({"status":"error","message":"لا يوجد حساب لحذفه"}),400

    uid=get_user_id()
    try:
        sb.table("assistant_chats").delete().eq("user_id",uid).execute()
        sb.table("assistant_usage").delete().eq("user_id",uid).execute()
        sb.table("library").delete().eq("user_id",uid).execute()
    except Exception as e:
        print("delete_my_account:",e)
    session.clear()
    return jsonify({"status":"success","message":"تم حذف حسابك بالكامل"})

@app.route('/request-deletion',methods=['POST','OPTIONS'])
@limiter.limit("5 per hour")
def request_deletion():
    if request.method=='OPTIONS':
        return '',204
    try:
        d=request.get_json()
        email=(d.get('email') or '').strip().lower()
        password=d.get('password') or ''
        if not email or '@' not in email:
            return jsonify({"status":"error","message":"بريد غير صحيح"}),400
        if not password:
            return jsonify({"status":"error","message":"كلمة المرور مطلوبة"}),400
        # تحقق من كلمة المرور عبر Supabase Auth
        r=requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},
            json={"email":email,"password":password},
            timeout=15,
        )
        if r.status_code!=200:
            return jsonify({"status":"error","message":"البريد أو كلمة المرور غير صحيحة"}),401
        # سجّل الطلب (اختياري: أنشئ جدول deletion_requests)
        print(f"🗑️ طلب حذف حساب (موثق): {email}")
        return jsonify({"status":"ok"})
    except Exception as e:
        print(f"❌ خطأ في طلب الحذف: {e}")
        return jsonify({"status":"error","message":"حدث خطأ، حاول لاحقاً"}),500

# ==================== لوحة التحكم ====================

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        p=request.form.get('password','')
        ap=os.environ.get("ADMIN_PASSWORD")
        if ap and secrets.compare_digest(p,ap):
            session['is_admin']=True;session.permanent=True
            return redirect(url_for('admin_dashboard'))
        return """<body style='background:#0d1117;color:#c9d1d9;font-family:sans-serif;text-align:center;padding:50px;'><h2>❌ كلمة مرور خاطئة</h2><a href='/admin/login' style='color:#58a6ff;'>حاول مرة أخرى</a></body>"""
    return """<body style='background:#0d1117;color:#c9d1d9;font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;'><form method='POST' style='background:#161b22;padding:30px;border-radius:15px;border:1px solid #30363d;text-align:center;'><h2 style='color:#58a6ff;'>🔐 دخول الأدمن</h2><input type='password' name='password' placeholder='كلمة المرور' required style='padding:14px;border-radius:8px;border:1px solid #30363d;background:#0d1117;color:#c9d1d9;font-size:16px;width:250px;'><br><br><button type='submit' style='background:#58a6ff;color:#fff;border:none;padding:12px 30px;border-radius:8px;cursor:pointer;font-size:16px;font-weight:bold;'>دخول</button></form></body>"""

@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):return redirect(url_for('admin_login'))
    try:
        recent_r=(sb.table("assistant_chats")
                    .select("user_id,title,created_at")
                    .order("created_at",desc=True)
                    .limit(10)
                    .execute())
        recent=recent_r.data or []
        users_r=(sb.table("assistant_chats").select("user_id").execute())
        users_set={row["user_id"] for row in (users_r.data or [])}
        total_convs=len(users_r.data or [])
    except Exception as e:
        print("admin_dashboard:",e);recent=[];users_set=set();total_convs=0

    today=_date.today().isoformat()
    today_convs=sum(1 for r in recent if (r.get("created_at") or "").startswith(today))

    recent_html=""
    for row in recent:
        user=row.get("user_id","")[:15]
        title=row.get("title") or "بدون عنوان"
        time=(row.get("created_at") or "")[:16].replace("T"," ")
        recent_html+=f'<div class="conv-item"><b>{title}</b><small>👤 {user} | 🕒 {time}</small></div>'
    if not recent_html:recent_html="<p style='color:#8b949e;text-align:center;'>لا توجد محادثات</p>"

    return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>لوحة تحكم نبراس</title><style>body{{font-family:'Segoe UI',Tahoma;background:#0d1117;color:#c9d1d9;padding:20px;margin:0}}.container{{max-width:600px;margin:auto}}h1{{color:#58a6ff;text-align:center}}.card{{background:#161b22;border-radius:15px;padding:15px;margin:15px 0;border:1px solid #30363d}}.stat{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #21262d}}.stat:last-child{{border:none}}.num{{color:#58a6ff;font-weight:bold;font-size:18px}}.conv-item{{padding:10px 0;border-bottom:1px solid #21262d}}.conv-item small{{color:#8b949e;display:block;font-size:12px}}.link-btn{{display:block;background:#58a6ff;color:#fff;text-decoration:none;padding:12px;border-radius:8px;text-align:center;font-weight:bold;margin-top:10px}}.back{{display:block;text-align:center;color:#58a6ff;text-decoration:none;margin-top:20px}}</style></head><body><div class="container"><h1>📊 لوحة تحكم نبراس</h1><div class="card"><div class="stat"><span>👥 المستخدمون النشطون</span><span class="num">{len(users_set)}</span></div><div class="stat"><span>💬 إجمالي المحادثات</span><span class="num">{total_convs}</span></div><div class="stat"><span>📅 آخر 10 (اليوم)</span><span class="num">{today_convs}</span></div></div><div class="card"><h3>🕒 آخر 10 محادثات</h3>{recent_html}</div><a href="/" class="back">⬅ الرئيسية</a></div></body></html>"""

# ==================== الإعدادات ====================

@app.route('/set_gender',methods=['POST'])
def set_gender():
    d=request.get_json();g=d.get('gender','male');session['voice_gender']=g
    return jsonify({"status":"ok"})

# ==================== /chat ====================

@app.route('/chat',methods=['POST'])
@limiter.limit("20 per minute")
def chat():
    try:
        d=request.get_json();um=d.get("message","").strip();hist=d.get("history",[]);cid=d.get("conv_id",None)
        if not um:return jsonify({"reply":"اكتب شيء أساعدك فيه"})

        is_admin=bool(session.get('is_admin'))
        user_email=session.get('user_email','')
        user_role=get_user_role(user_email) if user_email else 'guest'
        is_registered=is_admin or (bool(user_email) and user_role in ('user','admin','reviewer'))
        is_guest=not is_registered
        uid=get_user_id()

        # تحقق من الحدود
        usage,limits,can_chat=check_limits(uid,user_role if not is_admin else 'admin')

        if not can_chat:
            reply_limit=f"وصلت للحد اليومي ({limits['chat']} محادثة) 😊\n\n💡 تواصل مع المطور للحصول على وصول أوسع."
            nid=save_message(uid,um,reply_limit,cid)
            return jsonify({"reply":reply_limit,"conv_id":nid,"audio":None})

        # طلب صورة/فيديو
        draw_phrases=["ارسم لي","ابي صورة","ابي صوره","ابي صورت","صوره لي","ارسم","أنشئ","انشئ","انشى","صمم","ولّد","generate","draw","فيديو","ابي فيديو","عرض فيديو"]
        def is_image_request(text):
            tl=text.lower().strip()
            if len(tl.split())<=1:return False
            for p in draw_phrases:
                if p in tl:return True
            return False

        has_image=d.get("image") is not None

        if is_image_request(um) and not has_image:
            video_keywords=["فيديو","ابي فيديو","عرض فيديو"]
            is_video=any(kw in um for kw in video_keywords)

            # للأدمن/المسجل: استخدم الصور/الفيديو
            if is_video:
                vr=search_video(um)
                if vr and vr.startswith("ERROR:"):
                    reply=f"⚠️ {vr.replace('ERROR:','')}"
                    nid=save_message(uid,um,reply,cid)
                    return jsonify({"reply":reply,"conv_id":nid})
                elif vr:
                    reply="🎬 إليك الفيديو:";rw=reply+"\n"+vr
                    nid=save_message(uid,um,rw,cid)
                    return jsonify({"reply":rw,"image_url":vr,"conv_id":nid})
            else:
                ir=generate_image(um)
                if ir and ir.startswith("ERROR:"):
                    reply=f"⚠️ {ir.replace('ERROR:','')}"
                    nid=save_message(uid,um,reply,cid)
                    return jsonify({"reply":reply,"conv_id":nid})
                elif ir:
                    reply="🖼️ إليك الصورة:";rw=reply+"\n"+ir
                    nid=save_message(uid,um,rw,cid)
                    return jsonify({"reply":rw,"image_url":ir,"conv_id":nid})

        # تحليل صور: للمسجلين فقط
        if has_image and not is_registered:
            reply="عذراً، تحليل الصور متاح للأعضاء المسجلين فقط.\n\n🔐 أنشئ حساباً للحصول عليها."
            nid=save_message(uid,um,reply,cid)
            return jsonify({"reply":reply,"conv_id":nid})

        # بناء السياق
        server_hist=load_conversation(uid,cid) if cid else []
        if not server_hist:server_hist=[]
        server_hist.append({"role":"user","content":um})
        ch=server_hist[-15:]
        msgs=[{"role":"system","content":SP}]
        for e in ch:
            if isinstance(e.get("content"),str):
                msgs.append({"role":e["role"],"content":e["content"]})

        img_data=d.get("image",None)
        if img_data and is_registered:
            msgs.append({"role":"user","content":[
                {"type":"text","text":um or "حلل الصورة"},
                {"type":"image_url","image_url":{"url":img_data}}
            ]})

        # بحث ويب للمسجلين
        if is_registered:
            try:
                fc=""
                for m in msgs:
                    if isinstance(m.get("content"),str):
                        if m["role"]=="user":fc+=m["content"]+"\n"
                        elif m["role"]=="assistant":fc+="نبراس: "+m["content"]+"\n"
                sr=client.responses.create(model=OPENAI_MODEL,instructions=f"{SP}\n\nسياق:\n{fc}",input=f"ابحث عن أحدث المعلومات: {um}",tools=[{"type":"web_search"}])
                res=sr.output_text.strip()
                if res:msgs.append({"role":"user","content":f"نتيجة البحث:\n{res}"})
                inc_usage(uid,"search_count")
            except Exception as e:print(f"⚠️ بحث: {e}")

        # استدعاء OpenAI
        try:
            rl="high" if is_registered else "low"
            r=client.chat.completions.create(model=OPENAI_MODEL,messages=msgs,max_completion_tokens=8000,reasoning_effort=rl)
            reply=r.choices[0].message.content.strip()
            if not reply:reply="ما قدرت أجيب رد."
        except Exception as e:
            print(f"❌ {e}")
            return jsonify({"error":str(e)}),500

        # دمج الأسطر في فقرات
        lines=reply.split('\n');merged=[];cur=[]
        for line in lines:
            line=line.strip()
            if not line:
                if cur:merged.append(' '.join(cur));cur=[]
            else:cur.append(line)
        if cur:merged.append(' '.join(cur))
        reply='\n\n'.join(merged)

        nid=save_message(uid,um,reply,cid)
        inc_usage(uid,"chat_count")

        # صوت
        try:g=session.get('voice_gender','male');audio=generate_speech(reply,g)
        except Exception as e:print(f"⚠️ صوت: {e}");audio=None

        return jsonify({"reply":reply,"audio":audio,"conv_id":nid})
    except Exception as e:
        print(f"❌ {e}")
        return jsonify({"status":"error","message":str(e)}),500

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
