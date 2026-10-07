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
            seen[cid]={
                "id":cid,
                "conv_id":cid,
                "title":row.get("title") or "محادثة",
                "timestamp":row.get("created_at"),
            }
    return list(seen.values())

def save_message(uid,msg,resp,cid=None):
    if not cid:
        cid=secrets.token_hex(5)
    try:
        ex=(sb.table("assistant_chats").select("id").eq("user_id",uid).eq("conv_id",cid).limit(1).execute())
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
    try:
        r=(sb.table("assistant_chats").select("message,response,created_at").eq("user_id",uid).eq("conv_id",cid).order("created_at").execute())
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

# ==================== قوالب HTML ====================

SPH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>📄 محادثة نبراس</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css"><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>💬 {{ title or 'محادثة نبراس' }}</h1><a href="/">⬅ الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class="content">{{ msg.content|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

TOOLS_HTML="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>أدوات نبراس</title><style>body{font-family:'Segoe UI',Tahoma;background:#0f172a;color:#fff;margin:0;padding:20px}.container{max-width:900px;margin:auto}h1{text-align:center;color:#38bdf8}a{color:#38bdf8}.card{background:#1e293b;border-radius:15px;padding:20px;margin:20px 0;border:1px solid #334155}input,select,textarea{width:100%;padding:12px;margin:8px 0;border-radius:8px;border:none;background:#0f172a;color:#fff;box-sizing:border-box}button{background:#38bdf8;color:#000;padding:12px 20px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;width:100%}button:hover{background:#0ea5e9}.result{background:#0f172a;padding:15px;border-radius:8px;margin-top:10px;border:1px dashed #38bdf8}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}@media(max-width:600px){.grid{grid-template-columns:1fr}}</style></head><body><div class="container"><h1>🧰 أدوات نبراس المجانية</h1><p style="text-align:center"><a href="/">⬅ ارجع لنبراس</a></p><div class="card"><h3>📚 حاسبة GPA</h3><div class="grid"><input id="gpa1" placeholder="ساعات مادة 1" type="number"><select id="grade1"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><div class="grid"><input id="gpa2" placeholder="ساعات مادة 2" type="number"><select id="grade2"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><button onclick="calcGPA()">احسب</button><div id="gpaRes" class="result" style="display:none"></div></div><div class="card"><h3>📝 منشئ السيرة الذاتية</h3><input id="cvName" placeholder="الاسم"><input id="cvSpec" placeholder="التخصص"><textarea id="cvExp" placeholder="خبراتك"></textarea><button onclick="makeCV()">أنشئ</button><div id="cvRes" class="result" style="display:none"></div></div><div class="card"><h3>💰 حاسبة حساب المواطن</h3><input id="family" type="number" placeholder="عدد الأسرة"><input id="income" type="number" placeholder="الدخل"><button onclick="calcCitizen()">احسب</button><div id="citRes" class="result" style="display:none"></div></div><div class="card"><h3>💡 مولد أفكار مشاريع</h3><select id="budget"><option value="5000">5 آلاف</option><option value="10000">10 آلاف</option><option value="20000">20 ألف</option><option value="50000">50 ألف</option></select><button onclick="genIdea()">عطني فكرة</button><div id="ideaRes" class="result" style="display:none"></div></div></div><script>function calcGPA(){let h1=parseFloat(document.getElementById('gpa1').value)||0;let g1=parseFloat(document.getElementById('grade1').value)||0;let h2=parseFloat(document.getElementById('gpa2').value)||0;let g2=parseFloat(document.getElementById('grade2').value)||0;if(h1==0&&h2==0){alert('دخل ساعات');return;}let total=(h1*g1+h2*g2)/(h1+h2);document.getElementById('gpaRes').style.display='block';document.getElementById('gpaRes').innerHTML='معدلك: <b style="color:#38bdf8;font-size:22px">'+total.toFixed(2)+'</b> / 5';}function makeCV(){let n=document.getElementById('cvName').value;let s=document.getElementById('cvSpec').value;let e=document.getElementById('cvExp').value;if(!n){alert('اكتب اسمك');return;}let cv='السيرة الذاتية\\nالاسم: '+n+'\\nالتخصص: '+s+'\\n\\nالخبرات:\\n'+e;document.getElementById('cvRes').style.display='block';document.getElementById('cvRes').innerText=cv;}function calcCitizen(){let f=parseInt(document.getElementById('family').value)||1;let inc=parseInt(document.getElementById('income').value)||0;let support=0;if(inc<3000)support=f*400;else if(inc<6000)support=f*300;else support=f*150;if(support>3000)support=3000;document.getElementById('citRes').style.display='block';document.getElementById('citRes').innerHTML='الدعم: <b style="color:#22c55e">'+support+' ريال</b>';}const ideas={'5000':['متجر منتجات محلية','خدمة كتابة بحوث'],'10000':['فود ترك','متجر تغليف هدايا'],'20000':['دروس أونلاين','استوديو تصوير'],'50000':['مقهى','شركة توصيل']};function genIdea(){let b=document.getElementById('budget').value;let list=ideas[b];let rnd=list[Math.floor(Math.random()*list.length)];document.getElementById('ideaRes').style.display='block';document.getElementById('ideaRes').innerHTML='💡 <b style="color:#facc15;font-size:18px">'+rnd+'</b>';}</script></body></html>"""

