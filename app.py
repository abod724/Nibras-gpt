from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
import openai
import os
import secrets
import json
import hashlib
from datetime import datetime

app = Flask(__name__)

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
    """تحميل جميع المحادثات من ملف JSON"""
    if os.path.exists(CONVERSATIONS_FILE):
        try:
            with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_conversations(data):
    """حفظ المحادثات في ملف JSON"""
    with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_conversations(user_id):
    """استرجاع قائمة المحادثات لمستخدم معين"""
    all_conv = load_conversations()
    return all_conv.get(user_id, [])

def save_user_conversation(user_id, conversation):
    """حفظ محادثة جديدة لمستخدم مع عنوان فريد"""
    all_conv = load_conversations()
    if user_id not in all_conv:
        all_conv[user_id] = []
    
    # توليد عنوان من أول رسالة (أو "محادثة جديدة" إذا كانت فارغة)
    if conversation and len(conversation) > 0:
        base_title = conversation[0]["content"][:30]
        if len(conversation[0]["content"]) > 30:
            base_title += "..."
    else:
        base_title = "محادثة جديدة"
    
    # التأكد من عدم تكرار العنوان
    existing_titles = [c["title"] for c in all_conv[user_id]]
    title = base_title
    counter = 1
    while title in existing_titles:
        title = f"{base_title} ({counter})"
        counter += 1
    
    conv_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
    all_conv[user_id].append({
        "id": conv_id,
        "messages": conversation,
        "timestamp": datetime.now().isoformat(),
        "title": title
    })
    save_conversations(all_conv)
    return conv_id

def load_conversation_by_id(user_id, conv_id):
    """تحميل محادثة محددة بواسطة المعرف"""
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
    knowledge_content = "أنت نبراس، مساعد ذكي."

# ========== تعليمات النظام ==========
SYSTEM_PROMPT = f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.
3. **البحث بالويب** تستخدمه عندما يسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.

**ملف المعرفة الخاص بك:**
{knowledge_content}

