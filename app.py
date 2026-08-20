from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from gtts import gTTS
import openai
import os
import secrets
import json
import hashlib
from datetime import datetime
import io
import base64

app = Flask(__name__)

# ===== إعداد الحماية الخلفية (Rate Limiter) =====
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# إعداد المفاتيح السرية
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود! يجب إضافته في متغيرات البيئة")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_ENABLED = True

# ========== نظام تخزين المحادثات (في ملف JSON) ==========
CONVERSATIONS_FILE = "conversations.json"

def load_conversations():
    if os.path.exists(CONVERSATIONS_FILE):
        try:
            with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_conversations(data):
    with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_conversations(user_id):
    all_conv = load_conversations()
    return all_conv.get(user_id, [])

def save_user_conversation(user_id, conversation, conv_id=None):
    all_conv = load_conversations()
    if user_id not in all_conv:
        all_conv[user_id] = []
    
    if conv_id is None:
        if conversation and len(conversation) > 0:
            title = conversation[0]["content"][:30]
            if len(conversation[0]["content"]) > 30:
                title += "..."
        else:
            title = "محادثة جديدة"
        
        new_conv_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        all_conv[user_id].append({
            "id": new_conv_id,
            "messages": conversation,
            "timestamp": datetime.now().isoformat(),
            "title": title
        })
        save_conversations(all_conv)
        return new_conv_id
    else:
        for conv in all_conv[user_id]:
            if conv["id"] == conv_id:
                conv["messages"] = conversation
                conv["timestamp"] = datetime.now().isoformat()
                save_conversations(all_conv)
                return conv_id
        return save_user_conversation(user_id, conversation, None)

def load_conversation_by_id(user_id, conv_id):
    conversations = get_user_conversations(user_id)
    for conv in conversations:
        if conv["id"] == conv_id:
            return conv["messages"]
    return None

# ========== الذاكرة المؤقتة للجلسة الحالية ==========
session_memory = {}

# ========== تحميل ملف المعرفة ==========
knowledge_content = ""
possible_names = ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]
for filename in possible_names:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                knowledge_content = f.read()
                break
        except:
            pass

if not knowledge_content:
    knowledge_content = "أنت روز، صديقة ذكية للبنات."

# ========== تعليمات النظام ==========
SYSTEM_PROMPT = f"""
أنت "روز"، مساعدة شخصية ذكية، صديقة مقربة للبنات. تتحدثين بلهجة خليجية ناعمة ودافئة.
أنت خبيرة في الطبخ، المكياج، العناية بالبشرة، الموضة، والأمور النسائية.
ردودك مختصرة، ملهمة، وجميلة، مع لمسات من الدلال والحيوية.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.

**ملف المعرفة الخاص بك:**
{knowledge_content}

**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاولي الإجابة من ملف المعرفة أولاً.
- حافظي على لهجتك الناعمة.
- إذا لم تجدي المعلومة، قولي بصراحة "ما عندي علم يا عسل".
- **لا تكتبي "لحظة" أو "انتظر"**، أجيبي مباشرة.
"""

# ========== دالة إنشاء الصور ==========
def generate_image(prompt):
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        return response.data[0].url
    except Exception as e:
        print(f"❌ فشل توليد الصورة: {e}")
        return None

# ========== دالة توليد الصوت باستخدام gTTS (بديل edge-tts) ==========
def generate_speech(text, gender):
    try:
        # gTTS صوت أنثى افتراضي وواضح
        tts = gTTS(text=text, lang='ar', slow=False)
        audio_bytes = io.BytesIO()
        tts.write_to_fp(audio_bytes)
        audio_bytes.seek(0)
        return base64.b64encode(audio_bytes.read()).decode('utf-8')
    except Exception as e:
        print(f"❌ فشل توليد الصوت باستخدام gTTS: {e}")
        return None