LH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:40px 30px;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;max-width:400px;text-align:center}h2{font-size:26px;color:#1a2b3c;margin-bottom:25px}input{width:100%;padding:14px 16px;margin:10px 0;border:1px solid #dce1e8;border-radius:12px;font-size:16px;background:#fafbfc;box-sizing:border-box}input:focus{outline:0;border-color:#4a6a8a;background:#fff}button{width:100%;padding:16px;background:#4a6a8a;color:#fff;border:none;border-radius:12px;font-size:18px;font-weight:700;cursor:pointer;margin-top:15px}button:hover{background:#3a5a7a}button.alt{background:#eaeef2;color:#1a2b3c}button.alt:hover{background:#dce1e8}a{color:#4a6a8a;text-decoration:none;font-size:15px;display:inline-block;margin-top:20px}.error{color:#d9534f;background:#fde8e8;padding:12px;border-radius:10px;margin-bottom:15px;font-size:14px}.success{color:#1a7f37;background:#e6f4ea;padding:12px;border-radius:10px;margin-bottom:15px;font-size:14px}.tabs{display:flex;gap:8px;margin-bottom:20px}.tabs button{flex:1;padding:12px;font-size:15px;border-radius:12px;background:#eaeef2;color:#1a2b3c}.tabs button.active{background:#4a6a8a;color:#fff}.section{display:none}.section.active{display:block}</style></head><body><div class="box"><h2>🔐 نبراس</h2>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور" required><button type="submit">دخول</button></form></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required><button type="submit">إنشاء حساب</button></form></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><input type="email" name="email" placeholder="البريد الإلكتروني" required><button type="submit">إرسال رابط الاستعادة</button></form></div><a href="/">⬅ العودة للرئيسية</a><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:inline-block;margin-top:5px;font-size:12px;text-decoration:underline;">سياسة الخصوصية</a></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

HT=r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><title>نبراس GP | مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"/><link rel="icon" type="image/png" href="/static/icon-512.png"/><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.0.0/css/all.min.css"/><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#6a7b8c;--welcome-bg:#fff;--border-input:#dce1e8;--mute-muted:#444;--mute-hover:#1a2b3c;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--mic-active-bg:#fde8e8;--mic-active-color:#c33;--remove-btn-hover:#fde8e8;--modal-bg:rgba(0,0,0,0.5)}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-bot-msg:transparent;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#8b949e;--welcome-bg:#161b22;--border-input:#30363d;--mute-muted:#484f58;--mute-hover:#c9d1d9;--send-bg:#238636;--send-hover:#2ea043;--mic-active-bg:#2d1b1b;--mic-active-color:#f85149;--remove-btn-hover:#2d1b1b;--modal-bg:rgba(0,0,0,0.7)}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-color);flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.menu-btn{background:0 0;border:none;font-size:20px;color:var(--text-secondary);cursor:pointer;padding:4px 8px}.mute-btn{background:0 0;border:none;font-size:20px;color:var(--text-secondary);cursor:pointer;padding:4px 8px}.mute-btn.muted{opacity:.4;transform:scale(.9)}.btn-group{display:flex;gap:8px}.btn{padding:6px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center}.btn-outline{background:0 0;border:1px solid var(--primary-color);color:var(--primary-color)}.dropdown{position:absolute;top:64px;left:14px;right:14px;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 8px 30px var(--shadow-color);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:60vh;overflow-y:auto}.dropdown.show{display:flex}.dropdown .item{display:flex;align-items:center;gap:12px;padding:14px 18px;font-size:15px;color:var(--text-primary);background:0 0;border:none;width:100%;text-align:right;cursor:pointer;border-bottom:1px solid var(--border-color)}.dropdown .item:last-child{border-bottom:none}.dropdown .item i{width:22px;font-size:18px;color:var(--text-secondary)}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .conv-item{display:block;padding:12px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;width:100%;background:0 0;border:none;text-align:right;font-size:16px;color:var(--text-primary);font-weight:500}.dropdown .conv-item:hover{background:var(--bg-hover)}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:16px;min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:16px;font-weight:600;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--bg-user-msg);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.35;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.msg .generated-video{max-width:100%;border-radius:12px;margin:8px 0}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;font-size:16px;color:var(--text-secondary)}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}.welcome-overlay{position:fixed;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;pointer-events:none}.welcome-overlay .welcome-box{background:var(--welcome-bg);padding:30px 40px;border-radius:20px;text-align:center;max-width:90%;border:1px solid var(--border-color);pointer-events:auto}.welcome-overlay .welcome-box h2{font-size:28px;color:var(--text-primary);margin-bottom:8px}.welcome-overlay .welcome-box p{font-size:18px;color:var(--text-secondary)}.welcome-overlay.fade-out{animation:fadeOut .5s forwards}@keyframes fadeOut{to{opacity:0;transform:scale(.9)}}#imagePreviewContainer{display:none;padding:6px 18px;align-items:center;gap:10px;background:var(--bg-input);margin:0 14px;border-radius:20px 20px 0 0;border:1px solid var(--border-color);border-bottom:none;flex-wrap:wrap;flex-shrink:0}#imagePreviewContainer img{max-height:60px;border-radius:8px;border:1px solid var(--border-color)}#imagePreviewContainer .label{font-size:13px;color:var(--text-secondary)}#removeImageBtn{background:0 0;border:none;color:var(--danger-color);font-size:14px;cursor:pointer;padding:4px 8px;border-radius:12px}.input-area{display:flex;align-items:flex-end;justify-content:center;gap:8px;padding:8px 14px;margin:8px 14px 16px;background:var(--bg-input);border-radius:40px;border:1px solid var(--border-color);flex-shrink:0;min-height:60px}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:18px;font-weight:600;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow:hidden;min-height:20px;max-height:80px;font-family:inherit;line-height:1.4}.input-area textarea::placeholder{color:var(--placeholder-color)}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);font-size:20px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.input-area .btn-icon:hover{background:var(--bg-hover)}.input-area .mic-btn{color:var(--primary-color)}.input-area .mic-btn.listening{color:var(--mic-active-color);background:var(--mic-active-bg)}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:44px;height:44px;border-radius:50%;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 2px 8px var(--send-shadow)}.input-area .send:hover{background:var(--send-hover)}.plus-btn{background:0 0;border:none;color:var(--primary-color);font-size:24px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.3s}.plus-btn:hover{background:var(--bg-hover)}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:6px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--text-primary);cursor:pointer}.plus-options .option-btn:hover{background:var(--border-color)}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}.dropdown{top:58px;left:10px;right:10px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px;font-size:14px}.input-area .btn-icon{width:32px;height:32px;font-size:16px}.plus-btn{width:32px;height:32px;font-size:18px}}.gender-option{flex:1;padding:8px 4px;border-radius:10px;border:1px solid var(--border-color);background:0 0;font-size:14px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:4px}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color)}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color)}.share-modal .box h3{font-size:22px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:15px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px;color:#fff}.share-modal .box .share-btn.whatsapp{background:#25D366}.share-modal .box .share-btn.facebook{background:#1877F2}.share-modal .box .share-btn.twitter{background:#000}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:16px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600}.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;font-size:14px;padding:4px 8px;border-radius:8px;opacity:.5}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;font-size:14px;padding:4px 8px;border-radius:8px;opacity:.4}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999;pointer-events:none}</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="mute-btn" id="muteBtn"><i class="fas fa-volume-up"></i></button><button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}<a href="/logout" class="btn btn-outline">تسجيل خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div><div class="dropdown" id="dropdown"><button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button><button class="item" onclick="window.location.href='/tools'"><i class="fas fa-tools"></i> 🧰 أدوات مجانية</button><button class="item" data-action="share"><i class="fas fa-share-alt"></i> مشاركة المحادثة</button>{% if session.get('user_email') and not session.get('is_admin') %}<button class="item" onclick="deleteMyAccount()" style="color: #ff4d4d;"><i class="fas fa-user-slash"></i> حذف حسابي</button>{% endif %}<button class="item" data-action="theme-toggle"><i class="fas fa-moon"></i> <span id="themeLabel">الوضع الليلي</span></button><div class="item" style="flex-direction:column;align-items:stretch;gap:6px;cursor:default;border-bottom:1px solid var(--border-color)"><div style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--text-primary)"><i class="fas fa-microphone" style="font-size:18px;color:var(--text-secondary)"></i><span>صوت المساعد</span></div><div style="display:flex;gap:8px"><button class="gender-option active" data-gender="male">👨 ذكر</button><button class="gender-option" data-gender="female">👩 أنثى</button></div></div><div id="historyList"></div></div><div id="chat"></div><div id="imagePreviewContainer"><img id="imagePreview" src=""/><span class="label">📎 صورة معلقة</span><button id="removeImageBtn">✕ إزالة</button></div><div class="input-area"><button class="btn-icon mic-btn" id="micBtn"><i class="fas fa-microphone"></i></button><button class="plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button><div class="plus-options" id="plusOptions"><button class="option-btn camera" id="cameraBtn"><i class="fas fa-camera"></i></button><button class="option-btn gallery" id="galleryBtn"><i class="fas fa-images"></i></button><button class="option-btn files" id="filesBtn"><i class="fas fa-folder"></i></button></div><textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea><button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button></div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/><input type="file" id="fileInputGeneric" style="display:none"/></div><div class="share-modal" id="shareModal"><div class="box"><h3><i class="fas fa-share-alt" style="color:var(--primary-color)"></i> شارك المحادثة</h3><div class="share-grid"><a href="#" id="shareWhatsapp" target="_blank" class="share-btn whatsapp"><i class="fab fa-whatsapp"></i> واتساب</a><a href="#" id="shareFacebook" target="_blank" class="share-btn facebook"><i class="fab fa-facebook"></i> فيسبوك</a><a href="#" id="shareTwitter" target="_blank" class="share-btn twitter"><i class="fab fa-x-twitter"></i> X</a><button id="shareSnapchat" class="share-btn snapchat"><i class="fab fa-snapchat"></i> سناب</button></div><button class="close-btn" onclick="document.getElementById('shareModal').classList.remove('show')">إلغاء</button></div></div><script>(function(){let ch=[],pid=null,iw=!1,cid=null,ca=null;const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),fib=document.getElementById('filesBtn'),fig=document.getElementById('fileInputGeneric'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),sm=document.getElementById('shareModal');let im=!0;const mut=document.getElementById('muteBtn');mut.querySelector('i').className='fas fa-volume-mute';mut.classList.add('muted');mut.addEventListener('click',function(){im=!im;const ic=mut.querySelector('i');if(im){ic.className='fas fa-volume-mute';mut.classList.add('muted');if(ca){ca.pause();ca.currentTime=0}}else{ic.className='fas fa-volume-up';mut.classList.remove('muted')}});

function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.7));canvas.width=0;canvas.height=0;img.src='';};img.src=ev.target.result;};reader.readAsDataURL(file);}

