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
- اترك **سطراً فارغاً بين كل فقرة وأخرى**.
- استخدم `**الخط العريض**` لعناوين الفقرات، و `-` للقوائم.

**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة، قل بصراحة "ما عندي علم".
- دائماً حافظ على لهجتك العامية البيضاء.
"""

def remove_emoji(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF"
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
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes" />
    <meta name="description" content="نبراس GP، مساعد ذكي سعودي يتحدث باللهجة العامية البيضاء." />
    <title>نبراس</title>
    <link rel="icon" type="image/jpeg" href="/static/icon-512.jpeg" />
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
        body { background: #ffffff; height: 100dvh; display: flex; justify-content: center; }
        .app { width: 100%; max-width: 450px; height: 100dvh; background: #fff; display: flex; flex-direction: column; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #eaeef2; }
        .menu-btn, .mute-btn { background: none; border: none; font-size: 20px; color: #5a6b7c; cursor: pointer; padding: 4px 8px; }
        .mute-btn.muted { opacity: 0.4; }
        .dropdown { position: absolute; top: 64px; left: 14px; right: 14px; background: white; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.1); display: none; flex-direction: column; z-index: 100; max-height: 60vh; overflow-y: auto; }
        .dropdown.show { display: flex; }
        .dropdown .item { padding: 14px 18px; font-size: 15px; color: #1a2b3c; border-bottom: 1px solid #f0f2f5; cursor: pointer; text-align: right; }
        .dropdown .item:hover { background: #f5f7fa; }
        .gender-option { padding: 8px 12px; border-radius: 10px; border: 1px solid #dce1e8; background: transparent; font-size: 14px; font-weight: 600; color: #5a6b7c; cursor: pointer; margin: 4px; }
        .gender-option.active { background: #4a6a8a; color: white; border-color: #4a6a8a; }
        #chat { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; background: #fff; }
        .msg { max-width: 85%; padding: 12px 18px; border-radius: 20px; font-size: 16px; line-height: 1.8; word-wrap: break-word; }
        .msg.user { align-self: flex-end; background: #e3f2fd; border-bottom-left-radius: 6px; }
        .msg.bot { align-self: flex-start; background: #f5f7fa; border-bottom-right-radius: 6px; color: #1a2b3c; }
        .msg.error { background: #fde8e8; color: #a33; align-self: center; max-width: 90%; }
        .msg .time { font-size: 11px; opacity: 0.4; margin-top: 6px; display: block; }
        .typing-indicator { align-self: flex-start; background: #f5f7fa; padding: 12px 18px; border-radius: 20px; border-bottom-right-radius: 6px; color: #5a6b7c; }
        .input-area { display: flex; align-items: flex-end; gap: 8px; padding: 10px 14px; margin: 8px 14px 16px; background: #f5f7fa; border-radius: 40px; border: 1px solid #dce1e8; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 10px 0; font-size: 16px; outline: none; direction: rtl; resize: none; min-height: 24px; max-height: 80px; }
        .input-area .send { background: #4a6a8a; color: white; border: none; width: 40px; height: 40px; border-radius: 50%; cursor: pointer; font-size: 18px; }
        .input-area .btn-icon { background: none; border: none; color: #6a7b8c; font-size: 22px; cursor: pointer; padding: 4px; }
        .plus-btn { font-size: 24px; }
        .plus-btn.rotate { transform: rotate(45deg); }
        .plus-options { display: none; position: absolute; bottom: 80px; right: 30px; background: #fff; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); padding: 10px; gap: 8px; z-index: 50; }
        .plus-options.show { display: flex; }
        .plus-options .option-btn { width: 44px; height: 44px; border-radius: 50%; border: none; background: #f5f7fa; font-size: 20px; cursor: pointer; }
        #imagePreviewContainer { display: none; padding: 8px 18px; background: #f5f7fa; margin: 0 14px; border-radius: 20px 20px 0 0; border: 1px solid #dce1e8; align-items: center; gap: 10px; }
        #imagePreviewContainer img { max-height: 60px; border-radius: 8px; }
        #removeImageBtn { background: none; border: none; color: #c33; font-size: 16px; cursor: pointer; padding: 4px 8px; }
        
        h1, h2, h3 { margin: 10px 0 6px 0; line-height: 1.5; }
        h1 { font-size: 1.4em; border-bottom: 1px solid #eee; padding-bottom: 4px; }
        h2 { font-size: 1.25em; }
        h3 { font-size: 1.1em; }
        p { margin: 6px 0; }
        ul, ol { padding-right: 22px; margin: 8px 0; }
        li { margin: 4px 0; }
        blockquote { border-right: 3px solid #4a6a8a; padding-right: 12px; margin: 8px 0; color: #555; background: #f0f4f8; padding: 8px 12px; border-radius: 0 8px 8px 0; }
        pre { background: #f6f8fa; padding: 12px; border-radius: 8px; overflow-x: auto; margin: 8px 0; }
        code { background: #eef2f5; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-size: 0.95em; }
        pre code { background: transparent; padding: 0; }
        a { color: #4a6a8a; text-decoration: underline; }
        hr { border: none; border-top: 1px solid #e0e0e0; margin: 16px 0; }
        strong { font-weight: 700; }
        em { font-style: italic; }
        
        @media (max-width: 420px) {
            .msg { font-size: 15px; padding: 10px 14px; }
            #chat { padding: 14px 16px; }
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="header-right">
            <button class="mute-btn muted" id="muteBtn"><i class="fas fa-volume-mute"></i></button>
            <button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button>
        </div>
        <div class="header-left">
            <span style="font-weight:bold; font-size:18px; color:#1a2b3c;">نبراس</span>
        </div>
    </div>
    
    <div class="dropdown" id="dropdown">
        <button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
        <div class="item" style="flex-direction: column; gap: 8px; cursor: default;">
            <div style="display: flex; align-items: center; gap: 8px;"><i class="fas fa-microphone"></i> صوت المساعد</div>
            <div style="display: flex; gap: 6px;">
                <button class="gender-option active" data-gender="male">👨 ذكر</button>
                <button class="gender-option" data-gender="female">👩 أنثى</button>
            </div>
        </div>
        <div id="historyList"></div>
    </div>

    <div id="chat"></div>

    <div id="imagePreviewContainer">
        <img id="imagePreview" src="" alt="معاينة" />
        <span>📎 صورة معلقة</span>
        <button id="removeImageBtn">✕</button>
    </div>

    <div class="input-area">
        <button class="btn-icon" id="micBtn"><i class="fas fa-microphone"></i></button>
        <button class="btn-icon plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button>
        <div class="plus-options" id="plusOptions">
            <button class="option-btn" id="cameraBtn"><i class="fas fa-camera"></i></button>
            <button class="option-btn" id="galleryBtn"><i class="fas fa-images"></i></button>
        </div>
        <textarea id="userInput" placeholder="اكتب رسالتك..." autofocus></textarea>
        <button class="send" id="sendBtn"><i class="fas fa-paper-plane"></i></button>
    </div>
    
    <input type="file" id="fileInput" accept="image/*" style="display: none;" />
    <input type="file" id="cameraInput" accept="image/*" capture="environment" style="display: none;" />
</div>

<script>
(function() {
    let conversationHistory = [];
    let pendingImageData = null;
    let isWaiting = false;
    let currentConvId = null;
    let currentAudio = null;
    let isMuted = true;
    let isMale = true;

    const chatBox = document.getElementById('chat');
    const userInput = document.getElementById('userInput');
    const sendBtn = document.getElementById('sendBtn');
    const menuToggle = document.getElementById('menuToggle');
    const dropdown = document.getElementById('dropdown');
    const plusBtn = document.getElementById('plusBtn');
    const plusOptions = document.getElementById('plusOptions');
    const fileInput = document.getElementById('fileInput');
    const cameraInput = document.getElementById('cameraInput');
    const muteBtn = document.getElementById('muteBtn');
    const historyList = document.getElementById('historyList');

    muteBtn.addEventListener('click', function() {
        isMuted = !isMuted;
        this.classList.toggle('muted', isMuted);
        this.querySelector('i').className = isMuted ? 'fas fa-volume-mute' : 'fas fa-volume-up';
        if (isMuted && currentAudio) { currentAudio.pause(); currentAudio.currentTime = 0; }
    });

    menuToggle.addEventListener('click', e => {
        e.stopPropagation();
        dropdown.classList.toggle('show');
        if (dropdown.classList.contains('show')) loadHistory();
    });

    document.querySelectorAll('.gender-option').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            document.querySelectorAll('.gender-option').forEach(b => b.classList.remove('active'));
            this.classList.add('active');
            isMale = this.dataset.gender === 'male';
            fetch('/set_gender', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ gender: this.dataset.gender })
            });
        });
    });

    async function loadHistory() {
        try {
            const res = await fetch('/history');
            const data = await res.json();
            historyList.innerHTML = '';
            if (data.conversations?.length > 0) {
                data.conversations.forEach(conv => {
                    const btn = document.createElement('button');
                    btn.className = 'item';
                    btn.style.textAlign = 'right';
                    btn.textContent = conv.title;
                    btn.onclick = () => loadConversation(conv.id);
                    historyList.appendChild(btn);
                });
            } else {
                historyList.innerHTML = '<div class="item">📭 لا توجد محادثات سابقة</div>';
            }
        } catch (e) { console.error(e); }
    }

    async function loadConversation(convId) {
        try {
            const res = await fetch('/load_conversation/' + convId);
            const data = await res.json();
            if (data.messages) {
                chatBox.innerHTML = '';
                conversationHistory = data.messages;
                currentConvId = convId;
                data.messages.forEach(msg => addMessage(msg.content, msg.role === 'user' ? 'user' : 'bot', true));
                dropdown.classList.remove('show');
            }
        } catch (e) { console.error(e); }
    }

    document.querySelector('[data-action="new"]').addEventListener('click', () => {
        chatBox.innerHTML = '';
        conversationHistory = [];
        currentConvId = null;
        dropdown.classList.remove('show');
        pendingImageData = null;
        document.getElementById('imagePreviewContainer').style.display = 'none';
        userInput.value = '';
    });

    function formatBotText(text) {
        let safe = text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        safe = safe.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        safe = safe.replace(/`([^`]+)`/g, '<code>$1</code>');
        safe = safe.replace(/^### (.*)$/gm, '<h3>$1</h3>');
        safe = safe.replace(/^## (.*)$/gm, '<h2>$1</h2>');
        safe = safe.replace(/^# (.*)$/gm, '<h1>$1</h1>');
        safe = safe.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        safe = safe.replace(/\*(.*?)\*/g, '<em>$1</em>');
        safe = safe.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
        safe = safe.replace(/^> (.*)$/gm, '<blockquote>$1</blockquote>');
        safe = safe.replace(/^---$/gm, '<hr>');

        const blocks = safe.split(/\n\s*\n/);
        const result = [];

        blocks.forEach(block => {
            block = block.trim();
            if (!block) return;

            const lines = block.split('\n');
            let inUl = false, inOl = false;
            const processed = [];

            lines.forEach(line => {
                const ulMatch = line.match(/^- (.*)$/);
                const olMatch = line.match(/^\d+\. (.*)$/);

                if (ulMatch) {
                    if (!inUl) { processed.push('<ul>'); inUl = true; }
                    if (inOl) { processed.push('</ol>'); inOl = false; }
                    processed.push(`<li>${ulMatch[1]}</li>`);
                } else if (olMatch) {
                    if (!inOl) { processed.push('<ol>'); inOl = true; }
                    if (inUl) { processed.push('</ul>'); inUl = false; }
                    processed.push(`<li>${olMatch[1]}</li>`);
                } else {
                    if (inUl) { processed.push('</ul>'); inUl = false; }
                    if (inOl) { processed.push('</ol>'); inOl = false; }
                    processed.push(line);
                }
            });

            if (inUl) processed.push('</ul>');
            if (inOl) processed.push('</ol>');

            let final = processed.join('\n');
            if (!/^<(h[1-6]|ul|ol|pre|blockquote|hr)/i.test(final.trim())) {
                final = `<p>${final.replace(/\n/g, ' ')}</p>`;
            }
            result.push(final);
        });

        return result.join('\n');
    }

    function addMessage(text, sender, skipTyping, imageData) {
        const el = document.createElement('div');
        el.className = `msg ${sender}`;
        
        if (imageData) {
            el.innerHTML = `<img src="${imageData}" style="max-width:100%; border-radius:12px; margin-bottom:8px;" />`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;
            return el;
        }

        const time = new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });

        if (sender === 'bot' && !skipTyping) {
            el.innerHTML = `<span class="typing-text"></span><span class="time">${time}</span>`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;

            const typingSpan = el.querySelector('.typing-text');
            let i = 0;
            function type() {
                if (i < text.length) {
                    typingSpan.textContent += text[i];
                    i++;
                    chatBox.scrollTop = chatBox.scrollHeight;
                    setTimeout(type, 15);
                } else {
                    typingSpan.innerHTML = formatBotText(text);
                    chatBox.scrollTop = chatBox.scrollHeight;
                }
            }
            type();
        } else {
            el.innerHTML = (sender === 'bot' ? formatBotText(text) : text) + `<span class="time">${time}</span>`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;
        }
        return el;
    }

    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    document.getElementById('removeImageBtn').addEventListener('click', () => {
        pendingImageData = null;
        imagePreviewContainer.style.display = 'none';
    });

    plusBtn.addEventListener('click', e => {
        e.stopPropagation();
        plusOptions.classList.toggle('show');
        plusBtn.classList.toggle('rotate');
    });

    document.addEventListener('click', e => {
        if (!plusBtn.contains(e.target) && !plusOptions.contains(e.target)) {
            plusOptions.classList.remove('show');
            plusBtn.classList.remove('rotate');
        }
        if (!menuToggle.contains(e.target) && !dropdown.contains(e.target)) {
            dropdown.classList.remove('show');
        }
    });

    document.getElementById('galleryBtn').addEventListener('click', () => fileInput.click());
    document.getElementById('cameraBtn').addEventListener('click', () => cameraInput.click());

    function handleFile(file) {
        const reader = new FileReader();
        reader.onload = e => {
            pendingImageData = e.target.result;
            imagePreview.src = e.target.result;
            imagePreviewContainer.style.display = 'flex';
        };
        reader.readAsDataURL(file);
    }

    fileInput.addEventListener('change', e => e.target.files?.[0] && handleFile(e.target.files[0]));
    cameraInput.addEventListener('change', e => e.target.files?.[0] && handleFile(e.target.files[0]));

    async function sendMessage() {
        if (isWaiting) return;
        const text = userInput.value.trim();
        const image = pendingImageData;
        if (!text && !image) return;

        if (text) addMessage(text, 'user', true);
        if (image) addMessage('🖼️ صورة مرفقة', 'user', true, image);
        
        userInput.value = '';
        pendingImageData = null;
        imagePreviewContainer.style.display = 'none';
        isWaiting = true;

        const typing = document.createElement('div');
        typing.className = 'typing-indicator';
        typing.textContent = 'جاري التفكير...';
        chatBox.appendChild(typing);
        chatBox.scrollTop = chatBox.scrollHeight;

        try {
            const res = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: text || 'مرفق صورة',
                    image: image,
                    history: conversationHistory,
                    conv_id: currentConvId
                })
            });

            typing.remove();

            if (!res.ok) throw new Error('خطأ في الاتصال');
            const data = await res.json();
            
            addMessage(data.reply, 'bot');
            
            if (!isMuted && data.audio) {
                currentAudio = new Audio(`data:audio/mp3;base64,${data.audio}`);
                currentAudio.play();
            }

            if (data.conv_id) currentConvId = data.conv_id;
            if (data.history) conversationHistory = data.history;

        } catch (err) {
            typing.remove();
            addMessage('❌ تعذر الاتصال، حاول مرة أخرى.', 'error', true);
        } finally {
            isWaiting = false;
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    if (!sessionStorage.getItem('welcomed')) {
        setTimeout(() => {
            addMessage('أهلاً وسهلاً! أنا نبراس، مساعدك الذكي. تفضل كيف أخدمك؟', 'bot', true);
            sessionStorage.setItem('welcomed', 'true');
        }, 300);
    }

})();
</script>
</body>
</html>
"""
