from flask import Flask,request,jsonify,render_template_string,session,redirect,url_for,send_from_directory
import openai,os,secrets,json,hashlib,asyncio,edge_tts,base64,re,sqlite3,requests
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
app=Flask(__name__,static_folder='static')
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(16))
for k in ["OPENAI_API_KEY","OPENAI_MODEL"]:
 if not os.environ.get(k):raise Exception(f"{k} غير موجود!")
client=openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
limiter=Limiter(key_func=get_remote_address,default_limits=["500 per day","20 per hour"])
limiter.init_app(app)
DB_FILE="conversations.db"
def init_db():
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 c.execute('CREATE TABLE IF NOT EXISTS conversations (user_id TEXT, conv_id TEXT, messages TEXT, timestamp TEXT, title TEXT)')
 conn.commit();conn.close()
def get_user_conversations(uid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 c.execute("SELECT conv_id,messages,timestamp,title FROM conversations WHERE user_id=?",(uid,));rows=c.fetchall();conn.close()
 return [{"id":r[0],"messages":json.loads(r[1]),"timestamp":r[2],"title":r[3]} for r in rows]
def save_user_conversation(uid,conv,cid=None):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 if cid is None:
  nid=hashlib.md5(f"{uid}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
  c.execute("INSERT INTO conversations (user_id,conv_id,messages,timestamp,title) VALUES (?,?,?,?,?)",(uid,nid,json.dumps(conv),datetime.now().isoformat(),conv[0]["content"][:30]+"..." if len(conv[0]["content"])>30 else conv[0]["content"]))
  conn.commit();conn.close();return nid
 else:
  c.execute("UPDATE conversations SET messages=?,timestamp=? WHERE user_id=? AND conv_id=?",(json.dumps(conv),datetime.now().isoformat(),uid,cid))
  conn.commit();conn.close();return cid
def load_conversation_by_id(uid,cid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 c.execute("SELECT messages FROM conversations WHERE user_id=? AND conv_id=?",(uid,cid));r=c.fetchone();conn.close()
 return json.loads(r[0]) if r else None
init_db()
sm={}
kc=""
for fn in ["Knowledge.md","knowledge.md","معرفة.md","README.md","ملف_المعرفة.md"]:
 if os.path.exists(fn):
  try:
   with open(fn,"r",encoding="utf-8") as f:kc=f.read();break
  except:pass
if not kc:kc="أنت نبراس، مساعد ذكي."
SP=f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.
مصادر معرفتك: 1. ملف المعرفة (أدناه) 2. معرفتك العامة 3. البحث بالويب.
ملف المعرفة: {kc}
قاعدة التنسيق الذهبية: اكتب ردودك في فقرات نصية متصلة (2-4 جمل)، ممنوع فواصل أسطر بين الجمل.
تعليمات: حاول الإجابة من ملف المعرفة أولاً، ثم البحث، حافظ على العامية، قل "ما عندي علم" إن لم تعرف.
"""
def generate_image(p):
 try:
  k=os.environ.get("PEXELS_API_KEY")
  if not k:return "ERROR: PEXELS_API_KEY مفقود"
  r=requests.get(f"https://api.pexels.com/v1/search?query={requests.utils.quote(p)}&per_page=1&orientation=landscape",headers={"Authorization":k})
  d=r.json()
  return d["photos"][0]["src"]["large"] if r.status_code==200 and d.get("photos") else f"ERROR: {d.get('error','لا توجد صورة')}"
 except Exception as e:return f"ERROR: {str(e)}"
def search_video(p):
 try:
  k=os.environ.get("PEXELS_API_KEY")
  if not k:return "ERROR: PEXELS_API_KEY مفقود"
  r=requests.get(f"https://api.pexels.com/videos/search?query={requests.utils.quote(p)}&per_page=1",headers={"Authorization":k})
  d=r.json()
  if r.status_code==200 and d.get("videos"):
   vf=d["videos"][0]["video_files"]
   for v in vf:
    if v.get("quality")=="hd" and v.get("link"):return v["link"]
   return vf[0]["link"] if vf else "ERROR: لا يوجد رابط"
  return f"ERROR: {d.get('error','لا يوجد فيديو')}"
 except Exception as e:return f"ERROR: {str(e)}"
def generate_speech(text,gender):
 try:
  voice="ar-SA-ZariyahNeural" if gender=="female" else "ar-SA-HamedNeural"
  communicate=edge_tts.Communicate(text,voice)
  audio=bytearray()
  async def c():
   async for chunk in communicate.stream():
    if chunk["type"]=="audio":
     audio.extend(chunk["data"])
  asyncio.run(c())
  return base64.b64encode(audio).decode()
 except:return None
SPH='''<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>📄 محادثة نبراس</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css"><style>*{margin:0;padding:0;box-sizing:border-box;font-family:\'Segoe UI\',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;white-space:normal;word-wrap:break-word;overflow-wrap:break-word}.msg.user .content{background:#eaeef2}.msg.bot .content{background:#f5f7fa}.msg .content p{margin-bottom:8px}.msg .content p:last-child{margin-bottom:0}.msg .time{font-size:11px;color:#8b949e;margin-top:4px;display:block}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}@media(max-width:500px){.container{padding:15px}.msg .content{max-width:100%}}</style></head></body><div class="container"><div class="header"><h1>💬 {{ title or "محادثة نبراس" }}</h1><a href="/">⬅ الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ "user" if msg.role=="user" else "bot" }}"><div class="avatar">{{ "👤" if msg.role=="user" else "🤖" }}</div><div class="content">{{ msg.content|e|replace("\n","<br>")|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a> - مساعد ذكي</div></div></body></html>'''
TOOLS_HTML='''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>أدوات نبراس المجانية</title><style>body{font-family:\'Segoe UI\',Tahoma;background:#0f172a;color:#fff;margin:0;padding:20px}.container{max-width:900px;margin:auto}h1{text-align:center;color:#38bdf8}a{color:#38bdf8}.card{background:#1e293b;border-radius:15px;padding:20px;margin:20px 0;border:1px solid #334155}input,select,textarea{width:100%;padding:12px;margin:8px 0;border-radius:8px;border:none;background:#0f172a;color:#fff}button{background:#38bdf8;color:#000;padding:12px 20px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;width:100%}button:hover{background:#0ea5e9}.result{background:#0f172a;padding:15px;border-radius:8px;margin-top:10px;border:1px dashed #38bdf8}.grid{display:grid;grid-template-columns:1fr 1fr;gap:15px}@media(max-width:600px){.grid{grid-template-columns:1fr}}</style></head><body><div class="container"><h1>🧰 أدوات نبراس المجانية</h1><p style="text-align:center;color:#94a3b8">أدوات سريعة وذكية مجانية</p><p style="text-align:center"><a href="/">⬅ ارجع لنبراس</a></p><div class="card"><h3>📚 1- حاسبة المعدل GPA</h3><div class="grid"><input id="gpa1" placeholder="ساعات مادة 1" type="number"><select id="grade1"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><div class="grid"><input id="gpa2" placeholder="ساعات مادة 2" type="number"><select id="grade2"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><button onclick="calcGPA()">احسب</button><div id="gpaRes" class="result" style="display:none"></div></div><div class="card"><h3>📝 2- منشئ السيرة الذاتية ATS</h3><input id="cvName" placeholder="الاسم"><input id="cvSpec" placeholder="التخصص"><textarea id="cvExp" placeholder="الخبرات"></textarea><button onclick="makeCV()">أنشئ</button><div id="cvRes" class="result" style="display:none"></div></div><div class="card"><h3>💰 3- حاسبة حساب المواطن</h3><input id="family" type="number" placeholder="عدد الأفراد"><input id="income" type="number" placeholder="الدخل"><button onclick="calcCitizen()">احسب</button><div id="citRes" class="result" style="display:none"></div></div><div class="card"><h3>💡 4- مولد أفكار مشاريع</h3><select id="budget"><option value="5000">5 آلاف</option><option value="10000">10 آلاف</option><option value="20000">20 ألف</option><option value="50000">50 ألف</option></select><button onclick="genIdea()">فكرة</button><div id="ideaRes" class="result" style="display:none"></div></div></div><script>function calcGPA(){let h1=+document.getElementById("gpa1").value||0,g1=+document.getElementById("grade1").value||0,h2=+document.getElementById("gpa2").value||0,g2=+document.getElementById("grade2").value||0;if(!h1&&!h2)return alert("أدخل ساعات");let t=(h1*g1+h2*g2)/(h1+h2);document.getElementById("gpaRes").style.display="block";document.getElementById("gpaRes").innerHTML="معدلك: <b style=\"color:#38bdf8;font-size:22px\">"+t.toFixed(2)+"</b> / 5"}function makeCV(){let n=document.getElementById("cvName").value,s=document.getElementById("cvSpec").value,e=document.getElementById("cvExp").value;if(!n)return alert("اكتب اسمك");document.getElementById("cvRes").style.display="block";document.getElementById("cvRes").innerText=`السيرة الذاتية\nالاسم: ${n}\nالتخصص: ${s}\nالخبرات:\n${e}\nالمهارات:\n- العمل تحت الضغط\n- اللغة الإنجليزية\n- الحاسب الآلي`}function calcCitizen(){let f=+document.getElementById("family").value||1,i=+document.getElementById("income").value||0,s=0;if(i<3000)s=f*400;else if(i<6000)s=f*300;else s=f*150;if(s>3000)s=3000;document.getElementById("citRes").style.display="block";document.getElementById("citRes").innerHTML="الدعم التقريبي: <b style=\"color:#22c55e\">"+s+" ريال</b><br><small>حساب تقريبي</small>"}const ideas={"5000":["متجر إلكتروني","خدمة كتابة","تصميم سير"],"10000":["مغسلة متنقلة","عربة قهوة","تغليف هدايا"],"20000":["دروس خصوصية","استوديو تصوير","اكسسوارات"],"50000":["مقهى طلابي","توصيل داخلي","مركز تدريب"]};function genIdea(){let b=document.getElementById("budget").value,l=ideas[b];document.getElementById("ideaRes").style.display="block";document.getElementById("ideaRes").innerHTML="💡 فكرة برأس مال "+b+" ريال:<br><b style=\"color:#facc15;font-size:18px\">"+l[Math.floor(Math.random()*l.length)]+"</b>"}</script></body></html>'''
HT='''<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0,user-scalable=yes"/><meta name="google-site-verification" content="PyOhY3ZXN4LTBbK55EbrmeI5A5kqddF3cJeI_s1FwVc"/><title>نبراس GP | مساعد ذكي سعودي</title><meta name="description" content="نبراس GP مساعدك الذكي العربي الموثوق."/><link rel="manifest" href="/static/manifest.json"/><link rel="icon" type="image/png" href="/static/icon-512.png"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css"/><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#6a7b8c;--welcome-bg:#fff;--border-input:#dce1e8;--btn-gold-bg:#f1c40f;--btn-gold-text:#1a2b3c;--mute-muted:#444;--mute-hover:#1a2b3c;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--mic-active-bg:#fde8e8;--mic-active-color:#c33;--remove-btn-hover:#fde8e8;--modal-bg:rgba(0,0,0,0.5)}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-bot-msg:transparent;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#8b949e;--welcome-bg:#161b22;--border-input:#30363d;--btn-gold-bg:#d29922;--btn-gold-text:#0d1117;--mute-muted:#484f58;--mute-hover:#c9d1d9;--send-bg:#238636;--send-hover:#2ea043;--mic-active-bg:#2d1b1b;--mic-active-color:#f85149;--remove-btn-hover:#2d1b1b;--modal-bg:rgba(0,0,0,0.7)}*{margin:0;padding:0;box-sizing:border-box;font-family:"Segoe UI",Arial,sans-serif}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-color);flex-shrink:0;background:var(--bg-header)}.header-right,.header-left{display:flex;align-items:center;gap:6px}.menu-btn,.mute-btn{background:0;border:none;font-size:20px;color:var(--text-secondary);cursor:pointer;padding:4px 8px}.mute-btn.muted{color:var(--mute-muted);opacity:.4}.btn{padding:6px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none}.btn-outline{background:0;border:1px solid var(--primary-color);color:var(--primary-color)}.dropdown{position:absolute;top:64px;left:14px;right:14px;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 8px 30px var(--shadow-color);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:60vh;overflow-y:auto}.dropdown.show{display:flex}.dropdown .item,.dropdown .conv-item{display:flex;align-items:center;gap:12px;padding:14px 18px;font-size:15px;color:var(--text-primary);background:0;border:none;width:100%;text-align:right;cursor:pointer;border-bottom:1px solid var(--border-color)}.dropdown .item:hover,.dropdown .conv-item:hover{background:var(--bg-hover)}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app)}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:16px;font-weight:600;line-height:1.7;word-wrap:break-word;white-space:normal;color:var(--text-primary)}.msg.user{align-self:flex-end;background:var(--bg-user-msg);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg.error{background:var(--danger-bg);color:var(--danger-color)}.msg .image-upload,.msg .generated-image,.msg .generated-video{max-width:100%;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;border-bottom-right-radius:6px;color:var(--text-secondary)}.typing-dots{display:inline-block}.typing-dots::after{content:"...";animation:dot 1.2s steps(4,end) infinite}@keyframes dot{0%,20%{content:""}40%{content:"."}60%{content:".."}80%,100%{content:"..."}}.welcome-overlay{position:fixed;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;animation:fadeIn .5s ease}.welcome-overlay .welcome-box{background:var(--welcome-bg);padding:30px 40px;border-radius:20px;box-shadow:0 10px 40px var(--shadow-color);text-align:center;max-width:90%;border:1px solid var(--border-color)}.welcome-overlay .welcome-box h2{font-size:28px;color:var(--text-primary)}.welcome-overlay .welcome-box p{font-size:18px;color:var(--text-secondary)}@keyframes fadeIn{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:scale(1)}}.welcome-overlay.fade-out{animation:fadeOut .5s ease forwards}@keyframes fadeOut{from{opacity:1;transform:scale(.9)}to{opacity:0;transform:scale(.9)}}#imagePreviewContainer{display:none;padding:6px 18px;align-items:center;gap:10px;background:var(--bg-input);margin:0 14px;border-radius:20px 20px 0 0;border:1px solid var(--border-color);border-bottom:none;flex-wrap:wrap;flex-shrink:0}#imagePreviewContainer img{max-height:60px;border-radius:8px;border:1px solid var(--border-color)}#removeImageBtn{background:0;border:none;color:var(--danger-color);cursor:pointer;padding:4px 8px;border-radius:12px}.input-area{display:flex;align-items:flex-end;gap:8px;padding:8px 14px;margin:8px 14px 16px;background:var(--bg-input);border-radius:40px;border:1px solid var(--border-color);flex-shrink:0;min-height:60px}.input-area textarea{flex:1;border:none;background:0;padding:12px 0;font-size:18px;font-weight:600;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow:hidden;min-height:20px;max-height:80px}.input-area .btn-icon{background:0;border:none;color:var(--icon-color);font-size:20px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center}.input-area .mic-btn{color:var(--primary-color)}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:44px;height:44px;border-radius:50%;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 2px 8px var(--send-shadow)}.plus-btn{background:0;border:none;color:var(--primary-color);font-size:24px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;transition:.3s}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:6px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--text-primary);cursor:pointer}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color);box-shadow:0 20px 60px var(--shadow-color)}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:15px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px}.share-modal .box .share-btn.whatsapp{background:#25D366;color:#fff}.share-modal .box .share-btn.facebook{background:#1877F2;color:#fff}.share-modal .box .share-btn.twitter{background:#000;color:#fff}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:16px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600}.copy-btn{background:0;border:none;color:var(--text-secondary);cursor:pointer;font-size:14px;padding:4px 8px;border-radius:8px;opacity:.5}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999;animation:toastIn .3s ease;direction:rtl}@keyframes toastIn{from{opacity:0;transform:translateX(-50%) translateY(20px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}.code-block-wrapper{position:relative;margin:16px 0;border-radius:14px;border:1px solid var(--border-color);background:var(--bg-input);overflow:hidden;overflow-x:auto}.code-block-wrapper pre{margin:0;padding:20px 60px 20px 24px;background:0;border:none;border-radius:0;white-space:pre;font-size:15px;line-height:1.8;font-family:Consolas,monospace;direction:ltr;text-align:left}.code-block-wrapper .copy-code-btn{position:absolute;top:12px;left:14px;background:var(--bg-hover);border:1px solid var(--border-color);color:var(--text-secondary);border-radius:10px;padding:8px 18px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:6px}.code-block-wrapper .copy-code-btn:hover{background:var(--primary-color);color:#fff}</style></head><body><div class="app"><div class="header"><div class="header-right"><button class="mute-btn" id="muteBtn"><i class="fas fa-volume-up"></i></button><button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button></div><div class="header-left"><div class="btn-group">{% if session.get("admin_email") or session.get("user_email") %}<a href="/logout" class="btn btn-outline">تسجيل خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div><div class="dropdown" id="dropdown"><button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button><button class="item" onclick="window.location.href="/tools""><i class="fas fa-tools"></i> أدوات مجانية</button><button class="item" data-action="share"><i class="fas fa-share-alt"></i> مشاركة</button><button class="item" onclick="deleteMyData()" style="color:#ff4d4d"><i class="fas fa-trash-alt"></i> حذف حسابي</button><button class="item" data-action="theme-toggle"><i class="fas fa-moon"></i> <span id="themeLabel">الوضع الليلي</span></button><div class="item" style="flex-direction:column;align-items:stretch;gap:6px;cursor:default;border-bottom:1px solid var(--border-color)"><div style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--text-primary)"><i class="fas fa-microphone" style="font-size:18px;color:var(--text-secondary)"></i><span>صوت المساعد</span></div><div style="display:flex;gap:8px"><button class="gender-option active" data-gender="male">👨 ذكر</button><button class="gender-option" data-gender="female">👩 أنثى</button></div></div><div id="historyList"></div></div><div id="chat"></div><div id="imagePreviewContainer"><img id="imagePreview" src=""/><span class="label">📎 صورة</span><button id="removeImageBtn">✕</button></div><div class="input-area"><button class="btn-icon mic-btn" id="micBtn"><i class="fas fa-microphone"></i></button><button class="plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button><div class="plus-options" id="plusOptions"><button class="option-btn camera" id="cameraBtn"><i class="fas fa-camera"></i></button><button class="option-btn gallery" id="galleryBtn"><i class="fas fa-images"></i></button><button class="option-btn files" id="filesBtn"><i class="fas fa-folder"></i></button></div><textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea><button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button></div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/><input type="file" id="fileInputGeneric" style="display:none"/></div><div class="share-modal" id="shareModal"><div class="box"><h3><i class="fas fa-share-alt" style="color:var(--primary-color)"></i> شارك المحادثة</h3><div class="share-grid"><a href="#" id="shareWhatsapp" target="_blank" class="share-btn whatsapp"><i class="fab fa-whatsapp"></i> واتساب</a><a href="#" id="shareFacebook" target="_blank" class="share-btn facebook"><i class="fab fa-facebook"></i> فيسبوك</a><a href="#" id="shareTwitter" target="_blank" class="share-btn twitter"><i class="fab fa-x-twitter"></i> X</a><button id="shareSnapchat" class="share-btn snapchat"><i class="fab fa-snapchat"></i> سناب شات</button></div><button class="close-btn" onclick="document.getElementById("shareModal").classList.remove("show")">إلغاء</button></div></div><script>
(function(){
 console.log("نبراس يبدأ");
 var ch=[],pid=null,iw=!1,cid=null,ca=null;
 var cb=document.getElementById("chat"),ui=document.getElementById("userInput"),sb=document.getElementById("sendBtn"),mb=document.getElementById("micBtn"),fi=document.getElementById("fileInput"),ci=document.getElementById("cameraInput"),mt=document.getElementById("menuToggle"),dd=document.getElementById("dropdown"),pb=document.getElementById("plusBtn"),po=document.getElementById("plusOptions"),cab=document.getElementById("cameraBtn"),gb=document.getElementById("galleryBtn"),fib=document.getElementById("filesBtn"),fig=document.getElementById("fileInputGeneric"),ipc=document.getElementById("imagePreviewContainer"),ip=document.getElementById("imagePreview"),rib=document.getElementById("removeImageBtn"),hl=document.getElementById("historyList"),sm=document.getElementById("shareModal");
 if(!sb||!ui){cb.innerHTML='<div class="msg error">❌ فشل تحميل الواجهة</div>';return}
 var im=!0,mut=document.getElementById("muteBtn");if(mut){mut.querySelector("i").className="fas fa-volume-mute";mut.classList.add("muted");mut.onclick=function(){im=!im;var ic=mut.querySelector("i");if(im){ic.className="fas fa-volume-mute";mut.classList.add("muted");if(ca){ca.pause();ca.currentTime=0}}else{ic.className="fas fa-volume-up";mut.classList.remove("muted")}}}
 var isMale=!0,gopts=document.querySelectorAll(".gender-option");mt.onclick=function(e){e.stopPropagation();dd.classList.toggle("show");if(dd.classList.contains("show")){loadHistory();gopts.forEach(function(b){b.classList.remove("active")});var b=document.querySelector(".gender-option[data-gender=\""+(isMale?"male":"female")+"\"]");if(b)b.classList.add("active")}};
 gopts.forEach(function(b){b.onclick=function(e){e.stopPropagation();var g=this.dataset.gender;isMale=g==="male";gopts.forEach(function(x){x.classList.remove("active")});this.classList.add("active");fetch("/set_gender",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({gender:g})});dd.classList.remove("show")}});
 async function loadHistory(){try{var r=await fetch("/history"),d=await r.json();hl.innerHTML="";if(d.conversations&&d.conversations.length>0){d.conversations.forEach(function(c){var b=document.createElement("button");b.className="conv-item";b.textContent=c.title;b.onclick=function(){loadConversation(c.id)};hl.appendChild(b)})}else{var e=document.createElement("div");e.className="item";e.textContent="📭 لا توجد محادثات";hl.appendChild(e)}}catch(e){console.error(e)}}
 async function loadConversation(id){try{var r=await fetch("/load_conversation/"+id),d=await r.json();if(d.messages){cb.innerHTML="";ch=d.messages;cid=id;d.messages.forEach(function(m){addMessage(m.content,m.role==="user"?"user":"bot",!0)});dd.classList.remove("show")}}catch(e){console.error(e)}}
 document.querySelector("[data-action=\"new\"]").onclick=function(){cb.innerHTML="";ch=[];cid=null;dd.classList.remove("show");pid=null;ipc.style.display="none";ui.value=""};
 document.querySelector("[data-action=\"share\"]").onclick=function(e){e.stopPropagation();if(!cid){alert("⚠️ لا توجد محادثة");dd.classList.remove("show");return}var url=location.origin+"/share/"+cid,t=encodeURIComponent("اطلع على محادثتي مع نبراس:");document.getElementById("shareWhatsapp").href="https://api.whatsapp.com/send?text="+t+"%20"+encodeURIComponent(url);document.getElementById("shareFacebook").href="https://www.facebook.com/sharer/sharer.php?u="+encodeURIComponent(url);document.getElementById("shareTwitter").href="https://twitter.com/intent/tweet?url="+encodeURIComponent(url)+"&text="+t;var snap=document.getElementById("shareSnapchat");snap.onclick=function(ev){ev.stopPropagation();if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(function(){alert("✅ تم النسخ")}).catch(function(){alert("❌ فشل، الرابط: "+url)})}else alert("❌ الرابط: "+url);sm.classList.remove("show")};sm.classList.add("show");dd.classList.remove("show")};
 sm.onclick=function(e){if(e.target===sm)sm.classList.remove("show")};
 var ttb=document.querySelector("[data-action=\"theme-toggle\"]"),tl=document.getElementById("themeLabel");
 function setTheme(t){var h=document.documentElement;if(t==="dark"){h.classList.add("dark-mode");tl.textContent="الوضع الليلي";ttb.querySelector("i").className="fas fa-moon";localStorage.setItem("nibras-theme","dark")}else{h.classList.remove("dark-mode");tl.textContent="الوضع النهاري";ttb.querySelector("i").className="fas fa-sun";localStorage.setItem("nibras-theme","light")}}
 setTheme(localStorage.getItem("nibras-theme")||"light");ttb.onclick=function(e){e.stopPropagation();var cur=document.documentElement.classList.contains("dark-mode")?"dark":"light";setTheme(cur==="dark"?"light":"dark");dd.classList.remove("show")};
 function formatBotText(t){try{var s=String(t||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");return s.split(/\n\s*\n/).map(function(p){return p.replace(/[\r\n]+/g," ").trim()}).filter(function(p){return p.length>0}).join("<br><br>")}catch(e){return t||""}}
 function showToast(m){var o=document.querySelector(".toast");if(o)o.remove();var t=document.createElement("div");t.className="toast";t.textContent=m;document.body.appendChild(t);setTimeout(function(){t.style.animation="toastOut .3s ease forwards";setTimeout(function(){if(t.parentNode)t.remove()},300)},1500)}
 function initCodeCopyButtons(){document.querySelectorAll(".copy-code-btn").forEach(function(b){b.removeEventListener("click",codeCopyHandler);b.addEventListener("click",codeCopyHandler)})}
 function codeCopyHandler(e){e.stopPropagation();var b=e.currentTarget,c=b.getAttribute("data-code")||(b.parentElement.querySelector("code")?b.parentElement.querySelector("code").textContent:"");if(!c){showToast("❌ لا يوجد كود");return}function d(){b.textContent="✅ تم النسخ!";b.classList.add("copied");showToast("✅ تم النسخ");setTimeout(function(){b.textContent="📋 نسخ الكود";b.classList.remove("copied")},2200)}if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(c).then(d).catch(function(){try{var ta=document.createElement("textarea");ta.value=c;ta.style.position="fixed";ta.style.opacity="0";ta.style.left="-9999px";ta.style.top="-9999px";document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();d()}catch(e){showToast("❌ فشل")}})}else{try{var ta=document.createElement("textarea");ta.value=c;ta.style.position="fixed";ta.style.opacity="0";ta.style.left="-9999px";ta.style.top="-9999px";document.body.appendChild(ta);ta.select();document.execCommand("copy");ta.remove();d()}catch(e){showToast("❌ فشل")}}}
 function addMessage(t,s,isSys,img,imageUrl){try{s=s||"bot";isSys=isSys||!1;var el=document.createElement("div");el.className="msg "+s;if(s==="error")el.classList.add("error");var tm=isSys?"":new Date().toLocaleTimeString("ar-SA",{hour:"2-digit",minute:"2-digit"});if(img){el.innerHTML='<img src="'+img+'" class="image-upload" /><span class="file-label">'+(t||"صورة")+"</span>"+(tm?' <span class="time">'+tm+"</span>":"");cb.appendChild(el);cb.scrollTop=cb.scrollHeight;return el}var imatch=t.match(/(https?:\/\/[^\s]+\.(png|jpg|jpeg|gif|webp))/i),dt=t,genUrl=null;if(imatch){genUrl=imatch[0];dt=t.replace(imatch[0],"").trim();if(!dt)dt="الصورة المولدة"}if(s==="bot"&&!isSys&&!genUrl&&!imageUrl){var wrapper=document.createElement("div");wrapper.className="content-wrapper";var textDiv=document.createElement("div");textDiv.className="content-text";textDiv.innerHTML='<span class="typing-text"></span>';var actions=document.createElement("div");actions.className="actions";var copyBtn=document.createElement("button");copyBtn.className="copy-btn";copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.title="نسخ النص";copyBtn.onclick=function(e){e.stopPropagation();var ft=dt;if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(ft).then(function(){copyBtn.innerHTML='<i class="fas fa-check"></i>';copyBtn.classList.add("copied");showToast("تم نسخ النص!");setTimeout(function(){copyBtn.innerHTML='<i class="fas fa-copy"></i>';copyBtn.classList.remove("copied")},2000)}).catch(function(){showToast("فشل النسخ")})}else showToast("المتصفح لا يدعم النسخ")};var shareBtn=document.createElement("button");shareBtn.className="copy-btn";shareBtn.innerHTML='<i class="fas fa-share-alt"></i>';shareBtn.title="مشاركة";shareBtn.onclick=function(e){e.stopPropagation();window.open("https://api.whatsapp.com/send?text="+encodeURIComponent(dt),"_blank")};var delBtn=document.createElement("button");delBtn.className="del-msg-btn";delBtn.innerHTML='<i class="fas fa-trash-alt"></i>';delBtn.title="حذف";delBtn.onclick=function(e){e.stopPropagation();deleteMessage(el)};actions.appendChild(copyBtn);actions.appendChild(shareBtn);actions.appendChild(delBtn);wrapper.appendChild(textDiv);wrapper.appendChild(actions);el.appendChild(wrapper);if(tm){var sp=document.createElement("span");sp.className="time";sp.textContent=tm;el.appendChild(sp)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;var ts=textDiv.querySelector(".typing-text"),idx=0,interacted=!1;var onInteract=function(){interacted=!0;cb.removeEventListener("touchstart",onInteract);cb.removeEventListener("scroll",onInteract)};cb.addEventListener("touchstart",onInteract);cb.addEventListener("scroll",onInteract);(function typeChar(){if(idx<dt.length){ts.textContent+=dt.charAt(idx);idx++;if(!interacted)cb.scrollTop=cb.scrollHeight;setTimeout(typeChar,20)}else{ts.innerHTML=formatBotText(dt);initCodeCopyButtons();cb.scrollTop=cb.scrollHeight}})();return el}var content=dt;if(s==="bot")content=formatBotText(dt);if(genUrl)content+='<br/><img src="'+genUrl+'" class="generated-image" />';if(imageUrl){if(imageUrl.match(/\.(mp4|webm|mov)$/i)||imageUrl.includes("video"))content+='<br/><video controls class="generated-video" src="'+imageUrl+'"></video>';else content+='<br/><img src="'+imageUrl+'" class="generated-image" />'}var wrap2=document.createElement("div");wrap2.className="content-wrapper";var td2=document.createElement("div");td2.className="content-text";td2.innerHTML=content;wrap2.appendChild(td2);if(s==="bot"&&!isSys){var ac2=document.createElement("div");ac2.className="actions";var cb2=document.createElement("button");cb2.className="copy-btn";cb2.innerHTML='<i class="fas fa-copy"></i>';cb2.title="نسخ";cb2.onclick=function(e){e.stopPropagation();var ft=dt;if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(ft).then(function(){cb2.innerHTML='<i class="fas fa-check"></i>';cb2.classList.add("copied");showToast("تم النسخ");setTimeout(function(){cb2.innerHTML='<i class="fas fa-copy"></i>';cb2.classList.remove("copied")},2000)}).catch(function(){showToast("فشل")})}else showToast("لا يدعم")};var sb2=document.createElement("button");sb2.className="copy-btn";sb2.innerHTML='<i class="fas fa-share-alt"></i>';sb2.title="مشاركة";sb2.onclick=function(e){e.stopPropagation();window.open("https://api.whatsapp.com/send?text="+encodeURIComponent(dt),"_blank")};var db2=document.createElement("button");db2.className="del-msg-btn";db2.innerHTML='<i class="fas fa-trash-alt"></i>';db2.title="حذف";db2.onclick=function(e){e.stopPropagation();deleteMessage(el)};ac2.appendChild(cb2);ac2.appendChild(sb2);ac2.appendChild(db2);wrap2.appendChild(ac2)}el.appendChild(wrap2);if(tm){var sp2=document.createElement("span");sp2.className="time";sp2.textContent=tm;el.appendChild(sp2)}cb.appendChild(el);cb.scrollTop=cb.scrollHeight;initCodeCopyButtons();return el}catch(e){console.error("addMessage error:",e);var err=document.createElement("div");err.className="msg error";err.textContent="⚠️ خطأ في عرض الرسالة";cb.appendChild(err);return null}}
 async function deleteMessage(el){if(!cid){showToast("لا توجد محادثة");return}if(!confirm("حذف هذه الرسالة؟"))return;try{var idx=Array.from(cb.children).indexOf(el),r=await fetch("/delete_message",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({conv_id:cid,index:idx})}),d=await r.json();if(d.status==="ok"){ch.splice(idx,1);el.remove();showToast("تم الحذف")}else showToast("فشل: "+d.message)}catch(e){showToast("خطأ")}}
 function showWelcome(){if(!sessionStorage.getItem("welcomeShown")){var ov=document.createElement("div");ov.className="welcome-overlay";ov.innerHTML='<div class="welcome-box"><h2>👋 أهلاً في نبراس</h2><p>كيف نساعدك؟</p></div>';document.body.appendChild(ov);sessionStorage.setItem("welcomeShown","true");setTimeout(function(){if(document.body.contains(ov)){ov.classList.add("fade-out");setTimeout(function(){if(document.body.contains(ov))ov.remove()},500)}},5000);var rm=function(){if(document.body.contains(ov)){ov.classList.add("fade-out");setTimeout(function(){if(document.body.contains(ov))ov.remove()},500)}document.removeEventListener("click",rm);ui.removeEventListener("keydown",rm)};document.addEventListener("click",rm);ui.addEventListener("keydown",rm)}}
 function showImagePreview(d){ip.src=d;ipc.style.display="flex"}function clearPending(){pid=null;ipc.style.display="none";ip.src=""}rib.onclick=clearPending;
 ui.oninput=function(){this.style.height="auto";this.style.height=Math.min(this.scrollHeight,80)+"px"};
 var poOpen=!1;pb.onclick=function(){poOpen=!poOpen;po.classList.toggle("show",poOpen);this.classList.toggle("rotate",poOpen)};document.addEventListener("click",function(e){if(pb&&po&&!pb.contains(e.target)&&!po.contains(e.target)){po.classList.remove("show");poOpen=!1;pb.classList.remove("rotate")}if(mt&&dd&&!mt.contains(e.target)&&!dd.contains(e.target))dd.classList.remove("show")});
 gb.onclick=function(){fi.click();po.classList.remove("show")};fi.onchange=function(e){if(this.files&&this.files.length>0){var r=new FileReader();r.onload=function(ev){pid=ev.target.result;showImagePreview(pid);fi.value=""};r.readAsDataURL(this.files[0])}};
 cab.onclick=function(){ci.click();po.classList.remove("show")};ci.onchange=function(e){if(this.files&&this.files.length>0){var r=new FileReader();r.onload=function(ev){pid=ev.target.result;showImagePreview(pid);ci.value=""};r.readAsDataURL(this.files[0])}};
 fib.onclick=function(){fig.click();po.classList.remove("show")};fig.onchange=function(e){if(this.files&&this.files.length>0){var r=new FileReader();r.onload=function(ev){pid=ev.target.result;showImagePreview(pid);fig.value=""};r.readAsDataURL(this.files[0])}};
 async function sendMessage(){if(iw)return;var t=ui.value.trim(),img=pid;if(!t&&!img)return;if(t)addMessage(t,"user");if(img){addMessage("صورة","user",!1,img);clearPending()}ui.value="";ui.style.height="auto";iw=!0;var td=document.createElement("div");td.className="msg bot typing-indicator";td.innerHTML='<span class="typing-dots">جاري التفكير</span>';cb.appendChild(td);cb.scrollTop=cb.scrollHeight;var payload={message:t||"مرفق",image:img||null,history:ch,conv_id:cid};try{var r=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),d=await r.json();td.remove();if(r.ok){addMessage(d.reply,"bot",!1,null,d.image_url);if(!im&&d.audio){if(ca){ca.pause();ca.currentTime=0}ca=new Audio("data:audio/mp3;base64,"+d.audio);ca.play()}if(d.conv_id)cid=d.conv_id}else addMessage("خطأ: "+(d.error||"مشكلة"),"error")}catch(e){td.remove();addMessage("تعذر الاتصال","error")}finally{iw=!1}}
 sb.onclick=sendMessage;ui.onkeypress=function(e){if(e.key==="Enter"){e.preventDefault();sendMessage()}};
 var recog=null;mb.onclick=function(){if(!("webkitSpeechRecognition"in window)){addMessage("المتصفح لا يدعم الصوت.","bot",!0);return}if(this.classList.contains("listening")){this.classList.remove("listening");if(recog)recog.stop();return}var SR=window.SpeechRecognition||window.webkitSpeechRecognition;recog=new SR();recog.lang="ar-SA";this.classList.add("listening");addMessage("جاري الاستماع...","bot",!0);recog.onresult=function(e){ui.value=e.results[0][0].transcript;mb.classList.remove("listening");setTimeout(function(){sendMessage()},300)};recog.onerror=function(){mb.classList.remove("listening")};recog.start()};
 showWelcome();window.deleteMyData=function(){if(!confirm("حذف جميع البيانات؟"))return;fetch("/delete_my_data",{method:"POST",headers:{"Content-Type":"application/json"}}).then(function(r){return r.json()}).then(function(d){if(d.status==="success"){alert("✅ تم الحذف");location.href="/"}else alert("❌ فشل: "+d.message)}).catch(function(e){alert("❌ خطأ")})};
 console.log("✅ نبراس جاهز");
})();
</script></body></html>'''
LH='''<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{font-family:"Segoe UI",sans-serif}body{background:#f0f2f5;display:flex;justify-content:center;align-items:center;height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:40px 30px;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;max-width:400px;text-align:center}h2{font-size:28px;color:#1a2b3c;margin-bottom:25px}input{width:100%;padding:14px 16px;margin:12px 0;border:1px solid #dce1e8;border-radius:12px;font-size:18px;background:#fafbfc;box-sizing:border-box}input:focus{outline:0;border-color:#4a6a8a}button{width:100%;padding:16px;background:#4a6a8a;color:#fff;border:none;border-radius:12px;font-size:20px;font-weight:700;cursor:pointer;margin-top:15px}button:hover{background:#3a5a7a}a{color:#4a6a8a;text-decoration:none;display:inline-block;margin-top:20px}.error{color:#d9534f;margin-bottom:15px}</style></head><body><div class="box"><h2>🔐 دخول</h2>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور" required><button type="submit">دخول</button></form><a href="/">⬅ الرئيسية</a><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:inline-block;margin-top:5px;font-size:12px;text-decoration:underline;">سياسة الخصوصية</a></div></body></html>'''
@app.route('/')
def index():return render_template_string(HT)
@app.route('/share/<cid>')
def shared_conversation(cid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor();c.execute("SELECT messages,title FROM conversations WHERE conv_id=?",(cid,));r=c.fetchone();conn.close()
 return render_template_string(SPH,messages=json.loads(r[0]),title=r[1] or "محادثة") if r else "⚠️ غير موجودة",404
@app.route('/login',methods=['GET','POST'])
@limiter.limit("3 per minute")
def login():
 if request.method=='POST':
  e=request.form.get('email');p=request.form.get('password');ae="abdullaha0569361@gmail.com";ap=os.environ.get("ADMIN_PASSWORD")
  if e==ae:
   if not ap:return render_template_string(LH,error="خطأ: كلمة مرور الأدمن غير مضبوطة")
   if secrets.compare_digest(p,ap):session.clear();session['admin_email']=ae;return redirect(url_for('index'))
   return render_template_string(LH,error="كلمة مرور خاطئة")
  elif e and "@" in e:session['user_email']=e;return redirect(url_for('index'))
  return render_template_string(LH,error="بريد غير صحيح")
 return render_template_string(LH)
@app.route('/logout')
def logout():session.clear();return redirect(url_for('index'))
@app.route('/history')
def history():
 uid=get_user_id();cs=get_user_conversations(uid);cs.sort(key=lambda x:x["timestamp"],reverse=True)
 return jsonify({"conversations":[{"id":c["id"],"title":c["title"]} for c in cs]})
@app.route('/load_conversation/<cid>')
def load_conversation(cid):
 uid=get_user_id();ms=load_conversation_by_id(uid,cid)
 return jsonify({"messages":ms}) if ms else (jsonify({"messages":None}),404)
@app.route('/delete_message',methods=['POST'])
def delete_message():
 try:
  d=request.get_json();cid=d.get('conv_id');idx=d.get('index');uid=get_user_id()
  if not cid or idx is None:return jsonify({"status":"error","message":"بيانات ناقصة"}),400
  msgs=load_conversation_by_id(uid,cid)
  if not msgs or idx<0 or idx>=len(msgs):return jsonify({"status":"error","message":"غير موجودة"}),404
  del msgs[idx];save_user_conversation(uid,msgs,cid);return jsonify({"status":"ok"})
 except Exception as e:return jsonify({"status":"error","message":str(e)}),500
@app.route('/delete_my_data',methods=['POST'])
def delete_my_data():
 uid=get_user_id();conn=sqlite3.connect(DB_FILE);c=conn.cursor();c.execute("DELETE FROM conversations WHERE user_id=?",(uid,));conn.commit();conn.close();session.clear()
 return jsonify({"status":"success","message":"تم الحذف"})
def get_user_id():
 if 'admin_email' in session:return "admin_"+session['admin_email']
 elif 'user_email' in session:return "user_"+session['user_email']
 else:
  rip=request.headers.get('X-Forwarded-For')
  return "guest_"+(rip.split(',')[0].strip() if rip else request.remote_addr or 'unknown')
@app.route('/set_gender',methods=['POST'])
def set_gender():d=request.get_json();session['voice_gender']=d.get('gender','male');return jsonify({"status":"ok"})
@app.route('/chat',methods=['POST'])
@limiter.limit("5 per minute")
def chat():
 try:
  d=request.get_json();um=d.get("message","").strip();cid=d.get("conv_id",None)
  if not um:return jsonify({"reply":"اكتب شيئاً"})
  is_admin='admin_email' in session and session['admin_email']=="abdullaha0569361@gmail.com"
  uid=get_user_id()
  if cid is None:sm[uid]=[]
  model=os.environ.get("OPENAI_MODEL")
  use_web=allow_img=is_admin
  draw_phrases=["ارسم لي","ابي صورة","ابي صوره","ابي صورت","صوره لي","ارسم","أنشئ","انشئ","انشى","صمم","ولّد","generate","draw","فيديو","ابي فيديو","عرض فيديو"]
  def is_image_request(t):
   t=t.lower().strip()
   if len(t.split())<=1:return False
   return any(t.startswith(p) or p in t for p in draw_phrases)
  if allow_img and is_image_request(um):
   is_video=any(k in um for k in ["فيديو","ابي فيديو","عرض فيديو"])
   if is_video:
    video_result=search_video(um)
    if video_result and video_result.startswith("ERROR:"):
     reply=f"⚠️ عذراً، ما قدرت أجيب الفيديو. السبب: {video_result.replace('ERROR:','')}"
     sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
     return jsonify({"reply":reply,"conv_id":nid})
    elif video_result:
     reply=f"🎬 إليك الفيديو:\n{video_result}"
     sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
     return jsonify({"reply":reply,"image_url":video_result,"conv_id":nid})
    else:
     reply="⚠️ عذراً، تعذر جلب الفيديو."
     sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
     return jsonify({"reply":reply,"conv_id":nid})
   img_result=generate_image(um)
   if img_result and img_result.startswith("ERROR:"):
    reply=f"⚠️ عذراً، ما قدرت أولد الصورة. السبب: {img_result.replace('ERROR:','')}"
    sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
    return jsonify({"reply":reply,"conv_id":nid})
   elif img_result:
    reply=f"🖼️ الصورة:\n{img_result}"
    sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
    return jsonify({"reply":reply,"image_url":img_result,"conv_id":nid})
   else:
    reply="⚠️ تعذر توليد الصورة."
    sm[uid].append({"role":"user","content":um});sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
    return jsonify({"reply":reply,"conv_id":nid})
  sm[uid].append({"role":"user","content":um});ch=sm[uid][-10:];msgs=[{"role":"system","content":SP}]+[{"role":e["role"],"content":e["content"]} for e in ch]
  img_data=d.get("image",None)
  if img_data and is_admin:msgs.append({"role":"user","content":[{"type":"text","text":um or "حلل هذه الصورة"},{"type":"image_url","image_url":{"url":img_data}}]})
  if use_web:
   try:
    fc="".join(f"{m['role']}: {m['content']}\n" for m in msgs)
    sr=client.responses.create(model=model,instructions=f"{SP}\n\nسياق المحادثة:\n{fc}",input=f"ابحث عن: {um}، وملخص.",tools=[{"type":"web_search"}])
    if sr.output_text.strip():msgs.append({"role":"user","content":f"نتيجة البحث:\n{sr.output_text}"})
   except Exception as e:print(f"⚠️ فشل البحث: {e}")
  try:
   r=client.chat.completions.create(model=model,messages=msgs,max_completion_tokens=1000,temperature=0.8);reply=r.choices[0].message.content.strip() or "ما قدرت أجيب رد."
  except Exception as e:return jsonify({"error":str(e)}),500
  # دمج الأسطر إلى فقرات
  paras=[];cur=[]
  for line in reply.split('\n'):
   line=line.strip()
   if not line:
    if cur:paras.append(' '.join(cur));cur=[]
   else:cur.append(line)
  if cur:paras.append(' '.join(cur))
  reply='\n\n'.join(paras)
  sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
  audio=None
  try:audio=generate_speech(reply,session.get('voice_gender','male'))
  except:pass
  return jsonify({"reply":reply,"audio":audio,"conv_id":nid})
 except Exception as e:print(f"❌ خطأ: {e}");return jsonify({"error":str(e)}),500
@app.route('/tools')
def tools():return render_template_string(TOOLS_HTML)
@app.route('/robots.txt')
def serve_robots():return send_from_directory('static','robots.txt')
@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):return send_from_directory('.well-known',filename)
@app.route('/<path:filename>')
def serve_static_files(filename):return send_from_directory(app.static_folder,filename)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
