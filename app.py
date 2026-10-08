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

# ✅ الحدود: الضيف والمسجل كلاهما 15 محادثة، لكن المسجل عنده بحث وصور وذاكرة
LIMITS={
    "guest":  {"chat":15,  "search":0,   "image":0},
    "user":   {"chat":15,  "search":2,   "image":1},   # ← نفس الضيف + بحثين + صورة
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
        r=(sb.table("profiles").select("*").eq("email",email.lower().strip()).limit(1).execute())
        if r and r.data:
            return r.data[0]
    except Exception as e:
        print("get_user_profile:",e)
    return None

def save_user_profile(email, name=None, avatar=None):
    if not email: return
    try:
        data={"email":email.lower().strip()}
        if name is not None: data["display_name"]=name
        if avatar is not None: data["avatar_url"]=avatar
        sb.table("profiles").upsert(data, on_conflict="email").execute()
    except Exception as e:
        print("save_user_profile:",e)

def touch_user(email):
    if not email: return
    try:
        sb.table("profiles").update({"last_seen":datetime.utcnow().isoformat()}).eq("email",email.lower().strip()).execute()
    except Exception as e:
        print("touch_user:",e)

def get_user_memory(email):
    if not email: return {}
    try:
        r=(sb.table("profiles").select("memory").eq("email",email.lower().strip()).limit(1).execute())
        if r and r.data and r.data[0].get("memory"):
            return r.data[0]["memory"] or {}
    except Exception as e:
        print("get_user_memory:",e)
    return {}

def save_user_memory(email, memory_dict):
    if not email: return
    try:
        sb.table("profiles").update({"memory":memory_dict}).eq("email",email.lower().strip()).execute()
    except Exception as e:
        print("save_user_memory:",e)

def get_recent_summaries(uid, limit=5):
    try:
        r=(sb.table("assistant_chats")
             .select("conv_id,summary,title,created_at")
             .eq("user_id",uid)
             .not_.is_("summary","null")
             .order("created_at",desc=True)
             .limit(50)
             .execute())
        rows=r.data or []
    except Exception as e:
        print("get_recent_summaries:",e)
        return []
    seen={}
    for row in rows:
        cid=row.get("conv_id")
        if cid and cid not in seen and row.get("summary"):
            seen[cid]={"conv_id":cid,"summary":row["summary"],"title":row.get("title")}
        if len(seen)>=limit:
            break
    return list(seen.values())

def summarize_old_conversation(uid, cid):
    if not cid: return
    try:
        existing=(sb.table("assistant_chats").select("summary").eq("user_id",uid).eq("conv_id",cid).limit(1).execute())
        if existing and existing.data and existing.data[0].get("summary"):
            return
        msgs=load_conversation(uid,cid)
        if not msgs or len(msgs)<2: return
        convo_text=""
        for m in msgs[:20]:
            role="المستخدم" if m["role"]=="user" else "نبراس"
            convo_text+=f"{role}: {m['content'][:300]}\n"
        try:
            r=client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role":"system","content":"لخّص المحادثة التالية في 2-3 جمل قصيرة بالعربية. ركّز على: اسم المستخدم إن ذُكر، المواضيع التي تحدثوا عنها، أي معلومة شخصية ذكرها. اكتب بصيغة الغائب عن 'المستخدم'."},
                    {"role":"user","content":convo_text}
                ],
                max_completion_tokens=300
            )
            summary=r.choices[0].message.content.strip()
        except Exception as e:
            print("summarize generation:",e)
            return
        if not summary: return
        sb.table("assistant_chats").update({"summary":summary}).eq("user_id",uid).eq("conv_id",cid).execute()
        print(f"✅ تم تلخيص المحادثة {cid}: {summary[:80]}...")
    except Exception as e:
        print("summarize_old_conversation:",e)

def get_user_id():
    """✅ يرجع UID ثابت لكل مستخدم مسجل، و UID مؤقت للضيف (محفوظ في الجلسة)"""
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
    can_search=int(usage.get("search_count",0) or 0)<limits["search"]
    can_image=int(usage.get("image_count",0) or 0)<limits["image"]
    return usage,limits,can_chat,can_search,can_image

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
            title=(row.get("title") or "").strip() or "محادثة"
            seen[cid]={"id":cid,"conv_id":cid,"title":title,"timestamp":row.get("created_at")}
    return list(seen.values())

def save_message(uid,msg,resp,cid=None):
    if not cid:cid=secrets.token_hex(5)
    try:
        ex=(sb.table("assistant_chats").select("id").eq("user_id",uid).eq("conv_id",cid).limit(1).execute())
        has_prev=bool(ex.data)
        title=None
        if not has_prev:
            clean_msg=(msg or "").strip()
            clean_msg=re.sub(r'[^\w\s\u0600-\u06FF]','',clean_msg).strip()
            if clean_msg:
                title=clean_msg[:30]
                if len(clean_msg)>30:title+="..."
            else:
                title="محادثة جديدة"
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