let isMale=!0;const gopts=document.querySelectorAll('.gender-option');mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();gopts.forEach(b=>b.classList.remove('active'));if(isMale)document.querySelector('.gender-option[data-gender="male"]').classList.add('active');else document.querySelector('.gender-option[data-gender="female"]').classList.add('active')}});gopts.forEach(b=>{b.addEventListener('click',function(e){e.stopPropagation();const g=this.dataset.gender;isMale=g==='male';gopts.forEach(x=>x.classList.remove('active'));this.classList.add('active');fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:g})});dd.classList.remove('show')})});async function loadHistory(){try{const r=await fetch('/history'),d=await r.json();hl.innerHTML='';if(d.conversations&&d.conversations.length>0){d.conversations.forEach(c=>{const b=document.createElement('button');b.className='conv-item';b.textContent=c.title;b.onclick=()=>loadConversation(c.id);hl.appendChild(b)})}else{const e=document.createElement('div');e.className='item';e.textContent='📭 لا توجد محادثات';hl.appendChild(e)}}catch(e){}}async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;
var recentMessages=d.messages.slice(-50);
recentMessages.forEach(function(m){const s=m.role==='user'?'user':'bot';addMessage(m.content,s,!0)});dd.classList.remove('show')}}catch(e){}}document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.style.display='none';ui.value=''});document.querySelector('[data-action="share"]').addEventListener('click',function(e){e.stopPropagation();if(!cid){alert('⚠️ لا توجد محادثة!');dd.classList.remove('show');return}const url=window.location.origin+'/share/'+cid,text=encodeURIComponent('اطلع على محادثتي:');document.getElementById('shareWhatsapp').href='https://api.whatsapp.com/send?text='+text+'%20'+encodeURIComponent(url);document.getElementById('shareFacebook').href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(url);document.getElementById('shareTwitter').href='https://twitter.com/intent/tweet?url='+encodeURIComponent(url)+'&text='+text;document.getElementById('shareSnapchat').onclick=function(ev){ev.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(()=>alert('✅ تم نسخ الرابط!')).catch(()=>alert('الرابط: '+url))}else alert('الرابط: '+url);sm.classList.remove('show')};sm.classList.add('show');dd.classList.remove('show')});sm.addEventListener('click',function(e){if(e.target===sm)sm.classList.remove('show')});const ttb=document.querySelector('[data-action="theme-toggle"]'),tl=document.getElementById('themeLabel');function setTheme(t){const h=document.documentElement;if(t==='dark'){h.classList.add('dark-mode');tl.textContent='الوضع الليلي';ttb.querySelector('i').className='fas fa-moon';localStorage.setItem('nibras-theme','dark')}else{h.classList.remove('dark-mode');tl.textContent='الوضع النهاري';ttb.querySelector('i').className='fas fa-sun';localStorage.setItem('nibras-theme','light')}}const st=localStorage.getItem('nibras-theme')||'light';setTheme(st);if(ttb){ttb.addEventListener('click',function(e){e.stopPropagation();const cur=document.documentElement.classList.contains('dark-mode')?'dark':'light';const nw=cur==='dark'?'light':'dark';setTheme(nw);dd.classList.remove('show')})}