# ========== واجهة الدردشة (وردية وناعمة + زر قلب + زر سماعة) ==========
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes" />
    <title>روز - مساعدتك الذكية</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
        body { background: #fff5f7; height: 100dvh; display: flex; justify-content: center; align-items: center; margin: 0; padding: 0; }
        .app { width: 100%; max-width: 450px; height: 100dvh; background: #ffffff; display: flex; flex-direction: column; position: relative; box-shadow: 0 0 20px rgba(232, 139, 156, 0.15); }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #fce4ec; flex-shrink: 0; background: #fff5f7; }
        
        /* الجهة اليمنى: الصوت والقائمة */
        .header-right { display: flex; align-items: center; gap: 12px; }
        .mute-btn { background: none; border: none; font-size: 20px; color: #e88b9c; cursor: pointer; padding: 4px; transition: all 0.2s ease; }
        .mute-btn:hover { color: #d47384; }
        .mute-btn.muted { 
            opacity: 0.5; 
            transform: scale(0.7);  /* يصغر الزر عند كتم الصوت */
        }
        .menu-btn { background: none; border: none; font-size: 20px; color: #e88b9c; cursor: pointer; padding: 4px 8px; }
        .menu-btn:hover { color: #d47384; }

        /* الجهة اليسرى: زر القلب */
        .header-left { display: flex; align-items: center; gap: 12px; }
        .btn-heart {
            background: #e88b9c;
            color: white;
            border: none;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            font-size: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            transition: 0.2s;
            box-shadow: 0 4px 12px rgba(232, 139, 156, 0.25);
        }
        .btn-heart:hover {
            background: #d47384;
            transform: scale(1.05);
        }

        /* تم إخفاء زر الترقية لروز */
        .btn-gold { background: #f1c40f; color: #1a2b3c; font-weight: bold; display: none; }
        
        .dropdown { position: absolute; top: 64px; left: 14px; right: 14px; background: white; border-radius: 16px; box-shadow: 0 8px 30px rgba(232, 139, 156, 0.15); display: none; flex-direction: column; z-index: 100; border: 1px solid #fce4ec; max-height: 60vh; overflow-y: auto; }
        .dropdown.show { display: flex; }
        .dropdown .item { display: flex; align-items: center; gap: 12px; padding: 14px 18px; font-size: 15px; color: #5a3c41; background: none; border: none; width: 100%; text-align: right; cursor: pointer; border-bottom: 1px solid #fce4ec; }
        .dropdown .item:last-child { border-bottom: none; }
        .dropdown .item i { width: 22px; font-size: 18px; color: #e88b9c; }
        .dropdown .item:hover { background: #fff0f3; }
        .dropdown .conv-item {
            display: block;
            padding: 12px 18px;
            border-bottom: 1px solid #fce4ec;
            cursor: pointer;
            width: 100%;
            background: none;
            border: none;
            text-align: right;
            font-size: 16px;
            color: #5a3c41;
            font-weight: 500;
            transition: background 0.2s;
        }
        .dropdown .conv-item:hover { background: #fff0f3; }
        .dropdown .conv-item:last-child { border-bottom: none; }
        #chat { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; background: #ffffff; font-size: 16px; }
        .msg { max-width: 80%; padding: 12px 18px; border-radius: 20px; font-size: 16px; font-weight: 600; line-height: 1.6; word-wrap: break-word; white-space: pre-wrap; color: #3a2a2e; }
        .msg.user { align-self: flex-end; background: #ffeef2; border-bottom-left-radius: 6px; }
        .msg.bot { align-self: flex-start; background: #faf0f2; border-bottom-right-radius: 6px; }
        .msg .time { font-size: 10px; opacity: 0.5; display: block; margin-top: 4px; }
        .msg.error { background: #fce4ec; color: #b34a5a; align-self: center; max-width: 90%; }
        .msg .image-upload { max-width: 100%; max-height: 200px; border-radius: 12px; margin: 4px 0; border: 1px solid #fce4ec; display: block; }
        .msg .generated-image { max-width: 100%; border-radius: 12px; margin: 8px 0; border: 1px solid #fce4ec; display: block; }

        .welcome-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(232, 139, 156, 0.25);
            z-index: 9999;
            animation: fadeIn 0.5s ease;
            pointer-events: none;
        }
        .welcome-overlay .welcome-box {
            background: #ffffff;
            padding: 30px 40px;
            border-radius: 20px;
            box-shadow: 0 20px 40px rgba(232, 139, 156, 0.15);
            text-align: center;
            max-width: 90%;
            pointer-events: auto;
            direction: rtl;
            border: 1px solid #fce4ec;
        }
        .welcome-overlay .welcome-box h2 {
            font-size: 28px;
            color: #e88b9c;
            margin-bottom: 8px;
        }
        .welcome-overlay .welcome-box p {
            font-size: 18px;
            color: #b38b94;
            margin: 0;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: scale(0.9); }
            to { opacity: 1; transform: scale(1); }
        }
        .welcome-overlay.fade-out {
            animation: fadeOut 0.5s ease forwards;
        }
        @keyframes fadeOut {
            from { opacity: 1; transform: scale(1); }
            to { opacity: 0; transform: scale(0.9); }
        }

        #imagePreviewContainer {
            display: none;
            padding: 6px 18px;
            align-items: center;
            gap: 10px;
            background: #fff5f7;
            margin: 0 14px;
            border-radius: 20px 20px 0 0;
            border: 1px solid #fce4ec;
            border-bottom: none;
            flex-wrap: wrap;
            flex-shrink: 0;
        }
        #imagePreviewContainer img { max-height: 60px; border-radius: 8px; border: 1px solid #fce4ec; }
        #imagePreviewContainer .label { font-size: 13px; color: #b38b94; }
        #removeImageBtn { background: none; border: none; color: #e88b9c; font-size: 14px; cursor: pointer; padding: 4px 8px; border-radius: 12px; }
        #removeImageBtn:hover { background: #ffeef2; }
        .input-area { display: flex; align-items: flex-end; justify-content: center; gap: 8px; padding: 8px 14px; margin: 8px 14px 16px 14px; background: #fff5f7; border-radius: 40px; border: 1px solid #fce4ec; flex-shrink: 0; min-height: 60px; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 12px 0; font-size: 18px; font-weight: 500; outline: none; color: #3a2a2e; direction: rtl; resize: none; overflow: hidden; min-height: 20px; max-height: 80px; font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.4; }
        .input-area textarea::placeholder { color: #c4aab0; }
        .input-area .btn-icon { background: none; border: none; color: #e88b9c; font-size: 20px; cursor: pointer; padding: 4px; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .input-area .btn-icon:hover { background: #ffeef2; }
        .input-area .mic-btn { color: #e88b9c; }
        .input-area .mic-btn.listening { color: #b34a5a; background: #fce4ec; }
        .input-area .send { background: #e88b9c; color: white; border: none; width: 44px; height: 44px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-shadow: 0 4px 12px rgba(232, 139, 156, 0.25); }
        .input-area .send:hover { background: #d47384; transform: scale(1.02); }
        .plus-btn { background: none; border: none; color: #e88b9c; font-size: 24px; cursor: pointer; padding: 4px; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: 0.3s; }
        .plus-btn:hover { background: #e8ecf0; }
        .plus-btn.rotate { transform: rotate(45deg); }
        .plus-options { display: none; position: absolute; bottom: 70px; right: 0; background: #ffffff; border-radius: 20px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); padding: 8px; gap: 6px; flex-direction: row; border: 1px solid #fce4ec; z-index: 50; }
        .plus-options.show { display: flex; }
        .plus-options .option-btn { background: #fff5f7; border: none; border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #e88b9c; cursor: pointer; transition: 0.2s; }
        .plus-options .option-btn:hover { background: #ffeef2; }
        @media (max-width: 420px) {
            .header { padding: 12px 14px; }
            .btn { font-size: 12px; padding: 5px 12px; }
            .dropdown { top: 58px; left: 10px; right: 10px; }
            #chat { padding: 14px 16px; }
            .input-area { margin: 6px 10px 12px 10px; padding: 6px 10px; min-height: 50px; }
            .input-area textarea { font-size: 14px; }
            .input-area .send { width: 38px; height: 38px; font-size: 14px; }
            .input-area .btn-icon { width: 32px; height: 32px; font-size: 16px; }
            .plus-btn { width: 32px; height: 32px; font-size: 18px; }
            .msg .image-upload { max-height: 150px; }
            #imagePreviewContainer { padding: 4px 14px; }
            #imagePreviewContainer img { max-height: 50px; }
            .welcome-overlay .welcome-box { padding: 20px 25px; }
            .welcome-overlay .welcome-box h2 { font-size: 22px; }
            .welcome-overlay .welcome-box p { font-size: 16px; }
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <!-- ===== الجهة اليمنى: زر الصوت وزر القائمة ===== -->
        <div class="header-right">
            <button class="mute-btn" id="muteBtn" title="كتم/تفعيل الصوت"><i class="fas fa-volume-up"></i></button>
            <button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button>
        </div>
        
        <!-- ===== الجهة اليسرى: زر القلب ===== -->
        <div class="header-left">
            <div class="btn-group">
                {% if session.get('admin_email') or session.get('user_email') %}
                    <a href="/logout" class="btn-heart" style="background:#d47384;"><i class="fas fa-heart"></i></a>
                {% else %}
                    <a href="/login" class="btn-heart"><i class="fas fa-heart"></i></a>
                {% endif %}
                <!-- تم إخفاء زر الترقية -->
                <a href="/plans" class="btn btn-gold" style="display:none;">💎 ترقية</a>
            </div>
        </div>
    </div>
    
    <div class="dropdown" id="dropdown">
        <button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
        <div id="historyList"></div>
    </div>

    <div id="chat"></div>

    <div id="imagePreviewContainer">
        <img id="imagePreview" src="" alt="معاينة" />
        <span class="label">📎 صورة معلقة</span>
        <button id="removeImageBtn">✕ إزالة</button>
    </div>

    <div class="input-area">
        <button class="btn-icon mic-btn" id="micBtn"><i class="fas fa-microphone"></i></button>
        <button class="plus-btn" id="plusBtn"><i class="fas fa-plus"></i></button>
        <div class="plus-options" id="plusOptions">
            <button class="option-btn camera" id="cameraBtn"><i class="fas fa-camera"></i></button>
            <button class="option-btn gallery" id="galleryBtn"><i class="fas fa-images"></i></button>
            <button class="option-btn files" id="filesBtn"><i class="fas fa-folder"></i></button>
        </div>
        <textarea id="userInput" placeholder="اكتبي لروز..." autofocus rows="1"></textarea>
        <button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button>
    </div>
    
    <input type="file" id="fileInput" accept="image/*" style="display: none;" />
    <input type="file" id="cameraInput" accept="image/*" capture="environment" style="display: none;" />
    <input type="file" id="fileInputGeneric" style="display: none;" />
</div>
<script>
    (function() {
        let conversationHistory = [];
        let pendingImageData = null;
        let isWaiting = false;
        let currentConvId = null;
        
        const chatBox = document.getElementById('chat');
        const userInput = document.getElementById('userInput');
        const sendBtn = document.getElementById('sendBtn');
        const micBtn = document.getElementById('micBtn');
        const fileInput = document.getElementById('fileInput');
        const cameraInput = document.getElementById('cameraInput');
        const menuToggle = document.getElementById('menuToggle');
        const dropdown = document.getElementById('dropdown');
        const plusBtn = document.getElementById('plusBtn');
        const plusOptions = document.getElementById('plusOptions');
        const cameraBtn = document.getElementById('cameraBtn');
        const galleryBtn = document.getElementById('galleryBtn');
        const imagePreviewContainer = document.getElementById('imagePreviewContainer');
        const imagePreview = document.getElementById('imagePreview');
        const removeImageBtn = document.getElementById('removeImageBtn');
        const historyList = document.getElementById('historyList');

        // ===== حالة الصوت =====
        let isMuted = true;
        const muteBtn = document.getElementById('muteBtn');
        muteBtn.querySelector('i').className = 'fas fa-volume-mute';
        muteBtn.classList.add('muted');

        muteBtn.addEventListener('click', function() {
            isMuted = !isMuted;
            const icon = muteBtn.querySelector('i');
            if (isMuted) {
                icon.className = 'fas fa-volume-mute';
                muteBtn.classList.add('muted');
                if (currentAudio) { 
                    currentAudio.pause(); 
                    currentAudio.currentTime = 0; 
                }
            } else {
                icon.className = 'fas fa-volume-up';
                muteBtn.classList.remove('muted');
            }
        });

        // ===== تحميل المحادثات السابقة =====
        async function loadHistory() {
            try {
                const res = await fetch('/history');
                const data = await res.json();
                historyList.innerHTML = '';
                if (data.conversations && data.conversations.length > 0) {
                    data.conversations.forEach(conv => {
                        const btn = document.createElement('button');
                        btn.className = 'conv-item';
                        btn.textContent = conv.title;
                        btn.onclick = () => loadConversation(conv.id);
                        historyList.appendChild(btn);
                    });
                } else {
                    const empty = document.createElement('div');
                    empty.className = 'item';
                    empty.textContent = '📭 لا توجد محادثات سابقة';
                    historyList.appendChild(empty);
                }
            } catch (e) {
                console.error('خطأ في تحميل المحادثات:', e);
            }
        }

        // ===== تحميل محادثة معينة =====
        async function loadConversation(convId) {
            try {
                const res = await fetch(`/load_conversation/${convId}`);
                const data = await res.json();
                if (data.messages) {
                    chatBox.innerHTML = '';
                    conversationHistory = data.messages;
                    currentConvId = convId;
                    data.messages.forEach(msg => {
                        const sender = msg.role === 'user' ? 'user' : 'bot';
                        addMessage(msg.content, sender, true);
                    });
                    dropdown.classList.remove('show');
                }
            } catch (e) {
                console.error('خطأ في تحميل المحادثة:', e);
            }
        }

        // ===== محادثة جديدة =====
        document.querySelector('[data-action="new"]').addEventListener('click', function() {
            chatBox.innerHTML = '';
            conversationHistory = [];
            currentConvId = null;
            dropdown.classList.remove('show');
            pendingImageData = null;
            imagePreviewContainer.style.display = 'none';
            userInput.value = '';
        });

        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            dropdown.classList.toggle('show');
            if (dropdown.classList.contains('show')) {
                loadHistory();
            }
        });

        // ===== دالة addMessage =====
        function addMessage(text, sender = 'bot', isSystem = false, imageData = null) {
            const el = document.createElement('div');
            el.className = `msg ${sender}`;
            if (sender === 'error') el.classList.add('error');
            const now = new Date();
            const time = isSystem ? '' : now.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
            
            if (imageData) {
                el.innerHTML = `<img src="${imageData}" class="image-upload" /><span class="file-label">${text || 'صورة'}</span>${time ? ' <span class="time">'+time+'</span>' : ''}`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                return el;
            }

            const imageUrlMatch = text.match(/(https?:\/\/[^\s]+\.(png|jpg|jpeg|gif|webp))/i);
            let displayText = text;
            let generatedImageUrl = null;
            if (imageUrlMatch) {
                generatedImageUrl = imageUrlMatch[0];
                displayText = text.replace(imageUrlMatch[0], '').trim();
                if (!displayText) displayText = '🖼️ الصورة المولدة';
            }

            if (sender === 'bot' && !isSystem && !generatedImageUrl) {
                el.innerHTML = `<span class="typing-text"></span>${time ? ' <span class="time">'+time+'</span>' : ''}`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                const typingSpan = el.querySelector('.typing-text');
                let index = 0;
                function typeChar() {
                    if (index < displayText.length) {
                        typingSpan.textContent += displayText.charAt(index);
                        index++;
                        setTimeout(typeChar, 20);
                    } else {
                        chatBox.scrollTop = chatBox.scrollHeight;
                        if (generatedImageUrl) {
                            const imgEl = document.createElement('img');
                            imgEl.src = generatedImageUrl;
                            imgEl.className = 'generated-image';
                            el.appendChild(imgEl);
                            chatBox.scrollTop = chatBox.scrollHeight;
                        }
                    }
                }
                typeChar();
                return el;
            }

            let content = displayText;
            if (generatedImageUrl) {
                content += `<br/><img src="${generatedImageUrl}" class="generated-image" />`;
            }
            el.innerHTML = `${content}${time ? ' <span class="time">'+time+'</span>' : ''}`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;
            return el;
        }

        // ===== رسالة الترحيب في وسط الشاشة (5 ثوانٍ) =====
        function showWelcome() {
            if (!sessionStorage.getItem('welcomeShown')) {
                const overlay = document.createElement('div');
                overlay.className = 'welcome-overlay';
                overlay.innerHTML = `
                    <div class="welcome-box">
                        <h2>🌸 أهلاً بك في روز</h2>
                        <p>أنا هنا أساعدك في الطبخ، المكياج، والموضة 💗</p>
                    </div>
                `;
                document.body.appendChild(overlay);
                sessionStorage.setItem('welcomeShown', 'true');
                
                setTimeout(() => {
                    if (document.body.contains(overlay)) {
                        overlay.classList.add('fade-out');
                        setTimeout(() => {
                            if (document.body.contains(overlay)) overlay.remove();
                        }, 500);
                    }
                }, 5000);
                
                const removeWelcome = function() {
                    if (document.body.contains(overlay)) {
                        overlay.classList.add('fade-out');
                        setTimeout(() => {
                            if (document.body.contains(overlay)) overlay.remove();
                        }, 500);
                    }
                    document.removeEventListener('click', removeWelcome);
                    userInput.removeEventListener('keydown', removeWelcome);
                };
                document.addEventListener('click', removeWelcome);
                userInput.addEventListener('keydown', removeWelcome);
            }
        }

        // ===== باقي الكود =====
        function showImagePreview(dataUrl) {
            imagePreview.src = dataUrl;
            imagePreviewContainer.style.display = 'flex';
        }

        function clearPendingImage() {
            pendingImageData = null;
            imagePreviewContainer.style.display = 'none';
            imagePreview.src = '';
        }

        removeImageBtn.addEventListener('click', clearPendingImage);

        userInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 80) + 'px';
        });

        let plusOpen = false;
        plusBtn.addEventListener('click', function() {
            plusOpen = !plusOpen;
            plusOptions.classList.toggle('show', plusOpen);
            this.classList.toggle('rotate', plusOpen);
        });
        document.addEventListener('click', function(e) {
            if (!plusBtn.contains(e.target) && !plusOptions.contains(e.target)) {
                plusOptions.classList.remove('show');
                plusOpen = false;
                plusBtn.classList.remove('rotate');
            }
        });

        galleryBtn.addEventListener('click', function() { fileInput.click(); plusOptions.classList.remove('show'); });
        fileInput.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const reader = new FileReader();
                reader.onload = function(ev) {
                    pendingImageData = ev.target.result;
                    showImagePreview(pendingImageData);
                    fileInput.value = '';
                };
                reader.readAsDataURL(this.files[0]);
            }
        });

        cameraBtn.addEventListener('click', function() { cameraInput.click(); plusOptions.classList.remove('show'); });
        cameraInput.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const reader = new FileReader();
                reader.onload = function(ev) {
                    pendingImageData = ev.target.result;
                    showImagePreview(pendingImageData);
                    cameraInput.value = '';
                };
                reader.readAsDataURL(this.files[0]);
            }
        });

        async function sendMessage() {
            if (isWaiting) return;

            const text = userInput.value.trim();
            const imageToSend = pendingImageData;

            if (!text && !imageToSend) return;

            if (text) addMessage(text, 'user');
            if (imageToSend) {
                addMessage('🖼️ صورة مرفقة', 'user', false, imageToSend);
                clearPendingImage();
            }

            userInput.value = '';
            userInput.style.height = 'auto';
            isWaiting = true;

            // ===== إرسال حالة الصوت الحالية للسيرفر =====
            const payload = {
                message: text || "📎 مرفق",
                image: imageToSend || null,
                history: conversationHistory,
                conv_id: currentConvId,
                voice_enabled: !isMuted
            };

            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (res.ok) {
                    addMessage(data.reply, 'bot');
                    if (!isMuted && data.audio) {
                        if (currentAudio) { 
                            currentAudio.pause(); 
                            currentAudio.currentTime = 0; 
                        }
                        const audioSrc = `data:audio/mp3;base64,${data.audio}`;
                        currentAudio = new Audio(audioSrc);
                        currentAudio.play();
                    }
                    if (data.conv_id) {
                        currentConvId = data.conv_id;
                    }
                } else {
                    addMessage('خطأ: ' + (data.error || 'مشكلة في السيرفر'), 'error');
                }
            } catch (e) {
                addMessage('تعذر الاتصال بالسيرفر.', 'error');
            } finally {
                isWaiting = false;
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        userInput.addEventListener('keypress', (e) => { 
            if (e.key === 'Enter') { 
                e.preventDefault(); 
                sendMessage(); 
            } 
        });

        document.addEventListener('click', function(e) {
            if (!menuToggle.contains(e.target) && !dropdown.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });

        let recognition = null;
        micBtn.addEventListener('click', function() {
            if (!('webkitSpeechRecognition' in window)) {
                addMessage('المتصفح لا يدعم التعرف على الصوت.', 'bot', true);
                return;
            }
            if (this.classList.contains('listening')) {
                this.classList.remove('listening');
                if (recognition) recognition.stop();
                return;
            }
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            recognition = new SR();
            recognition.lang = 'ar-SA';
            this.classList.add('listening');
            addMessage('جاري الاستماع...', 'bot', true);
            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                userInput.value = transcript;
                micBtn.classList.remove('listening');
                setTimeout(() => sendMessage(), 300);
            };
            recognition.onerror = () => { micBtn.classList.remove('listening'); };
            recognition.start();
        });

        // ===== تشغيل الترحيب عند تحميل الصفحة =====
        showWelcome();

    })();
</script>
</body>
</html>
"""

# ========== صفحات الدخول ==========
LOGIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>دخول - روز</title>
<style>
    * { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    body { background: #fff5f7; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; padding: 15px; }
    .box { background: white; padding: 40px 30px; border-radius: 20px; box-shadow: 0 4px 20px rgba(232, 139, 156, 0.15); width: 100%; max-width: 400px; text-align: center; border: 1px solid #fce4ec; }
    h2 { font-size: 28px; color: #e88b9c; margin-bottom: 25px; }
    input { width: 100%; padding: 14px 16px; margin: 12px 0; border: 1px solid #fce4ec; border-radius: 12px; font-size: 18px; background: #fafbfc; box-sizing: border-box; }
    input:focus { outline: none; border-color: #e88b9c; background: #fff; }
    button { width: 100%; padding: 16px; background: #e88b9c; color: white; border: none; border-radius: 12px; font-size: 20px; font-weight: bold; cursor: pointer; margin-top: 15px; }
    button:hover { background: #d47384; }
    a { color: #e88b9c; text-decoration: none; font-size: 16px; display: inline-block; margin-top: 20px; }
    .error { color: #b34a5a; margin-bottom: 15px; }
</style>
</head>
<body>
<div class="box">
    <h2>🌸 تسجيل الدخول</h2>
    {% if error %}<div class="error">{{ error }}</div>{% endif %}
    <form method="POST">
        <input type="email" name="email" placeholder="البريد الإلكتروني" required>
        <input type="password" name="password" placeholder="كلمة المرور" required>
        <button type="submit">دخول</button>
    </form>
    <a href="/">⬅ العودة للرئيسية</a>
</div></body></html>
"""

# ========== مسارات التطبيق ==========
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        if email == "abdullaha0569361@gmail.com":
            session['admin_email'] = email
            return redirect(url_for('index'))
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
        return "guest_" + request.remote_addr

@app.route('/chat', methods=['POST'])
@limiter.limit("10 per minute")
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        history = data.get("history", [])
        conv_id = data.get("conv_id", None)

        if not user_message:
            return jsonify({"reply": "اكتبي شي يا عسل"})

        is_admin = 'admin_email' in session and session['admin_email'] == "abdullaha0569361@gmail.com"
        is_trial_user = 'user_email' in session and not is_admin
        trial_remaining = session.get('trial_remaining', 0)

        user_id = get_user_id()

        if conv_id is None:
            session_memory[user_id] = []

        # =========================================================
        # البحث والصور للأدمن فقط!
        # =========================================================
        if is_admin:
            model = "gpt-4o"
            use_web_search = True
            allow_images = True
            limit_msg = None
        else:
            model = "gpt-4o"
            use_web_search = False
            allow_images = False
            if is_trial_user and trial_remaining > 0:
                limit_msg = f"💎 تبقى لك {trial_remaining} محادثة تجريبية مميزة!"
            elif is_trial_user and trial_remaining == 0:
                limit_msg = "⚠️ انتهت المحادثات التجريبية. الترقية للاستمرار."
            else:
                limit_msg = None

        # =========================================================
        # كشف طلب إنشاء صورة
        # =========================================================
        draw_keywords = [
            "ارسم", "أنشئ", "انشئ", "انشى", "صوره", "صورة", "صور", 
            "رسم", "ارسمي", "صمم", "ولّد", "generate", "draw", "ارسم لي",
            "أنشئ لي", "انشئ لي", "انشى لي", "صوره لي"
        ]
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

        # =========================================================
        # باقي الكود
        # =========================================================
        session_memory[user_id].append({"role": "user", "content": user_message})
        chat_history = session_memory[user_id][-10:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for entry in chat_history:
            messages.append({"role": entry["role"], "content": entry["content"]})

        image_data = data.get("image", None)
        if image_data and allow_images:
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": user_message or "حللي هذه الصورة"}, {"type": "image_url", "image_url": {"url": image_data}}]
            })

        # ===== البحث بالويب (لن يعمل إلا للأدمن فقط) =====
        if use_web_search:
            try:
                full_context = ""
                for msg in messages:
                    if msg["role"] == "user":
                        full_context += msg["content"] + "\n"
                    elif msg["role"] == "assistant":
                        full_context += "روز: " + msg["content"] + "\n"
                
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

        # ===== الرد النهائي =====
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_completion_tokens=1000,
                temperature=0.8
            )
            reply = response.choices[0].message.content.strip()
            if not reply:
                reply = "ما قدرت أجيب لك رد، حاولي مرة ثانية."
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
            reply = "حدث خطأ في السيرفر، حاولي مرة أخرى."

        session_memory[user_id].append({"role": "assistant", "content": reply})

        new_conv_id = save_user_conversation(user_id, session_memory[user_id], conv_id)

        if is_trial_user and trial_remaining > 0:
            session['trial_remaining'] = trial_remaining - 1
            if session['trial_remaining'] == 0:
                session['is_trial_expired'] = True
                reply += "\n\n⚠️ انتهت محادثاتك التجريبية. الترقية للاستمرار مع البحث بالويب والصور."

        return jsonify({"reply": reply, "conv_id": new_conv_id})

    except Exception as e:
        print(f"❌ خطأ عام في /chat: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
