from flask import Flask,request,jsonify,render_template_string,session,redirect,url_for,send_from_directory
import openai,os,secrets,json,hashlib,asyncio,edge_tts,base64,re,sqlite3,requests
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
app=Flask(__name__,static_folder='static')
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(16))
OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:raise Exception("OPENAI_API_KEY غير موجود!")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise Exception("OPENAI_MODEL غير موجود! أضفه في متغيرات البيئة.")

client=openai.OpenAI(api_key=OPENAI_API_KEY)
limiter=Limiter(key_func=get_remote_address,default_limits=["500 per day","20 per hour"])
limiter.init_app(app)

# ====== خدمة الملفات الثابتة ======
@app.route('/robots.txt')
def serve_robots():return send_from_directory('static','robots.txt')

# ====== مسار عام لخدمة جميع الملفات من مجلد .well-known في الجذر ======
@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):
    return send_from_directory('.well-known', filename)
# ======================================================

DB_FILE="conversations.db"
def init_db():
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 c.execute('''CREATE TABLE IF NOT EXISTS conversations (user_id TEXT, conv_id TEXT, messages TEXT, timestamp TEXT, title TEXT)''')
 conn.commit();conn.close()
def get_user_conversations(uid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 c.execute("SELECT conv_id,messages,timestamp,title FROM conversations WHERE user_id=?",(uid,));rows=c.fetchall();conn.close();res=[]
 for r in rows:res.append({"id":r[0],"messages":json.loads(r[1]),"timestamp":r[2],"title":r[3]})
 return res
def save_user_conversation(uid,conv,cid=None):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor()
 if cid is None:
  title=conv[0]["content"][:30]+"..." if len(conv[0]["content"])>30 else conv[0]["content"]
  nid=hashlib.md5(f"{uid}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
  c.execute("INSERT INTO conversations (user_id,conv_id,messages,timestamp,title) VALUES (?,?,?,?,?)",(uid,nid,json.dumps(conv),datetime.now().isoformat(),title))
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

# ====== نظام التعليمات المعدل ======
SP=f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.
**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.
3. **البحث بالويب** تستخدمه عندما يسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.
**ملف المعرفة الخاص بك:**
{kc}

**⚠️ قاعدة التنسيق الذهبية (الأهم):**
- اكتب ردودك في **فقرات نصية متصلة**. كل فقرة تحتوي على **2 إلى 4 جمل** فقط.
- **ممنوع** وضع كل جملة في سطر منفصل. استخدم النقاط والفواصل وعلامات الترقيم داخل الفقرة نفسها.
- **ممنوع** وضع فواصل أسطر (`Enter`) بين الجمل. الفاصل الوحيد المسموح به هو سطر فارغ بين الفقرة والأخرى.
- اجعل الجملة الواحدة بطول معتدل (حوالي 10-20 كلمة)، بحيث تكون واضحة ومختصرة لكنها تحمل فكرة كاملة.
- مثال على الشكل المطلوب (فقرة جيدة): "أهلاً بك، كيف حالك اليوم؟ هذا سؤال جميل يحتاج لتفكير بسيط. الرياض تعتبر من أفضل المدن للعيش في السعودية. تتميز بجوها الحضاري ومشاريعها الحديثة."
- مثال ممنوع (جمل قصيرة متفرقة): "أهلاً بك. كيف حالك؟ هذا سؤال جميل. الرياض مدينة رائعة."

**تعليمات إضافية:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة في ملف المعرفة، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- لا تكتب "لحظة" أو "انتظر"، فقط انتظر النتيجة ورد مباشرة.
"""
# ======================================================

def remove_emoji(t):
 return re.compile("["+u"\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002702-\U000027B0\U000024C2-\U0001F251\U0001f926-\U0001f937\U00010000-\U0010ffff\u2640-\u2642\u2600-\u2B55\u200d\u23cf\u23e9\u231a\ufe0f\u3030"+"]+",flags=re.UNICODE).sub('',t)

# ====== دالة توليد الصورة باستخدام Pexels API ======
def generate_image(prompt):
    try:
        api_key = os.environ.get("PEXELS_API_KEY")
        if not api_key:
            return "ERROR: PEXELS_API_KEY غير موجود في البيئة"
        query = requests.utils.quote(prompt)
        url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape"
        headers = {"Authorization": api_key}
        response = requests.get(url, headers=headers)
        data = response.json()
        if response.status_code == 200 and data.get("photos") and len(data["photos"]) > 0:
            return data["photos"][0]["src"]["large"]
        else:
            error_msg = data.get('error', 'لم أجد صورة مناسبة')
            return f"ERROR: {error_msg}"
    except Exception as e:
        return f"ERROR: {str(e)}"

# ====== دالة البحث عن فيديو باستخدام Pexels API ======
def search_video(prompt):
    try:
        api_key = os.environ.get("PEXELS_API_KEY")
        if not api_key:
            return "ERROR: PEXELS_API_KEY غير موجود في البيئة"
        query = requests.utils.quote(prompt)
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=1"
        headers = {"Authorization": api_key}
        response = requests.get(url, headers=headers)
        data = response.json()
        if response.status_code == 200 and data.get("videos") and len(data["videos"]) > 0:
            video_files = data["videos"][0]["video_files"]
            for vf in video_files:
                if vf.get("quality") == "hd" and vf.get("link"):
                    return vf["link"]
            if video_files and video_files[0].get("link"):
                return video_files[0]["link"]
            return "ERROR: ما لقيت رابط فيديو"
        else:
            error_msg = data.get('error', 'لم أجد فيديو مناسباً')
            return f"ERROR: {error_msg}"
    except Exception as e:
        return f"ERROR: {str(e)}"

# ==================== دالة الصوت المعدلة (edge_tts) ====================
def generate_speech(text, gender):
    try:
        if gender == "female":
            voice = "ar-SA-ZariyahNeural"
        else:
            voice = "ar-SA-HamedNeural"
        communicate = edge_tts.Communicate(text, voice)
        audio_data = bytearray()
        async def collect_audio():
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])
        asyncio.run(collect_audio())
        return base64.b64encode(audio_data).decode('utf-8')
    except Exception as e:
        print(f"❌ فشل الصوت: {e}")
        return None
# ======================================================================

# ====== تم إصلاح الثغرة هنا: إزالة |safe وترميز المحتوى ======
SPH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>📄 محادثة نبراس</title><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css"><style>*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}body{background:#f4f7fc;display:flex;justify-content:center;align-items:center;min-height:100dvh;padding:20px}.container{max-width:700px;width:100%;background:#fff;border-radius:24px;box-shadow:0 10px 40px rgba(0,0,0,0.08);padding:30px 25px}.header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #eaeef2;padding-bottom:15px;margin-bottom:25px}.header h1{font-size:22px;color:#1a2b3c}.header a{color:#4a6a8a;text-decoration:none;font-size:15px}.msg{display:flex;margin-bottom:18px;gap:10px}.msg .avatar{width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;flex-shrink:0;font-size:14px}.msg.user .avatar{background:#eaeef2;color:#1a2b3c}.msg.bot .avatar{background:#4a6a8a;color:#fff}.msg .content{background:#f5f7fa;padding:12px 18px;border-radius:16px;border-top-right-radius:4px;max-width:85%;line-height:1.8;color:#111;white-space:normal;word-wrap:break-word;overflow-wrap:break-word}.msg.user .content{background:#eaeef2}.msg.bot .content{background:#f5f7fa}.msg .content p{margin-bottom:8px}.msg .content p:last-child{margin-bottom:0}.msg .time{font-size:11px;color:#8b949e;margin-top:4px;display:block}.footer{text-align:center;margin-top:30px;padding-top:20px;border-top:1px solid #eaeef2;color:#8b949e;font-size:14px}.footer a{color:#4a6a8a;text-decoration:none;font-weight:700}@media(max-width:500px){.container{padding:15px}.msg .content{max-width:100%}}</style></head></body><div class="container"><div class="header"><h1>💬 {{ title or 'محادثة نبراس' }}</h1><a href="/">⬅ الرئيسية</a></div><div>{% for msg in messages %}<div class="msg {{ 'user' if msg.role == 'user' else 'bot' }}"><div class="avatar">{{ '👤' if msg.role == 'user' else '🤖' }}</div><div class="content">{{ msg.content|e|replace('\n','<br>')|safe }}</div></div>{% endfor %}</div><div class="footer">تمت المشاركة من <a href="/">نبراس</a> - مساعد ذكي</div></div></body></html>"""
# ============================================================

TOOLS_HTML="""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>أدوات  </title><style>body{font-family:'Segoe UI',Tahoma; background:#0f172a; color:#fff; margin:0; padding:20px}.container{max-width:900px; margin:auto}h1{text-align:center; color:#38bdf8}a{color:#38bdf8}.card{background:#1e293b; border-radius:15px; padding:20px; margin:20px 0; border:1px solid #334155}input,select,textarea{width:100%; padding:12px; margin:8px 0; border-radius:8px; border:none; background:#0f172a; color:#fff}button{background:#38bdf8; color:#000; padding:12px 20px; border:none; border-radius:8px; font-weight:bold; cursor:pointer; width:100%}button:hover{background:#0ea5e9}.result{background:#0f172a; padding:15px; border-radius:8px; margin-top:10px; border:1px dashed #38bdf8}.grid{display:grid; grid-template-columns:1fr 1fr; gap:15px}@media(max-width:600px){.grid{grid-template-columns:1fr}}</style></head><body><div class="container"><h1>    </h1><p style="text-align:center; color:#94a3b8">أدوات سريعة وذكية تخدمك بشكل فوري  </p><p style="text-align:center"><a href="/">⬅ ارجع لنبراس</a></p><div class="card"><h3>📚 1- حاسبة المعدل الجامعي GPA</h3><div class="grid"><input id="gpa1" placeholder="عدد الساعات - مادة 1" type="number"><select id="grade1"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><div class="grid"><input id="gpa2" placeholder="عدد الساعات - مادة 2" type="number"><select id="grade2"><option value="5">A+ (5)</option><option value="4.75">A (4.75)</option><option value="4.5">B+ (4.5)</option><option value="4">B (4)</option><option value="3.5">C+ (3.5)</option><option value="3">C (3)</option></select></div><button onclick="calcGPA()">احسب معدلي</button><div id="gpaRes" class="result" style="display:none"></div></div><div class="card"><h3>📝 2- منشئ السيرة الذاتية ATS</h3><input id="cvName" placeholder="الاسم الكامل"><input id="cvSpec" placeholder="التخصص - مثلا: أمن سيبراني"><textarea id="cvExp" placeholder="خبراتك باختصار"></textarea><button onclick="makeCV()">أنشئ سيرتي</button><div id="cvRes" class="result" style="display:none"></div></div><div class="card"><h3>💰 3- حاسبة حساب المواطن التقريبية</h3><input id="family" type="number" placeholder="عدد أفراد الأسرة"><input id="income" type="number" placeholder="إجمالي الدخل الشهري"><button onclick="calcCitizen()">احسب الدعم التقريبي</button><div id="citRes" class="result" style="display:none"></div></div><div class="card"><h3>💡 4- مولد أفكار مشاريع </h3><select id="budget"><option value="5000">رأس مال 5 آلاف</option><option value="10000">10 آلاف</option><option value="20000">20 ألف</option><option value="50000">50 ألف</option></select><button onclick="genIdea()">عطني فكرة مشروع</button><div id="ideaRes" class="result" style="display:none"></div></div></div><script>function calcGPA(){let h1=parseFloat(document.getElementById('gpa1').value)||0;let g1=parseFloat(document.getElementById('grade1').value)||0;let h2=parseFloat(document.getElementById('gpa2').value)||0;let g2=parseFloat(document.getElementById('grade2').value)||0;if(h1==0&&h2==0){alert('دخل ساعات');return;}let total=(h1*g1+h2*g2)/(h1+h2);document.getElementById('gpaRes').style.display='block';document.getElementById('gpaRes').innerHTML='معدلك التقريبي: <b style="color:#38bdf8; font-size:22px">'+total.toFixed(2)+'</b> / 5';}function makeCV(){let n=document.getElementById('cvName').value;let s=document.getElementById('cvSpec').value;let e=document.getElementById('cvExp').value;if(!n){alert('اكتب اسمك');return;}let cv=`السيرة الذاتية\nالاسم: ${n}\nالتخصص: ${s}\n\nالخبرات:\n${e}\n\nالمهارات:\n- العمل تحت الضغط\n- اللغة الإنجليزية\n- الحاسب الآلي\n\nالهدف: الحصول على وظيفة في مجال ${s} والمساهمة في رؤية 2030`;document.getElementById('cvRes').style.display='block';document.getElementById('cvRes').innerText=cv;}function calcCitizen(){let f=parseInt(document.getElementById('family').value)||1;let inc=parseInt(document.getElementById('income').value)||0;let support=0;if(inc<3000)support=f*400;else if(inc<6000)support=f*300;else support=f*150;if(support>3000)support=3000;document.getElementById('citRes').style.display='block';document.getElementById('citRes').innerHTML='الدعم التقريبي المتوقع: <b style="color:#22c55e">'+support+' ريال</b><br><small>هذا حساب تقريبي فقط، الرقم الرسمي من حساب المواطن</small>';}const ideas={'5000':['متجر إلكتروني منتجات محلية','خدمة كتابة بحوث للطلاب','تصميم سير ذاتية'],'10000':['مغسلة ملابس متنقلة','عربة فود ترك قهوة مختصة','متجر تغليف هدايا'],'20000':['مشروع دروس خصوصية أونلاين','استوديو تصوير صغير','محل اكسسوارات جوالات'],'50000':['مقهى طلابي قرب الجامعة','شركة توصيل داخلي','مركز تدريب حاسب']};function genIdea(){let b=document.getElementById('budget').value;let list=ideas[b];let rnd=list[Math.floor(Math.random()*list.length)];document.getElementById('ideaRes').style.display='block';document.getElementById('ideaRes').innerHTML='💡 فكرة مقترحة برأس مال '+b+' ريال:<br><b style="color:#facc15; font-size:18px">'+rnd+'</b><br><br>اسأل نبراس: "سوي لي دراسة جدوى لـ '+rnd+'"';}</script></body></html>"""

HT=r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0,user-scalable=yes"/><meta name="google-site-verification" content="PyOhY3ZXN4LTBbK55EbrmeI5A5kqddF3cJeI_s1FwVc"/><meta http-equiv="Content-Language" content="ar"/><title>نبراس GP | مساعد ذكي سعودي - أسئلة، صور، وصوت</title><meta name="description" content="نبراس GP هو مساعدك الذكي العربي الموثوق. يقدم إجابات فورية ودقيقة حول أي موضوع، يولّد لك صوراً إبداعية، ويحول النص إلى كلام مسموع. اختصر وقتك وزد إنتاجيتك مع أقوى ذكاء اصطناعي عربي." /><meta name="keywords" content="مساعد ذكي عربي, ذكاء اصطناعي بالعربي, نبراس, AI عربي, مساعد صوتي, توليد صور, روبوت دردشة, حلول فورية" /><meta property="og:title" content="نبراس GP | مساعد ذكي سعودي - أسئلة، صور، وصوت" /><meta property="og:description" content="احصل على إجابات فورية، صور إبداعية، وصوت بشري واضح. مساعدك الذكي العربي الشامل." /><meta property="og:url" content="https://nibras-al.onrender.com/" /><meta property="og:image" content="https://nibras-al.onrender.com/static/icon-512.png" /><link rel="manifest" href="/static/manifest.json"/><link rel="icon" type="image/png" href="/static/icon-512.png"/><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css"/><style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#6a7b8c;--welcome-bg:#fff;--border-input:#dce1e8;--btn-gold-bg:#f1c40f;--btn-gold-text:#1a2b3c;--mute-muted:#444;--mute-hover:#1a2b3c;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--mic-active-bg:#fde8e8;--mic-active-color:#c33;--remove-btn-hover:#fde8e8;--modal-bg:rgba(0,0,0,0.5)}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-bot-msg:transparent;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#8b949e;--welcome-bg:#161b22;--border-input:#30363d;--btn-gold-bg:#d29922;--btn-gold-text:#0d1117;--mute-muted:#484f58;--mute-hover:#c9d1d9;--send-bg:#238636;--send-hover:#2ea043;--mic-active-bg:#2d1b1b;--mic-active-color:#f85149;--remove-btn-hover:#2d1b1b;--modal-bg:rgba(0,0,0,0.7)}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body);transition:background .3s}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;transition:background .3s;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}@media(orientation:landscape) and (max-width:599px){.app{max-width:100%;border-radius:0;box-shadow:none;top:0;left:0;right:0;bottom:0;transform:none;height:100%;max-height:100%}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;border-bottom:1px solid var(--border-color);flex-shrink:0;background:var(--bg-header);transition:background .3s}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.menu-btn{background:0 0;border:none;font-size:20px;color:var(--text-secondary);cursor:pointer;padding:4px 8px}.mute-btn{background:0 0;border:none;font-size:20px;color:var(--text-secondary);cursor:pointer;padding:4px 8px;transition:color .2s}.mute-btn:hover{color:var(--mute-hover)}.mute-btn.muted{color:var(--mute-muted);opacity:.4;transform:scale(.9);transition:all .2s}.btn-group{display:flex;gap:8px}.btn{padding:6px 16px;border-radius:20px;font-size:14px;border:none;cursor:pointer;text-decoration:none;display:inline-block;text-align:center}.btn-outline{background:0 0;border:1px solid var(--primary-color);color:var(--primary-color)}.btn-gold{background:var(--btn-gold-bg);color:var(--btn-gold-text);font-weight:700}.dropdown{position:absolute;top:64px;left:14px;right:14px;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 8px 30px var(--shadow-color);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:60vh;overflow-y:auto}.dropdown.show{display:flex}.dropdown .item{display:flex;align-items:center;gap:12px;padding:14px 18px;font-size:15px;color:var(--text-primary);background:0 0;border:none;width:100%;text-align:right;cursor:pointer;border-bottom:1px solid var(--border-color)}.dropdown .item:last-child{border-bottom:none}.dropdown .item i{width:22px;font-size:18px;color:var(--text-secondary)}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .conv-item{display:block;padding:12px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;width:100%;background:0 0;border:none;text-align:right;font-size:16px;color:var(--text-primary);font-weight:500;transition:background .2s}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item:last-child{border-bottom:none}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:16px;transition:background .3s;min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:16px;font-weight:600;line-height:1.7;word-wrap:break-word;white-space:normal;color:var(--text-primary);transition:background .3s,color .3s;position:relative}.msg.user{align-self:flex-end;background:var(--bg-user-msg);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.35;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.msg .generated-video{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;border-bottom-right-radius:6px;font-size:16px;font-weight:600;color:var(--text-secondary)}.typing-dots{display:inline-block}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}.welcome-overlay{position:fixed;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);z-index:9999;animation:fadeIn .5s ease;pointer-events:none}.welcome-overlay .welcome-box{background:var(--welcome-bg);padding:30px 40px;border-radius:20px;box-shadow:0 10px 40px var(--shadow-color);text-align:center;max-width:90%;pointer-events:auto;direction:rtl;border:1px solid var(--border-color)}.welcome-overlay .welcome-box h2{font-size:28px;color:var(--text-primary);margin-bottom:8px}.welcome-overlay .welcome-box p{font-size:18px;color:var(--text-secondary);margin:0}@keyframes fadeIn{from{opacity:0;transform:scale(.9)}to{opacity:1;transform:scale(1)}}.welcome-overlay.fade-out{animation:fadeOut .5s ease forwards}@keyframes fadeOut{from{opacity:1;transform:scale(.9)}to{opacity:0;transform:scale(.9)}}#imagePreviewContainer{display:none;padding:6px 18px;align-items:center;gap:10px;background:var(--bg-input);margin:0 14px;border-radius:20px 20px 0 0;border:1px solid var(--border-color);border-bottom:none;flex-wrap:wrap;flex-shrink:0}#imagePreviewContainer img{max-height:60px;border-radius:8px;border:1px solid var(--border-color)}#imagePreviewContainer .label{font-size:13px;color:var(--text-secondary)}#removeImageBtn{background:0 0;border:none;color:var(--danger-color);font-size:14px;cursor:pointer;padding:4px 8px;border-radius:12px}#removeImageBtn:hover{background:var(--remove-btn-hover)}.input-area{display:flex;align-items:flex-end;justify-content:center;gap:8px;padding:8px 14px;margin:8px 14px 16px;background:var(--bg-input);border-radius:40px;border:1px solid var(--border-color);flex-shrink:0;min-height:60px}.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:18px;font-weight:600;outline:0;color:var(--text-primary);direction:rtl;resize:none;overflow:hidden;min-height:20px;max-height:80px;font-family:'Segoe UI',Arial,sans-serif;line-height:1.4}.input-area textarea::placeholder{color:var(--placeholder-color)}.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);font-size:20px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0}.input-area .btn-icon:hover{background:var(--bg-hover)}.input-area .mic-btn{color:var(--primary-color)}.input-area .mic-btn.listening{color:var(--mic-active-color);background:var(--mic-active-bg)}.input-area .send{background:var(--send-bg);color:#fff;border:none;width:44px;height:44px;border-radius:50%;font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 2px 8px var(--send-shadow)}.input-area .send:hover{background:var(--send-hover)}.plus-btn{background:0 0;border:none;color:var(--primary-color);font-size:24px;cursor:pointer;padding:4px;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.3s}.plus-btn:hover{background:var(--bg-hover)}.plus-btn.rotate{transform:rotate(45deg)}.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:6px;flex-direction:row;border:1px solid var(--border-color);z-index:50}.plus-options.show{display:flex}.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-size:20px;color:var(--text-primary);cursor:pointer;transition:.2s}.plus-options .option-btn:hover{background:var(--border-color)}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}.dropdown{top:58px;left:10px;right:10px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px;font-size:14px}.input-area .btn-icon{width:32px;height:32px;font-size:16px}.plus-btn{width:32px;height:32px;font-size:18px}.msg .image-upload{max-height:150px}#imagePreviewContainer{padding:4px 14px}#imagePreviewContainer img{max-height:50px}.welcome-overlay .welcome-box{padding:20px 25px}.welcome-overlay .welcome-box h2{font-size:22px}.welcome-overlay .welcome-box p{font-size:16px}}.gender-option{flex:1;padding:8px 4px;border-radius:10px;border:1px solid var(--border-color);background:0 0;font-size:14px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s;display:flex;align-items:center;justify-content:center;gap:4px}.gender-option:hover{background:var(--bg-hover)}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color)}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px;backdrop-filter:blur(4px)}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color);box-shadow:0 20px 60px var(--shadow-color)}.share-modal .box h3{font-size:22px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:15px;font-weight:600;border:none;cursor:pointer;transition:transform .15s;flex:1 0 auto;justify-content:center;min-width:70px}.share-modal .box .share-btn:hover{transform:scale(1.03)}.share-modal .box .share-btn.whatsapp{background:#25D366;color:#fff}.share-modal .box .share-btn.facebook{background:#1877F2;color:#fff}.share-modal .box .share-btn.twitter{background:#000;color:#fff}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:16px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600}.share-modal .box .close-btn:hover{background:var(--border-color)}@media(max-width:400px){.share-modal .box .share-btn{font-size:13px;padding:8px 12px}}.bot-content{white-space:normal;word-wrap:break-word;overflow-wrap:break-word}.bot-content p{margin:0 0 10px}.bot-content p:last-child{margin-bottom:0}
.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;font-size:14px;padding:4px 8px;border-radius:8px;transition:all .2s;opacity:0.5;margin-right:4px}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}
/* ====== أزرار تحت النص ====== */
.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap;justify-content:flex-start}
.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;font-size:14px;padding:4px 8px;border-radius:8px;transition:all .2s;opacity:0.4}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999;animation:toastIn .3s ease;direction:rtl;pointer-events:none}@keyframes toastIn{from{opacity:0;transform:translateX(-50%) translateY(20px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}@keyframes toastOut{from{opacity:1;transform:translateX(-50%) translateY(0)}to{opacity:0;transform:translateX(-50%) translateY(20px)}}
.code-block-wrapper{position:relative;margin:16px 0;border-radius:14px;border:1px solid var(--border-color);background:var(--bg-input);overflow:hidden;display:block;width:100%;overflow-x:auto;box-shadow:0 2px 8px rgba(0,0,0,0.05)}.code-block-wrapper pre{margin:0;padding:20px 60px 20px 24px;background:transparent;border:none;border-radius:0;white-space:pre;word-break:normal;font-size:15px;line-height:1.8;font-family:'Courier New',Consolas,monospace;direction:ltr;text-align:left}.code-block-wrapper .copy-code-btn{position:absolute;top:12px;left:14px;background:var(--bg-hover);border:1px solid var(--border-color);color:var(--text-secondary);border-radius:10px;padding:8px 18px;font-size:14px;font-weight:700;cursor:pointer;transition:all .2s ease;z-index:5;display:flex;align-items:center;gap:6px}.code-block-wrapper .copy-code-btn:hover{background:var(--primary-color);color:#fff;border-color:var(--primary-color);transform:scale(1.02)}.code-block-wrapper .copy-code-btn.copied{background:#28a745;color:#fff;border-color:#28a745}
</style></head><body><div class="app"><div class="header"><div class="header-right"><button class="mute-btn" id="muteBtn"><i class="fas fa-volume-up"></i></button><button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button></div><div class="header-left"><div class="btn-group">{% if session.get('admin_email') or session.get('user_email') %}<a href="/logout" class="btn btn-outline">تسجيل خروج</a>{% else %}<a href="/login" class="btn btn-outline">دخول</a>{% endif %}</div></div></div><div class="dropdown" id="dropdown"><button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
<button class="item" onclick="window.location.href='/tools'"><i class="fas fa-tools"></i>  أدوات مجانية</button>
<button class="item" data-action="share"><i class="fas fa-share-alt"></i> مشاركة المحادثة</button><button class="item" onclick="deleteMyData()" style="color: #ff4d4d;"><i class="fas fa-trash-alt"></i> حذف حسابي</button><button class="item" data-action="theme-toggle"><i class="fas fa-moon"></i> <span id="themeLabel">الوضع الليلي</span></button><div class="item" style="flex-direction:column;align-items:stretch;gap:6px;cursor:default;border-bottom:1px solid var(--border-color)"><div style="display:flex;align-items:center;gap:8px;font-size:14px;color:var(--text-primary)"><i class="fas fa-microphone" style="font-size:18px;color:var(--text-secondary)"></i><span>صوت المساعد</span></div><div style="display:flex;gap:8px"><button class="gender-option active" data-gender="male">👨 ذكر</button><button class="gender-option" data-gender="female">👩 أنثى</button></div></div><div id="historyList"></div></div><div id="chat"></div><div id="imagePreviewContainer"><img id="imagePreview" src=""/><span class="label">📎 صورة معلقة</span><button id="removeImageBtn">✕ إزالة</button></div><div class="input-area"><button class="btn-icon mic-btn" id="micBtn"><i class="fas fa-microphone"></i></button><button class="plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button><div class="plus-options" id="plusOptions"><button class="option-btn camera" id="cameraBtn"><i class="fas fa-camera"></i></button><button class="option-btn gallery" id="galleryBtn"><i class="fas fa-images"></i></button><button class="option-btn files" id="filesBtn"><i class="fas fa-folder"></i></button></div><textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea><button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button></div><input type="file" id="fileInput" accept="image/*" style="display:none"/><input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none"/><input type="file" id="fileInputGeneric" style="display:none"/></div><div class="share-modal" id="shareModal"><div class="box"><h3><i class="fas fa-share-alt" style="color:var(--primary-color)"></i> شارك المحادثة</h3><div class="share-grid"><a href="#" id="shareWhatsapp" target="_blank" class="share-btn whatsapp"><i class="fab fa-whatsapp"></i> واتساب</a><a href="#" id="shareFacebook" target="_blank" class="share-btn facebook"><i class="fab fa-facebook"></i> فيسبوك</a><a href="#" id="shareTwitter" target="_blank" class="share-btn twitter"><i class="fab fa-x-twitter"></i> X</a><button id="shareSnapchat" class="share-btn snapchat"><i class="fab fa-snapchat"></i> سناب شات</button></div><button class="close-btn" onclick="document.getElementById('shareModal').classList.remove('show')">إلغاء</button></div></div><script>
// ====== بداية الكود مع تحسينات التوافق ومعالج الأخطاء ======
(function(){
    console.log("✅ بدء تشغيل نبراس (JS)");

    // معالج الأخطاء العام لعرض أي خطأ في شاشة المحادثة
    window.onerror = function(msg, url, line, col, error) {
        var errMsg = '⚠️ خطأ في الجافا سكريبت: ' + msg;
        console.error(errMsg);
        var chatEl = document.getElementById('chat');
        if (chatEl) {
            var errDiv = document.createElement('div');
            errDiv.className = 'msg error';
            errDiv.textContent = errMsg + ' (انظر سجلات الخادم)';
            chatEl.appendChild(errDiv);
        }
        return true;
    };

    try {
        var ch=[], pid=null, iw=false, cid=null, ca=null;
        var cb = document.getElementById('chat');
        var ui = document.getElementById('userInput');
        var sb = document.getElementById('sendBtn');
        var mb = document.getElementById('micBtn');
        var fi = document.getElementById('fileInput');
        var ci = document.getElementById('cameraInput');
        var mt = document.getElementById('menuToggle');
        var dd = document.getElementById('dropdown');
        var pb = document.getElementById('plusBtn');
        var po = document.getElementById('plusOptions');
        var cab = document.getElementById('cameraBtn');
        var gb = document.getElementById('galleryBtn');
        var fib = document.getElementById('filesBtn');
        var fig = document.getElementById('fileInputGeneric');
        var ipc = document.getElementById('imagePreviewContainer');
        var ip = document.getElementById('imagePreview');
        var rib = document.getElementById('removeImageBtn');
        var hl = document.getElementById('historyList');
        var sm = document.getElementById('shareModal');

        // التحقق من وجود العناصر الأساسية
        if (!cb) console.warn("⚠️ #chat غير موجود");
        if (!ui) console.warn("⚠️ #userInput غير موجود");
        if (!sb) console.warn("⚠️ #sendBtn غير موجود");
        if (!mt) console.warn("⚠️ #menuToggle غير موجود");

        // إذا كانت العناصر الأساسية مفقودة، نعرض خطأ في الشاشة
        if (!sb || !ui) {
            if (cb) {
                var errDiv = document.createElement('div');
                errDiv.className = 'msg error';
                errDiv.textContent = '❌ فشل تحميل الواجهة، حاول تحديث الصفحة.';
                cb.appendChild(errDiv);
            }
            return;
        }

        var im = true;
        var mut = document.getElementById('muteBtn');
        if (mut) {
            var muteIcon = mut.querySelector('i');
            if (muteIcon) muteIcon.className = 'fas fa-volume-mute';
            mut.classList.add('muted');
            mut.addEventListener('click', function(){
                im = !im;
                var ic = mut.querySelector('i');
                if (im) {
                    if (ic) ic.className = 'fas fa-volume-mute';
                    mut.classList.add('muted');
                    if (ca) { ca.pause(); ca.currentTime = 0; }
                } else {
                    if (ic) ic.className = 'fas fa-volume-up';
                    mut.classList.remove('muted');
                }
            });
        }

        var isMale = true;
        var gopts = document.querySelectorAll('.gender-option');
        if (mt) {
            mt.addEventListener('click', function(e){
                e.stopPropagation();
                dd.classList.toggle('show');
                if (dd.classList.contains('show')) {
                    loadHistory();
                    gopts.forEach(function(b){ b.classList.remove('active'); });
                    if (isMale) {
                        var maleBtn = document.querySelector('.gender-option[data-gender="male"]');
                        if (maleBtn) maleBtn.classList.add('active');
                    } else {
                        var femaleBtn = document.querySelector('.gender-option[data-gender="female"]');
                        if (femaleBtn) femaleBtn.classList.add('active');
                    }
                }
            });
        }

        gopts.forEach(function(b){
            b.addEventListener('click', function(e){
                e.stopPropagation();
                var g = this.dataset.gender;
                isMale = (g === 'male');
                gopts.forEach(function(x){ x.classList.remove('active'); });
                this.classList.add('active');
                fetch('/set_gender', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ gender: g })
                }).catch(function(err){ console.error("خطأ في ضبط الجنس:", err); });
                if (dd) dd.classList.remove('show');
            });
        });

        async function loadHistory() {
            try {
                var r = await fetch('/history');
                if (!r.ok) throw new Error("فشل تحميل التاريخ");
                var d = await r.json();
                if (hl) {
                    hl.innerHTML = '';
                    if (d.conversations && d.conversations.length > 0) {
                        d.conversations.forEach(function(c){
                            var b = document.createElement('button');
                            b.className = 'conv-item';
                            b.textContent = c.title;
                            b.onclick = function() { loadConversation(c.id); };
                            hl.appendChild(b);
                        });
                    } else {
                        var e = document.createElement('div');
                        e.className = 'item';
                        e.textContent = '📭 لا توجد محادثات سابقة';
                        hl.appendChild(e);
                    }
                }
            } catch(e) {
                console.error('خطأ في تحميل المحادثات:', e);
                if (cb) {
                    var errDiv = document.createElement('div');
                    errDiv.className = 'msg error';
                    errDiv.textContent = '⚠️ فشل تحميل المحادثات السابقة';
                    cb.appendChild(errDiv);
                }
            }
        }

        async function loadConversation(id) {
            try {
                var r = await fetch('/load_conversation/' + id);
                if (!r.ok) throw new Error("فشل تحميل المحادثة");
                var d = await r.json();
                if (d.messages && cb) {
                    cb.innerHTML = '';
                    ch = d.messages;
                    cid = id;
                    d.messages.forEach(function(m){
                        var s = (m.role === 'user') ? 'user' : 'bot';
                        addMessage(m.content, s, true);
                    });
                    if (dd) dd.classList.remove('show');
                }
            } catch(e) {
                console.error('خطأ في تحميل المحادثة:', e);
            }
        }

        var newBtn = document.querySelector('[data-action="new"]');
        if (newBtn) {
            newBtn.addEventListener('click', function(){
                if (cb) cb.innerHTML = '';
                ch = [];
                cid = null;
                if (dd) dd.classList.remove('show');
                pid = null;
                if (ipc) ipc.style.display = 'none';
                if (ui) ui.value = '';
            });
        }

        var shareBtn = document.querySelector('[data-action="share"]');
        if (shareBtn) {
            shareBtn.addEventListener('click', function(e){
                e.stopPropagation();
                if (!cid) {
                    alert('⚠️ لا توجد محادثة حالية للمشاركة! ابدأ محادثة أولاً.');
                    if (dd) dd.classList.remove('show');
                    return;
                }
                var url = window.location.origin + '/share/' + cid;
                var text = encodeURIComponent('اطلع على محادثتي مع نبراس:');
                var wa = document.getElementById('shareWhatsapp');
                var fb = document.getElementById('shareFacebook');
                var tw = document.getElementById('shareTwitter');
                var snap = document.getElementById('shareSnapchat');
                if (wa) wa.href = 'https://api.whatsapp.com/send?text=' + text + '%20' + encodeURIComponent(url);
                if (fb) fb.href = 'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(url);
                if (tw) tw.href = 'https://twitter.com/intent/tweet?url=' + encodeURIComponent(url) + '&text=' + text;
                if (snap) {
                    snap.onclick = function(ev){
                        ev.stopPropagation();
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                            navigator.clipboard.writeText(url).then(function(){
                                alert('✅ تم نسخ الرابط! افتح سناب شات والصقه.');
                            }).catch(function(){
                                alert('❌ فشل النسخ، الرابط هو: ' + url);
                            });
                        } else {
                            alert('❌ فشل النسخ، الرابط هو: ' + url);
                        }
                        if (sm) sm.classList.remove('show');
                    };
                }
                if (sm) sm.classList.add('show');
                if (dd) dd.classList.remove('show');
            });
        }

        if (sm) {
            sm.addEventListener('click', function(e){
                if (e.target === sm) sm.classList.remove('show');
            });
        }

        var ttb = document.querySelector('[data-action="theme-toggle"]');
        var tl = document.getElementById('themeLabel');
        function setTheme(t) {
            var h = document.documentElement;
            if (t === 'dark') {
                h.classList.add('dark-mode');
                if (tl) tl.textContent = 'الوضع الليلي';
                if (ttb) {
                    var i = ttb.querySelector('i');
                    if (i) i.className = 'fas fa-moon';
                }
                localStorage.setItem('nibras-theme', 'dark');
            } else {
                h.classList.remove('dark-mode');
                if (tl) tl.textContent = 'الوضع النهاري';
                if (ttb) {
                    var i = ttb.querySelector('i');
                    if (i) i.className = 'fas fa-sun';
                }
                localStorage.setItem('nibras-theme', 'light');
            }
        }
        var st = localStorage.getItem('nibras-theme') || 'light';
        setTheme(st);
        if (ttb) {
            ttb.addEventListener('click', function(e){
                e.stopPropagation();
                var cur = document.documentElement.classList.contains('dark-mode') ? 'dark' : 'light';
                var nw = (cur === 'dark') ? 'light' : 'dark';
                setTheme(nw);
                if (dd) dd.classList.remove('show');
            });
        }

        // ====== دالة تنسيق النص ======
        function formatBotText(t) {
            try {
                var s = String(t || '');
                s = s.replace(/&/g, '&amp;')
                     .replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;')
                     .replace(/"/g, '&quot;')
                     .replace(/'/g, '&#39;');
                var paragraphs = s.split(/\n\s*\n/);
                var result = paragraphs.map(function(p) {
                    return p.replace(/[\r\n]+/g, ' ').trim();
                }).filter(function(p) { return p.length > 0; }).join('<br><br>');
                return result;
            } catch(e) {
                console.error("خطأ في formatBotText:", e);
                return t || '';
            }
        }

        function showToast(msg) {
            var old = document.querySelector('.toast');
            if (old) old.remove();
            var t = document.createElement('div');
            t.className = 'toast';
            t.textContent = msg;
            document.body.appendChild(t);
            setTimeout(function(){
                t.style.animation = 'toastOut .3s ease forwards';
                setTimeout(function(){ if (t.parentNode) t.remove(); }, 300);
            }, 1500);
        }

        function initCodeCopyButtons() {
            document.querySelectorAll('.copy-code-btn').forEach(function(btn){
                btn.removeEventListener('click', codeCopyHandler);
                btn.addEventListener('click', codeCopyHandler);
            });
        }

        function codeCopyHandler(e) {
            e.stopPropagation();
            var btn = e.currentTarget;
            var code = btn.getAttribute('data-code') || '';
            if (!code) {
                var pre = btn.parentElement.querySelector('code');
                if (pre) code = pre.textContent || '';
            }
            if (!code) {
                showToast('❌ لا يوجد كود للنسخ');
                return;
            }
            function copyDone() {
                btn.textContent = '✅ تم النسخ!';
                btn.classList.add('copied');
                showToast('✅ تم نسخ الكود!');
                setTimeout(function(){
                    btn.textContent = '📋 نسخ الكود';
                    btn.classList.remove('copied');
                }, 2200);
            }
            function copyFail() {
                showToast('❌ فشل النسخ');
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(code).then(copyDone).catch(function(){
                    fallbackCopy(code, copyDone, copyFail);
                });
            } else {
                fallbackCopy(code, copyDone, copyFail);
            }
        }

        function fallbackCopy(text, onSuccess, onFail) {
            try {
                var ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                ta.style.left = '-9999px';
                ta.style.top = '-9999px';
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                ta.remove();
                onSuccess();
            } catch(e) {
                onFail();
            }
        }

        // ====== دالة إضافة رسالة ======
        function addMessage(t, s, isSys, img, imageUrl) {
            try {
                s = s || 'bot';
                isSys = isSys || false;
                if (!cb) return null;
                var el = document.createElement('div');
                el.className = 'msg ' + s;
                if (s === 'error') el.classList.add('error');
                var now = new Date();
                var tm = isSys ? '' : now.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
                if (img) {
                    el.innerHTML = '<img src="'+img+'" class="image-upload" /><span class="file-label">'+(t||'صورة')+'</span>'+(tm ? ' <span class="time">'+tm+'</span>' : '');
                    cb.appendChild(el);
                    cb.scrollTop = cb.scrollHeight;
                    return el;
                }
                var imatch = t.match(/(https?:\/\/[^\s]+\.(png|jpg|jpeg|gif|webp))/i);
                var dt = t, genUrl = null;
                if (imatch) {
                    genUrl = imatch[0];
                    dt = t.replace(imatch[0], '').trim();
                    if (!dt) dt = 'الصورة المولدة';
                }
                if (s === 'bot' && !isSys && !genUrl && !imageUrl) {
                    var wrapper = document.createElement('div');
                    wrapper.className = 'content-wrapper';
                    var textDiv = document.createElement('div');
                    textDiv.className = 'content-text';
                    textDiv.innerHTML = '<span class="typing-text"></span>';
                    var actions = document.createElement('div');
                    actions.className = 'actions';
                    var copyBtn = document.createElement('button');
                    copyBtn.className = 'copy-btn';
                    copyBtn.innerHTML = '<i class="fas fa-copy"></i>';
                    copyBtn.title = 'نسخ النص';
                    copyBtn.addEventListener('click', function(e){
                        e.stopPropagation();
                        var fullText = dt;
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                            navigator.clipboard.writeText(fullText).then(function(){
                                copyBtn.innerHTML = '<i class="fas fa-check"></i>';
                                copyBtn.classList.add('copied');
                                showToast('تم نسخ النص!');
                                setTimeout(function(){
                                    copyBtn.innerHTML = '<i class="fas fa-copy"></i>';
                                    copyBtn.classList.remove('copied');
                                }, 2000);
                            }).catch(function(){
                                showToast('فشل النسخ');
                            });
                        } else {
                            showToast('المتصفح لا يدعم النسخ');
                        }
                    });
                    var shareBtn2 = document.createElement('button');
                    shareBtn2.className = 'copy-btn';
                    shareBtn2.innerHTML = '<i class="fas fa-share-alt"></i>';
                    shareBtn2.title = 'مشاركة النص';
                    shareBtn2.addEventListener('click', function(e){
                        e.stopPropagation();
                        var fullText = dt;
                        var url = 'https://api.whatsapp.com/send?text=' + encodeURIComponent(fullText);
                        window.open(url, '_blank');
                    });
                    var delBtn = document.createElement('button');
                    delBtn.className = 'del-msg-btn';
                    delBtn.innerHTML = '<i class="fas fa-trash-alt"></i>';
                    delBtn.title = 'حذف هذه الرسالة';
                    delBtn.addEventListener('click', function(e){
                        e.stopPropagation();
                        deleteMessage(el);
                    });
                    actions.appendChild(copyBtn);
                    actions.appendChild(shareBtn2);
                    actions.appendChild(delBtn);
                    wrapper.appendChild(textDiv);
                    wrapper.appendChild(actions);
                    el.appendChild(wrapper);
                    if (tm) {
                        var timeSpan = document.createElement('span');
                        timeSpan.className = 'time';
                        timeSpan.textContent = tm;
                        el.appendChild(timeSpan);
                    }
                    cb.appendChild(el);
                    cb.scrollTop = cb.scrollHeight;
                    var ts = textDiv.querySelector('.typing-text');
                    var idx = 0, interacted = false;
                    var onInteract = function(){
                        interacted = true;
                        cb.removeEventListener('touchstart', onInteract);
                        cb.removeEventListener('scroll', onInteract);
                    };
                    cb.addEventListener('touchstart', onInteract);
                    cb.addEventListener('scroll', onInteract);
                    function typeChar() {
                        if (idx < dt.length) {
                            ts.textContent += dt.charAt(idx);
                            idx++;
                            if (!interacted) cb.scrollTop = cb.scrollHeight;
                            setTimeout(typeChar, 20);
                        } else {
                            var formatted = formatBotText(dt);
                            ts.innerHTML = formatted;
                            initCodeCopyButtons();
                            cb.scrollTop = cb.scrollHeight;
                        }
                    }
                    typeChar();
                    return el;
                }
                var content = dt;
                if (s === 'bot') content = formatBotText(dt);
                if (genUrl) content += '<br/><img src="'+genUrl+'" class="generated-image" />';
                if (imageUrl) {
                    if (imageUrl.match(/\.(mp4|webm|mov)$/i) || imageUrl.includes('video')) {
                        content += '<br/><video controls class="generated-video" src="'+imageUrl+'"></video>';
                    } else {
                        content += '<br/><img src="'+imageUrl+'" class="generated-image" />';
                    }
                }
                var wrapper2 = document.createElement('div');
                wrapper2.className = 'content-wrapper';
                var textDiv2 = document.createElement('div');
                textDiv2.className = 'content-text';
                textDiv2.innerHTML = content;
                wrapper2.appendChild(textDiv2);
                if (s === 'bot' && !isSys) {
                    var actions2 = document.createElement('div');
                    actions2.className = 'actions';
                    var copyBtn2 = document.createElement('button');
                    copyBtn2.className = 'copy-btn';
                    copyBtn2.innerHTML = '<i class="fas fa-copy"></i>';
                    copyBtn2.title = 'نسخ النص';
                    copyBtn2.addEventListener('click', function(e){
                        e.stopPropagation();
                        var fullText = dt;
                        if (navigator.clipboard && navigator.clipboard.writeText) {
                            navigator.clipboard.writeText(fullText).then(function(){
                                copyBtn2.innerHTML = '<i class="fas fa-check"></i>';
                                copyBtn2.classList.add('copied');
                                showToast('تم نسخ النص!');
                                setTimeout(function(){
                                    copyBtn2.innerHTML = '<i class="fas fa-copy"></i>';
                                    copyBtn2.classList.remove('copied');
                                }, 2000);
                            }).catch(function(){
                                showToast('فشل النسخ');
                            });
                        } else {
                            showToast('المتصفح لا يدعم النسخ');
                        }
                    });
                    var shareBtn3 = document.createElement('button');
                    shareBtn3.className = 'copy-btn';
                    shareBtn3.innerHTML = '<i class="fas fa-share-alt"></i>';
                    shareBtn3.title = 'مشاركة النص';
                    shareBtn3.addEventListener('click', function(e){
                        e.stopPropagation();
                        var fullText = dt;
                        var url = 'https://api.whatsapp.com/send?text=' + encodeURIComponent(fullText);
                        window.open(url, '_blank');
                    });
                    var delBtn2 = document.createElement('button');
                    delBtn2.className = 'del-msg-btn';
                    delBtn2.innerHTML = '<i class="fas fa-trash-alt"></i>';
                    delBtn2.title = 'حذف هذه الرسالة';
                    delBtn2.addEventListener('click', function(e){
                        e.stopPropagation();
                        deleteMessage(el);
                    });
                    actions2.appendChild(copyBtn2);
                    actions2.appendChild(shareBtn3);
                    actions2.appendChild(delBtn2);
                    wrapper2.appendChild(actions2);
                }
                el.appendChild(wrapper2);
                if (tm) {
                    var timeSpan2 = document.createElement('span');
                    timeSpan2.className = 'time';
                    timeSpan2.textContent = tm;
                    el.appendChild(timeSpan2);
                }
                cb.appendChild(el);
                cb.scrollTop = cb.scrollHeight;
                initCodeCopyButtons();
                return el;
            } catch(e) {
                console.error("خطأ في addMessage:", e);
                if (cb) {
                    var errEl = document.createElement('div');
                    errEl.className = 'msg error';
                    errEl.textContent = '⚠️ حدث خطأ في عرض الرسالة: ' + e.message;
                    cb.appendChild(errEl);
                }
                return null;
            }
        }

        async function deleteMessage(el) {
            if (!cid) { showToast('لا توجد محادثة'); return; }
            if (!confirm('هل تريد حذف هذه الرسالة؟')) return;
            try {
                var idx = Array.from(cb.children).indexOf(el);
                var r = await fetch('/delete_message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ conv_id: cid, index: idx })
                });
                var d = await r.json();
                if (d.status === 'ok') {
                    ch.splice(idx, 1);
                    el.remove();
                    showToast('تم حذف الرسالة');
                } else {
                    showToast('فشل الحذف: ' + d.message);
                }
            } catch(e) {
                showToast('خطأ في الاتصال');
            }
        }

        // ====== وظائف الصور والإرسال ======
        function showWelcome() {
            if (!sessionStorage.getItem('welcomeShown')) {
                var ov = document.createElement('div');
                ov.className = 'welcome-overlay';
                ov.innerHTML = '<div class="welcome-box"><h2>👋 أهلاً بك في نبراس</h2><p>نورتنا! كيف نقدر نساعدك اليوم؟</p></div>';
                document.body.appendChild(ov);
                sessionStorage.setItem('welcomeShown', 'true');
                setTimeout(function(){
                    if (document.body.contains(ov)) {
                        ov.classList.add('fade-out');
                        setTimeout(function(){ if (document.body.contains(ov)) ov.remove(); }, 500);
                    }
                }, 5000);
                var rm = function(){
                    if (document.body.contains(ov)) {
                        ov.classList.add('fade-out');
                        setTimeout(function(){ if (document.body.contains(ov)) ov.remove(); }, 500);
                    }
                    document.removeEventListener('click', rm);
                    if (ui) ui.removeEventListener('keydown', rm);
                };
                document.addEventListener('click', rm);
                if (ui) ui.addEventListener('keydown', rm);
            }
        }

        function showImagePreview(d) {
            if (ip) ip.src = d;
            if (ipc) ipc.style.display = 'flex';
        }

        function clearPending() {
            pid = null;
            if (ipc) ipc.style.display = 'none';
            if (ip) ip.src = '';
        }

        if (rib) rib.addEventListener('click', clearPending);

        if (ui) {
            ui.addEventListener('input', function(){
                this.style.height = 'auto';
                this.style.height = Math.min(this.scrollHeight, 80) + 'px';
            });
        }

        var poOpen = false;
        if (pb && po) {
            pb.addEventListener('click', function(){
                poOpen = !poOpen;
                po.classList.toggle('show', poOpen);
                this.classList.toggle('rotate', poOpen);
            });
        }

        // مستمع النقر العام (بشرط وجود العناصر)
        document.addEventListener('click', function(e){
            // إغلاق plus options
            if (pb && po && !pb.contains(e.target) && !po.contains(e.target)) {
                po.classList.remove('show');
                poOpen = false;
                pb.classList.remove('rotate');
            }
            // إغلاق القائمة المنسدلة
            if (mt && dd && !mt.contains(e.target) && !dd.contains(e.target)) {
                dd.classList.remove('show');
            }
        });

        if (gb && fi) {
            gb.addEventListener('click', function(){ fi.click(); if (po) po.classList.remove('show'); });
        }
        if (fi) {
            fi.addEventListener('change', function(e){
                if (this.files && this.files.length > 0) {
                    var r = new FileReader();
                    r.onload = function(ev) {
                        pid = ev.target.result;
                        showImagePreview(pid);
                        fi.value = '';
                    };
                    r.readAsDataURL(this.files[0]);
                }
            });
        }

        if (cab && ci) {
            cab.addEventListener('click', function(){ ci.click(); if (po) po.classList.remove('show'); });
        }
        if (ci) {
            ci.addEventListener('change', function(e){
                if (this.files && this.files.length > 0) {
                    var r = new FileReader();
                    r.onload = function(ev) {
                        pid = ev.target.result;
                        showImagePreview(pid);
                        ci.value = '';
                    };
                    r.readAsDataURL(this.files[0]);
                }
            });
        }

        if (fib && fig) {
            fib.addEventListener('click', function(){ fig.click(); if (po) po.classList.remove('show'); });
        }
        if (fig) {
            fig.addEventListener('change', function(e){
                if (this.files && this.files.length > 0) {
                    var r = new FileReader();
                    r.onload = function(ev) {
                        pid = ev.target.result;
                        showImagePreview(pid);
                        fig.value = '';
                    };
                    r.readAsDataURL(this.files[0]);
                }
            });
        }

        // ====== إرسال الرسالة ======
        async function sendMessage() {
            if (iw) return;
            var t = ui ? ui.value.trim() : '';
            var img = pid;
            if (!t && !img) return;
            if (t) addMessage(t, 'user');
            if (img) {
                addMessage('صورة مرفقة', 'user', false, img);
                clearPending();
            }
            if (ui) {
                ui.value = '';
                ui.style.height = 'auto';
            }
            iw = true;
            var td = document.createElement('div');
            td.className = 'msg bot typing-indicator';
            td.innerHTML = '<span class="typing-dots">جاري التفكير</span>';
            if (cb) {
                cb.appendChild(td);
                cb.scrollTop = cb.scrollHeight;
            }
            var payload = { message: t || "مرفق", image: img || null, history: ch, conv_id: cid };
            try {
                var r = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                var d = await r.json();
                if (td.parentNode) td.remove();
                if (r.ok) {
                    addMessage(d.reply, 'bot', false, null, d.image_url);
                    if (!im && d.audio) {
                        if (ca) { ca.pause(); ca.currentTime = 0; }
                        var src = 'data:audio/mp3;base64,' + d.audio;
                        ca = new Audio(src);
                        ca.play().catch(function(e){ console.warn("فشل تشغيل الصوت:", e); });
                    }
                    if (d.conv_id) cid = d.conv_id;
                } else {
                    addMessage('خطأ: ' + (d.error || 'مشكلة في السيرفر'), 'error');
                }
            } catch(e) {
                if (td.parentNode) td.remove();
                addMessage('تعذر الاتصال بالسيرفر، حاول مرة أخرى.', 'error');
            } finally {
                iw = false;
            }
        }

        if (sb) {
            sb.addEventListener('click', sendMessage);
            console.log("✅ زر الإرسال مربوط");
        }

        if (ui) {
            ui.addEventListener('keypress', function(e){
                if (e.key === 'Enter') {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }

        // ====== الميكروفون ======
        var recog = null;
        if (mb) {
            mb.addEventListener('click', function(){
                if (!('webkitSpeechRecognition' in window)) {
                    addMessage('المتصفح لا يدعم التعرف على الصوت.', 'bot', true);
                    return;
                }
                if (this.classList.contains('listening')) {
                    this.classList.remove('listening');
                    if (recog) recog.stop();
                    return;
                }
                var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
                recog = new SR();
                recog.lang = 'ar-SA';
                this.classList.add('listening');
                addMessage('جاري الاستماع...', 'bot', true);
                recog.onresult = function(e) {
                    var tr = e.results[0][0].transcript;
                    if (ui) ui.value = tr;
                    mb.classList.remove('listening');
                    setTimeout(function(){ sendMessage(); }, 300);
                };
                recog.onerror = function() {
                    mb.classList.remove('listening');
                };
                recog.start();
            });
        }

        showWelcome();

        // تعريف deleteMyData عالمياً
        window.deleteMyData = function() {
            if (!confirm('⚠️ هل أنت متأكد؟ سيتم حذف جميع محادثاتك وبياناتك نهائياً.')) return;
            fetch('/delete_my_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            })
            .then(function(response){ return response.json(); })
            .then(function(data){
                if (data.status === 'success') {
                    alert('✅ تم حذف جميع بياناتك بنجاح.');
                    window.location.href = '/';
                } else {
                    alert('❌ فشل الحذف: ' + (data.message || 'خطأ غير معروف'));
                }
            })
            .catch(function(err){
                alert('❌ حدث خطأ في الاتصال.');
                console.error(err);
            });
        };

        console.log("✅ تم تهيئة جميع الأزرار بنجاح");

    } catch(e) {
        console.error("❌ خطأ فادح في الـ JS:", e);
        var chatEl = document.getElementById('chat');
        if (chatEl) {
            var errDiv = document.createElement('div');
            errDiv.className = 'msg error';
            errDiv.textContent = '❌ خطأ فادح: ' + e.message + '. حاول تحديث الصفحة.';
            chatEl.appendChild(errDiv);
        }
    }
})();
</script></body></html>"""
LH="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>دخول - نبراس</title><style>*{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif}body{background:#f0f2f5;display:flex;justify-content:center;align-items:center;height:100dvh;margin:0;padding:15px}.box{background:#fff;padding:40px 30px;border-radius:20px;box-shadow:0 4px 20px rgba(0,0,0,0.08);width:100%;max-width:400px;text-align:center}h2{font-size:28px;color:#1a2b3c;margin-bottom:25px}input{width:100%;padding:14px 16px;margin:12px 0;border:1px solid #dce1e8;border-radius:12px;font-size:18px;background:#fafbfc;box-sizing:border-box}input:focus{outline:0;border-color:#4a6a8a;background:#fff}button{width:100%;padding:16px;background:#4a6a8a;color:#fff;border:none;border-radius:12px;font-size:20px;font-weight:700;cursor:pointer;margin-top:15px}button:hover{background:#3a5a7a}a{color:#4a6a8a;text-decoration:none;font-size:16px;display:inline-block;margin-top:20px}.error{color:#d9534f;margin-bottom:15px}</style></head><body><div class="box"><h2>🔐 تسجيل الدخول</h2>{% if error %}<div class="error">{{ error }}</div>{% endif %}<form method="POST"><input type="email" name="email" placeholder="البريد الإلكتروني" required><input type="password" name="password" placeholder="كلمة المرور" required><button type="submit">دخول</button></form><a href="/">⬅ العودة للرئيسية</a><br><a href="https://abod724.github.io/nibras-privacy/" target="_blank" style="display:inline-block; margin-top:5px; font-size:12px; text-decoration:underline;">سياسة الخصوصية</a></div></body></html>"""
@app.route('/')
def index():return render_template_string(HT)
@app.route('/share/<cid>')
def shared_conversation(cid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor();c.execute("SELECT messages,title FROM conversations WHERE conv_id=?",(cid,));r=c.fetchone();conn.close()
 if r:m=json.loads(r[0]);t=r[1] or "محادثة نبراس";return render_template_string(SPH,messages=m,title=t)
 return "⚠️ المحادثة غير موجودة أو تم حذفها.",404
@app.route('/login',methods=['GET','POST'])
@limiter.limit("3 per minute")
def login():
 if request.method=='POST':
  e=request.form.get('email');p=request.form.get('password');ae="abdullaha0569361@gmail.com";ap=os.environ.get("ADMIN_PASSWORD")
  if e==ae:
   if not ap:return render_template_string(LH,error="خطأ: لم يتم إعداد كلمة مرور الأدمن في الخادم.")
   if secrets.compare_digest(p,ap):session.clear();session['admin_email']=ae;return redirect(url_for('index'))
   else:return render_template_string(LH,error="كلمة مرور الأدمن غير صحيحة.")
  elif e and "@" in e:
   session['user_email']=e
   return redirect(url_for('index'))
  else:return render_template_string(LH,error="يرجى إدخال بريد إلكتروني صحيح.")
 return render_template_string(LH)
@app.route('/logout')
def logout():session.clear();return redirect(url_for('index'))
@app.route('/history')
def history():
 uid=get_user_id();cs=get_user_conversations(uid);cs.sort(key=lambda x:x["timestamp"],reverse=True);return jsonify({"conversations":[{"id":c["id"],"title":c["title"]} for c in cs]})
@app.route('/load_conversation/<cid>')
def load_conversation(cid):
 uid=get_user_id();ms=load_conversation_by_id(uid,cid)
 if ms:return jsonify({"messages":ms})
 return jsonify({"messages":None}),404
@app.route('/delete_message', methods=['POST'])
def delete_message():
    try:
        d=request.get_json();cid=d.get('conv_id');idx=d.get('index')
        uid=get_user_id()
        if not cid or idx is None:return jsonify({"status":"error","message":"بيانات ناقصة"}),400
        msgs=load_conversation_by_id(uid,cid)
        if not msgs:return jsonify({"status":"error","message":"المحادثة غير موجودة"}),404
        if idx<0 or idx>=len(msgs):return jsonify({"status":"error","message":"الرسالة غير موجودة"}),404
        del msgs[idx]
        save_user_conversation(uid,msgs,cid)
        return jsonify({"status":"ok"})
    except Exception as e:return jsonify({"status":"error","message":str(e)}),500
@app.route('/delete_my_data', methods=['POST'])
def delete_my_data():
    uid = get_user_id()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM conversations WHERE user_id = ?", (uid,))
    conn.commit()
    conn.close()
    session.clear()
    return jsonify({"status": "success", "message": "تم حذف جميع بياناتك ومحادثاتك بنجاح."})
def get_user_id():
 if 'admin_email' in session:return "admin_"+session['admin_email']
 elif 'user_email' in session:return "user_"+session['user_email']
 else:
  rip=request.headers.get('X-Forwarded-For')
  if rip:rip=rip.split(',')[0].strip()
  else:rip=request.remote_addr
  return "guest_"+(rip or 'unknown')
@app.route('/set_gender',methods=['POST'])
def set_gender():d=request.get_json();session['voice_gender']=d.get('gender','male');return jsonify({"status":"ok"})
@app.route('/chat',methods=['POST'])
@limiter.limit("5 per minute")
def chat():
 try:
  d=request.get_json();um=d.get("message","").strip();hist=d.get("history",[]);cid=d.get("conv_id",None)
  if not um:return jsonify({"reply":"اكتب شيء أساعدك فيه"})
  is_admin='admin_email' in session and session['admin_email']=="abdullaha0569361@gmail.com"
  uid=get_user_id()
  if cid is None:sm[uid]=[]
  model = OPENAI_MODEL
  if is_admin:
   use_web=True
   allow_img=True
  else:
   use_web=False
   allow_img=True
  draw_phrases = ["ارسم لي", "ابي صورة", "ابي صوره", "ابي صورت", "صوره لي", "ارسم", "أنشئ", "انشئ", "انشى", "صمم", "ولّد", "generate", "draw", "فيديو", "ابي فيديو", "عرض فيديو"]
  def is_image_request(text):
      text_lower = text.lower().strip()
      if len(text_lower.split()) <= 1:
          return False
      for phrase in draw_phrases:
          if text_lower.startswith(phrase) or phrase in text_lower:
              return True
      return False
  if allow_img and is_image_request(um):
   print(f"🎨 اكتشاف طلب رسم أو فيديو: {um}")
   video_keywords = ["فيديو", "ابي فيديو", "عرض فيديو"]
   is_video = any(kw in um for kw in video_keywords)
   if is_video:
       video_result = search_video(um)
       if video_result and video_result.startswith("ERROR:"):
           error_clear = video_result.replace("ERROR:", "")
           reply = f"⚠️ عذراً، ما قدرت أجيب الفيديو. السبب: {error_clear}"
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply, "conv_id": nid})
       elif video_result:
           reply = f"🎬 إليك الفيديو الذي طلبتـه:"
           reply_with_url = reply + "\n" + video_result
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply_with_url})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply_with_url, "image_url": video_result, "conv_id": nid})
       else:
           reply = "⚠️ عذراً، تعذر جلب الفيديو بسبب خطأ غير معروف."
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply, "conv_id": nid})
   img_result = generate_image(um)
   if img_result and img_result.startswith("ERROR:"):
        error_clear = img_result.replace("ERROR:", "")
        reply = f"⚠️ عذراً، ما قدرت أولد الصورة. السبب: {error_clear}"
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "conv_id": nid})
   elif img_result:
        reply = f"🖼️ إليك الصورة التي طلبتها:"
        reply_with_url = reply + "\n" + img_result
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply_with_url})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply_with_url, "image_url": img_result, "conv_id": nid})
   else:
        reply = "⚠️ عذراً، تعذر توليد الصورة بسبب خطأ غير معروف."
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "conv_id": nid})
  sm[uid].append({"role":"user","content":um});ch=sm[uid][-10:];msgs=[{"role":"system","content":SP}]
  for e in ch:msgs.append({"role":e["role"],"content":e["content"]})
  img_data=d.get("image",None)
  if img_data and is_admin:msgs.append({"role":"user","content":[{"type":"text","text":um or "حلل هذه الصورة"},{"type":"image_url","image_url":{"url":img_data}}]})
  if use_web:
   try:
    fc=""
    for m in msgs:
     if m["role"]=="user":fc+=m["content"]+"\n"
     elif m["role"]=="assistant":fc+="نبراس: "+m["content"]+"\n"
    sr=client.responses.create(model=model,instructions=f"{SP}\n\nسياق المحادثة السابقة:\n{fc}",input=f"ابحث في الويب عن أحدث المعلومات حول: {um}، وقدم لي ملخصاً مفيداً.",tools=[{"type":"web_search"}])
    res=sr.output_text.strip()
    if res:msgs.append({"role":"user","content":f"نتيجة البحث:\n{res}\n\nاستخدم هذه المعلومات."})
   except Exception as e:print(f"⚠️ فشل البحث: {e}")
  try:
   r=client.chat.completions.create(model=model,messages=msgs,max_completion_tokens=1000,temperature=0.8);reply=r.choices[0].message.content.strip()
   if not reply:reply="ما قدرت أجيب لك رد، حاول مرة أخرى."
  except openai.BadRequestError as e:
   print(f"❌ فشل النموذج {model}: {e}")
   return jsonify({"error": f"النموذج {model} غير مدعوم أو حدث خطأ: {str(e)}"}), 400
  except Exception as e:
   print(f"❌ خطأ عام: {e}")
   return jsonify({"error": str(e)}), 500
  
  # ====== تنظيف النص: دمج الأسطر العمودية في فقرات ======
  lines = reply.split('\n')
  merged_paragraphs = []
  current_paragraph = []
  
  for line in lines:
      line = line.strip()
      if not line:
          if current_paragraph:
              merged_paragraphs.append(' '.join(current_paragraph))
              current_paragraph = []
      else:
          current_paragraph.append(line)
  
  if current_paragraph:
      merged_paragraphs.append(' '.join(current_paragraph))
  
  reply = '\n\n'.join(merged_paragraphs)
  # ============================================================
  
  sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
  try:gender=session.get('voice_gender','male');audio=generate_speech(reply,gender)
  except Exception as e:print(f"⚠️ فشل الصوت: {e}");audio=None
  return jsonify({"reply":reply,"audio":audio,"conv_id":nid})
 except Exception as e:print(f"❌ خطأ عام: {e}");return jsonify({"error":str(e)}),500
@app.route('/tools')
def tools():
    return render_template_string(TOOLS_HTML)
@app.route('/<path:filename>')
def serve_static_files(filename):return send_from_directory(app.static_folder,filename)
if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