function formatBotText(t){let s=String(t||'');let paragraphs=s.split(/\n\s*\n/);return paragraphs.map(p=>p.replace(/[\r\n]+/g,' ').trim()).filter(p=>p.length>0).join('<br><br>');}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>{t.style.animation='toastOut .3s forwards';setTimeout(()=>t.remove(),300)},1500);}

function addMessage(t,s,isSys,img,imageUrl){s=s||'bot';isSys=isSys||false;const el=document.createElement('div');el.className='msg '+s;if(s==='error')el.classList.add('error');const now=new Date(),tm=isSys?'':now.toLocaleTimeString('ar-SA',{hour:'2-digit',minute:'2-digit'});if(img){el.innerHTML='<img src="'+img+'" class="image-upload" />';cb.appendChild(el);cb.scrollTop=cb.scrollHeight;return el}const imatch=t.match(/(https?:\/\/[^\s]+\.(png|jpg|jpeg|gif|webp))/i);let dt=t,genUrl=null;if(imatch){genUrl=imatch[0];dt=t.replace(imatch[0],'').trim();if(!dt)dt='الصورة المولدة'}if(s==='bot'&&!isSys&&!genUrl&&!imageUrl){const wrapper=document.createElement('div');wrapper.className='content-wrapper';const textDiv=document.createElement('div');textDiv.className='content-text';textDiv.innerHTML='<span class="typing-text"></span>';const actions=document.createElement('div');actions.className='actions';const copyBtn=document.createElement('button');copyBtn.className='copy-btn';copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.addEventListener('click',function(e){e.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(dt).then(()=>{copyBtn.innerHTML='<i class="fas fa-check"></i>';copyBtn.classList.add('copied');showToast('تم النسخ!');setTimeout(()=>{copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.classList.remove('copied')},2000)}).catch(()=>{showToast('فشل النسخ')})}else{showToast('المتصفح لا يدعم النسخ')}});const shareBtn=document.createElement('button');shareBtn.className='copy-btn';shareBtn.innerHTML='<i class="fas fa-share-alt"></i>';shareBtn.addEventListener('click',function(e){e.stopPropagation();const url='https://api.whatsapp.com/send?text='+encodeURIComponent(dt);window.open(url,'_blank');});const delBtn=document.createElement('button');delBtn.className='del-msg-btn';delBtn.innerHTML='<i class="fas fa-trash-alt"></i>';delBtn.addEventListener('click',function(e){e.stopPropagation();deleteMessage(el)});actions.appendChild(copyBtn);actions.appendChild(shareBtn);actions.appendChild(delBtn);wrapper.appendChild(textDiv);wrapper.appendChild(actions);el.appendChild(wrapper);if(tm){const timeSpan=document.createElement('span');timeSpan.className='time';timeSpan.textContent=tm;el.appendChild(timeSpan)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;const ts=textDiv.querySelector('.typing-text');let idx=0,interacted=false;const onInteract=function(){interacted=true;cb.removeEventListener('touchstart',onInteract);cb.removeEventListener('scroll',onInteract)};cb.addEventListener('touchstart',onInteract);cb.addEventListener('scroll',onInteract);function typeChar(){if(idx<dt.length){ts.textContent+=dt.charAt(idx);idx++;if(!interacted)cb.scrollTop=cb.scrollHeight;setTimeout(typeChar,20)}else{ts.innerHTML=formatBotText(dt);cb.scrollTop=cb.scrollHeight}}typeChar();return el}let content=dt;if(s==='bot')content=formatBotText(dt);if(genUrl)content+='<br/><img src="'+genUrl+'" class="generated-image" />';if(imageUrl){if(imageUrl.match(/\.(mp4|webm|mov)$/i)||imageUrl.includes('video')){content+='<br><video controls class="generated-video" src="'+imageUrl+'"></video>';}else{content+='<br><img src="'+imageUrl+'" class="generated-image" />';}}const wrapper=document.createElement('div');wrapper.className='content-wrapper';const textDiv=document.createElement('div');textDiv.className='content-text';textDiv.innerHTML=content;wrapper.appendChild(textDiv);if(s==='bot'&&!isSys){const actions=document.createElement('div');actions.className='actions';const copyBtn=document.createElement('button');copyBtn.className='copy-btn';copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.addEventListener('click',function(e){e.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(dt).then(()=>{copyBtn.innerHTML='<i class="fas fa-check"></i>';copyBtn.classList.add('copied');showToast('تم النسخ!');setTimeout(()=>{copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.classList.remove('copied')},2000)}).catch(()=>{showToast('فشل النسخ')})}else{showToast('المتصفح لا يدعم النسخ')}});const shareBtn=document.createElement('button');shareBtn.className='copy-btn';shareBtn.innerHTML='<i class="fas fa-share-alt"></i>';shareBtn.addEventListener('click',function(e){e.stopPropagation();const url='https://api.whatsapp.com/send?text='+encodeURIComponent(dt);window.open(url,'_blank');});const delBtn=document.createElement('button');delBtn.className='del-msg-btn';delBtn.innerHTML='<i class="fas fa-trash-alt"></i>';delBtn.addEventListener('click',function(e){e.stopPropagation();deleteMessage(el)});actions.appendChild(copyBtn);actions.appendChild(shareBtn);actions.appendChild(delBtn);wrapper.appendChild(actions)}el.appendChild(wrapper);if(tm){const timeSpan=document.createElement('span');timeSpan.className='time';timeSpan.textContent=tm;el.appendChild(timeSpan)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;return el}

