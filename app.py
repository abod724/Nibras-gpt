from flask import Flask,request,jsonify,render_template_string,session,redirect,url_for,send_from_directory
import openai,os,secrets,json,hashlib,asyncio,edge_tts,base64,re,sqlite3,requests,hmac
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

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")  # اختياري

client=openai.OpenAI(api_key=OPENAI_API_KEY)
limiter=Limiter(key_func=get_remote_address,default_limits=["500 per day","20 per hour"])
limiter.init_app(app)
@app.route('/robots.txt')
def serve_robots():return send_from_directory('static','robots.txt')
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
SP=f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.
**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.
3. **البحث بالويب** تستخدمه عندما يسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.
**ملف المعرفة الخاص بك:**
{kc}
**⚠️ قواعد التنسيق الإلزامية (يجب الالتزام بها):**
- اكتب ردك في فقرات نصية عادية متصلة (مثل ChatGPT والمقالات).
- **ممنوع** وضع كل جملة في سطر مستقل (ممنوع الشعر). اكتب جملة طويلة تكمل في السطر التالي.
- اترك **سطراً فارغاً** بين كل فقرة وأخرى.
- استخدم `**الخط العريض**` لعناوين الفقرات، و `-` للقوائم.
**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة في ملف المعرفة، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- لا تكتب "لحظة" أو "انتظر"، فقط انتظر النتيجة ورد مباشرة.
"""
def remove_emoji(t):
 return re.compile("["+u"\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002702-\U000027B0\U000024C2-\U0001F251\U0001f926-\U0001f937\U00010000-\U0010ffff\u2640-\u2642\u2600-\u2B55\u200d\u23cf\u23e9\u231a\ufe0f\u3030"+"]+",flags=re.UNICODE).sub('',t)

# ====== دالة توليد الصورة باستخدام Unsplash (آمن ومجاني) ======
def generate_image(prompt):
    try:
        access_key = os.environ.get("UNSPLASH_ACCESS_KEY")
        if not access_key:
            return "ERROR: UNSPLASH_ACCESS_KEY غير موجود في البيئة"
        
        query = requests.utils.quote(prompt)
        url = f"https://api.unsplash.com/photos/random?query={query}&orientation=landscape"
        headers = {"Authorization": f"Client-ID {access_key}"}
        response = requests.get(url, headers=headers)
        data = response.json()
        
        if response.status_code == 200 and data.get("urls"):
            return data["urls"]["regular"]
        else:
            error_msg = data.get('errors', ['خطأ غير معروف'])[0]
            return f"ERROR: لم أجد صورة مناسبة - {error_msg}"
    except Exception as e:
        return f"ERROR:{str(e)}"
# ===================================================================

def generate_speech(text, gender):
 try:
  voice="onyx" if gender=="male" else "nova"
  r=client.audio.speech.create(model="tts-1",voice=voice,input=remove_emoji(text),response_format="mp3",speed=1.0)
  return base64.b64encode(r.content).decode('utf-8')
 except Exception as e:print(f"❌ فشل الصوت: {e}");return None
SPH="""... (نفس المحتوى السابق) ..."""  # اختصرت للاختصار
HT=r"""... (نفس المحتوى السابق) ..."""
LH="""... (نفس المحتوى السابق) ..."""
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
  
  # ====== الصور للجميع، البحث للأدمن فقط ======
  if is_admin:
   use_web=True
   allow_img=True
  else:
   use_web=False
   allow_img=True
  # ==========================================
  
  # ====== قائمة العبارات الدقيقة لطلب الصورة ======
  draw_phrases = ["ارسم لي", "ابي صورة", "ابي صوره", "ابي صورت", "صوره لي", "ارسم", "أنشئ", "انشئ", "انشى", "صمم", "ولّد", "generate", "draw"]
  def is_image_request(text):
      text_lower = text.lower().strip()
      if len(text_lower.split()) <= 1:
          return False
      for phrase in draw_phrases:
          if text_lower.startswith(phrase) or phrase in text_lower:
              return True
      return False
  # ==============================================

  if allow_img and is_image_request(um):
   print(f"🎨 اكتشاف طلب رسم: {um}")
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
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply + "\n" + img_result})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "image_url": img_result, "conv_id": nid})
   else:
        reply = "⚠️ عذراً، تعذر توليد الصورة بسبب خطأ غير معروف."
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "conv_id": nid})
  
  sm[uid].append({"role":"user","content":um});ch=sm[uid][-10:];msgs=[{"role":"system","content":SP}]
  for e in ch:msgs.append({"role":e["role"],"content":e["content"]})
  img_data=d.get("image",None)
  if img_data and allow_img:msgs.append({"role":"user","content":[{"type":"text","text":um or "حلل هذه الصورة"},{"type":"image_url","image_url":{"url":img_data}}]})
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
  sm[uid].append({"role":"assistant","content":reply});nid=save_user_conversation(uid,sm[uid],cid)
  try:gender=session.get('voice_gender','male');audio=generate_speech(reply,gender)
  except Exception as e:print(f"⚠️ فشل الصوت: {e}");audio=None
  return jsonify({"reply":reply,"audio":audio,"conv_id":nid})
 except Exception as e:print(f"❌ خطأ عام: {e}");return jsonify({"error":str(e)}),500
@app.route('/<path:filename>')
def serve_static_files(filename):return send_from_directory(app.static_folder,filename)

# ================== إضافة نقاط Webhook ==================
@app.route('/webhook/openai', methods=['POST'])
def openai_webhook():
    """
    يستقبل أحداث webhook من OpenAI.
    يجب أن تضع WEBHOOK_SECRET في متغيرات البيئة للتحقق من التوقيع (اختياري).
    """
    try:
        # التحقق من التوقيع إذا كان WEBHOOK_SECRET موجود
        if WEBHOOK_SECRET:
            signature = request.headers.get('webhook-signature')
            if not signature:
                return jsonify({"error": "Missing signature"}), 401
            # حساب التوقيع المتوقع (بافتراض أن OpenAI تستخدم SHA256)
            payload = request.get_data(as_text=True)
            expected = hmac.new(WEBHOOK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return jsonify({"error": "Invalid signature"}), 401

        # قراءة الحدث
        event = request.get_json()
        if not event:
            return jsonify({"error": "Invalid JSON"}), 400

        # تسجيل الحدث في ملف (أو يمكنك تخزينه في قاعدة البيانات)
        with open("webhook_events.log", "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} - {json.dumps(event, ensure_ascii=False)}\n")

        # معالجة أنواع الأحداث المختلفة
        event_type = event.get("type")
        if event_type == "fine_tuning.job.succeeded":
            # مثلاً: إرسال إشعار للمستخدم (يمكنك تخصيصه)
            print(f"✅ نجاح تعديل النموذج: {event.get('data', {})}")
            # يمكنك هنا إرسال رسالة للمستخدم عبر التطبيق أو البريد الإلكتروني
        elif event_type == "fine_tuning.job.failed":
            print(f"❌ فشل تعديل النموذج: {event.get('data', {})}")
        elif event_type == "batch.completed":
            print(f"✅ اكتمال Batch: {event.get('data', {})}")
        elif event_type == "response.completed":
            print(f"✅ اكتمال رد: {event.get('data', {})}")
        # أضف أحداثاً أخرى حسب الحاجة

        # رد بـ 200 OK لإعلام OpenAI باستلام الحدث
        return jsonify({"status": "received"}), 200

    except Exception as e:
        print(f"❌ خطأ في webhook: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/test', methods=['GET'])
def test_webhook():
    """
    نقطة اختبار لإرسال حدث تجريبي إلى webhook (محاكاة).
    """
    test_event = {
        "id": "evt_test123",
        "type": "fine_tuning.job.succeeded",
        "created_at": int(datetime.now().timestamp()),
        "data": {"fine_tuning_job_id": "ft-job-abc", "status": "succeeded"}
    }
    # محاكاة طلب POST لنفس المسار
    with app.test_client() as client:
        resp = client.post('/webhook/openai', json=test_event)
        return jsonify({
            "message": "تم إرسال حدث اختبار",
            "response_status": resp.status_code,
            "response_json": resp.get_json()
        })
# ======================================================

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