SPH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>محادثة نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;word-wrap:break-word}.msg.user .content{background:#eaeef2}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}</style></head><body><div class="container"><div class="header"><h1>{{ title or 'محادثة نبراس' }}</h1><a href="/">الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class="content">{{ msg.content|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a></div></div></body></html>"""

LIBRARY_HTML="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>مكتبتي - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;min-height:100dvh;color:#1a2b3c;padding:20px}.container{max-width:1000px;margin:0 auto}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;flex-wrap:wrap;gap:12px}.topbar h1{font-size:24px;color:#1a2b3c;display:flex;align-items:center;gap:10px}.topbar a{color:#4a6a8a;text-decoration:none;font-weight:600;padding:10px 18px;border:1.5px solid #4a6a8a;border-radius:12px;transition:all .2s}.topbar a:hover{background:#4a6a8a;color:#fff}.upload-zone{background:#fff;border:2px dashed #dce1e8;border-radius:20px;padding:40px 20px;text-align:center;margin-bottom:24px;transition:all .25s;cursor:pointer}.upload-zone:hover,.upload-zone.dragover{border-color:#4a6a8a;background:#f5f9ff}.upload-zone svg{width:48px;height:48px;stroke:#4a6a8a;stroke-width:1.5;fill:none;margin-bottom:12px}.upload-zone h3{font-size:17px;color:#1a2b3c;margin-bottom:6px}.upload-zone p{color:#8b949e;font-size:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}.img-card{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.06);position:relative;transition:transform .2s,box-shadow .2s}.img-card:hover{transform:translateY(-3px);box-shadow:0 8px 24px rgba(0,0,0,0.12)}.img-card .preview{width:100%;height:180px;object-fit:cover;display:block;background:#f5f7fa}.img-card .info{padding:10px 14px}.img-card .info .title{font-size:14px;font-weight:600;color:#1a2b3c;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.img-card .info .source{font-size:11px;color:#8b949e;margin-top:2px}.img-card .delete-btn{position:absolute;top:8px;left:8px;background:rgba(255,255,255,0.95);border:none;width:34px;height:34px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px rgba(0,0,0,0.15);transition:all .2s}.img-card .delete-btn:hover{background:#ff4757}.img-card .delete-btn:hover svg{stroke:#fff}.img-card .delete-btn svg{width:16px;height:16px;stroke:#ff4757;stroke-width:2;fill:none}.empty{text-align:center;padding:60px 20px;color:#8b949e}.empty svg{width:64px;height:64px;stroke:#dce1e8;stroke-width:1.5;fill:none;margin-bottom:16px}.empty h3{color:#5a6b7c;font-size:18px;margin-bottom:6px}.empty p{font-size:14px}.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.85);color:#fff;padding:12px 24px;border-radius:30px;font-size:14px;z-index:9999}@media(max-width:520px){.topbar h1{font-size:20px}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}.img-card .preview{height:150px}}</style></head><body><div class="container"><div class="topbar"><h1><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#4a6a8a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</h1><a href="/">الرئيسية</a></div><div class="upload-zone" id="uploadZone"><svg viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg><h3>ارفع صورة جديدة</h3><p>اضغط أو اسحب الصورة هنا</p></div><input type="file" id="fileInput" accept="image/*" style="display:none" multiple><div id="grid" class="grid"><div style="text-align:center;padding:30px;color:#8b949e;grid-column:1/-1">جاري التحميل...</div></div></div><script>
const zone=document.getElementById('uploadZone');const fi=document.getElementById('fileInput');const grid=document.getElementById('grid');
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),2500);}
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
async function loadImages(){try{const r=await fetch('/library/images');const d=await r.json();grid.innerHTML='';if(!d.images||d.images.length===0){grid.innerHTML='<div class="empty" style="grid-column:1/-1"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg><h3>مكتبتك فاضية</h3><p>ارفع أول صورة</p></div>';return;}d.images.forEach(img=>{const src=img.image_data||img.image_url;const card=document.createElement('div');card.className='img-card';card.innerHTML='<img class="preview" src="'+src+'" loading="lazy"/><button class="delete-btn" title="حذف"><svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg></button><div class="info"><div class="title">'+(img.title||'صورة')+'</div><div class="source">'+(img.source==='generated'?'مولدة':'مرفوعة')+'</div></div>';card.querySelector('.delete-btn').onclick=async(e)=>{e.stopPropagation();if(!confirm('حذف هذه الصورة؟'))return;const r=await fetch('/library/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:img.id})});const res=await r.json();if(res.status==='ok'){card.remove();showToast('تم الحذف');if(grid.children.length===0)loadImages();}else showToast('فشل الحذف');};grid.appendChild(card);});}catch(e){grid.innerHTML='<div class="empty" style="grid-column:1/-1"><h3>خطأ</h3><p>تعذر تحميل الصور</p></div>';}}
async function uploadFiles(files){for(const file of files){if(!file.type.startsWith('image/'))continue;await new Promise(res=>{compressImage(file,1000,async(dataUrl)=>{try{const r=await fetch('/library/upload',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_data:dataUrl,title:file.name})});const d=await r.json();if(d.status==='ok')showToast('تم رفع الصورة');else showToast('فشل الرفع');}catch(e){showToast('خطأ في الاتصال');}res();});});}loadImages();}
zone.onclick=()=>fi.click();fi.onchange=(e)=>{if(e.target.files.length>0)uploadFiles(e.target.files);fi.value='';};zone.ondragover=(e)=>{e.preventDefault();zone.classList.add('dragover');};zone.ondragleave=()=>zone.classList.remove('dragover');zone.ondrop=(e)=>{e.preventDefault();zone.classList.remove('dragover');uploadFiles(e.dataTransfer.files);};loadImages();
</script></body></html>"""

LH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:20px}.box{background:#fff;padding:44px 32px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.logo{width:64px;height:64px;background:#4a6a8a;border-radius:20px;display:flex;align-items:center;justify-content:center;margin:0 auto 18px;color:#fff;font-size:26px;font-weight:700}h2{font-size:24px;color:#1a2b3c;margin-bottom:8px;font-weight:700}.subtitle{color:#8b949e;font-size:14px;margin-bottom:28px}.tabs{display:flex;justify-content:center;gap:26px;border-bottom:1px solid #eaeef2;margin-bottom:26px}.tabs button{background:0 0;border:none;padding:12px 0;font-size:15px;font-weight:600;color:#8b949e;cursor:pointer;position:relative;font-family:inherit;transition:color .2s}.tabs button.active{color:#4a6a8a}.tabs button.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:2px;background:#4a6a8a;border-radius:2px}.section{display:none}.section.active{display:block}.field{margin:12px 0}.field input{width:100%;padding:15px 18px;border:1.5px solid #e5e9ef;border-radius:14px;font-size:15px;background:#fafbfc;box-sizing:border-box;font-family:inherit;transition:all .2s;color:#1a2b3c}.field input:focus{outline:0;border-color:#4a6a8a;background:#fff;box-shadow:0 0 0 4px rgba(74,106,138,0.1)}.field input::placeholder{color:#a5b0be}button.submit{width:100%;padding:15px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;margin-top:16px;font-family:inherit;transition:all .2s}button.submit:hover{background:#3a5a7a}button.submit:active{transform:scale(0.98)}a{color:#4a6a8a;text-decoration:none;font-size:14px;display:inline-block;margin-top:18px;font-weight:600}a:hover{color:#3a5a7a}.error{color:#d63031;background:#ffe8e8;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.success{color:#00b894;background:#e6fff5;padding:13px 16px;border-radius:12px;margin-bottom:18px;font-size:14px;font-weight:600;text-align:right}.divider{margin:22px 0 0;padding-top:18px;border-top:1px solid #eef1f6}.privacy-link{font-size:12px;color:#a5b0be;margin-top:6px;text-decoration:underline;font-weight:500}@media(max-width:420px){.box{padding:34px 24px}h2{font-size:22px}}</style></head><body><div class="box"><div class="logo">🔐</div><h2>نبراس</h2><p class="subtitle">مساعدك الذكي الشخصي</p>{% if error %}<div class="error">{{ error }}</div>{% endif %}{% if success %}<div class="success">{{ success }}</div>{% endif %}<div class="tabs"><button type="button" class="tab-btn active" data-tab="login">دخول</button><button type="button" class="tab-btn" data-tab="signup">حساب جديد</button><button type="button" class="tab-btn" data-tab="recover">استعادة</button></div><div class="section active" id="tab-login"><form method="POST" action="/login"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور" required></div><button type="submit" class="submit">تسجيل الدخول</button></form></div><div class="section" id="tab-signup"><form method="POST" action="/signup"><div class="field"><input type="text" name="name" placeholder="الاسم الكامل" required minlength="2"></div><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><div class="field"><input type="password" name="password" placeholder="كلمة المرور (8 أحرف +)" minlength="8" required></div><button type="submit" class="submit">إنشاء حساب جديد</button></form></div><div class="section" id="tab-recover"><form method="POST" action="/recover"><div class="field"><input type="email" name="email" placeholder="البريد الإلكتروني" required></div><button type="submit" class="submit">إرسال رابط الاستعادة</button></form></div><div class="divider"><a href="/">العودة للرئيسية</a><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" class="privacy-link">سياسة الخصوصية</a></div></div><script>document.querySelectorAll('.tab-btn').forEach(function(b){b.addEventListener('click',function(){document.querySelectorAll('.tab-btn').forEach(x=>x.classList.remove('active'));document.querySelectorAll('.section').forEach(x=>x.classList.remove('active'));this.classList.add('active');document.getElementById('tab-'+this.dataset.tab).classList.add('active')})});</script></body></html>"""

HT=r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><title>نبراس GP | مساعد ذكي</title><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--border-input:#dce1e8;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--modal-bg:rgba(0,0,0,0.5)}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#58a6ff;--border-input:#30363d;--send-bg:#238636;--send-hover:#2ea043;--modal-bg:rgba(0,0,0,0.7)}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-color);flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s,opacity .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.icon-btn.voice-on{color:var(--primary-color);opacity:1}.icon-btn.voice-off{color:var(--primary-color);opacity:0.85}.btn-group{display:flex;gap:8px;align-items:center}.btn{padding:7px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center;font-family:inherit;font-weight:600}.btn-outline{background:0 0;border:1.5px solid var(--primary-color);color:var(--primary-color);transition:all .2s}.btn-outline:hover{background:var(--primary-color);color:#fff}.user-badge{display:flex;align-items:center;gap:6px;background:var(--bg-hover);padding:6px 12px;border-radius:20px;font-size:13px;color:var(--text-primary);font-weight:600;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.user-badge svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}.dropdown{position:absolute;top:64px;left:14px;right:14px;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 8px 30px var(--shadow-color);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:60vh;overflow-y:auto}.dropdown.show{display:flex}.dropdown .item{display:flex;align-items:center;gap:12px;padding:14px 18px;font-size:15px;color:var(--text-primary);background:0 0;border:none;width:100%;text-align:right;cursor:pointer;border-bottom:1px solid var(--border-color);font-family:inherit;font-weight:500}.dropdown .item:last-child{border-bottom:none}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-secondary);stroke-width:2;fill:none;flex-shrink:0}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .conv-item{display:block;padding:12px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;width:100%;background:0 0;border:none;text-align:right;font-size:15px;color:var(--text-primary);font-weight:500;font-family:inherit}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .item.danger{color:#ff4d4d}.dropdown .item.danger svg{stroke:#ff4d4d}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:16px;min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:16px;font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--bg-user-msg);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.5;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.msg .generated-video{max-width:100%;border-radius:12px;margin:8px 0}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;font-size:16px;color:var(--text-secondary)}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}#imagePreviewContainer{display:none;padding:6px 18px;align-items:center;gap:10px;background:var(--bg-input);margin:0 14px;border-radius:20px 20px 0 0;border:1px solid var(--border-color);border-bottom:none;flex-wrap:wrap;flex-shrink:0}#imagePreviewContainer img{max-height:60px;border-radius:8px;border:1px solid var(--border-color)}#imagePreviewContainer .label{font-size:13px;color:var(--text-secondary)}#removeImageBtn{background:0 0;border:none;color:var(--danger-color);font-size:13px;cursor:pointer;padding:4px 10px;border-radius:10px;font-family:inherit;font-weight:600}.input-area{display:flex;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:40px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:16px;font-weight:500;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow:hidden;min-height:22px;max-height:80px;font-family:inherit;line-height:1.4}.input-area textarea::placeholder{color:var(--placeholder-color)}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}.input-area .btn-icon:hover{background:var(--bg-hover)}.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.input-area .mic-btn{color:var(--primary-color)}.input-area .mic-btn.listening{color:#c33;background:#fde8e8}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 14px rgba(74,106,138,0.35);transition:background .2s,transform .15s}.input-area .send:hover{background:var(--send-hover);transform:scale(1.05)}.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .3s}.plus-btn:hover{background:var(--bg-hover)}.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}.plus-options .option-btn:hover{background:var(--border-color)}.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.gender-option{flex:1;padding:8px 4px;border-radius:10px;border:1px solid var(--border-color);background:0 0;font-size:13px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:4px;font-family:inherit}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color)}.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color)}.share-modal .box h3{font-size:20px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:14px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px;color:#fff;font-family:inherit}.share-modal .box .share-btn.whatsapp{background:#25D366}.share-modal .box .share-btn.facebook{background:#1877F2}.share-modal .box .share-btn.twitter{background:#000}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:15px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600;font-family:inherit}.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center;transition:opacity .2s}.copy-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center}.msg .actions .del-msg-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px}.input-area .btn-icon{width:32px;height:32px}.plus-btn{width:32px;height:32px}}</style></head><body>
<div class="app"><div class="header"><div class="header-right"><button class="icon-btn voice-off" id="voiceToggle" title="تشغيل/إيقاف الصوت"><svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg></button><button class="icon-btn" id="menuToggle" title="القائمة"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg></button></div><div class="header-left"><div class="btn-group">{% if session.get('user_email') or session.get('is_admin') %}{% if user_name %}<div class="user-badge" title="{{ session.get('user_email') }}"><svg viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>{{ user_name }}</div>{% endif %}<a href="/logout" class="btn btn-outline">خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div><div class="dropdown" id="dropdown"><button class="item" data-action="new"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> محادثة جديدة</button><button class="item" onclick="window.location.href='/library'"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg> مكتبتي</button><button class="item" data-action="share"><svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg> مشاركة المحادثة</button>{% if session.get('user_email') and not session.get('is_admin') %}<button class="item danger" onclick="deleteMyAccount()"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="17" y1="8" x2="22" y2="13"/><line x1="22" y1="8" x2="17" y2="13"/></svg> حذف حسابي</button>{% endif %}<button class="item" data-action="theme-toggle"><svg id="themeIcon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg> <span id="themeLabel">الوضع الليلي</span></button><div class="item" style="flex-direction:column;align-items:stretch;gap:8px;cursor:default;border-bottom:1px solid var(--border-color)"><div style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--text-primary)"><svg viewBox="0 0 24 24" style="width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/></svg><span>صوت المساعد</span></div><div style="display:flex;gap:8px"><button class="gender-option active" data-gender="male">ذكر</button><button class="gender-option" data-gender="female">أنثى</button></div></div><div id="historyList"></div></div><div id="chat"></div><div id="imagePreviewContainer"><img id="imagePreview" src=""/><span class="label">صورة معلقة</span><button id="removeImageBtn">إزالة</button></div><div class="input-area"><button class="btn-icon mic-btn" id="micBtn" title="صوت"><svg viewBox="0 0 24 24"><path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="8" y1="22" x2="16" y2="22"/></svg></button><button class="plus-btn" id="plusBtn" title="إضافة"><svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></button><div class="plus-options" id="plusOptions"><button class="option-btn" id="cameraBtn" title="كاميرا"><svg viewBox="0 0 24 24"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg></button><button class="option-btn" id="galleryBtn" title="صور"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg></button></div><textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea><button class="send" id="sendBtn" title="إرسال"><svg viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg></button></div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/></div><div class="share-modal" id="shareModal"><div class="box"><h3>شارك المحادثة</h3><div class="share-grid"><a href="#" id="shareWhatsapp" target="_blank" class="share-btn whatsapp">واتساب</a><a href="#" id="shareFacebook" target="_blank" class="share-btn facebook">فيسبوك</a><a href="#" id="shareTwitter" target="_blank" class="share-btn twitter">X</a><button id="shareSnapchat" class="share-btn snapchat">سناب</button></div><button class="close-btn" onclick="document.getElementById('shareModal').classList.remove('show')">إلغاء</button></div></div><script>(function(){let ch=[],pid=null,iw=!1,cid=null,ca=null,voiceOn=false;const cb=document.getElementById('chat'),ui=document.getElementById('userInput'),sb=document.getElementById('sendBtn'),mb=document.getElementById('micBtn'),fi=document.getElementById('fileInput'),ci=document.getElementById('cameraInput'),mt=document.getElementById('menuToggle'),dd=document.getElementById('dropdown'),pb=document.getElementById('plusBtn'),po=document.getElementById('plusOptions'),cab=document.getElementById('cameraBtn'),gb=document.getElementById('galleryBtn'),ipc=document.getElementById('imagePreviewContainer'),ip=document.getElementById('imagePreview'),rib=document.getElementById('removeImageBtn'),hl=document.getElementById('historyList'),sm=document.getElementById('shareModal'),vt=document.getElementById('voiceToggle');
const SVG_SPK_ON='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>';
const SVG_SPK_OFF='<svg viewBox="0 0 24 24"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/></svg>';
vt.addEventListener('click',function(){voiceOn=!voiceOn;if(voiceOn){vt.classList.remove('voice-off');vt.classList.add('voice-on');vt.innerHTML=SVG_SPK_ON;showToast('الصوت مفعّل');}else{vt.classList.remove('voice-on');vt.classList.add('voice-off');vt.innerHTML=SVG_SPK_OFF;if(ca){ca.pause();ca.currentTime=0;ca=null;}showToast('الصوت مغلق');}});
function compressImage(file,maxWidth,callback){var reader=new FileReader();reader.onload=function(ev){var img=new Image();img.onload=function(){var canvas=document.createElement('canvas');var ratio=Math.min(maxWidth/img.width,maxWidth/img.height,1);canvas.width=img.width*ratio;canvas.height=img.height*ratio;var ctx=canvas.getContext('2d');ctx.drawImage(img,0,0,canvas.width,canvas.height);callback(canvas.toDataURL('image/jpeg',0.75));};img.src=ev.target.result;};reader.readAsDataURL(file);}
let isMale=!0;const gopts=document.querySelectorAll('.gender-option');mt.addEventListener('click',function(e){e.stopPropagation();dd.classList.toggle('show');if(dd.classList.contains('show')){loadHistory();gopts.forEach(b=>b.classList.remove('active'));if(isMale)document.querySelector('.gender-option[data-gender="male"]').classList.add('active');else document.querySelector('.gender-option[data-gender="female"]').classList.add('active')}});gopts.forEach(b=>{b.addEventListener('click',function(e){e.stopPropagation();const g=this.dataset.gender;isMale=g==='male';gopts.forEach(x=>x.classList.remove('active'));this.classList.add('active');fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:g})});dd.classList.remove('show')})});
async function loadHistory(){
    try{
        const r = await fetch('/history');
        const d = await r.json();
        hl.innerHTML = '';
        if(d.conversations && d.conversations.length > 0){
            d.conversations.forEach(c => {
                const b = document.createElement('button');
                b.className = 'conv-item';
                b.textContent = (c.title && c.title.trim()) ? c.title : 'محادثة';
                b.onclick = () => loadConversation(c.id);
                hl.appendChild(b);
            });
        } else {
            const e = document.createElement('div');
            e.className = 'item';
            e.textContent = 'لا توجد محادثات';
            hl.appendChild(e);
        }
    } catch(e){ console.error('loadHistory:', e); }
}
async function loadConversation(id){try{const r=await fetch('/load_conversation/'+id),d=await r.json();if(d.messages){cb.innerHTML='';ch=d.messages;cid=id;d.messages.slice(-50).forEach(function(m){const s=m.role==='user'?'user':'bot';addMessage(m.content,s,!0)});dd.classList.remove('show')}}catch(e){}}document.querySelector('[data-action="new"]').addEventListener('click',function(){cb.innerHTML='';ch=[];cid=null;dd.classList.remove('show');pid=null;ipc.style.display='none';ui.value=''});document.querySelector('[data-action="share"]').addEventListener('click',function(e){e.stopPropagation();if(!cid){alert('لا توجد محادثة!');dd.classList.remove('show');return}const url=window.location.origin+'/share/'+cid,text=encodeURIComponent('اطلع على محادثتي:');document.getElementById('shareWhatsapp').href='https://api.whatsapp.com/send?text='+text+'%20'+encodeURIComponent(url);document.getElementById('shareFacebook').href='https://www.facebook.com/sharer/sharer.php?u='+encodeURIComponent(url);document.getElementById('shareTwitter').href='https://twitter.com/intent/tweet?url='+encodeURIComponent(url)+'&text='+text;document.getElementById('shareSnapchat').onclick=function(ev){ev.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(()=>alert('تم نسخ الرابط!')).catch(()=>alert('الرابط: '+url))}else alert('الرابط: '+url);sm.classList.remove('show')};sm.classList.add('show');dd.classList.remove('show')});sm.addEventListener('click',function(e){if(e.target===sm)sm.classList.remove('show')});const ttb=document.querySelector('[data-action="theme-toggle"]'),tl=document.getElementById('themeLabel'),ti=document.getElementById('themeIcon');function setTheme(t){const h=document.documentElement;if(t==='dark'){h.classList.add('dark-mode');tl.textContent='الوضع النهاري';ti.innerHTML='<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';localStorage.setItem('nibras-theme','dark')}else{h.classList.remove('dark-mode');tl.textContent='الوضع الليلي';ti.innerHTML='<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';localStorage.setItem('nibras-theme','light')}}setTheme(localStorage.getItem('nibras-theme')||'light');if(ttb){ttb.addEventListener('click',function(e){e.stopPropagation();const cur=document.documentElement.classList.contains('dark-mode')?'dark':'light';setTheme(cur==='dark'?'light':'dark');dd.classList.remove('show')})}
function formatBotText(t){let s=String(t||'');let paragraphs=s.split(/\n\s*\n/);return paragraphs.map(p=>p.replace(/[\r\n]+/g,' ').trim()).filter(p=>p.length>0).join('<br><br>');}
function showToast(msg){const old=document.querySelector('.toast');if(old)old.remove();const t=document.createElement('div');t.className='toast';t.textContent=msg;document.body.appendChild(t);setTimeout(()=>t.remove(),1500);}
const SVG_COPY='<svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
const SVG_CHECK='<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>';
const SVG_SHARE='<svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/></svg>';
const SVG_TRASH='<svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg>';
function buildActions(dt,el){const actions=document.createElement('div');actions.className='actions';const copyBtn=document.createElement('button');copyBtn.className='copy-btn';copyBtn.innerHTML=SVG_COPY;copyBtn.addEventListener('click',function(e){e.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(dt).then(()=>{copyBtn.innerHTML=SVG_CHECK;copyBtn.classList.add('copied');showToast('تم النسخ');setTimeout(()=>{copyBtn.innerHTML=SVG_COPY;copyBtn.classList.remove('copied')},2000)})}});const shareBtn=document.createElement('button');shareBtn.className='copy-btn';shareBtn.innerHTML=SVG_SHARE;shareBtn.addEventListener('click',function(e){e.stopPropagation();window.open('https://api.whatsapp.com/send?text='+encodeURIComponent(dt),'_blank');});const delBtn=document.createElement('button');delBtn.className='del-msg-btn';delBtn.innerHTML=SVG_TRASH;delBtn.addEventListener('click',function(e){e.stopPropagation();deleteMessage(el)});actions.appendChild(copyBtn);actions.appendChild(shareBtn);actions.appendChild(delBtn);return actions;}
function addMessage(t,s,isSys,img,imageUrl){s=s||'bot';isSys=isSys||false;const el=document.createElement('div');el.className='msg '+s;if(s==='error')el.classList.add('error');const now=new Date(),tm=isSys?'':now.toLocaleTimeString('ar-SA',{hour:'2-digit',minute:'2-digit'});if(img){el.innerHTML='<img src="'+img+'" class="image-upload" />';cb.appendChild(el);cb.scrollTop=cb.scrollHeight;return el}const imatch=t.match(/(https?:\/\/[^\s]+\.(png|jpg|jpeg|gif|webp))/i);let dt=t,genUrl=null;if(imatch){genUrl=imatch[0];dt=t.replace(imatch[0],'').trim();if(!dt)dt='الصورة المولدة'}if(s==='bot'&&!isSys&&!genUrl&&!imageUrl){const wrapper=document.createElement('div');wrapper.className='content-wrapper';const textDiv=document.createElement('div');textDiv.className='content-text';textDiv.innerHTML='<span class="typing-text"></span>';const actions=buildActions(dt,el);wrapper.appendChild(textDiv);wrapper.appendChild(actions);el.appendChild(wrapper);if(tm){const timeSpan=document.createElement('span');timeSpan.className='time';timeSpan.textContent=tm;el.appendChild(timeSpan)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;const ts=textDiv.querySelector('.typing-text');let idx=0,interacted=false;const onInteract=function(){interacted=true;cb.removeEventListener('touchstart',onInteract);cb.removeEventListener('scroll',onInteract)};cb.addEventListener('touchstart',onInteract);cb.addEventListener('scroll',onInteract);function typeChar(){if(idx<dt.length){ts.textContent+=dt.charAt(idx);idx++;if(!interacted)cb.scrollTop=cb.scrollHeight;setTimeout(typeChar,20)}else{ts.innerHTML=formatBotText(dt);cb.scrollTop=cb.scrollHeight}}typeChar();return el}let content=dt;if(s==='bot')content=formatBotText(dt);if(genUrl)content+='<br/><img src="'+genUrl+'" class="generated-image" />';if(imageUrl){if(imageUrl.match(/\.(mp4|webm|mov)$/i)||imageUrl.includes('video')){content+='<br><video controls class="generated-video" src="'+imageUrl+'"></video>';}else{content+='<br><img src="'+imageUrl+'" class="generated-image" />';}}const wrapper=document.createElement('div');wrapper.className='content-wrapper';const textDiv=document.createElement('div');textDiv.className='content-text';textDiv.innerHTML=content;wrapper.appendChild(textDiv);if(s==='bot'&&!isSys){wrapper.appendChild(buildActions(dt,el))}el.appendChild(wrapper);if(tm){const timeSpan=document.createElement('span');timeSpan.className='time';timeSpan.textContent=tm;el.appendChild(timeSpan)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;return el}
async function deleteMessage(el){if(!cid){showToast('لا توجد محادثة');return}if(!confirm('حذف هذه الرسالة؟'))return;try{const idx=Array.from(cb.children).indexOf(el);const r=await fetch('/delete_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({conv_id:cid,index:idx})});const d=await r.json();if(d.status==='ok'){ch.splice(idx,1);el.remove();showToast('تم الحذف');}else{showToast('فشل الحذف')}}catch(e){showToast('خطأ في الاتصال')}}
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
async function sendMessage(){if(iw)return;const t=ui.value.trim(),img=pid;if(!t&&!img)return;if(t)addMessage(t,'user');if(img){addMessage('صورة مرفقة','user',false,img);clearPending()}ui.value='';ui.style.height='auto';iw=true;const td=document.createElement('div');td.className='msg bot typing-indicator';td.innerHTML='<span class="typing-dots">جاري التفكير</span>';cb.appendChild(td);cb.scrollTop=cb.scrollHeight;const payload={message:t||"مرفق",image:img||null,history:ch,conv_id:cid};try{const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),d=await r.json();if(td.parentNode)td.remove();if(r.ok){addMessage(d.reply,'bot',false,null,d.image_url);if(d.conv_id)cid=d.conv_id;if(voiceOn&&d.reply&&!d.image_url&&d.reply.length<1500){fetch('/voice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:d.reply})}).then(r=>r.json()).then(v=>{if(v.audio){if(ca){ca.pause();ca.currentTime=0;}const src='data:audio/mp3;base64,'+v.audio;ca=new Audio(src);ca.onended=function(){ca=null;};ca.play();}}).catch(()=>{});}}else addMessage('خطأ: '+(d.error||'مشكلة'),'error')}catch(e){if(td.parentNode)td.remove();addMessage('تعذر الاتصال بالسيرفر.','error')}finally{iw=false}}
sb.addEventListener('click',sendMessage);
ui.addEventListener('keypress',function(e){if(e.key==='Enter'){e.preventDefault();sendMessage()}});
document.addEventListener('click',function(e){if(!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove('show')});
let recog=null;
mb.addEventListener('click',function(){if(!('webkitSpeechRecognition' in window)){addMessage('المتصفح لا يدعم التعرف على الصوت.','bot',true);return}if(this.classList.contains('listening')){this.classList.remove('listening');if(recog)recog.stop();return}const SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang='ar-SA';this.classList.add('listening');addMessage('جاري الاستماع...','bot',true);recog.onresult=function(e){const tr=e.results[0][0].transcript;ui.value=tr;mb.classList.remove('listening');setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove('listening')};recog.start()});
window.deleteMyAccount=function(){if(!confirm('تحذير: سيتم حذف حسابك بالكامل. متأكد؟'))return;if(!confirm('تأكيد نهائي؟'))return;fetch('/delete_my_account',{method:'POST',headers:{'Content-Type':'application/json'}}).then(r=>r.json()).then(d=>{if(d.status==='success'){alert('تم حذف حسابك');window.location.href='/'}else alert('فشل: '+(d.message||''))}).catch(e=>alert('خطأ'))};
})();</script></body></html>"""

# ==================== Routes ====================

@app.route('/')
def index():
    user_name=None
    email=session.get('user_email')
    if email and not session.get('is_admin'):
        p=get_user_profile(email)
        if p:
            user_name=p.get("display_name") or email.split("@")[0]
        else:
            user_name=email.split("@")[0]
        mem=get_user_memory(email)
        if mem.get('name'):
            user_name=mem['name']
    elif session.get('is_admin'):
        user_name="أدمن"
    return render_template_string(HT,user_name=user_name)

@app.route('/library')
def library_page():
    if not session.get('user_email') and not session.get('is_admin'):
        return redirect(url_for('login'))
    return render_template_string(LIBRARY_HTML)

@app.route('/library/images')
def library_images():
    uid=get_user_id()
    imgs=get_user_images(uid)
    return jsonify({"images":imgs})

@app.route('/library/upload',methods=['POST'])
def library_upload():
    try:
        if not session.get('user_email') and not session.get('is_admin'):
            return jsonify({"status":"error","message":"يجب تسجيل الدخول"}),401
        d=request.get_json()
        image_data=d.get('image_data')
        title=d.get('title') or "صورة"
        if not image_data:
            return jsonify({"status":"error","message":"لا توجد صورة"}),400
        if len(image_data)>5000000:
            return jsonify({"status":"error","message":"الصورة كبيرة جداً"}),413
        uid=get_user_id()
        save_image_to_library(uid,image_data=image_data,title=title,source="upload")
        return jsonify({"status":"ok"})
    except Exception as e:
        print("library_upload:",e)
        return jsonify({"status":"error","message":str(e)}),500

@app.route('/library/delete',methods=['POST'])
def library_delete():
    try:
        if not session.get('user_email') and not session.get('is_admin'):
            return jsonify({"status":"error","message":"يجب تسجيل الدخول"}),401
        d=request.get_json()
        image_id=d.get('id')
        if not image_id:
            return jsonify({"status":"error","message":"معرف مفقود"}),400
        uid=get_user_id()
        ok=delete_user_image(uid,image_id)
        return jsonify({"status":"ok"}) if ok else jsonify({"status":"error"}),404
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}),500

@app.route('/share/<cid>')
def shared_conversation(cid):
    rows=load_conversation_public(cid)
    if not rows:return "المحادثة غير موجودة.",404
    msgs=[]
    title="محادثة نبراس"
    for i,row in enumerate(rows):
        if i==0 and row.get("title"):title=row["title"]
        if row.get("message"):msgs.append({"role":"user","content":row["message"]})
        if row.get("response"):msgs.append({"role":"assistant","content":row["response"]})
    return render_template_string(SPH,messages=msgs,title=title)

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
            r=requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},json={"email":e,"password":p},timeout=15)
        except Exception as ex:
            return render_template_string(LH,error="تعذر الاتصال بخدمة الدخول.")
        if r.status_code!=200:
            err_text = r.text.lower()
            if "email not confirmed" in err_text or "not confirmed" in err_text:
                return render_template_string(LH,error="يجب تأكيد بريدك أولاً.")
            return render_template_string(LH,error="البريد الإلكتروني أو كلمة المرور غير صحيحة.")
        data=r.json()
        session.clear();session.permanent=True
        session['user_email']=e
        session['is_admin']=False
        session['access_token']=data.get('access_token')
        session['refresh_token']=data.get('refresh_token')
        session['user_role']=get_user_role(e)
        touch_user(e)
        return redirect(url_for('index'))
    return render_template_string(LH)

@app.route('/signup',methods=['POST'])
@limiter.limit("5 per hour")
def signup():
    e=request.form.get('email','').strip().lower()
    p=request.form.get('password','')
    name=request.form.get('name','').strip()
    if not e or "@" not in e or len(p)<8:
        return render_template_string(LH,error="بريد صحيح وكلمة مرور 8 أحرف على الأقل مطلوبة.")
    if not name or len(name)<2:
        return render_template_string(LH,error="الاسم الكامل مطلوب.")
    try:
        redirect_url = f"{request.host_url.rstrip('/')}/verified"
        sb.auth.sign_up({"email": e,"password": p,"options": {"email_redirect_to": redirect_url,"data": {"display_name": name}}})
        save_user_profile(e, name=name)
        save_user_memory(e, {"name": name})
        return render_template_string(LH,success="تم إنشاء حسابك! افتح بريدك واضغط رابط التأكيد.")
    except Exception as ex:
        err_msg = str(ex)
        if "39 seconds" in err_msg or "rate limit" in err_msg.lower():
            return render_template_string(LH,error="انتظر 60 ثانية ثم حاول مرة أخرى.")
        if "already" in err_msg.lower():
            return render_template_string(LH,error="هذا البريد مسجل مسبقاً.")
        return render_template_string(LH,error=f"فشل: {ex}")

@app.route('/verified')
def verified():
    return """<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>تم التحقق - نبراس</title><style>*{font-family:'Segoe UI',Tahoma,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:44px 30px;border-radius:24px;box-shadow:0 4px 30px rgba(0,0,0,0.06);width:100%;max-width:420px;text-align:center}.icon{width:80px;height:80px;background:#4a6a8a;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 20px}.icon svg{width:40px;height:40px;stroke:#fff;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round}h2{font-size:24px;color:#1a2b3c;margin-bottom:12px;font-weight:700}p{color:#5a6b7c;line-height:1.8;margin-bottom:22px;font-size:15px}a{display:inline-block;background:#4a6a8a;color:#fff;padding:14px 40px;border-radius:14px;text-decoration:none;font-weight:700;font-size:15px}a:hover{background:#3a5a7a}</style></head><body><div class="box"><div class="icon"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg></div><h2>تم تأكيد حسابك!</h2><p>بريدك مؤكد. يمكنك تسجيل الدخول الآن.</p><a href="/login">تسجيل الدخول</a></div>
<script>
(async function(){
    try{
        var accessToken=null,code=null;
        if(window.location.hash){var hp=new URLSearchParams(window.location.hash.substring(1));accessToken=hp.get('access_token');}
        var urlParams=new URLSearchParams(window.location.search);
        if(!accessToken){code=urlParams.get('code');accessToken=urlParams.get('access_token');}
        if(code){try{await fetch("__SUPABASE_URL__"+'/auth/v1/token?grant_type=pkce',{method:'POST',headers:{'apikey':"__SUPABASE_KEY__",'Content-Type':'application/json'},body:JSON.stringify({auth_code:code})});}catch(e){}}
        if(accessToken){try{await fetch("__SUPABASE_URL__"+'/auth/v1/user',{headers:{'apikey':"__SUPABASE_KEY__",'Authorization':'Bearer '+accessToken}});}catch(e){}}
    }catch(e){}
})();
</script></div></body></html>""".replace("__SUPABASE_URL__",SUPABASE_URL or "").replace("__SUPABASE_KEY__",SUPABASE_KEY or "")

@app.route('/recover',methods=['POST'])
@limiter.limit("5 per hour")
def recover():
    e=request.form.get('email','').strip().lower()
    if not e or "@" not in e:
        return render_template_string(LH,error="أدخل بريداً صحيحاً.")
    try:
        requests.post(f"{SUPABASE_URL}/auth/v1/recover",headers={"apikey":SUPABASE_KEY,"Content-Type":"application/json"},json={"email":e},timeout=15)
        return render_template_string(LH,success="تم إرسال رابط استعادة كلمة المرور إلى بريدك.")
    except Exception as ex:
        return render_template_string(LH,error=f"تعذر إرسال الرابط: {ex}")

@app.route('/logout')
def logout():session.clear();return redirect(url_for('index'))

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
        sb.table("image_library").delete().eq("user_id",uid).execute()
        sb.table("profiles").delete().eq("email",email.lower()).execute()
    except Exception as e:
        print("delete_my_account:",e)
    session.clear()
    return jsonify({"status":"success","message":"تم حذف حسابك"})

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        p=request.form.get('password','')
        ap=os.environ.get("ADMIN_PASSWORD")
        if ap and secrets.compare_digest(p,ap):
            session['is_admin']=True;session.permanent=True
            return redirect(url_for('admin_dashboard'))
        return """<body style='background:#f4f7fc;color:#1a2b3c;font-family:sans-serif;text-align:center;padding:50px;'><h2>كلمة مرور خاطئة</h2><a href='/admin/login' style='color:#4a6a8a;'>حاول مرة أخرى</a></body>"""
    return """<body style='background:#f4f7fc;color:#1a2b3c;font-family:sans-serif;display:flex;justify-content:center;align-items:center;min-height:100dvh;margin:0;'><form method='POST' style='background:#fff;padding:30px;border-radius:20px;box-shadow:0 4px 30px rgba(0,0,0,0.06);text-align:center;'><h2 style='color:#4a6a8a;'>دخول الأدمن</h2><input type='password' name='password' placeholder='كلمة المرور' required style='padding:14px;border-radius:12px;border:1.5px solid #dce1e8;background:#fafbfc;color:#1a2b3c;font-size:16px;width:250px;font-family:inherit;'><br><br><button type='submit' style='background:#4a6a8a;color:#fff;border:none;padding:12px 30px;border-radius:12px;cursor:pointer;font-size:16px;font-weight:bold;font-family:inherit;'>دخول</button></form></body>"""

@app.route('/admin')
def admin_dashboard():
    if not session.get('is_admin'):return redirect(url_for('admin_login'))
    try:
        recent_r=(sb.table("assistant_chats").select("user_id,title,created_at").order("created_at",desc=True).limit(10).execute())
        recent=recent_r.data or []
        users_r=(sb.table("profiles").select("email,display_name,role,created_at,last_seen").order("created_at",desc=True).limit(30).execute())
        users_list=users_r.data or []
        chats_r=(sb.table("assistant_chats").select("user_id").execute())
        total_convs=len(chats_r.data or [])
    except Exception as e:
        print("admin_dashboard:",e);recent=[];users_list=[];total_convs=0
    today=_date.today().isoformat()
    today_convs=sum(1 for r in recent if (r.get("created_at") or "").startswith(today))
    recent_html=""
    for row in recent:
        user=row.get("user_id","")[:20]
        title=row.get("title") or "بدون عنوان"
        time=(row.get("created_at") or "")[:16].replace("T"," ")
        recent_html+=f'<div class="conv-item"><b>{title}</b><small>{user} | {time}</small></div>'
    if not recent_html:recent_html="<p style='color:#8b949e;text-align:center;'>لا توجد محادثات</p>"
    users_html=""
    for u in users_list:
        name=u.get("display_name") or "بدون اسم"
        email=u.get("email","")
        role=u.get("role","user")
        role_badge="👑" if role=="admin" else "👤"
        users_html+=f'<div class="conv-item"><b>{role_badge} {name}</b><small>{email} | {role}</small></div>'
    if not users_html:users_html="<p style='color:#8b949e;text-align:center;'>لا يوجد مستخدمون</p>"
    return f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>لوحة تحكم نبراس</title><style>body{{font-family:'Segoe UI',Tahoma;background:#f4f7fc;color:#1a2b3c;padding:20px;margin:0}}.container{{max-width:600px;margin:auto}}h1{{color:#4a6a8a;text-align:center}}.card{{background:#fff;border-radius:15px;padding:15px;margin:15px 0;box-shadow:0 4px 16px rgba(0,0,0,0.04)}}.stat{{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eef1f6}}.stat:last-child{{border:none}}.num{{color:#4a6a8a;font-weight:bold;font-size:18px}}.conv-item{{padding:10px 0;border-bottom:1px solid #eef1f6}}.conv-item small{{color:#8b949e;display:block;font-size:12px}}.back{{display:block;text-align:center;color:#4a6a8a;text-decoration:none;margin-top:20px;font-weight:600}}</style></head><body><div class="container"><h1>لوحة تحكم نبراس</h1><div class="card"><div class="stat"><span>المستخدمون</span><span class="num">{len(users_list)}</span></div><div class="stat"><span>إجمالي المحادثات</span><span class="num">{total_convs}</span></div><div class="stat"><span>آخر 10 (اليوم)</span><span class="num">{today_convs}</span></div></div><div class="card"><h3>المستخدمون المسجلون</h3>{users_html}</div><div class="card"><h3>آخر 10 محادثات</h3>{recent_html}</div><a href="/" class="back">الرئيسية</a></div></body></html>"""

@app.route('/set_gender',methods=['POST'])
def set_gender():
    d=request.get_json();g=d.get('gender','male');session['voice_gender']=g
    return jsonify({"status":"ok"})

@app.route('/voice',methods=['POST'])
@limiter.limit("30 per minute")
def voice():
    try:
        d=request.get_json()
        text=(d.get('text') or "").strip()
        if not text or len(text)>3000:
            return jsonify({"audio":None})
        g=session.get('voice_gender','male')
        audio=generate_speech(text,g)
        return jsonify({"audio":audio})
    except Exception as e:
        print(f"voice: {e}")
        return jsonify({"audio":None})

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
        
        # ✅ الحصول على الحدود والحالات
        usage,limits,can_chat,can_search,can_image=check_limits(uid,user_role if not is_admin else 'admin')
        
        # ✅ إذا وصل لحد المحادثات، يوقف
        if not can_chat:
            reply_limit="وصلت للحد اليومي للمحادثات (15). تقدر ترجع بكرة إن شاء الله."
            # فقط نحفظ لو مسجل
            if is_registered:
                nid=save_message(uid,um,reply_limit,cid)
            else:
                nid=cid
            return jsonify({"reply":reply_limit,"conv_id":nid,"audio":None})
        
        # ✅ تحديث last_seen و حفظ المحادثة السابقة (فقط للمسجل)
        if is_registered and user_email:
            try: touch_user(user_email)
            except: pass
            if not cid:
                try:
                    recent=(sb.table("assistant_chats").select("conv_id")
                            .eq("user_id",uid).order("created_at",desc=True).limit(1).execute())
                    if recent and recent.data:
                        last_cid=recent.data[0].get("conv_id")
                        if last_cid: summarize_old_conversation(uid, last_cid)
                except Exception as e:
                    print("auto-summarize:",e)
        
        # ✅ إذا فيه صورة مرفقة (يحتاج مسجل + can_image)
        has_image=d.get("image") is not None
        if has_image:
            if not is_registered:
                reply="تحليل الصور متاح للمسجلين فقط. سجّل دخولك عشان تستفيد."
                nid=cid
                return jsonify({"reply":reply,"conv_id":nid})
            if not can_image:
                reply="وصلت للحد اليومي لتحليل الصور (صورة واحدة). تقدر ترجع بكرة."
                nid=save_message(uid,um,reply,cid)
                inc_usage(uid,"chat_count")
                return jsonify({"reply":reply,"conv_id":nid})
        
        # ✅ إذا فيه بحث بالويب
        search_keywords=["أحدث","اليوم","الآن","2025","2026","جديد","خبر","أخبار","سعر","أسعار","مباراة","نتيجة","طقس","متى"]
        need_search=any(kw in um for kw in search_keywords)
        
        # ✅ الذاكرة طويلة المدى (فقط للمسجل)
        user_memory={}
        memory_context=""
        if is_registered:
            user_memory=get_user_memory(user_email) if user_email else {}
            # استخراج الاسم
            name_patterns=[
                r'(?:اسمي|انا|أنا|إسمي)\s+([\u0600-\u06FF]{2,20})',
                r'(?:اسمي|انا|أنا|إسمي)\s+([A-Za-z]{2,20})',
                r'(?:نادني|سميني|لقبي)\s+([\u0600-\u06FF]{2,20})',
            ]
            for pattern in name_patterns:
                match=re.search(pattern,um)
                if match:
                    candidate=match.group(1).strip()
                    stopwords=['وش','ايش','مين','هو','هي','من','في','على','ما','لا','واحد','شي']
                    if candidate not in stopwords and len(candidate)>=2:
                        user_memory['name']=candidate
                        if user_email: save_user_memory(user_email,user_memory)
                        break
            
            memory_parts=[]
            if user_memory.get('name'):
                memory_parts.append(f"اسم المستخدم: {user_memory['name']}")
            elif user_email:
                profile=get_user_profile(user_email)
                if profile and profile.get('display_name'):
                    memory_parts.append(f"اسم المستخدم: {profile['display_name']}")
            
            summaries=get_recent_summaries(uid, limit=5)
            if summaries:
                summary_lines=[]
                for s in summaries:
                    title=s.get('title','محادثة')
                    summary=s['summary']
                    summary_lines.append(f"• عن [{title}]: {summary}")
                memory_parts.append("مواضيع سابقة تحدثنا فيها:\n"+"\n".join(summary_lines))
            
            if memory_parts:
                memory_context="\n\n**معلومات عن المستخدم:**\n"+"\n".join(memory_parts)
        
        # ✅ بناء السياق
        server_hist=load_conversation(uid,cid) if (cid and is_registered) else []
        if not server_hist:server_hist=[]
        server_hist.append({"role":"user","content":um})
        ch=server_hist[-15:]
        msgs=[{"role":"system","content":SP+memory_context}]
        for e in ch:
            if isinstance(e.get("content"),str):
                msgs.append({"role":e["role"],"content":e["content"]})
        
        img_data=d.get("image",None)
        if img_data and is_registered and can_image:
            msgs.append({"role":"user","content":[{"type":"text","text":um or "حلل الصورة"},{"type":"image_url","image_url":{"url":img_data}}]})
        
        # ✅ البحث بالويب (فقط للمسجل + can_search)
        if is_registered and need_search and can_search:
            try:
                fc=""
                for m in msgs[-6:]:
                    if isinstance(m.get("content"),str):
                        if m["role"]=="user":fc+=m["content"]+"\n"
                        elif m["role"]=="assistant":fc+="نبراس: "+m["content"]+"\n"
                sr=client.responses.create(model=OPENAI_MODEL,instructions=f"{SP}\n\nسياق:\n{fc}",input=f"ابحث عن أحدث المعلومات: {um}",tools=[{"type":"web_search"}])
                res=sr.output_text.strip()
                if res:msgs.append({"role":"user","content":f"نتيجة البحث:\n{res}"})
                inc_usage(uid,"search_count")
            except Exception as e:print(f"بحث: {e}")
        
        # ✅ توليد الرد
        try:
            r=client.chat.completions.create(model=OPENAI_MODEL,messages=msgs,max_completion_tokens=8000,reasoning_effort="low")
            reply=r.choices[0].message.content.strip()
            if not reply:reply="ما قدرت أجيب رد."
        except Exception as e:
            print(f"{e}")
            return jsonify({"error":str(e)}),500
        
        # ✅ تنسيق الفقرات
        lines=reply.split('\n');merged=[];cur=[]
        for line in lines:
            line=line.strip()
            if not line:
                if cur:merged.append(' '.join(cur));cur=[]
            else:cur.append(line)
        if cur:merged.append(' '.join(cur))
        reply='\n\n'.join(merged)
        
        # ✅ الحفظ (فقط للمسجل)
        nid=cid
        if is_registered:
            nid=save_message(uid,um,reply,cid)
            inc_usage(uid,"chat_count")
            if has_image and can_image:
                inc_usage(uid,"image_count")
        else:
            # الضيف: نستخدم cid مؤقت في الجلسة فقط
            if not nid:
                nid="guest_conv_"+secrets.token_hex(5)
        
        return jsonify({"reply":reply,"audio":None,"conv_id":nid})
    except Exception as e:
        print(f"{e}")
        return jsonify({"status":"error","message":str(e)}),500

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
