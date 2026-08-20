from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
import openai
import os
import secrets
import json
import hashlib
from datetime import datetime
import asyncio
import edge_tts
import base64
import re
import sqlite3

app = Flask(__name__)

# ===== الإعدادات الأساسية =====
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود! يجب إضافته في متغيرات البيئة")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# ===== ملف robots.txt مدمج مباشرة (بدون مجلد static) =====
@app.route('/robots.txt')
def serve_robots():
    return "User-agent: *\nAllow: /"

# ===== تحميل ملف المعرفة (اختياري) =====
knowledge_content = ""
possible_names = ["Knowledge.md", "knowledge.md", "معرفة.md"]
for filename in possible_names:
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            knowledge_content = f.read()
            break
if not knowledge_content:
    knowledge_content = "أنت روز، صديقة ذكية للبنات. لديك معرفة واسعة في الطبخ والمكياج والموضة."

# ===== تعليمات النظام =====
SYSTEM_PROMPT = f"""
أنت "روز"، مساعدة شخصية ذكية، صديقة مقربة للبنات. تتحدثين بلهجة خليجية ناعمة ودافئة.
أنت خبيرة في الطبخ، المكياج، العناية بالبشرة، الموضة، والأمور النسائية.
ردودك مختصرة، ملهمة، وجميلة، مع لمسات من الدلال والحيوية.
استخدمي ملف المعرفة أدناه كمرجع أساسي.

ملف المعرفة الخاص بك:
{knowledge_content}

تعليمات:
- إذا سألك المستخدم عن شيء، حاولي الإجابة من ملف المعرفة أولاً.
- حافظي على لهجتك الناعمة.
- إذا لم تجدي المعلومة، قولي بصراحة "ما عندي علم يا عسل".
- لا تكتبي "لحظة" أو "انتظر"، أجيبي مباشرة.
"""

