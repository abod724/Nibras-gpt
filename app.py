from flask import Flask,request,jsonify,render_template_string,session,redirect,url_for,send_from_directory
import openai,os,secrets,json,hashlib,asyncio,edge_tts,base64,re,sqlite3,requests
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
app=Flask(__name__,static_folder='static')
app.secret_key=os.environ.get("SECRET_KEY",secrets.token_hex(16))
OPENAI_API_KEY=os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:raise Exception("OPENAI_API_KEY غير موجود!")

# ====== استخدم gpt-4o-mini كافتراضي لتوفير المال ======
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

client=openai.OpenAI(api_key=OPENAI_API_KEY)
limiter=Limiter(key_func=get_remote_address,default_limits=["500 per day","20 per hour"])
limiter.init_app(app)

# ====== خدمة الملفات الثابتة ======
@app.route('/robots.txt')
def serve_robots():return send_from_directory('static','robots.txt')

@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):
    return send_from_directory('.well-known', filename)

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

**⚠️ قاعدة التنسيق الذهبية (الأهم):**
- اكتب ردودك في **فقرات نصية متصلة**. كل فقرة تحتوي على **2 إلى 4 جمل** فقط.
- **ممنوع** وضع كل جملة في سطر منفصل. استخدم النقاط والفواصل وعلامات الترقيم داخل الفقرة نفسها.
- **ممنوع** وضع فواصل أسطر (`Enter`) بين الجمل. الفاصل الوحيد المسموح به هو سطر فارغ بين الفقرة والأخرى.
- اجعل الجملة الواحدة بطول معتدل (حوالي 10-20 كلمة).

