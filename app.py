from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
import openai
import os
import secrets
from datetime import datetime

app = Flask(__name__)

# إعداد المفاتيح السرية
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود! يجب إضافته في متغيرات البيئة")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_ENABLED = True

# ========== نظام الذاكرة المؤقتة (بدون قاعدة بيانات) ==========
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
- إذا كان السؤال يتطلب معلومات حديثة (أخبار، طقس، أحداث)، استخدم البحث بالويب.
- دائماً حافظ على لهجتك العامية البيضاء.
- إذا لم تجد المعلومة في أي من المصادر، قل بصراحة "ما عندي علم".
- إذا سألك عن الترقية، أجب أن الخطة المدفوعة بـ 7 ريال شهرياً وتشمل بحث بالويب وتوليد الصور.
"""

# ========== الواجهة الكاملة (مع رفع الصور، مايك، قائمة، وأزرار الدخول والترقية) ==========
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
        .logo { font-size: 20px; font-weight: bold; color: #1a2b3c; }
        .btn-group { display: flex; gap: 8px; }
        .btn { padding: 6px 16px; border-radius: 20px; font-size: 14px; border: none; cursor: pointer; text-decoration: none; display: inline-block; text-align: center; }
        .btn-outline { background: transparent; border: 1px solid #4a6a8a; color: #4a6a8a; }
        .btn-gold { background: #f1c40f; color: #1a2b3c; font-weight: bold; }
        .dropdown { position: absolute; top: 64px; left: 14px; right: 14px; background: white; border-radius: 16px; box-shadow: 0 8px 30px rgba(0,0,0,0.08); display: none; flex-direction: column; z-index: 100; border: 1px solid #eaedf2; }
        .dropdown.show { display: flex; }
        .dropdown .item { display: flex; align-items: center; gap: 12px; padding: 14px 18px; font-size: 15px; color: #1a2b3c; background: none; border: none; width: 100%; text-align: right; cursor: pointer; border-bottom: 1px solid #f0f2f5; }
        .dropdown .item:last-child { border-bottom: none; }
        .dropdown .item i { width: 22px; font-size: 18px; color: #5a6b7c; }
        .dropdown .item:hover { background: #f5f7fa; }
        #chat { flex: 1; overflow-y: auto; padding: 20px 24px; display: flex; flex-direction: column; gap: 12px; background: #ffffff; font-size: 16px; }
        .msg { max-width: 80%; padding: 12px 18px; border-radius: 20px; font-size: 16px; line-height: 1.6; word-wrap: break-word; white-space: pre-wrap; }
        .msg.user { align-self: flex-end; background: #eef2f7; color: #1a2b3c; border-bottom-left-radius: 6px; }
        .msg.bot { align-self: flex-start; background: #ffffff; color: #1a2b3c; border-bottom-right-radius: 6px; }
        .msg .time { font-size: 10px; opacity: 0.35; display: block; margin-top: 4px; }
        .msg.error { background: #fde8e8; color: #a33; align-self: center; max-width: 90%; }
        .msg .image-upload { max-width: 100%; max-height: 200px; border-radius: 12px; margin: 4px 0; border: 1px solid #ddd; display: block; }
        .msg .file-label { font-size: 12px; color: #6a7b8c; margin-top: 2px; display: block; }
        .input-area { display: flex; align-items: center; gap: 6px; padding: 6px 12px; margin: 8px 14px 16px 14px; background: #f5f7fa; border-radius: 40px; border: 1px solid #dce1e8; flex-shrink: 0; position: relative; }
        .input-area textarea { flex: 1; border: none; background: transparent; padding: 12px 4px; font-size: 16px; outline: none; color: #1a2b3c; direction: rtl; resize: none; overflow: hidden; min-height: 40px; max-height: 120px; font-family: 'Segoe UI', Arial, sans-serif; line-height: 1.5; }
        .input-area textarea::placeholder { color: #9aabbc; }
        .input-area .btn-icon { background: none; border: none; color: #6a7b8c; font-size: 20px; cursor: pointer; padding: 4px; border-radius: 50%; width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .input-area .btn-icon:hover { background: #e8ecf0; }
        .input-area .mic-btn { color: #4a6a8a; }
        .input-area .mic-btn.listening { color: #c33; background: #fde8e8; }
        .input-area .send { background: #4a6a8a; color: white; border: none; width: 44px; height: 44px; border-radius: 50%; font-size: 18px; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-shadow: 0 2px 8px rgba(74,106,138,0.2); }
        .input-area .send:hover { background: #3a5a7a; }
        .plus-btn { background: none; border: none; color: #4a6a8a; font-size: 24px; cursor: pointer; padding: 4px; border-radius: 50%; width: 38px; height: 38px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: 0.3s; }
        .plus-btn:hover { background: #e8ecf0; }
        .plus-btn.rotate { transform: rotate(45deg); }
        .plus-options { display: none; position: absolute; bottom: 70px; right: 0; background: #ffffff; border-radius: 20px; box-shadow: 0 8px 30px rgba(0,0,0,0.12); padding: 12px; gap: 8px; flex-direction: row; border: 1px solid #eaeef2; z-index: 50; }
        .plus-options.show { display: flex; }
        .plus-options .option-btn { background: #f5f7fa; border: none; border-radius: 50%; width: 52px; height: 52px; display: flex; align-items: center; justify-content: center; font-size: 22px; color: #1a2b3c; cursor: pointer; transition: 0.2s; }
        .plus-options .option-btn:hover { background: #e8ecf0; transform: scale(1.05); }
        .plus-options .option-btn.camera { color: #e74c3c; }
        .plus-options .option-btn.gallery { color: #2ecc71; }
        .plus-options .option-btn.files { color: #3498db; }
        @media (max-width: 420px) {
            .header { padding: 12px 14px; }
            .logo { font-size: 18px; }
            .btn-group { gap: 6px; }
            .btn { font-size: 12px; padding: 5px 12px; }
            .dropdown { top: 58px; left: 10px; right: 10px; }
            #chat { padding: 14px 16px; }
            .msg { font-size: 15px; padding: 10px 14px; }
            .input-area { margin: 6px 10px 12px 10px; padding: 4px 10px; }
            .input-area textarea { font-size: 15px; padding: 10px 2px; }
            .input-area .send { width: 40px; height: 40px; font-size: 16px; }
            .input-area .btn-icon { width: 34px; height: 34px; font-size: 18px; }
            .plus-btn { width: 34px; height: 34px; font-size: 20px; }
            .plus-options { bottom: 60px; padding: 8px; gap: 6px; }
            .plus-options .option-btn { width: 44px; height: 44px; font-size: 18px; }
            .msg .image-upload { max-height: 150px; }
        }
    </style>
</head>
<body>
<div class="app">
    <!-- الشريط العلوي مع الأزرار الجديدة -->
    <div class="header">
        <div class="logo">نبراس</div>
        <div class="btn-group">
            <a href="/login" class="btn btn-outline">دخول</a>
            <a href="/plans" class="btn btn-gold">💎 ترقية</a>
        </div>
    </div>
    
    <!-- قائمة منسدلة (ثلاث نقاط) -->
    <div class="dropdown" id="dropdown">
        <button class="item" data-action="new"><i class="fas fa-plus-circle"></i> محادثة جديدة</button>
        <button class="item" data-action="library"><i class="fas fa-layer-group"></i> المكتبة</button>
        <button class="item" data-action="history"><i class="fas fa-history"></i> المحادثات السابقة</button>
    </div>

    <!-- منطقة الدردشة -->
    <div id="chat">
        <div class="msg bot">مرحباً بك في نبراس!</div>
    </div>

    <!-- منطقة الإدخال مع الأزرار -->
    <div class="input-area">
        <button class="btn-icon mic-btn" id="micBtn" title="تسجيل صوت"><i class="fas fa-microphone"></i></button>
        <button class="plus-btn" id="plusBtn" title="إضافة"><i class="fas fa-plus"></i></button>
        <div class="plus-options" id="plusOptions">
            <button class="option-btn camera" id="cameraBtn" title="كاميرا"><i class="fas fa-camera"></i></button>
            <button class="option-btn gallery" id="galleryBtn" title="معرض الصور"><i class="fas fa-images"></i></button>
            <button class="option-btn files" id="filesBtn" title="ملفات"><i class="fas fa-folder"></i></button>
        </div>
        <textarea id="userInput" placeholder="اكتب رسالتك..." autofocus rows="1" style="resize: none; overflow: hidden; min-height: 40px; max-height: 120px; flex: 1; border: none; background: transparent; padding: 12px 4px; font-size: 15px; outline: none; color: #1a2b3c; direction: rtl; line-height: 1.5;"></textarea>
        <button class="send" id="sendBtn"><i class="fas fa-arrow-left"></i></button>
    </div>
    
    <!-- عناصر الإدخال المخفية -->
    <input type="file" id="fileInput" accept="image/*" style="display: none;" />
    <input type="file" id="cameraInput" accept="image/*" capture="environment" style="display: none;" />
    <input type="file" id="fileInputGeneric" style="display: none;" />
</div>
<script>
    (function() {
        let conversationHistory = [];
        let pendingImageData = null;
        const chatBox = document.getElementById('chat');
        const userInput = document.getElementById('userInput');
        const sendBtn = document.getElementById('sendBtn');
        const micBtn = document.getElementById('micBtn');
        const fileInput = document.getElementById('fileInput');
        const cameraInput = document.getElementById('cameraInput');
        const fileInputGeneric = document.getElementById('fileInputGeneric');
        const menuToggle = document.getElementById('menuToggle');
        const dropdown = document.getElementById('dropdown');
        const plusBtn = document.getElementById('plusBtn');
        const plusOptions = document.getElementById('plusOptions');
        const cameraBtn = document.getElementById('cameraBtn');
        const galleryBtn = document.getElementById('galleryBtn');
        const filesBtn = document.getElementById('filesBtn');

        userInput.addEventListener('input', function() {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 120) + 'px';
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

        cameraBtn.addEventListener('click', function() {
            cameraInput.click();
            plusOptions.classList.remove('show');
            plusOpen = false;
            plusBtn.classList.remove('rotate');
        });
        cameraInput.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const file = this.files[0];
                const reader = new FileReader();
                reader.onload = function(ev) {
                    const imgData = ev.target.result;
                    pendingImageData = imgData;
                    addMessage(file.name, 'user', false, imgData);
                    let imgs = getImages();
                    imgs.push(imgData);
                    saveImages(imgs);
                    sendMessageAfterMedia();
                    cameraInput.value = '';
                };
                reader.readAsDataURL(file);
            }
        });

        galleryBtn.addEventListener('click', function() {
            fileInput.click();
            plusOptions.classList.remove('show');
            plusOpen = false;
            plusBtn.classList.remove('rotate');
        });
        fileInput.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const file = this.files[0];
                const reader = new FileReader();
                reader.onload = function(ev) {
                    const imgData = ev.target.result;
                    pendingImageData = imgData;
                    addMessage(file.name, 'user', false, imgData);
                    let imgs = getImages();
                    imgs.push(imgData);
                    saveImages(imgs);
                    sendMessageAfterMedia();
                    fileInput.value = '';
                };
                reader.readAsDataURL(file);
            }
        });

        filesBtn.addEventListener('click', function() {
            fileInputGeneric.click();
            plusOptions.classList.remove('show');
            plusOpen = false;
            plusBtn.classList.remove('rotate');
        });
        fileInputGeneric.addEventListener('change', function(e) {
            if (this.files && this.files.length > 0) {
                const file = this.files[0];
                addMessage(`📎 تم رفع: ${file.name}`, 'user');
                fileInputGeneric.value = '';
            }
        });

        function addMessage(text, sender = 'bot', isSystem = false, imageData = null) {
            const el = document.createElement('div');
            el.className = `msg ${sender}`;
            if (sender === 'error') el.classList.add('error');
            const now = new Date();
            const time = now.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
            if (imageData) {
                pendingImageData = imageData;
                el.innerHTML = `<img src="${imageData}" class="image-upload" /><span class="file-label">${text || 'صورة'}</span><span class="time"> ${time}</span>`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                if (!isSystem && sender !== 'error') {
                    conversationHistory.push({ role: sender, content: '📷 رفع صورة' });
                    if (conversationHistory.length > 20) conversationHistory = conversationHistory.slice(-20);
                    saveHistory(sender, text);
                }
                return;
            }
            if (sender === 'bot' && !isSystem) {
                el.innerHTML = `<span class="typing-text"></span><span class="time"> ${time}</span>`;
                chatBox.appendChild(el);
                chatBox.scrollTop = chatBox.scrollHeight;
                const typingSpan = el.querySelector('.typing-text');
                let index = 0;
                function typeChar() {
                    if (index < text.length) {
                        typingSpan.textContent += text.charAt(index);
                        index++;
                        chatBox.scrollTop = chatBox.scrollHeight;
                        setTimeout(typeChar, 20);
                    }
                }
                typeChar();
                if (!isSystem && sender !== 'error') {
                    conversationHistory.push({ role: sender, content: text });
                    if (conversationHistory.length > 20) conversationHistory = conversationHistory.slice(-20);
                    saveHistory(sender, text);
                }
                return;
            }
            el.innerHTML = `${text} <span class="time">${time}</span>`;
            chatBox.appendChild(el);
            chatBox.scrollTop = chatBox.scrollHeight;
            if (!isSystem && sender !== 'error') {
                conversationHistory.push({ role: sender, content: text });
                if (conversationHistory.length > 20) conversationHistory = conversationHistory.slice(-20);
                saveHistory(sender, text);
            }
        }

        function saveHistory(sender, text) {
            let hist = JSON.parse(localStorage.getItem('niras_history') || '[]');
            hist.push({ sender, text, time: new Date().toISOString() });
            if (hist.length > 100) hist = hist.slice(-100);
            localStorage.setItem('niras_history', JSON.stringify(hist));
        }
        function getHistory() {
            return JSON.parse(localStorage.getItem('niras_history') || '[]');
        }

        function getImages() {
            return JSON.parse(localStorage.getItem('niras_images') || '[]');
        }
        function saveImages(imgs) {
            localStorage.setItem('niras_images', JSON.stringify(imgs));
        }
        function deleteImage(index) {
            let imgs = getImages();
            if (index >= 0 && index < imgs.length) {
                imgs.splice(index, 1);
                saveImages(imgs);
                addMessage('تم حذف الصورة.', 'bot', true);
                showLibrary();
            }
        }

        function showLibrary() {
            const imgs = getImages();
            if (imgs.length === 0) {
                addMessage('لا توجد صور.', 'bot', true);
                return;
            }
            let html = '<div class="gallery">';
            imgs.forEach((src, idx) => {
                html += `<div class="img-wrap">
                    <img src="${src}" />
                    <button class="del" data-idx="${idx}">×</button>
                </div>`;
            });
            html += '</div>';
            const container = document.createElement('div');
            container.className = 'msg bot';
            container.innerHTML = html + `<span class="time">${new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })}</span>`;
            chatBox.appendChild(container);
            chatBox.scrollTop = chatBox.scrollHeight;
            container.querySelectorAll('.del').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.stopPropagation();
                    const idx = parseInt(this.dataset.idx);
                    deleteImage(idx);
                });
            });
        }

        function showHistory() {
            const hist = getHistory();
            if (hist.length === 0) {
                addMessage('لا توجد محادثات.', 'bot', true);
                return;
            }
            let msg = '';
            hist.slice(-12).forEach((entry) => {
                const t = new Date(entry.time).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
                const txt = entry.text.length > 40 ? entry.text.substring(0, 40) + '...' : entry.text;
                msg += `- ${txt} (${t})\n`;
            });
            addMessage(msg, 'bot', true);
            hist.slice(-5).forEach(entry => {
                const btn = document.createElement('button');
                btn.textContent = entry.text.length > 22 ? entry.text.substring(0, 22) + '…' : entry.text;
                btn.style.cssText = 'background:#f0f2f5;border:none;border-radius:30px;padding:4px 12px;margin:4px;cursor:pointer;font-size:13px;color:#1a2b3c;';
                btn.onclick = function() { userInput.value = entry.text; userInput.focus(); };
                chatBox.appendChild(btn);
            });
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        function newChat() {
            chatBox.innerHTML = '<div class="msg bot">بدأت محادثة جديدة!</div>';
            conversationHistory = [];
        }

        function handleAction(action) {
            dropdown.classList.remove('show');
            switch(action) {
                case 'new': newChat(); break;
                case 'library': showLibrary(); break;
                case 'history': showHistory(); break;
                default: break;
            }
        }

        document.querySelectorAll('.dropdown .item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                handleAction(item.dataset.action);
            });
        });

        menuToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });
        document.addEventListener('click', () => {
            dropdown.classList.remove('show');
        });

        let recognition = null;
        micBtn.addEventListener('click', function() {
            if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
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
            recognition.continuous = false;
            recognition.interimResults = false;
            this.classList.add('listening');
            addMessage('جاري الاستماع...', 'bot', true);
            recognition.onresult = (event) => {
                const transcript = event.results[0][0].transcript;
                userInput.value = transcript;
                micBtn.classList.remove('listening');
                setTimeout(() => {
                    sendMessage();
                }, 300);
            };
            recognition.onerror = (event) => {
                micBtn.classList.remove('listening');
                if (event.error !== 'aborted') {
                    addMessage('لم يتعرف على الصوت، حاول مرة أخرى.', 'bot', true);
                }
            };
            recognition.onend = () => {
                micBtn.classList.remove('listening');
            };
            recognition.start();
        });

        function sendMessageAfterMedia() {
            const text = userInput.value.trim();
            const imageToSend = pendingImageData;
            pendingImageData = null;
            sendMessageInternal(text || "📎 ملف مرفق", imageToSend);
        }

        async function sendMessageInternal(text, image = null) {
            userInput.value = '';
            userInput.style.height = '40px';
            userInput.focus();
            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, image: image, history: conversationHistory })
                });
                const data = await res.json();
                if (res.ok) {
                    addMessage(data.reply, 'bot');
                } else {
                    addMessage('خطأ: ' + (data.error || 'مشكلة في السيرفر'), 'error');
                }
            } catch (e) {
                addMessage('تعذر الاتصال بالسيرفر.', 'error');
            }
        }

        async function sendMessage() {
            const text = userInput.value.trim();
            if (!text) return;
            addMessage(text, 'user');
            userInput.value = '';
            userInput.style.height = '40px';
            userInput.focus();
            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, image: null, history: conversationHistory })
                });
                const data = await res.json();
                if (res.ok) {
                    addMessage(data.reply, 'bot');
                } else {
                    addMessage('خطأ: ' + (data.error || 'مشكلة في السيرفر'), 'error');
                }
            } catch (e) {
                addMessage('تعذر الاتصال بالسيرفر.', 'error');
            }
        }

        sendBtn.addEventListener('click', sendMessage);
        userInput.addEventListener('keypress', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
        
        // إضافة زر القائمة (الثلاث نقاط) في الـ header
        const headerRight = document.querySelector('.header .btn-group');
        if(headerRight) {
            const menuBtn = document.createElement('button');
            menuBtn.className = 'btn-icon menu-btn';
            menuBtn.id = 'menuToggle';
            menuBtn.style.cssText = 'background:none;border:none;font-size:20px;color:#5a6b7c;cursor:pointer;padding:4px 8px;';
            menuBtn.innerHTML = '<i class="fas fa-ellipsis-v"></i>';
            headerRight.insertBefore(menuBtn, headerRight.firstChild);
            
            menuBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                document.getElementById('dropdown').classList.toggle('show');
            });
        }
    })();
</script>
</body>
</html>
"""

