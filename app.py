from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, send_from_directory
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

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود! يجب إضافته في متغيرات البيئة")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_ENABLED = True

@app.route('/robots.txt')
def serve_robots():
    return send_from_directory('static', 'robots.txt')

DB_FILE = "conversations.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversations
                 (user_id TEXT, conv_id TEXT, messages TEXT, timestamp TEXT, title TEXT)''')
    conn.commit()
    conn.close()

def get_user_conversations(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT conv_id, messages, timestamp, title FROM conversations WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({"id": row[0], "messages": json.loads(row[1]), "timestamp": row[2], "title": row[3]})
    return result

def save_user_conversation(user_id, conversation, conv_id=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if conv_id is None:
        title = conversation[0]["content"][:30] + "..." if len(conversation[0]["content"]) > 30 else conversation[0]["content"]
        new_conv_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        messages_json = json.dumps(conversation)
        c.execute("INSERT INTO conversations (user_id, conv_id, messages, timestamp, title) VALUES (?, ?, ?, ?, ?)",
                  (user_id, new_conv_id, messages_json, datetime.now().isoformat(), title))
        conn.commit(); conn.close(); return new_conv_id
    else:
        messages_json = json.dumps(conversation)
        c.execute("UPDATE conversations SET messages=?, timestamp=? WHERE user_id=? AND conv_id=?",
                  (messages_json, datetime.now().isoformat(), user_id, conv_id))
        conn.commit(); conn.close(); return conv_id

def load_conversation_by_id(user_id, conv_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT messages FROM conversations WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    row = c.fetchone(); conn.close()
    if row: return json.loads(row[0])
    return None

init_db()
session_memory = {}
knowledge_content = ""
possible_names = ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]
for filename in possible_names:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: knowledge_content = f.read(); break
        except: pass
if not knowledge_content: knowledge_content = "أنت نبراس، مساعد ذكي."

SYSTEM_PROMPT = f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.
3. **البحث بالويب** تستخدمه عندما يسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.

**ملف المعرفة الخاص بك:**
{knowledge_content}

**⚠️ قواعد التنسيق الإلزامية:**
- اكتب ردك في فقرات نصية عادية متصلة.
- **ممنوع** وضع كل جملة في سطر مستقل.
- اترك سطراً فارغاً بين الفقرات.
- استخدم `**الخط العريض**`، و`-` للقوائم.

**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة في ملف المعرفة، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- لا تكتب "لحظة" أو "انتظر".
"""

def remove_emoji(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF" u"\U00002500-\U00002BEF" u"\U00002702-\U000027B0" u"\U000024C2-\U0001F251" u"\U0001f926-\U0001f937" u"\U00010000-\U0010ffff" u"\u2640-\u2642" u"\u2600-\u2B55" u"\u200d" u"\u23cf" u"\u23e9" u"\u231a" u"\ufe0f" u"\u3030"
    "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def generate_image(prompt):
    try:
        response = client.images.generate(model="dall-e-3", prompt=prompt, n=1, size="1024x1024")
        return response.data[0].url
    except Exception as e:
        print(f"❌ فشل توليد الصورة: {e}"); return None

async def generate_speech(text, gender):
    voice_id = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariyahNeural"
    communicate = edge_tts.Communicate(remove_emoji(text), voice_id, rate='-15%')
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio": audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode('utf-8')

# =====================================================================
# الواجهة الجديدة المصغرة (مطابقة تماماً لتصميم DeepSeek الحقيقي)
# =====================================================================
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes" />
    <title>نبراس</title>
    <link rel="manifest" href="/static/manifest.json" />
    <link rel="icon" type="image/jpeg" href="/static/icon-512.jpeg" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
        body { background: #ffffff; height: 100dvh; display: flex; justify-content: center; align-items: center; margin: 0; padding: 0; }
        .app { width: 100%; max-width: 450px; height: 100dvh; background: #ffffff; display: flex; flex-direction: column; position: relative; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #eaeef2; flex-shrink: 0; }
        .header-right, .header-left { display: flex; align-items: center; gap: 10px; }
        .logo-text { font-weight: 600; color: #1a2b3c; text-decoration: none; font-size: 15px; }
        .menu-btn, .mute-btn { background: none; border: none; font-size: 20px; color: #5a6b7c; cursor: pointer; padding: 4px 8px; border-radius: 50%; }
        
        .welcome-area { flex: 1; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 15px; }
        .brand-logo { font-size: 35px; line-height: 1; }
        .mode-title { font-size: 17px; font-weight: 700; color: #1a2b3c; display: flex; gap: 5px; align-items: center; }
        
        .mode-buttons { display: flex; gap: 5px; background: #f0f2f5; padding: 4px; border-radius: 30px; }
        .mode-btn { border: none; background: transparent; padding: 8px 18px; border-radius: 30px; font-size: 14px; font-weight: 600; color: #5a6b7c; cursor: pointer; display: flex; align-items: center; gap: 5px; }
        .mode-btn.active { background: #ffffff; color: #1a2b3c; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
        .mode-btn i { font-size: 14px; }

        #chat { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; }
        .msg { max-width: 90%; padding: 12px 16px; border-radius: 20px; font-size: 16px; font-weight: 700; line-height: 1.8; word-wrap: break-word; white-space: normal; color: #000000; }
        .msg.user { align-self: flex-end; background: #eef2f7; border-bottom-right-radius: 6px; }
        .msg.bot { align-self: flex-start; background: transparent; border-bottom-left-radius: 6px; }
        
        .msg.bot h1, .msg.bot h2, .msg.bot h3 { font-weight: 700; margin: 15px 0 10px; }
        .msg.bot strong { font-weight: 800; }
        .msg.bot code { background: #f1f3f5; padding: 2px 5px; border-radius: 4px; font-family: monospace; font-size: 14px; }
        .msg.bot p { margin: 0 0 10px; }
        .msg .time { font-size: 10px; opacity: 0.4; margin-top: 4px; }

        .input-wrap { padding: 8px 14px 14px; flex-shrink: 0; }
        .input-area { display: flex; align-items: center; gap: 8px; background: #f5f7fa; border-radius: 40px; border: 1px solid #eaeef2; padding: 5px 12px; min-height: 48px; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 8px 0; font-size: 16px; outline: none; color: #111; direction: rtl; resize: none; overflow: hidden; max-height: 80px; }
        .input-area textarea::placeholder { color: #9aabbc; }
        .icon-btn { background: none; border: none; color: #6a7b8c; font-size: 18px; cursor: pointer; padding: 4px; border-radius: 50%; flex-shrink: 0; }
        
        .mode-btn.small { background: #f0f2f5; padding: 5px 10px; font-size: 12px; border-radius: 20px; flex-shrink: 0; display: flex; align-items: center; gap: 3px; color: #5a6b7c; }
        .mode-btn.small i { font-size: 12px; }
        .mode-btn.small.active { background: #eef2f7; color: #1a2b3c; }
        
        .send-btn { background: #4a6a8a; color: white; border: none; width: 36px; height: 36px; border-radius: 50%; font-size: 14px; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
        .send-btn:hover { background: #3a5a7a; }
        
        .typing-indicator { align-self: flex-start; background: transparent; padding: 12px 18px; font-size: 16px; color: #5a6b7c; }
        .typing-dots::after { content: '...'; animation: dotAnimation 1.2s steps(4, end) infinite; }
        @keyframes dotAnimation { 0%, 20% { content: ''; } 40% { content: '.'; } 60% { content: '..'; } 80%, 100% { content: '...'; } }
        
        .dropdown { position: absolute; top: 60px; left: 14px; right: 14px; background: white; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); display: none; flex-direction: column; z-index: 100; border: 1px solid #eaedf2; }
        .dropdown.show { display: flex; }
        .dropdown .item { display: flex; align-items: center; gap: 12px; padding: 14px 18px; font-size: 15px; color: #1a2b3c; border-bottom: 1px solid #f0f2f5; cursor: pointer; background: none; border: none; width: 100%; text-align: right; }
        .dropdown .item:last-child { border-bottom: none; }
        .dropdown .conv-item { display: block; padding: 12px 18px; border-bottom: 1px solid #f0f2f5; cursor: pointer; width: 100%; background: none; border: none; text-align: right; font-size: 16px; color: #1a2b3c; }
        .dropdown .conv-item:hover { background: #f5f7fa; }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="header-right">
            <button class="mute-btn" id="muteBtn" title="كتم الصوت"><i class="fas fa-volume-up"></i></button>
            <button class="menu-btn" id="menuToggle"><i class="fas fa-bars"></i></button>
        </div>
        <div class="header-left">
            <a href="/login" class="logo-text">دخول</a>
        </div>
    </div>

    <div class="dropdown" id="dropdown">
        <button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
        <button class="item" onclick="window.location.href='/plans'"><i class="fas fa-gem"></i> ترقية</button>
        <div id="historyList" style="border-top: 1px solid #f0f2f5;"></div>
    </div>

    <!-- منطقة الترحيب (الحوت الصغير والأنيق) -->
    <div class="welcome-area" id="welcomeArea">
        <div class="brand-logo">🐋</div>
        <div class="mode-title">وضع سريع 🐋</div>
        <div class="mode-buttons">
            <!-- الترتيب الصحيح: الرؤية (يمين)، خبير، سريع (يسار) -->
            <button class="mode-btn" onclick="setMode('vision')"><i class="fas fa-eye"></i> الرؤية</button>
            <button class="mode-btn" onclick="setMode('expert')"><i class="fas fa-gem"></i> خبير</button>
            <button class="mode-btn active" onclick="setMode('fast')"><i class="fas fa-bolt"></i> سريع</button>
        </div>
    </div>

    <div id="chat" style="display: none;"></div>

    <!-- شريط الإدخال (مصغر وأنيق) -->
    <div class="input-wrap">
        <div class="input-area">
            <!-- زر الإرسال في أقصى اليمين (كما في التصميم الأصلي لـ RTL) -->
            <button class="send-btn" id="sendBtn"><i class="fas fa-arrow-up"></i></button>
            <button class="mode-btn small active" id="thinkBtn"><i class="fas fa-network-wired"></i> تفكير</button>
            <button class="mode-btn small" id="searchBtn"><i class="fas fa-globe"></i> بحث</button>
            <textarea id="userInput" placeholder="رسالة أو اضغط للتحدث..." autofocus rows="1"></textarea>
            <button class="icon-btn" id="plusBtn"><i class="fas fa-plus"></i></button>
            <button class="icon-btn" id="micBtn"><i class="fas fa-microphone"></i></button>
            <input type="file" id="fileInput" accept="image/*" style="display: none;" />
        </div>
    </div>
</div>

<script>
    (function() {
        let conversationHistory = [];
        let pendingImageData = null;
        let isWaiting = false;
        let currentConvId = null;
        let currentAudio = null;
        let isMuted = true;
        let currentMode = 'fast';

        const chatBox = document.getElementById('chat');
        const welcomeArea = document.getElementById('welcomeArea');
        const userInput = document.getElementById('userInput');
        const sendBtn = document.getElementById('sendBtn');
        const micBtn = document.getElementById('micBtn');
        const plusBtn = document.getElementById('plusBtn');
        const fileInput = document.getElementById('fileInput');
        const menuToggle = document.getElementById('menuToggle');
        const dropdown = document.getElementById('dropdown');
        const muteBtn = document.getElementById('muteBtn');
        const historyList = document.getElementById('historyList');
        
        function toggleWelcome() {
            if (chatBox.children.length === 0) {
                welcomeArea.style.display = 'flex';
                chatBox.style.display = 'none';
            } else {
                welcomeArea.style.display = 'none';
                chatBox.style.display = 'flex';
            }
        }

        window.setMode = function(mode) {
            currentMode = mode;
            document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
            document.querySelector(`.mode-btn[onclick="setMode('${mode}')"]`).classList.add('active');
        };

        muteBtn.addEventListener('click', function() {
            isMuted = !isMuted;
            muteBtn.querySelector('i').className = isMuted ? 'fas fa-volume-mute' : 'fas fa-volume-up';
            if (isMuted && currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; }
        });

        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation(); dropdown.classList.toggle('show');
            if (dropdown.classList.contains('show')) loadHistory();
        });

        document.addEventListener('click', function(e) {
            if (!menuToggle.contains(e.target) && !dropdown.contains(e.target)) dropdown.classList.remove('show');
        });

        async function loadHistory() {
            const res = await fetch('/history'); const data = await res.json();
            historyList.innerHTML = '';
            if (data.conversations && data.conversations.length > 0) {
                data.conversations.forEach(conv => {
                    const btn = document.createElement('button'); btn.className = 'conv-item'; btn.textContent = conv.title;
                    btn.onclick = () => loadConversation(conv.id); historyList.appendChild(btn);
                });
            } else { historyList.innerHTML = '<div class="item">📭 لا توجد محادثات</div>'; }
        }

        async function loadConversation(convId) {
            const res = await fetch('/load_conversation/' + convId); const data = await res.json();
            if (data.messages) {
                chatBox.innerHTML = ''; conversationHistory = data.messages; currentConvId = convId;
                data.messages.forEach(msg => addMessage(msg.content, msg.role === 'user' ? 'user' : 'bot', true));
                toggleWelcome(); dropdown.classList.remove('show');
            }
        }

        document.querySelector('[data-action="new"]').addEventListener('click', function() {
            chatBox.innerHTML = ''; conversationHistory = []; currentConvId = null; dropdown.classList.remove('show'); toggleWelcome();
        });

        function formatBotText(text) {
            var safe = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            safe = safe.replace(/^### (.*)$/gm, '<h3>$1</h3>');
            safe = safe.replace(/^## (.*)$/gm, '<h2>$1</h2>');
            safe = safe.replace(/^# (.*)$/gm, '<h1>$1</h1>');
            safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
            var paragraphs = safe.split(/\n\s*\n/);
            return paragraphs.map(function(p) {
                p = p.trim(); if (!p) return '';
                p = p.replace(/\n/g, ' ');
                return '<p>' + p + '</p>';
            }).join('');
        }

        function addMessage(text, sender, isSystem = false, imageData = null) {
            const el = document.createElement('div'); el.className = 'msg ' + sender;
            if (sender === 'error') el.classList.add('error');
            const time = isSystem ? '' : ' <span class="time">' + new Date().toLocaleTimeString('ar-SA', {hour:'2-digit', minute:'2-digit'}) + '</span>';
            
            if (imageData) {
                el.innerHTML = '<img src="' + imageData + '" class="image-upload" /><span class="file-label">' + (text || 'صورة') + '</span>' + time;
                chatBox.appendChild(el); chatBox.scrollTop = chatBox.scrollHeight;
                return el;
            }

            if (sender === 'user') {
                el.innerHTML = text + time;
            } else {
                el.innerHTML = '<div class="bot-content">' + formatBotText(text) + '</div>' + time;
            }
            chatBox.appendChild(el); chatBox.scrollTop = chatBox.scrollHeight;
            return el;
        }

        function showTyping() {
            const typingDiv = document.createElement('div');
            typingDiv.className = 'msg bot typing-indicator';
            typingDiv.innerHTML = '<span class="typing-dots">جاري التفكير</span>';
            chatBox.appendChild(typingDiv); chatBox.scrollTop = chatBox.scrollHeight;
            return typingDiv;
        }

        plusBtn.addEventListener('click', function() { fileInput.click(); });
        fileInput.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const reader = new FileReader();
                reader.onload = function(ev) {
                    pendingImageData = ev.target.result;
                    addMessage('🖼️ صورة مرفقة', 'user', false, ev.target.result);
                };
                reader.readAsDataURL(this.files[0]); this.value = '';
            }
        });

        async function sendMessage() {
            if (isWaiting) return;
            const text = userInput.value.trim();
            if (!text && !pendingImageData) return;

            if (text) addMessage(text, 'user');
            if (pendingImageData) addMessage('🖼️ صورة مرفقة', 'user', false, pendingImageData);
            
            userInput.value = ''; 
            isWaiting = true;
            toggleWelcome();

            const typingDiv = showTyping();

            const payload = { 
                message: text || "📎 مرفق", 
                image: pendingImageData || null, 
                history: conversationHistory, 
                conv_id: currentConvId,
                mode: currentMode 
            };
            pendingImageData = null;

            try {
                const res = await fetch('/chat', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (typingDiv.parentNode) typingDiv.remove();

                if (res.ok) {
                    addMessage(data.reply, 'bot');
                    if (!isMuted && data.audio) {
                        if (currentAudio) currentAudio.pause();
                        currentAudio = new Audio('data:audio/mp3;base64,' + data.audio); currentAudio.play();
                    }
                    if (data.conv_id) currentConvId = data.conv_id;
                } else addMessage('خطأ: ' + (data.error || 'مشكلة'), 'error');
            } catch (e) {
                if (typingDiv.parentNode) typingDiv.remove();
                addMessage('تعذر الاتصال بالسيرفر.', 'error');
            } finally {
                isWaiting = false;
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') { e.preventDefault(); sendMessage(); } });
        
        micBtn.addEventListener('click', function() {
            if (!('webkitSpeechRecognition' in window)) { addMessage('المتصفح لا يدعم الصوت.', 'bot', true); return; }
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            let recognition = new SR(); recognition.lang = 'ar-SA'; this.classList.add('listening');
            recognition.onresult = (event) => { userInput.value = event.results[0][0].transcript; this.classList.remove('listening'); sendMessage(); };
            recognition.onerror = () => { this.classList.remove('listening'); };
            recognition.start();
        });

        toggleWelcome();
    })();
</script>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>دخول - نبراس</title>
<style>
    * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    body { background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 15px; }
    .box { background: white; padding: 40px 30px; border-radius: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); width: 100%; max-width: 400px; text-align: center; }
    h2 { font-size: 28px; color: #1a2b3c; margin-bottom: 25px; }
    input { width: 100%; padding: 14px 16px; margin: 12px 0; border: 1px solid #dce1e8; border-radius: 12px; font-size: 18px; background: #fafbfc; box-sizing: border-box; }
    input:focus { outline: none; border-color: #4a6a8a; background: #fff; }
    button { width: 100%; padding: 16px; background: #4a6a8a; color: white; border: none; border-radius: 12px; font-size: 20px; font-weight: bold; cursor: pointer; margin-top: 15px; }
    button:hover { background: #3a5a7a; }
    a { color: #4a6a8a; text-decoration: none; font-size: 16px; display: inline-block; margin-top: 20px; }
    .error { color: #d9534f; margin-bottom: 15px; }
</style>
</head>
<body>
<div class="box">
    <h2>🔐 تسجيل الدخول</h2>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
        <input type="email" name="email" placeholder="البريد الإلكتروني" required>
        <input type="password" name="password" placeholder="كلمة المرور" required>
        <button type="submit">دخول</button>
    </form>
    <a href="/">⬅ العودة للرئيسية</a>
</div></body></html>
"""

PLANS_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>خطط نبراس</title>
<style>
    * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    body { background: #f0f2f5; padding: 20px; margin: 0; }
    .container { max-width: 500px; margin: 0 auto; }
    .back { display: inline-block; margin-bottom: 25px; padding: 12px 24px; background: #4a6a8a; color: white; text-decoration: none; border-radius: 12px; font-size: 16px; }
    h1 { font-size: 32px; color: #1a2b3c; text-align: center; margin-bottom: 30px; }
    .plan { background: white; border-radius: 16px; padding: 30px 25px; margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border-right: 6px solid #4a6a8a; }
    .plan.premium { border-right-color: #f1c40f; }
    .plan h3 { font-size: 26px; margin: 0 0 10px 0; color: #1a2b3c; }
    .price { font-size: 34px; font-weight: bold; color: #2d7d46; }
    .plan ul { margin: 20px 0 25px 0; padding: 0; list-style: none; font-size: 18px; line-height: 2.2; }
    .plan ul li { border-bottom: 1px solid #f0f2f5; padding: 4px 0; }
    .plan ul li:last-child { border-bottom: none; }
    .badge { display: inline-block; padding: 6px 18px; border-radius: 30px; font-size: 16px; }
    .badge.free { background: #eef2f7; color: #1a2b3c; }
    .badge.premium { background: #2d7d46; color: white; }
    .btn { display: block; padding: 18px; background: #4a6a8a; color: white; text-align: center; text-decoration: none; border-radius: 14px; font-size: 20px; font-weight: bold; margin-top: 10px; }
    .btn.gold { background: #f1c40f; color: #1a2b3c; }
</style>
</head>
<body>
<div class="container">
    <a href="/" class="back">⬅ العودة للرئيسية</a>
    <h1>💎 خطط نبراس</h1>
    <div class="plan">
        <span class="badge free">مجاني</span>
        <h3>الخطة المجانية</h3>
        <div class="price">0 <span>ر.س / شهرياً</span></div>
        <ul><li>✅ محادثات غير محدودة</li><li>✅ إجابات سريعة وذكية</li></ul>
    </div>
    <div class="plan premium">
        <span class="badge premium">مميز</span>
        <h3>الخطة المدفوعة</h3>
        <div class="price">7 <span>ر.س / شهرياً</span></div>
        <ul><li>✅ ذكاء متقدم (إجابات أعمق)</li><li>✅ بحث بالويب (معلومات حديثة)</li><li>✅ تحليل الصور</li><li>✅ إنشاء الصور (DALL-E 3)</li><li>✅ ردود أسرع</li></ul>
        <a href="#" class="btn gold">💎 اشترك الآن</a>
    </div>
</div></body></html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        admin_email = "abdullaha0569361@gmail.com"
        admin_password = os.environ.get("ADMIN_PASSWORD")

        if email == admin_email:
            if not admin_password:
                return render_template_string(LOGIN_HTML, error="خطأ: لم يتم إعداد كلمة مرور الأدمن في الخادم.")
            if secrets.compare_digest(password, admin_password):
                session.clear()
                session['admin_email'] = admin_email
                return redirect(url_for('index'))
            else:
                return render_template_string(LOGIN_HTML, error="كلمة مرور الأدمن غير صحيحة.")
        elif email and "@" in email:
            session['user_email'] = email
            session['trial_remaining'] = 5
            session['is_trial_expired'] = False
            return redirect(url_for('index'))
        else:
            return render_template_string(LOGIN_HTML, error="يرجى إدخال بريد إلكتروني صحيح.")
    return render_template_string(LOGIN_HTML)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/plans')
def plans():
    return render_template_string(PLANS_HTML)

@app.route('/history')
def history():
    user_id = get_user_id()
    conversations = get_user_conversations(user_id)
    conversations.sort(key=lambda x: x["timestamp"], reverse=True)
    result = [{"id": c["id"], "title": c["title"]} for c in conversations]
    return jsonify({"conversations": result})

@app.route('/load_conversation/<conv_id>')
def load_conversation(conv_id):
    user_id = get_user_id()
    messages = load_conversation_by_id(user_id, conv_id)
    if messages:
        return jsonify({"messages": messages})
    return jsonify({"messages": None}), 404

def get_user_id():
    if 'admin_email' in session:
        return "admin_" + session['admin_email']
    elif 'user_email' in session:
        return "user_" + session['user_email']
    else:
        real_ip = request.headers.get('X-Forwarded-For')
        if real_ip:
            real_ip = real_ip.split(',')[0].strip()
        else:
            real_ip = request.remote_addr
        return "guest_" + (real_ip or 'unknown')

@app.route('/set_gender', methods=['POST'])
def set_gender():
    data = request.get_json()
    session['voice_gender'] = data.get('gender', 'male')
    return jsonify({"status": "ok"})

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        history = data.get("history", [])
        conv_id = data.get("conv_id", None)

        if not user_message:
            return jsonify({"reply": "اكتب شيء أساعدك فيه"})

        is_admin = 'admin_email' in session and session['admin_email'] == "abdullaha0569361@gmail.com"
        is_trial_user = 'user_email' in session and not is_admin
        trial_remaining = session.get('trial_remaining', 0)

        user_id = get_user_id()

        if conv_id is None:
            session_memory[user_id] = []

        if is_admin:
            model = "gpt-4o"
            use_web_search = True
            allow_images = True
            limit_msg = None
        elif is_trial_user and trial_remaining > 0 and not session.get('is_trial_expired'):
            model = "gpt-4o"
            use_web_search = False
            allow_images = False
            limit_msg = f"💎 تبقى لك {trial_remaining} محادثة تجريبية مميزة!"
        else:
            model = "gpt-4o"
            use_web_search = False
            allow_images = False
            if is_trial_user and trial_remaining == 0:
                limit_msg = "⚠️ انتهت المحادثات التجريبية. الترقية للاستمرار."

        draw_keywords = ["ارسم", "أنشئ", "انشئ", "انشى", "صوره", "صورة", "صور", "رسم", "ارسمي", "صمم", "ولّد", "generate", "draw", "ارسم لي", "أنشئ لي", "انشئ لي", "انشى لي", "صوره لي"]
        if allow_images and any(keyword in user_message for keyword in draw_keywords):
            print(f"🎨 اكتشاف طلب رسم: {user_message}")
            image_url = generate_image(user_message)
            if image_url:
                reply = f"🖼️ إليك الصورة التي طلبتها:\n{image_url}"
                session_memory[user_id].append({"role": "user", "content": user_message})
                session_memory[user_id].append({"role": "assistant", "content": reply})
                new_conv_id = save_user_conversation(user_id, session_memory[user_id], conv_id)
                if is_trial_user and trial_remaining > 0:
                    session['trial_remaining'] = trial_remaining - 1
                    if session['trial_remaining'] == 0:
                        session['is_trial_expired'] = True
                        reply += "\n\n⚠️ انتهت محادثاتك التجريبية. الترقية للاستمرار."
                return jsonify({"reply": reply, "conv_id": new_conv_id})
            else:
                print("⚠️ فشل توليد الصورة، نكمل للرد النصي.")

        session_memory[user_id].append({"role": "user", "content": user_message})
        chat_history = session_memory[user_id][-10:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for entry in chat_history:
            messages.append({"role": entry["role"], "content": entry["content"]})

        image_data = data.get("image", None)
        if image_data and allow_images:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": user_message or "حلل هذه الصورة"}, {"type": "image_url", "image_url": {"url": image_data}}]
            })

        if use_web_search:
            try:
                full_context = ""
                for msg in messages:
                    if msg["role"] == "user":
                        full_context += msg["content"] + "\n"
                    elif msg["role"] == "assistant":
                        full_context += "نبراس: " + msg["content"] + "\n"
                search_response = client.responses.create(
                    model="gpt-4o",
                    instructions=f"{SYSTEM_PROMPT}\n\nسياق المحادثة السابقة:\n{full_context}",
                    input=f"ابحث في الويب عن أحدث المعلومات حول: {user_message}، وقدم لي ملخصاً مفيداً.",
                    tools=[{"type": "web_search"}]
                )
                search_result = search_response.output_text.strip()
                if search_result:
                    messages.append({"role": "user", "content": f"نتيجة البحث:\n{search_result}\n\nاستخدم هذه المعلومات."})
            except Exception as e:
                print(f"⚠️ فشل البحث بالويب: {e}")

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=1000,
                temperature=0.8
            )
            reply = response.choices[0].message.content.strip()
            if not reply:
                reply = "ما قدرت أجيب لك رد، حاول مرة أخرى."
        except openai.BadRequestError as e:
            print(f"⚠️ فشل نموذج {model}: {e}. جارٍ التبديل لـ gpt-4o-mini.")
            try:
                fallback_model = "gpt-4o-mini"
                response = client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    max_completion_tokens=800,
                    temperature=0.8
                )
                reply = response.choices[0].message.content.strip()
                if not reply:
                    reply = "فشل النموذج المتقدم، تم التبديل للنموذج العادي."
            except Exception as e2:
                reply = f"حدث خطأ في الاتصال بـ OpenAI: {str(e2)}"
        except Exception as e:
            print(f"❌ خطأ: {e}")
            reply = "حدث خطأ في السيرفر، حاول مرة أخرى."

        session_memory[user_id].append({"role": "assistant", "content": reply})
        new_conv_id = save_user_conversation(user_id, session_memory[user_id], conv_id)

        if is_trial_user and trial_remaining > 0:
            session['trial_remaining'] = trial_remaining - 1
            if session['trial_remaining'] == 0:
                session['is_trial_expired'] = True
                reply += "\n\n⚠️ انتهت محادثاتك التجريبية. الترقية للاستمرار مع البحث بالويب والصور."

        try:
            user_gender = session.get('voice_gender', 'male')
            audio_base64 = asyncio.run(generate_speech(reply, user_gender))
        except Exception as e:
            print(f"⚠️ فشل توليد الصوت: {e}")
            audio_base64 = None

        return jsonify({"reply": reply, "audio": audio_base64, "conv_id": new_conv_id})

    except Exception as e:
        print(f"❌ خطأ عام في /chat: {e}")
        return jsonify({"error": str(e)}), 500

# =====================================================================
# (الإضافة الوحيدة): مسار لقراءة أي ملف من مجلد static (مثل robots.txt, sitemap.xml, manifest.json, أي صورة أو ملف)
# =====================================================================
@app.route('/<path:filename>')
def serve_static_files(filename):
    return send_from_directory(app.static_folder, filename)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