# ========== قاعدة بيانات المحادثات ==========
DB_FILE = "conversations.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversations
                 (user_id TEXT, conv_id TEXT, messages TEXT, timestamp TEXT, title TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON conversations(user_id)')
    conn.commit()
    conn.close()

def get_user_conversations(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT conv_id, messages, timestamp, title FROM conversations WHERE user_id=? ORDER BY timestamp DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [{"id": row[0], "messages": json.loads(row[1]), "timestamp": row[2], "title": row[3]} for row in rows]

def save_user_conversation(user_id, conversation, conv_id=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if conv_id is None:
        title = conversation[0]["content"][:30] + "..." if len(conversation[0]["content"]) > 30 else conversation[0]["content"]
        new_conv_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        messages_json = json.dumps(conversation)
        c.execute("INSERT INTO conversations (user_id, conv_id, messages, timestamp, title) VALUES (?, ?, ?, ?, ?)",
                  (user_id, new_conv_id, messages_json, datetime.now().isoformat(), title))
        conn.commit()
        conn.close()
        return new_conv_id
    else:
        messages_json = json.dumps(conversation)
        c.execute("UPDATE conversations SET messages=?, timestamp=? WHERE user_id=? AND conv_id=?",
                  (messages_json, datetime.now().isoformat(), user_id, conv_id))
        conn.commit()
        conn.close()
        return conv_id

def load_conversation_by_id(user_id, conv_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT messages FROM conversations WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    row = c.fetchone()
    conn.close()
    return json.loads(row[0]) if row else None

init_db()

# ===== دالة إزالة الإيموجي للصوت =====
def remove_emoji(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF"
        u"\U00002500-\U00002BEF" u"\U00002702-\U000027B0"
        u"\U000024C2-\U0001F251" u"\U0001f926-\U0001f937"
        u"\U00010000-\U0010ffff" u"\u2640-\u2642"
        u"\u2600-\u2B55" u"\u200d" u"\u23cf"
        u"\u23e9" u"\u231a" u"\ufe0f" u"\u3030"
    "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

# ===== دالة الصوت (Edge TTS) =====
async def generate_speech_async(text, gender):
    voice_id = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariyahNeural"
    clean_text = remove_emoji(text)
    communicate = edge_tts.Communicate(clean_text, voice_id, rate='-15%')
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode('utf-8')

def generate_speech(text, gender):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(generate_speech_async(text, gender))
    finally:
        loop.close()

# ===== واجهة الدردشة (وردية، ناعمة) =====
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes" />
    <title>روز - مساعدتك الذكية</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; }
        body { background: #fff5f7; height: 100dvh; display: flex; justify-content: center; align-items: center; margin: 0; }
        .app { width: 100%; max-width: 450px; height: 100dvh; background: #ffffff; display: flex; flex-direction: column; position: relative; border-radius: 24px 24px 0 0; box-shadow: 0 0 20px rgba(255, 105, 135, 0.1); }
        
        .header { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; background: #fff5f7; border-bottom: 1px solid #fce4ec; border-radius: 24px 24px 0 0; flex-shrink: 0; }
        .header-right { display: flex; align-items: center; gap: 12px; }
        .header-left { display: flex; align-items: center; gap: 12px; }
        .menu-btn, .mute-btn { background: none; border: none; font-size: 20px; color: #e88b9c; cursor: pointer; padding: 4px; transition: 0.2s; }
        .menu-btn:hover, .mute-btn:hover { color: #d47384; }
        .mute-btn.muted { opacity: 0.4; transform: scale(0.9); }

        .btn-group { display: flex; gap: 8px; }
        .btn { padding: 8px 20px; border-radius: 30px; font-size: 14px; border: none; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; transition: 0.2s; }
        .btn-outline { background: transparent; border: 1.5px solid #e88b9c; color: #e88b9c; }
        .btn-outline:hover { background: #e88b9c; color: white; }

        .dropdown { position: absolute; top: 72px; left: 14px; right: 14px; background: #ffffff; border-radius: 24px; box-shadow: 0 8px 30px rgba(232, 139, 156, 0.15); display: none; flex-direction: column; z-index: 100; border: 1px solid #fce4ec; max-height: 60vh; overflow-y: auto; }
        .dropdown.show { display: flex; }
        .dropdown .item { display: flex; align-items: center; gap: 12px; padding: 14px 18px; font-size: 15px; color: #5a3c41; background: none; border: none; width: 100%; text-align: right; cursor: pointer; border-bottom: 1px solid #fce4ec; transition: 0.2s; }
        .dropdown .item:hover { background: #fff0f3; }
        .dropdown .conv-item { display: block; padding: 14px 18px; border-bottom: 1px solid #fce4ec; cursor: pointer; width: 100%; background: none; border: none; text-align: right; font-size: 15px; color: #5a3c41; transition: 0.2s; }
        .dropdown .conv-item:hover { background: #fff0f3; }

        #chat { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; background: #ffffff; }
        .msg { max-width: 85%; padding: 14px 20px; border-radius: 24px; font-size: 16px; line-height: 1.6; word-wrap: break-word; white-space: pre-wrap; color: #3a2a2e; }
        .msg.user { align-self: flex-end; background: #ffeef2; border-bottom-left-radius: 6px; }
        .msg.bot { align-self: flex-start; background: #faf0f2; border-bottom-right-radius: 6px; }
        .msg .time { font-size: 10px; opacity: 0.5; display: block; margin-top: 4px; }
        .msg.error { background: #fce4ec; color: #b34a5a; align-self: center; max-width: 90%; }
        .msg .image-upload { max-width: 100%; max-height: 200px; border-radius: 16px; margin: 4px 0; border: 1px solid #fce4ec; }
        .typing-indicator { align-self: flex-start; background: #faf0f2; padding: 14px 20px; border-radius: 24px; border-bottom-right-radius: 6px; color: #b38b94; font-size: 16px; }
        .typing-dots::after { content: '...'; animation: dots 1.2s steps(4, end) infinite; }
        @keyframes dots { 0%, 20% { content: ''; } 40% { content: '.'; } 60% { content: '..'; } 80%, 100% { content: '...'; } }

        .welcome-overlay { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(232, 139, 156, 0.25); z-index: 9999; animation: fadeIn 0.5s ease; }
        .welcome-box { background: #ffffff; padding: 40px; border-radius: 32px; box-shadow: 0 20px 40px rgba(232, 139, 156, 0.15); text-align: center; max-width: 90%; border: 1px solid #fce4ec; }
        .welcome-box h2 { font-size: 28px; color: #e88b9c; margin-bottom: 8px; }
        .welcome-box p { font-size: 18px; color: #b38b94; margin: 0; }
        @keyframes fadeIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }

        #imagePreviewContainer { display: none; padding: 8px 16px; align-items: center; gap: 10px; background: #fff5f7; margin: 0 14px; border-radius: 20px 20px 0 0; border: 1px solid #fce4ec; border-bottom: none; }
        #imagePreviewContainer img { max-height: 60px; border-radius: 12px; border: 1px solid #fce4ec; }
        #removeImageBtn { background: none; border: none; color: #e88b9c; font-size: 14px; cursor: pointer; }

        .input-area { display: flex; align-items: flex-end; gap: 8px; padding: 8px 14px; margin: 8px 14px 16px 14px; background: #fff5f7; border-radius: 40px; border: 1px solid #fce4ec; flex-shrink: 0; min-height: 60px; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 12px 0; font-size: 16px; font-weight: 500; outline: none; color: #3a2a2e; direction: rtl; resize: none; overflow: hidden; min-height: 20px; max-height: 80px; line-height: 1.4; }
        .input-area textarea::placeholder { color: #c4aab0; }
        .input-area .btn-icon { background: none; border: none; color: #e88b9c; font-size: 20px; cursor: pointer; padding: 4px; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; transition: 0.2s; }
        .input-area .btn-icon:hover { background: #ffeef2; }
        .input-area .send { background: #e88b9c; color: white; border: none; width: 44px; height: 44px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(232, 139, 156, 0.25); transition: 0.2s; }
        .input-area .send:hover { background: #d47384; transform: scale(1.02); }
        .plus-btn { background: none; border: none; color: #e88b9c; font-size: 22px; cursor: pointer; padding: 4px; transition: 0.3s; }
        .plus-btn.rotate { transform: rotate(45deg); }
        
        .plus-options { display: none; position: absolute; bottom: 80px; right: 14px; background: #ffffff; border-radius: 24px; box-shadow: 0 8px 30px rgba(232, 139, 156, 0.15); padding: 8px; gap: 6px; flex-direction: row; border: 1px solid #fce4ec; z-index: 50; }
        .plus-options.show { display: flex; }
        .plus-options .option-btn { background: #fff5f7; border: none; border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #e88b9c; cursor: pointer; transition: 0.2s; }
        .plus-options .option-btn:hover { background: #ffeef2; }

        .gender-option { flex: 1; padding: 8px 4px; border-radius: 12px; border: 1px solid #fce4ec; background: transparent; font-size: 14px; color: #b38b94; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 4px; }
        .gender-option:hover { background: #fff5f7; }
        .gender-option.active { background: #e88b9c; color: white; border-color: #e88b9c; }

        @media (max-width: 420px) {
            .header { padding: 12px 16px; }
            .btn { font-size: 12px; padding: 6px 14px; }
            .welcome-box { padding: 30px; }
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="header-right">
            <button class="mute-btn" id="muteBtn" title="كتم/تفعيل الصوت"><i class="fas fa-volume-up"></i></button>
            <button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button>
        </div>
        <div class="header-left">
            <div class="btn-group">
                <a href="/login" class="btn btn-outline" style="display:{% if session.get('user_email') or session.get('admin_email') %}none{% endif %}">دخول</a>
                <a href="/logout" class="btn btn-outline" style="display:{% if not session.get('user_email') and not session.get('admin_email') %}none{% endif %}">خروج</a>
            </div>
        </div>
    </div>

    <div class="dropdown" id="dropdown">
        <button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
        <div class="item" style="flex-direction: column; align-items: stretch; gap: 8px; cursor: default; border-bottom: 1px solid #fce4ec;">
            <div style="display:flex; align-items:center; gap:8px; font-size:14px; color:#3a2a2e;">
                <i class="fas fa-microphone" style="color:#e88b9c;"></i> <span>صوت روز</span>
            </div>
            <div style="display:flex; gap:8px;">
                <button class="gender-option active" data-gender="male">👨 ذكر</button>
                <button class="gender-option" data-gender="female">👩 أنثى</button>
            </div>
        </div>
        <div id="historyList"></div>
    </div>

    <div id="chat"></div>

    <div id="imagePreviewContainer">
        <img id="imagePreview" src="" alt="معاينة" />
        <span style="font-size:13px; color:#b38b94;">📎 صورة</span>
        <button id="removeImageBtn">✕ إزالة</button>
    </div>

    <div class="input-area">
        <button class="btn-icon mic-btn" id="micBtn"><i class="fas fa-microphone"></i></button>
        <button class="plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button>
        <div class="plus-options" id="plusOptions">
            <button class="option-btn camera" id="cameraBtn"><i class="fas fa-camera"></i></button>
            <button class="option-btn gallery" id="galleryBtn"><i class="fas fa-images"></i></button>
        </div>
        <textarea id="userInput" placeholder="اكتبي لروز..." autofocus rows="1"></textarea>
        <button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button>
    </div>
    
    <input type="file" id="fileInput" accept="image/*" style="display:none;" />
    <input type="file" id="cameraInput" accept="image/*" capture="environment" style="display:none;" />
</div>
<script>
    (function(){
        let history=[], pendingImage=null, waiting=false, currentId=null, currentAudio=null;
        const chat=document.getElementById('chat'), input=document.getElementById('userInput'), send=document.getElementById('sendBtn');
        const mic=document.getElementById('micBtn'), fileIn=document.getElementById('fileInput'), camIn=document.getElementById('cameraInput');
        const menu=document.getElementById('menuToggle'), dropdown=document.getElementById('dropdown');
        const plusBtn=document.getElementById('plusBtn'), plusOpt=document.getElementById('plusOptions');
        const imgCont=document.getElementById('imagePreviewContainer'), imgPrev=document.getElementById('imagePreview'), rmImg=document.getElementById('removeImageBtn');
        const histList=document.getElementById('historyList');
        let muted=true; const muteBtn=document.getElementById('muteBtn'); muteBtn.querySelector('i').className='fas fa-volume-mute'; muteBtn.classList.add('muted');
        muteBtn.onclick=()=>{ muted=!muted; muteBtn.querySelector('i').className=muted?'fas fa-volume-mute':'fas fa-volume-up'; muteBtn.classList.toggle('muted',muted); if(currentAudio){currentAudio.pause(); currentAudio.currentTime=0;} }

        let isMale=true; document.querySelectorAll('.gender-option').forEach(b=>{ b.onclick=e=>{ e.stopPropagation(); isMale=b.dataset.gender=='male'; document.querySelectorAll('.gender-option').forEach(x=>x.classList.remove('active')); b.classList.add('active'); fetch('/set_gender',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({gender:b.dataset.gender})}); dropdown.classList.remove('show'); } });

        menu.onclick=e=>{ e.stopPropagation(); dropdown.classList.toggle('show'); if(dropdown.classList.contains('show')) loadHistory(); };
        document.onclick=e=>{ if(!dropdown.contains(e.target)&&e.target!==menu) dropdown.classList.remove('show'); if(!plusOpt.contains(e.target)&&e.target!==plusBtn) plusOpt.classList.remove('show'); };

        async function loadHistory(){ try{ const res=await fetch('/history'); const data=await res.json(); histList.innerHTML=''; if(data.conversations&&data.conversations.length>0){ data.conversations.forEach(c=>{ const btn=document.createElement('button'); btn.className='conv-item'; btn.textContent=c.title; btn.onclick=()=>loadConv(c.id); histList.appendChild(btn); }); } else { const emp=document.createElement('div'); emp.className='item'; emp.textContent='📭 لا توجد محادثات'; histList.appendChild(emp); } }catch(e){console.error(e);} }
        async function loadConv(id){ const res=await fetch(`/load_conversation/${id}`); const data=await res.json(); if(data.messages){ chat.innerHTML=''; history=data.messages; currentId=id; data.messages.forEach(m=>addMessage(m.content,m.role==='user'?'user':'bot',true)); dropdown.classList.remove('show'); } }
        document.querySelector('[data-action="new"]').onclick=()=>{ chat.innerHTML=''; history=[]; currentId=null; pendingImage=null; imgCont.style.display='none'; input.value=''; dropdown.classList.remove('show'); };

        function addMessage(text, sender='bot', isSystem=false, img=null){
            const el=document.createElement('div'); el.className=`msg ${sender}`; if(sender==='error') el.classList.add('error');
            const time=isSystem?'':new Date().toLocaleTimeString('ar-SA',{hour:'2-digit',minute:'2-digit'});
            if(img){ el.innerHTML=`<img src="${img}" class="image-upload" />${time?' <span class="time">'+time+'</span>':''}`; chat.appendChild(el); chat.scrollTop=chat.scrollHeight; return; }
            let display=text, genImg=null; 
            // تم إصلاح التعبير النمطي (Regex) هنا لتجنب خطأ بايثون
            const match=text.match(/(https?:\\/\\/[^\s]+\\.(png|jpg|jpeg|gif|webp))/i);
            if(match){ genImg=match[0]; display=text.replace(match[0],'').trim()||'🖼️'; }
            if(sender==='bot'&&!isSystem&&!genImg){
                el.innerHTML=`<span class="typing-text"></span>${time?' <span class="time">'+time+'</span>':''}`; chat.appendChild(el); chat.scrollTop=chat.scrollHeight;
                let idx=0; const span=el.querySelector('.typing-text'); function type(){ if(idx<display.length){ span.textContent+=display.charAt(idx++); chat.scrollTop=chat.scrollHeight; setTimeout(type,20); } else if(genImg){ const imgEl=document.createElement('img'); imgEl.src=genImg; imgEl.className='generated-image'; el.appendChild(imgEl); chat.scrollTop=chat.scrollHeight; } } type(); return;
            }
            el.innerHTML=`${display}${genImg?'<br/><img src="'+genImg+'" class="generated-image" />':''}${time?' <span class="time">'+time+'</span>':''}`; chat.appendChild(el); chat.scrollTop=chat.scrollHeight;
        }

        if(!sessionStorage.getItem('roseWelcome')){ const ov=document.createElement('div'); ov.className='welcome-overlay'; ov.innerHTML=`<div class="welcome-box"><h2>🌸 أهلاً بك في روز</h2><p>أنا هنا أساعدك في الطبخ، المكياج، والموضة 💗</p></div>`; document.body.appendChild(ov); sessionStorage.setItem('roseWelcome','true'); setTimeout(()=>{ ov.classList.add('fade-out'); setTimeout(()=>ov.remove(),500); },4000); }

        document.getElementById('galleryBtn').onclick=()=>{ fileIn.click(); plusOpt.classList.remove('show'); };
        document.getElementById('cameraBtn').onclick=()=>{ camIn.click(); plusOpt.classList.remove('show'); };
        fileIn.onchange=e=>{ const f=e.target.files[0]; if(f){ const r=new FileReader(); r.onload=ev=>{ pendingImage=ev.target.result; imgPrev.src=pendingImage; imgCont.style.display='flex'; }; r.readAsDataURL(f); fileIn.value=''; } };
        camIn.onchange=fileIn.onchange;
        rmImg.onclick=()=>{ pendingImage=null; imgCont.style.display='none'; imgPrev.src=''; };

        plusBtn.onclick=()=>{ plusOpt.classList.toggle('show'); plusBtn.classList.toggle('rotate'); };

        async function sendMessage(){
            if(waiting) return;
            const txt=input.value.trim(), img=pendingImage;
            if(!txt&&!img) return;
            if(txt) addMessage(txt,'user');
            if(img){ addMessage('🖼️','user',false,img); pendingImage=null; imgCont.style.display='none'; }
            input.value=''; input.style.height='auto'; waiting=true;
            const typing=document.createElement('div'); typing.className='msg bot typing-indicator'; typing.innerHTML='<span class="typing-dots">جاري التفكير</span>'; chat.appendChild(typing); chat.scrollTop=chat.scrollHeight;
            try{
                const res=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:txt||"📎 مرفق",image:img||null,history:history,conv_id:currentId,voice_enabled:!muted})});
                const data=await res.json();
                if(typing.parentNode) typing.remove();
                if(res.ok){ addMessage(data.reply,'bot'); if(!muted&&data.audio){ if(currentAudio){currentAudio.pause();currentAudio.currentTime=0;} currentAudio=new Audio(`data:audio/mp3;base64,${data.audio}`); currentAudio.play(); } if(data.conv_id) currentId=data.conv_id; }
                else addMessage('خطأ: '+(data.error||'مشكلة'),'error');
            }catch(e){ if(typing.parentNode) typing.remove(); addMessage('تعذر الاتصال','error'); }finally{ waiting=false; }
        }
        send.onclick=sendMessage; input.onkeypress=e=>{ if(e.key==='Enter'){ e.preventDefault(); sendMessage(); } };

        let rec=null; mic.onclick=()=>{ if(!('webkitSpeechRecognition'in window)) return addMessage('المتصفح لا يدعم الصوت.','bot',true); if(mic.classList.contains('listening')){ mic.classList.remove('listening'); if(rec) rec.stop(); return; } const SR=window.SpeechRecognition||window.webkitSpeechRecognition; rec=new SR(); rec.lang='ar-SA'; mic.classList.add('listening'); rec.onresult=e=>{ input.value=e.results[0][0].transcript; mic.classList.remove('listening'); setTimeout(sendMessage,300); }; rec.onerror=()=>mic.classList.remove('listening'); rec.start(); };
    })();
</script>
</body>
</html>
"""

# ===== صفحة الدخول (وردية بسيطة) =====
LOGIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>دخول - روز</title>
<style>
    * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    body { background: #fff5f7; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
    .box { background: white; padding: 40px; border-radius: 30px; box-shadow: 0 8px 30px rgba(232, 139, 156, 0.15); width: 100%; max-width: 400px; text-align: center; border: 1px solid #fce4ec; }
    h2 { font-size: 28px; color: #e88b9c; margin-bottom: 20px; }
    input { width: 100%; padding: 14px; margin: 10px 0; border: 1px solid #fce4ec; border-radius: 16px; font-size: 16px; outline: none; }
    input:focus { border-color: #e88b9c; }
    button { width: 100%; padding: 16px; background: #e88b9c; color: white; border: none; border-radius: 30px; font-size: 18px; font-weight: bold; cursor: pointer; margin-top: 10px; transition: 0.2s; }
    button:hover { background: #d47384; transform: scale(1.01); }
    a { color: #e88b9c; text-decoration: none; display: inline-block; margin-top: 20px; }
</style>
</head>
<body>
<div class="box">
    <h2>🌸 دخول روز</h2>
    {% if error %}<div style="color:#b34a5a;margin-bottom:15px;">{{ error }}</div>{% endif %}
    <form method="POST">
        <input type="email" name="email" placeholder="بريدك الإلكتروني" required>
        <input type="password" name="password" placeholder="كلمة المرور (للأدمن)" style="margin-top:0;">
        <button type="submit">دخول</button>
    </form>
    <a href="/">⬅ العودة</a>
</div></body></html>
"""

# ===== المسارات =====
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        if email == "abdullaha0569361@gmail.com":
            if password == "roseadmin":
                session['admin_email'] = email
                return redirect(url_for('index'))
            else:
                return render_template_string(LOGIN_HTML, error="كلمة مرور الأدمن غير صحيحة")
        elif email and "@" in email:
            session['user_email'] = email
            return redirect(url_for('index'))
        return render_template_string(LOGIN_HTML, error="بريد إلكتروني غير صحيح")
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/history')
def history():
    user_id = get_user_id()
    convs = get_user_conversations(user_id)
    return jsonify({"conversations": [{"id": c["id"], "title": c["title"]} for c in convs]})

@app.route('/load_conversation/<conv_id>')
def load_conversation(conv_id):
    user_id = get_user_id()
    msgs = load_conversation_by_id(user_id, conv_id)
    return jsonify({"messages": msgs}) if msgs else (jsonify({"messages": None}), 404)

@app.route('/set_gender', methods=['POST'])
def set_gender():
    session['voice_gender'] = request.get_json().get('gender', 'male')
    return jsonify({"status": "ok"})

def get_user_id():
    if 'admin_email' in session:
        return "admin_" + session['admin_email']
    elif 'user_email' in session:
        return "user_" + session['user_email']
    else:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        return "guest_" + (ip.split(',')[0].strip() if ip else 'unknown')

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        conv_id = data.get("conv_id", None)
        image_data = data.get("image", None)
        voice_enabled = bool(data.get("voice_enabled", False))

        if not user_message and not image_data:
            return jsonify({"reply": "اكتبي شي يا عسل"})

        user_id = get_user_id()
        is_admin = 'admin_email' in session and session['admin_email'] == "abdullaha0569361@gmail.com"

        if is_admin:
            model = "gpt-4o"
            allow_images = True
        else:
            model = "gpt-4o-mini"
            allow_images = False

        if conv_id is None:
            conversation_history = []
        else:
            conversation_history = load_conversation_by_id(user_id, conv_id) or []

        if image_data and allow_images:
            user_content = [{"type": "text", "text": user_message or "حللي هذه الصورة"}, {"type": "image_url", "image_url": {"url": image_data}}]
        else:
            user_content = user_message

        conversation_history.append({"role": "user", "content": user_content})
        chat_history = conversation_history[-10:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + chat_history

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=800,
                temperature=0.8
            )
            reply = response.choices[0].message.content.strip() or "ما قدرت أجيب، حاولي مرة ثانية."
        except Exception as e:
            print(f"خطأ: {e}")
            reply = "حدث خطأ، حاولي لاحقاً."

        conversation_history.append({"role": "assistant", "content": reply})
        new_id = save_user_conversation(user_id, conversation_history, conv_id)

        audio_base64 = None
        if voice_enabled:
            try:
                gender = session.get('voice_gender', 'female')
                audio_base64 = generate_speech(reply, gender)
            except Exception as e:
                print(f"فشل الصوت: {e}")

        return jsonify({"reply": reply, "audio": audio_base64, "conv_id": new_id})
    except Exception as e:
        print(f"خطأ عام: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