async function deleteMessage(el){if(!cid){showToast('لا توجد محادثة');return}if(!confirm('حذف هذه الرسالة؟'))return;try{const idx=Array.from(cb.children).indexOf(el);const r=await fetch('/delete_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conv_id:cid,index:idx})});const d=await r.json();if(d.status==='ok'){ch.splice(idx,1);el.remove();showToast('تم الحذف');}else{showToast('فشل: '+d.message);}}catch(e){showToast('خطأ في الاتصال')}}

function showWelcome(){if(!sessionStorage.getItem('welcomeShown')){const ov=document.createElement('div');ov.className='welcome-overlay';ov.innerHTML='<div class="welcome-box"><h2>👋 أهلاً بك في نبراس</h2><p>كيف نقدر نساعدك اليوم؟</p></div>';document.body.appendChild(ov);sessionStorage.setItem('welcomeShown','true');setTimeout(function(){if(document.body.contains(ov)){ov.classList.add('fade-out');setTimeout(function(){if(document.body.contains(ov))ov.remove()},500)}},5000);const rm=function(){if(document.body.contains(ov)){ov.classList.add('fade-out');setTimeout(function(){if(document.body.contains(ov))ov.remove()},500)}document.removeEventListener('click',rm);ui.removeEventListener('keydown',rm)};document.addEventListener('click',rm);ui.addEventListener('keydown',rm)}}

function showImagePreview(d){ip.src=d;ipc.style.display='flex'}
function clearPending(){pid=null;ipc.style.display='none';ip.src=''}
rib.addEventListener('click',clearPending);
ui.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,80)+'px'});
let poOpen=false;
pb.addEventListener('click',function(){poOpen=!poOpen;po.classList.toggle('show',poOpen);this.classList.toggle('rotate',poOpen)});
document.addEventListener('click',function(e){if(!pb.contains(e.target)&&!po.contains(e.target)){po.classList.remove('show');poOpen=false;pb.classList.remove('rotate')}});
gb.addEventListener('click',function(){fi.click();po.classList.remove('show')});
fi.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];fi.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
cab.addEventListener('click',function(){ci.click();po.classList.remove('show')});
ci.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];ci.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});
fib.addEventListener('click',function(){fig.click();po.classList.remove('show')});
fig.addEventListener('change',function(e){if(this.files&&this.files.length>0){var f=this.files[0];fig.value='';compressImage(f,800,function(dataUrl){pid=dataUrl;showImagePreview(pid);});}});