**تعليمات إضافية:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة في ملف المعرفة، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- لا تكتب "لحظة" أو "انتظر"، فقط انتظر النتيجة ورد مباشرة.
"""

def remove_emoji(t):
 return re.compile("["+u"\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002500-\U00002BEF\U00002702-\U000027B0\U000024C2-\U0001F251\U0001f926-\U0001f937\U00010000-\U0010ffff\u2640-\u2642\u2600-\u2B55\u200d\u23cf\u23e9\u231a\ufe0f\u3030"+"]+",flags=re.UNICODE).sub('',t)

# ====== توليد الصورة (Pexels - مجاني) ======
def generate_image(prompt):
    try:
        api_key = os.environ.get("PEXELS_API_KEY")
        if not api_key:
            return "ERROR: PEXELS_API_KEY غير موجود"
        query = requests.utils.quote(prompt)
        url = f"https://api.pexels.com/v1/search?query={query}&per_page=1&orientation=landscape"
        headers = {"Authorization": api_key}
        response = requests.get(url, headers=headers)
        data = response.json()
        if response.status_code == 200 and data.get("photos") and len(data["photos"]) > 0:
            return data["photos"][0]["src"]["large"]
        else:
            return f"ERROR: {data.get('error', 'لم أجد صورة')}"
    except Exception as e:
        return f"ERROR: {str(e)}"

# ====== البحث عن فيديو (Pexels - مجاني) ======
def search_video(prompt):
    try:
        api_key = os.environ.get("PEXELS_API_KEY")
        if not api_key:
            return "ERROR: PEXELS_API_KEY غير موجود"
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
            return f"ERROR: {data.get('error', 'لم أجد فيديو')}"
    except Exception as e:
        return f"ERROR: {str(e)}"

# ====== البحث المجاني بالويب (DuckDuckGo) ======
def search_web(query):
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5, region='xa-ar')
            if not results:
                return None
            formatted = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
            return formatted
    except Exception as e:
        print(f"⚠️ فشل بحث DuckDuckGo: {e}")
        return None

# ====== الصوت المجاني (Edge TTS) ======
async def generate_speech_async(text, gender):
    voice = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariyahNeural"
    try:
        communicate = edge_tts.Communicate(text, voice)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return base64.b64encode(audio_data).decode('utf-8')
    except Exception as e:
        print(f"❌ فشل الصوت (Edge TTS): {e}")
        return None

def generate_speech(text, gender):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result = loop.run_until_complete(generate_speech_async(text, gender))
    loop.close()
    return result

# ====== قوالب HTML (نفس قوالبك الأصلية) ======
SPH="""<!DOCTYPE html>... (ضع كود SPH كاملاً من ملفك القديم) ..."""

HT=r"""<!DOCTYPE html>... (ضع كود HT كاملاً من ملفك القديم) ..."""

LH="""<!DOCTYPE html>... (ضع كود LH كاملاً من ملفك القديم) ..."""
@app.route('/')
def index():return render_template_string(HT)

@app.route('/share/<cid>')
def shared_conversation(cid):
 conn=sqlite3.connect(DB_FILE);c=conn.cursor();c.execute("SELECT messages,title FROM conversations WHERE conv_id=?",(cid,));r=c.fetchone();conn.close()
 if r:m=json.loads(r[0]);t=r[1] or "محادثة نبراس";return render_template_string(SPH,messages=m,title=t)
 return "⚠️ المحادثة غير موجودة",404

@app.route('/login',methods=['GET','POST'])
@limiter.limit("3 per minute")
def login():
 if request.method=='POST':
  e=request.form.get('email');p=request.form.get('password');ae="abdullaha0569361@gmail.com";ap=os.environ.get("ADMIN_PASSWORD")
  if e==ae:
   if not ap:return render_template_string(LH,error="خطأ: لم يتم إعداد كلمة مرور الأدمن.")
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
    return jsonify({"status": "success", "message": "تم حذف جميع بياناتك."})

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

# ====== نقطة الدردشة الرئيسية (معدلة بالكامل) ======
@app.route('/chat',methods=['POST'])
@limiter.limit("5 per minute")
def chat():
 try:
  d=request.get_json();um=d.get("message","").strip();hist=d.get("history",[]);cid=d.get("conv_id",None)
  if not um:return jsonify({"reply":"اكتب شيء أساعدك فيه"})
  uid=get_user_id()
  if cid is None:sm[uid]=[]
  model = OPENAI_MODEL

  # ====== الصور والفيديو (Pexels - مجاني) ======
  draw_phrases = ["ارسم لي", "ابي صورة", "ابي صوره", "ابي صورت", "صوره لي", "ارسم", "أنشئ", "انشئ", "انشى", "صمم", "ولّد", "generate", "draw", "فيديو", "ابي فيديو", "عرض فيديو"]
  is_image_req = any(phrase in um for phrase in draw_phrases)

  if is_image_req:
   video_keywords = ["فيديو", "ابي فيديو", "عرض فيديو"]
   is_video = any(kw in um for kw in video_keywords)
   if is_video:
       video_result = search_video(um)
       if video_result and video_result.startswith("ERROR:"):
           reply = f"⚠️ عذراً، ما قدرت أجيب الفيديو: {video_result.replace('ERROR:', '')}"
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply, "conv_id": nid})
       elif video_result:
           reply = f"🎬 إليك الفيديو الذي طلبتـه:\n{video_result}"
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply, "image_url": video_result, "conv_id": nid})
       else:
           reply = "⚠️ عذراً، تعذر جلب الفيديو."
           sm[uid].append({"role": "user", "content": um})
           sm[uid].append({"role": "assistant", "content": reply})
           nid = save_user_conversation(uid, sm[uid], cid)
           return jsonify({"reply": reply, "conv_id": nid})

   img_result = generate_image(um)
   if img_result and img_result.startswith("ERROR:"):
        reply = f"⚠️ عذراً، ما قدرت أولد الصورة: {img_result.replace('ERROR:', '')}"
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "conv_id": nid})
   elif img_result:
        reply = f"🖼️ إليك الصورة التي طلبتها:\n{img_result}"
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "image_url": img_result, "conv_id": nid})
   else:
        reply = "⚠️ عذراً، تعذر توليد الصورة."
        sm[uid].append({"role": "user", "content": um})
        sm[uid].append({"role": "assistant", "content": reply})
        nid = save_user_conversation(uid, sm[uid], cid)
        return jsonify({"reply": reply, "conv_id": nid})

  # ====== البحث المجاني بالويب (للجميع) ======
  search_result = search_web(um)
  if search_result:
      hist.append({"role": "user", "content": f"نتيجة البحث عن '{um}':\n{search_result}\n\nاستخدم هذه المعلومات في ردك."})
      print("✅ تم جلب نتائج بحث مجانية من DuckDuckGo")

  # ====== بناء المحادثة ======
  context = hist[-10:] if len(hist) > 10 else hist
  msgs=[{"role":"system","content":SP}]
  for e in context:msgs.append({"role":e["role"],"content":e["content"]})
  msgs.append({"role":"user","content":um})

  # ====== استدعاء النموذج (المدفوع لكن رخيص) ======
  try:
   r=client.chat.completions.create(model=model,messages=msgs,max_completion_tokens=1000,temperature=0.8);reply=r.choices[0].message.content.strip()
   if not reply:reply="ما قدرت أجيب لك رد، حاول مرة أخرى."
  except Exception as e:
   print(f"❌ فشل النموذج: {e}")
   return jsonify({"error": str(e)}), 500

  # ====== تنظيف النص ======
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

  # ====== حفظ المحادثة ======
  sm[uid].append({"role":"user","content":um})
  sm[uid].append({"role":"assistant","content":reply})
  if len(sm[uid]) > 50:
      sm[uid] = sm[uid][-50:]
  nid = save_user_conversation(uid, sm[uid], cid)

  # ====== الصوت المجاني ======
  try:gender=session.get('voice_gender','male');audio=generate_speech(reply,gender)
  except Exception as e:print(f"⚠️ فشل الصوت: {e}");audio=None

  return jsonify({"reply":reply,"audio":audio,"conv_id":nid})

 except Exception as e:print(f"❌ خطأ عام: {e}");return jsonify({"error":str(e)}),500

@app.route('/<path:filename>')
def serve_static_files(filename):return send_from_directory(app.static_folder,filename)

if __name__=='__main__':app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)))