# ========== صفحة تسجيل الدخول ==========
LOGIN_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><title>دخول - نبراس</title>
<style>body{font-family:Arial;background:#f0f2f5;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}.box{background:white;padding:30px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1);width:300px;text-align:center}input{width:100%;padding:10px;margin:10px 0;border:1px solid #ccc;border-radius:5px}button{width:100%;padding:10px;background:#4a6a8a;color:white;border:none;border-radius:5px;cursor:pointer}</style>
</head>
<body>
<div class="box"><h2>تسجيل الدخول إلى نبراس</h2>
<form method="POST">
<input type="email" name="email" placeholder="البريد الإلكتروني" required>
<input type="password" name="password" placeholder="كلمة المرور" required>
<button type="submit">دخول</button>
</form>
<p><a href="/" style="color:#4a6a8a;">العودة للرئيسية</a></p>
</div></body></html>
"""

# ========== صفحة خطط نبراس (الترقية) ==========
PLANS_HTML = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head><meta charset="UTF-8"><title>خطط نبراس</title>
<style>body{font-family:Arial;background:#f0f2f5;padding:20px}.container{max-width:500px;margin:0 auto}.back{display:inline-block;margin-bottom:15px;padding:8px 16px;background:#4a6a8a;color:white;text-decoration:none;border-radius:8px}.plan{background:white;border-radius:12px;padding:20px;margin-bottom:15px;box-shadow:0 2px 10px rgba(0,0,0,0.05);border-right:4px solid #4a6a8a}.plan.premium{border-right-color:#f1c40f}.plan h3{font-size:22px;color:#1a2b3c}.price{font-size:28px;font-weight:bold;color:#2d7d46}.price span{font-size:16px;color:#6a7b8c}.btn{display:block;padding:12px;background:#4a6a8a;color:white;text-align:center;text-decoration:none;border-radius:8px;font-size:18px}.btn.gold{background:#f1c40f;color:#1a2b3c}</style>
</head>
<body>
<div class="container"><a href="/" class="back">⬅ العودة للرئيسية</a>
<h1 style="color:#1a2b3c;">💎 خطط نبراس</h1>
<div class="plan"><span style="background:#eef2f7;padding:4px 12px;border-radius:30px;font-size:14px;">مجاني</span>
<h3>الخطة المجانية</h3><div class="price">0 <span>ر.س / شهرياً</span></div>
<ul><li>✅ محادثات غير محدودة</li><li>✅ إجابات سريعة وذكية</li></ul>
</div>
<div class="plan premium"><span style="background:#2d7d46;padding:4px 12px;border-radius:30px;font-size:14px;color:white;">مميز</span>
<h3>الخطة المدفوعة</h3><div class="price">7 <span>ر.س / شهرياً</span></div>
<ul><li>✅ ذكاء متقدم (إجابات أعمق)</li><li>✅ بحث بالويب (معلومات حديثة)</li><li>✅ تحليل الصور</li><li>✅ ردود أسرع</li></ul>
<a href="#" class="btn gold">💎 اشترك الآن</a>
</div></div></body></html>
"""

# ========== مسارات التطبيق ==========
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # هذا مجرد واجهة عرض، لأنك ما عندك قاعدة بيانات مستخدمين حقيقية في هذا الكود
        return "<h3>نظام تسجيل الدخول غير مفعل حالياً (يحتاج قاعدة بيانات).</h3>"
    return render_template_string(LOGIN_HTML)

@app.route('/plans')
def plans():
    return render_template_string(PLANS_HTML)

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()
        history = data.get("history", [])

        if not user_message:
            return jsonify({"reply": "اكتب شيء أساعدك فيه"})

        user_id = request.remote_addr
        if user_id not in session_memory:
            session_memory[user_id] = []

        session_memory[user_id].append({"role": "user", "content": user_message})
        chat_history = session_memory[user_id][-10:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for entry in chat_history:
            messages.append({"role": entry["role"], "content": entry["content"]})
        for entry in history:
            if entry["role"] in ["user", "bot"]:
                messages.append({"role": entry["role"], "content": entry["content"]})

        # البحث بالويب
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
                messages.append({
                    "role": "user",
                    "content": f"نتيجة البحث عن '{user_message}':\n{search_result}\n\nاستخدم هذه المعلومات في ردك."
                })
        except Exception as e:
            print(f"⚠️ فشل البحث بالويب: {e}")

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=1000,
                temperature=0.8
            )
            reply = response.choices[0].message.content.strip()
            if not reply:
                reply = "ما قدرت أجيب لك رد، حاول مرة أخرى."
        except Exception as e:
            print(f"❌ خطأ في الرد: {e}")
            reply = "حدث خطأ، حاول مرة أخرى."

        session_memory[user_id].append({"role": "assistant", "content": reply})
        return jsonify({"reply": reply})

    except Exception as e:
        print(f"❌ خطأ: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