async function sendMessage(){if(iw)return;const t=ui.value.trim(),img=pid;if(!t&&!img)return;if(t)addMessage(t,'user');if(img){addMessage('صورة مرفقة','user',false,img);clearPending()}ui.value='';ui.style.height='auto';iw=true;const td=document.createElement('div');td.className='msg bot typing-indicator';td.innerHTML='<span class="typing-dots">جاري التفكير</span>';cb.appendChild(td);cb.scrollTop=cb.scrollHeight;const payload={message:t||"مرفق",image:img||null,history:ch,conv_id:cid};try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(td.parentNode)td.remove();if(r.ok){addMessage(d.reply,'bot',false,null,d.image_url);if(!im&&d.audio){if(ca){ca.pause();ca.currentTime=0;ca.src='';ca=null;}const src='data:audio/mp3;base64,'+d.audio;ca=new Audio(src);ca.onended=function(){if(ca){ca.src='';ca=null;}};ca.play()}if(d.conv_id)cid=d.conv_id}else addMessage('خطأ: '+(d.error||'مشكلة'),'error')}catch(e){if(td.parentNode)td.remove();addMessage('تعذر الاتصال بالسيرفر.','error')}finally{iw=false}}

sb.addEventListener('click',sendMessage);
ui.addEventListener('keypress',function(e){if(e.key==='Enter'){e.preventDefault();sendMessage()}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
let recog=null;
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage('المتصفح لا يدعم التعرف على الصوت.','bot',true);return}if(this.classList.contains('listening')){this.classList.remove('listening');if(recog)recog.stop();return}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang='ar-SA';this.classList.add('listening');addMessage('جاري الاستماع...','bot',true);recog.onresult=function(e){const tr=e.results[0][0].transcript;ui.value=tr;mb.classList.remove('listening');setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove('listening')};recog.start()});showWelcome()