**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة في ملف المعرفة، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- **لا تكتب "لحظة" أو "انتظر" أو أي نص انتظار**، فقط انتظر النتيجة ورد مباشرة.
"""

# ========== دالة إنشاء الصور ==========
def generate_image(prompt):
    """توليد صورة باستخدام DALL-E 3"""
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

# ========== واجهة الدردشة (مع المحادثات السابقة بدون تواريخ) ==========
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=yes" />
    <title>نبراس</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css" />
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
        body { background: #ffffff; height: 100dvh; display: flex; justify-content: center; align-items: center; margin: 0; padding: 0; }
        .app { width: 100%; max-width: 450px; height: 100dvh; background: #ffffff; display: flex; flex-direction: column; position: relative; }
        .header { display: flex; justify-content: space-between; align-items: center; padding: 14px 18px; border-bottom: 1px solid #eaeef2; flex-shrink: 0; background: #ffffff; }
        .menu-btn { background: none; border: none; font-size: 20px; color: #5a6b7c; cursor: pointer; padding: 4px 8px; }
        .btn-group { display: flex; gap: 8px; }
        .btn { padding: 6px 16px; border-radius: 20px; font-size: 14px; border: none; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; }
        .btn-outline { background: transparent; border: 1px solid #4a6a8a; color: #4a6a8a; }
        .btn-gold { background: #f1c40f; color: #1a2b3c; font-weight: bold; }
        .dropdown { position: absolute; top: 64px; left: 14px; right: 14px; background: white; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); display: none; flex-direction: column; z-index: 100; border: 1px solid #eaedf2; max-height: 60vh; overflow-y: auto; }
        .dropdown.show { display: flex; }
        .dropdown .item { display: flex; align-items: center; gap: 12px; padding: 14px 18px; font-size: 15px; color: #1a2b3c; background: none; border: none; width: 100%; text-align: right; cursor: pointer; border-bottom: 1px solid #f0f2f5; }
        .dropdown .item:last-child { border-bottom: none; }
        .dropdown .item i { width: 22px; font-size: 18px; color: #5a6b7c; }
        .dropdown .item:hover { background: #f5f7fa; }
        /* تنسيق عناوين المحادثات (بدون تواريخ) */
        .dropdown .conv-item {
            display: block;
            padding: 12px 18px;
            border-bottom: 1px solid #f0f2f5;
            cursor: pointer;
            width: 100%;
            background: none;
            border: none;
            text-align: right;
            font-size: 16px;
            color: #1a2b3c;
            font-weight: 500;
            transition: background 0.2s;
        }
        .dropdown .conv-item:hover {
            background: #f5f7fa;
        }
        .dropdown .conv-item:last-child {
            border-bottom: none;
        }
        #chat { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; background: #ffffff; font-size: 16px; }
        .msg { max-width: 80%; padding: 12px 18px; border-radius: 20px; font-size: 16px; line-height: 1.6; word-wrap: break-word; white-space: pre-wrap; }
        .msg.user { align-self: flex-end; background: transparent; color: #1a2b3c; border-bottom-left-radius: 6px; }
        .msg.bot { align-self: flex-start; background: #ffffff; color: #1a2b3c; border-bottom-right-radius: 6px; }
        .msg .time { font-size: 10px; opacity: 0.35; display: block; margin-top: 4px; }
        .msg.error { background: #fde8e8; color: #a33; align-self: center; max-width: 90%; }
        .msg .image-upload { max-width: 100%; max-height: 200px; border-radius: 12px; margin: 4px 0; border: 1px solid #ddd; display: block; }
        .msg .generated-image { max-width: 100%; border-radius: 12px; margin: 8px 0; border: 1px solid #e0e0e0; display: block; }

        #imagePreviewContainer {
            display: none;
            padding: 6px 18px;
            align-items: center;
            gap: 10px;
            background: #f5f7fa;
            margin: 0 14px;
            border-radius: 20px 20px 0 0;
            border: 1px solid #dce1e8;
            border-bottom: none;
            flex-wrap: wrap;
            flex-shrink: 0;
        }
        #imagePreviewContainer img { max-height: 60px; border-radius: 8px; border: 1px solid #ddd; }
        #imagePreviewContainer .label { font-size: 13px; color: #5a6b7c; }
        #removeImageBtn { background: none; border: none; color: #c33; font-size: 14px; cursor: pointer; padding: 4px 8px; border-radius: 12px; }
        #removeImageBtn:hover { background: #fde8e8; }
        .input-area { display: flex; align-items: flex-end; justify-content: center; gap: 8px; padding: 8px 14px; margin: 8px 14px 16px 14px; background: #f5f7fa; border-radius: 40px; border: 1px solid #dce1e8; flex-shrink: 0; min-height: 60px; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 12px 0; font-size: 16px; outline: none; color: #1a2b3c; direction: rtl; resize: none; overflow: hidden; min-height: 20px; max-height: 80px; font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.4; }
        .input-area textarea::placeholder { color: #9aabbc; }
        .input-area .btn-icon { background: none; border: none; color: #6a7b8c; font-size: 20px; cursor: pointer; padding: 4px; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .input-area .btn-icon:hover { background: #e8ecf0; }
        .input-area .mic-btn { color: #4a6a8a; }
        .input-area .mic-btn.listening { color: #c33; background: #fde8e8; }
        .input-area .send { background: #4a6a8a; color: white; border: none; width: 44px; height: 44px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-shadow: 0 2px 8px rgba(74,106,138,0.2); }
        .input-area .send:hover { background: #3a5a7a; }
        .plus-btn { background: none; border: none; color: #4a6a8a; font-size: 24px; cursor: pointer; padding: 4px; border-radius: 50%; width: 36px; height: 36px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: 0.3s; }
        .plus-btn:hover { background: #e8ecf0; }
        .plus-btn.rotate { transform: rotate(45deg); }
        .plus-options { display: none; position: absolute; bottom: 70px; right: 0; background: #ffffff; border-radius: 20px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); padding: 8px; gap: 6px; flex-direction: row; border: 1px solid #eaeef2; z-index: 50; }
        .plus-options.show { display: flex; }
        .plus-options .option-btn { background: #f5f7fa; border: none; border-radius: 50%; width: 44px; height: 44px; display: flex; align-items: center; justify-content: center; font-size: 20px; color: #1a2b3c; cursor: pointer; transition: 0.2s; }
        .plus-options .option-btn:hover { background: #e8ecf0; }
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
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <button class="menu-btn" id="menuToggle"><i class="fas fa-ellipsis-v"></i></button>
        <div class="btn-group">
            {% if session.get('admin_email') or session.get('user_email') %}
                <a href="/logout" class="btn btn-outline">تسجيل خروج</a>
            {% else %}
                <a href="/login" class="btn btn-outline">دخول</a>
            {% endif %}
            <a href="/plans" class="btn btn-gold">💎 ترقية</a>
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
        <textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1"></textarea>
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

        // ===== تحميل المحادثات السابقة (عناوين فقط) =====
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

        // ===== أزرار القائمة =====
        document.querySelector('[data-action="new"]').addEventListener('click', function() {
            chatBox.innerHTML = '';
            conversationHistory = [];
            currentConvId = null;
            dropdown.classList.remove('show');
            pendingImageData = null;
            imagePreviewContainer.style.display = 'none';
            userInput.value = '';
        });

        // ===== زر المحادثات السابقة (تم إزالته من الـ HTML، لكن نتركه للتوافق) =====
        // عند فتح القائمة، نحمل المحادثات
        menuToggle.addEventListener('click', function(e) {
            e.stopPropagation();
            dropdown.classList.toggle('show');
            if (dropdown.classList.contains('show')) {
                loadHistory();
            }
        });

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

        function addMessage(text, sender = 'bot', isSystem = false, imageData = null) {
            const el = document.createElement('div');
            el.className = `msg ${sender}`;
            if (sender === 'error') el.classList.add('error');
            const now = new Date();
            const time = now.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
            
            if (imageData) {
                el.innerHTML = `<img src="${imageData}" class="image-upload" /><span class="file-label">${text || 'صورة'}</span><span class="time"> ${time}</span>`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                return;
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
                el.innerHTML = `<span class="typing-text"></span><span class="time"> ${time}</span>`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                const typingSpan = el.querySelector('.typing-text');
                let index = 0;
                function typeChar() {
                    if (index < displayText.length) {
                        typingSpan.textContent += displayText.charAt(index);
                        index++;
                        chatBox.scrollTop = chatBox.scrollHeight;
                        setTimeout(typeChar, 20);
                    } else {
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
                return;
            }

            let content = displayText;
            if (generatedImageUrl) {
                content += `<br/><img src="${generatedImageUrl}" class="generated-image" />`;
            }
            el.innerHTML = `${content} <span class="time">${time}</span>`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;
        }

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

            const payload = {
                message: text || "📎 مرفق",
                image: imageToSend || null,
                history: conversationHistory,
                conv_id: currentConvId
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

        // إغلاق القائمة عند النقر خارجها
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
    })();
</script>
</body>
</html>
"""