window.deleteMyAccount=function(){
    if(!confirm('⚠️ تحذير: سيتم حذف حسابك بالكامل (الإيميل + كلمة المرور + كل المحادثات).\n\nهل أنت متأكد؟'))return;
    if(!confirm('🔴 تأكيد نهائي: هل أنت متأكد 100%؟ لا يمكن التراجع!'))return;
    fetch('/delete_my_account',{method:'POST',headers:{'Content-Type':'application/json'}})
        .then(r=>r.json()).then(d=>{
            if(d.status==='success'){alert('✅ تم حذف حسابك بالكامل. الوداع! 👋');window.location.href='/'}
            else{alert('❌ فشل: '+(d.message||'خطأ'))}
        }).catch(e=>{alert('❌ خطأ في الاتصال')});
};
})();</script></body></html>"""

# ==================== Routes ====================

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

        if e==ADMIN_EMAIL.lower():
            if not ap:return render_template_string(LH,error="لم يتم إعداد كلمة مرور الأدمن.")
            if secrets.compare_digest(p,ap):
                session.clear();session.permanent=True
                session['user_email']=e;session['is_admin']=True
                session['user_role']='admin'
                return redirect(url_for('index'))
            return render_template_string(LH,error="كلمة مرور الأدمن غير صحيحة.")

        try:
            r=requests.post(
                f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},
                json={"email":e,"password":p},
                timeout=15,
            )
        except Exception as ex:
            return render_template_string(LH,error="تعذر الاتصال بخدمة الدخول.")

        if r.status_code!=200:
            err_text = r.text.lower()
            if "email not confirmed" in err_text or "not confirmed" in err_text:
                return render_template_string(LH,error="⚠️ يجب تأكيد بريدك أولاً. افتح بريدك واضغط رابط التأكيد.")
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
    if not e or "@" not in e or len(p)<8:
        return render_template_string(LH,error="بريد صحيح وكلمة مرور 8 أحرف على الأقل مطلوبة.")
    try:
        redirect_url = f"{request.host_url.rstrip('/')}/verified"
        sb.auth.sign_up({
            "email": e,
            "password": p,
            "options": {"email_redirect_to": redirect_url}
        })
        return render_template_string(LH,success="✅ تم إنشاء حسابك! افتح بريدك واضغط رابط التأكيد.")
    except Exception as ex:
        err_msg = str(ex)
        if "39 seconds" in err_msg or "rate limit" in err_msg.lower():
            return render_template_string(LH,error="⏳ انتظر 60 ثانية ثم حاول مرة أخرى.")
        if "already" in err_msg.lower():
            return render_template_string(LH,error="هذا البريد مسجل مسبقاً. جرّب تسجيل الدخول.")
        return render_template_string(LH,error=f"فشل: {ex}")

@app.route('/verified')
def verified():
    return """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>تم التحقق - نبراس</title><style>*{font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:40px 30px;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;max-width:420px;text-align:center}.icon{font-size:60px;margin-bottom:20px}h2{font-size:24px;color:#1a2b3c;margin-bottom:15px}p{color:#5a6b7c;line-height:1.8;margin-bottom:20px}a{display:inline-block;background:#4a6a8a;color:#fff;padding:14px 32px;border-radius:12px;text-decoration:none;font-weight:700;font-size:16px}a:hover{background:#3a5a7a}.loading{color:#4a6a8a;font-size:14px;margin-top:15px}</style></head><body><div class="box" id="box"><div class="icon">⏳</div><h2>جاري التحقق...</h2><p class="loading">يتم تأكيد حسابك الآن</p></div>
<script>
(async function(){
    var box=document.getElementById('box');
    var SUPABASE_URL="__SUPABASE_URL__";
    var SUPABASE_KEY="__SUPABASE_KEY__";
    try{
        var accessToken=null,refreshToken=null,code=null;
        if(window.location.hash){
            var hp=new URLSearchParams(window.location.hash.substring(1));
            accessToken=hp.get('access_token');
            refreshToken=hp.get('refresh_token');
        }
        var urlParams=new URLSearchParams(window.location.search);
        if(!accessToken){
            code=urlParams.get('code');
            accessToken=urlParams.get('access_token');
            refreshToken=urlParams.get('refresh_token');
        }
        if(code){
            var resp=await fetch(SUPABASE_URL+'/auth/v1/token?grant_type=pkce',{
                method:'POST',
                headers:{'apikey':SUPABASE_KEY,'Content-Type':'application/json'},
                body:JSON.stringify({auth_code:code})
            });
            if(resp.ok){
                var d=await resp.json();
                accessToken=d.access_token;
            }
        }
        if(accessToken){
            await fetch(SUPABASE_URL+'/auth/v1/user',{
                headers:{'apikey':SUPABASE_KEY,'Authorization':'Bearer '+accessToken}
            });
        }
        box.innerHTML='<div class="icon">✅</div><h2>تم تأكيد حسابك!</h2><p>بريدك مؤكد. يمكنك تسجيل الدخول الآن.</p><a href="/login">تسجيل الدخول</a>';
    }catch(e){
        box.innerHTML='<div class="icon">✅</div><h2>تم تأكيد حسابك!</h2><p>يمكنك تسجيل الدخول الآن.</p><a href="/login">تسجيل الدخول</a>';
    }
})();
</script></div></body></html>""".replace("__SUPABASE_URL__",SUPABASE_URL or "").replace("__SUPABASE_KEY__",SUPABASE_KEY or "")

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
        r=requests.post(
            f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
            headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},
            json={"email":email,"password":password},
            timeout=15,
        )
        if r.status_code!=200:
            return jsonify({"status":"error","message":"البريد أو كلمة المرور غير صحيحة"}),401
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
        recent_r=(sb.table("assistant_chats").select("user_id,title,created_at").order("created_at",desc=True).limit(10).execute())
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

    return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>لوحة تحكم نبراس</title><style>body{{font-family:'Segoe UI',Tahoma;background:#0d1117;color:#c9d1d9;padding:20px;margin:0}}.container{{max-width:600px;margin:auto}}h1{{color:#58a6ff;text-align:center}}.card{{background:#161b22;border-radius:15px;padding:15px;margin:15px 0;border:1px solid #30363d}}.stat{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #21262d}}.stat:last-child{{border:none}}.num{{color:#58a6ff;font-weight:bold;font-size:18px}}.conv-item{{padding:10px 0;border-bottom:1px solid #21262d}}.conv-item small{{color:#8b949e;display:block;font-size:12px}}.back{{display:block;text-align:center;color:#58a6ff;text-decoration:none;margin-top:20px}}</style></head><body><div class="container"><h1>📊 لوحة تحكم نبراس</h1><div class="card"><div class="stat"><span>👥 المستخدمون النشطون</span><span class="num">{len(users_set)}</span></div><div class="stat"><span>💬 إجمالي المحادثات</span><span class="num">{total_convs}</span></div><div class="stat"><span>📅 آخر 10 (اليوم)</span><span class="num">{today_convs}</span></div></div><div class="card"><h3>🕒 آخر 10 محادثات</h3>{recent_html}</div><a href="/" class="back">⬅ الرئيسية</a></div></body></html>"""

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
        is_registered=is_admin or (bool(user_email) and user_role in ('user','admin'))
        uid=get_user_id()

        usage,limits,can_chat=check_limits(uid,user_role if not is_admin else 'admin')

        if not can_chat:
            reply_limit=f"وصلت للحد اليومي ({limits['chat']} محادثة) 😊\n\n💡 تواصل مع المطور للحصول على وصول أوسع."
            nid=save_message(uid,um,reply_limit,cid)
            return jsonify({"reply":reply_limit,"conv_id":nid,"audio":None})

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

        if has_image and not is_registered:
            reply="عذراً، تحليل الصور متاح للأعضاء المسجلين فقط.\n\n🔐 أنشئ حساباً للحصول عليها."
            nid=save_message(uid,um,reply,cid)
            return jsonify({"reply":reply,"conv_id":nid})

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

        try:
            rl="high" if is_registered else "low"
            r=client.chat.completions.create(model=OPENAI_MODEL,messages=msgs,max_completion_tokens=8000,reasoning_effort=rl)
            reply=r.choices[0].message.content.strip()
            if not reply:reply="ما قدرت أجيب رد."
        except Exception as e:
            print(f"❌ {e}")
            return jsonify({"error":str(e)}),500

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

        try:g=session.get('voice_gender','male');audio=generate_speech(reply,g)
        except Exception as e:print(f"⚠️ صوت: {e}");audio=None

        return jsonify({"reply":reply,"audio":audio,"conv_id":nid})
    except Exception as e:
        print(f"❌ {e}")
        return jsonify({"status":"error","message":str(e)}),500

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