# ========== صفحة الدخول والخطط ==========
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

@app.route('/plans')
def plans():
    return render_template_string(PLANS_HTML)

@app.route('/history')
def history():
    """إرجاع قائمة المحادثات السابقة (عناوين فقط، مرتبة تنازلياً)"""
    user_id = get_user_id()
    conversations = get_user_conversations(user_id)
    # ترتيب تنازلي حسب الوقت (الأحدث أولاً)
    conversations.sort(key=lambda x: x["timestamp"], reverse=True)
    result = [{"id": c["id"], "title": c["title"]} for c in conversations]
    return jsonify({"conversations": result})

@app.route('/load_conversation/<conv_id>')
def load_conversation(conv_id):
    """تحميل محادثة محددة"""
    user_id = get_user_id()
    messages = load_conversation_by_id(user_id, conv_id)
    if messages:
        return jsonify({"messages": messages})
    return jsonify({"messages": None}), 404

def get_user_id():
    """استخراج معرف المستخدم من الجلسة"""
    if 'admin_email' in session:
        return "admin_" + session['admin_email']
    elif 'user_email' in session:
        return "user_" + session['user_email']
    else:
        return "guest_" + request.remote_addr

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

        if is_admin:
            model = "gpt-4o"
            use_web_search = True
            allow_images = True
            limit_msg = None
        elif is_trial_user and trial_remaining > 0 and not session.get('is_trial_expired'):
            model = "gpt-4o"
            use_web_search = True
            allow_images = True
            limit_msg = f"💎 تبقى لك {trial_remaining} محادثة تجريبية مميزة!"
        else:
            model = "gpt-4o-mini"
            use_web_search = False
            allow_images = False
            if is_trial_user and trial_remaining == 0:
                limit_msg = "⚠️ انتهت المحادثات التجريبية. الترقية للاستمرار."

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
                if user_id not in session_memory:
                    session_memory[user_id] = []
                session_memory[user_id].append({"role": "user", "content": user_message})
                session_memory[user_id].append({"role": "assistant", "content": reply})
                
                # حفظ في قاعدة البيانات
                save_user_conversation(user_id, session_memory[user_id])
                
                if is_trial_user and trial_remaining > 0:
                    session['trial_remaining'] = trial_remaining - 1
                    if session['trial_remaining'] == 0:
                        session['is_trial_expired'] = True
                        reply += "\n\n⚠️ انتهت محادثاتك التجريبية. الترقية للاستمرار."
                
                return jsonify({"reply": reply, "conv_id": conv_id})
            else:
                print("⚠️ فشل توليد الصورة، نكمل للرد النصي.")

        # =========================================================
        # باقي الكود (تحليل الصور، محادثة، بحث ويب)
        # =========================================================
        if user_id not in session_memory:
            session_memory[user_id] = []
        
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

        # ===== البحث بالويب =====
        if use_web_search:
            try:
                full_context = ""
                for msg in messages:
                    if msg["role"] == "user":
                        full_context += msg["content"] + "\n"
                    elif msg["role"] == "assistant":
                        full_context += "نبراس: " + msg["content"] + "\n"
                
                search_response = client.responses.create(
                    model="gpt-4o-mini",
                    instructions=f"{SYSTEM_PROMPT}\n\nسياق المحادثة السابقة:\n{full_context}",
                    input=f"ابحث في الويب عن أحدث المعلومات حول: {user_message}، وقدم لي ملخصاً مفيداً.",
                    tools=[{"type": "web_search"}],
                    temperature=0.7,
                    max_output_tokens=800
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
                max_tokens=1000,
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
                    max_tokens=800,
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

        # حفظ المحادثة في قاعدة البيانات بعد كل رد
        save_user_conversation(user_id, session_memory[user_id])

        if is_trial_user and trial_remaining > 0:
            session['trial_remaining'] = trial_remaining - 1
            if session['trial_remaining'] == 0:
                session['is_trial_expired'] = True
                reply += "\n\n⚠️ انتهت محادثاتك التجريبية. الترقية للاستمرار مع البحث بالويب والصور."

        return jsonify({"reply": reply, "conv_id": conv_id})

    except Exception as e:
        print(f"❌ خطأ عام في /chat: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
