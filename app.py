# ============================================================
# app.py - بوت خدمة عملاء بشخصية سعودية
# (مرتبط بملف personality.py للشخصية والأسلوب)
# ============================================================

from flask import Flask, request, jsonify, render_template_string
import random
import os

# استيراد الشخصية من ملف منفصل
from personality import (
    BOT_NAME,
    BOT_NATIONALITY,
    BOT_ROLE,
    BOT_PERSONALITY,
    BOT_DIALECT,
    BOT_BACKGROUND,
    BOT_RESPONSE_STYLE,
    EXAMPLE_RESPONSES,
    get_bot_personality
)

# ---------- المتغيرات الأساسية (عدل القيم بين علامات الاقتباس) ----------
COMPANY_NAME = "متجر البناء"              # اسم شركتك
WELCOME_MSG = EXAMPLE_RESPONSES["ترحيب"]  # رسالة الترحيب من ملف الشخصية

# أسعار المنتجات (عدل الأرقام حسب متجرك)
STEEL_PRICE = "٣٦٠٠ - ٣٧٥٠ ريال للطن"
CEMENT_PRICE = "١٤ ريال للكيس (٥٠ كجم)"
PLUMBING_PRICE = "حسب القطر والكمية (يبدأ من ٥ ريال للمتر)"
ELECTRICITY_PRICE = "حسب النوع والقطر"
WOOD_PRICE = "حسب النوع والسماكة"

# ردود إضافية (اختيارية)
THANK_REPLY = EXAMPLE_RESPONSES["شكر"]
GOODBYE_REPLY = EXAMPLE_RESPONSES["وداع"]
FALLBACK_REPLY = EXAMPLE_RESPONSES["عدم فهم"]

# ---------- تهيئة التطبيق ----------
app = Flask(__name__)

# ---------- واجهة المستخدم (مربع كتابة + زر إرسال) ----------
HTML_PAGE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ company }}</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #f4f4f4; display: flex; justify-content: center; padding: 20px; margin: 0; }
        .chat-box { width: 420px; max-width: 100%; background: white; border-radius: 20px; padding: 20px; box-shadow: 0 6px 20px rgba(0,0,0,0.1); }
        .header { border-bottom: 2px solid #007bff; padding-bottom: 10px; margin-bottom: 15px; }
        .header h3 { margin: 0; color: #1e293b; }
        .header small { color: #64748b; font-size: 13px; }
        .messages { height: 400px; overflow-y: auto; padding: 5px 0; display: flex; flex-direction: column; gap: 8px; }
        .user-msg { background: #007bff; color: white; padding: 10px 14px; border-radius: 18px; align-self: flex-end; max-width: 80%; }
        .bot-msg { background: #e9edf2; color: #1e293b; padding: 10px 14px; border-radius: 18px; align-self: flex-start; max-width: 80%; }
        .input-area { display: flex; gap: 10px; margin-top: 12px; }
        .input-area input { flex: 1; padding: 12px; border: 2px solid #e2e8f0; border-radius: 30px; outline: none; font-size: 15px; }
        .input-area input:focus { border-color: #007bff; }
        .input-area button { padding: 12px 24px; background: #007bff; color: white; border: none; border-radius: 30px; font-size: 16px; cursor: pointer; transition: 0.2s; }
        .input-area button:hover { background: #0056b3; }
        .quick-btns { display: flex; gap: 6px; flex-wrap: wrap; margin: 12px 0 5px; }
        .quick-btns button { background: #f1f5f9; border: 1px solid #e2e8f0; padding: 5px 14px; border-radius: 30px; font-size: 13px; cursor: pointer; transition: 0.2s; }
        .quick-btns button:hover { background: #007bff; color: white; border-color: #007bff; }
        .timestamp { font-size: 10px; opacity: 0.5; margin-top: 4px; text-align: left; }
        .messages::-webkit-scrollbar { width: 5px; }
        .messages::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 10px; }
    </style>
</head>
<body>
<div class="chat-box">
    <div class="header">
        <h3>{{ company }}</h3>
        <small>🤖 {{ bot_name }} • {{ nationality }}</small>
    </div>
    <div class="quick-btns">
        <button onclick="sendQuick('سعر الحديد')">حديد</button>
        <button onclick="sendQuick('سعر الاسمنت')">اسمنت</button>
        <button onclick="sendQuick('مواسير سباكة')">سباكة</button>
        <button onclick="sendQuick('كابلات كهرباء')">كهرباء</button>
        <button onclick="sendQuick('خشب بناء')">خشب</button>
    </div>
    <div class="messages" id="msgArea">
        <div class="bot-msg">👋 {{ welcome }}</div>
    </div>
    <div class="input-area">
        <input type="text" id="userInput" placeholder="اكتب استفسارك..." onkeydown="if(event.key=='Enter') sendMsg()">
        <button onclick="sendMsg()">إرسال</button>
    </div>
</div>
<script>
    function addMsg(text, cls) {
        const area = document.getElementById('msgArea');
        const d = document.createElement('div');
        d.className = cls;
        d.innerHTML = text + '<div class="timestamp">' + new Date().toLocaleTimeString('ar-SA', {hour:'2-digit', minute:'2-digit'}) + '</div>';
        area.appendChild(d);
        area.scrollTop = area.scrollHeight;
    }
    async function sendMsg() {
        const input = document.getElementById('userInput');
        const msg = input.value.trim();
        if (!msg) return;
        addMsg(msg, 'user-msg');
        input.value = '';
        input.disabled = true;
        const typing = document.createElement('div');
        typing.className = 'bot-msg';
        typing.id = 'typing';
        typing.innerHTML = 'جاري التفكير ⏳';
        document.getElementById('msgArea').appendChild(typing);
        const res = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: msg})
        });
        const data = await res.json();
        document.getElementById('typing')?.remove();
        addMsg(data.response, 'bot-msg');
        input.disabled = false;
        input.focus();
    }
    function sendQuick(text) {
        document.getElementById('userInput').value = text;
        sendMsg();
    }
</script>
</body>
</html>
"""

# ---------- منطق البوت (يستخدم الشخصية) ----------
def bot_reply(user_msg):
    msg = user_msg.lower().strip()
    
    # ردود تعتمد على الشخصية
    if "السلام" in msg or "هلا" in msg or "مرحب" in msg:
        return EXAMPLE_RESPONSES["ترحيب"]
    elif "شكر" in msg:
        return EXAMPLE_RESPONSES["شكر"]
    elif "مع السلامة" in msg or "وداع" in msg:
        return EXAMPLE_RESPONSES["وداع"]
    
    # ردود المنتجات
    elif "حديد" in msg:
        return f"{EXAMPLE_RESPONSES['استفسار عن منتج']} سعر الحديد {STEEL_PRICE}."
    elif "اسمنت" in msg:
        return f"{EXAMPLE_RESPONSES['استفسار عن منتج']} سعر الاسمنت {CEMENT_PRICE}."
    elif "سباك" in msg or "مواسير" in msg or "pvc" in msg:
        return f"{EXAMPLE_RESPONSES['استفسار عن منتج']} مواسير PVC {PLUMBING_PRICE}."
    elif "كهرب" in msg or "كابل" in msg or "سلك" in msg:
        return f"{EXAMPLE_RESPONSES['استفسار عن منتج']} كابلات كهرباء {ELECTRICITY_PRICE}."
    elif "خشب" in msg or "ابلكاش" in msg:
        return f"{EXAMPLE_RESPONSES['استفسار عن منتج']} خشب بناء {WOOD_PRICE}."
    
    # رد عام عند عدم الفهم (من الشخصية)
    else:
        return EXAMPLE_RESPONSES["عدم فهم"]

# ---------- مسارات التطبيق ----------
@app.route('/')
def index():
    return render_template_string(
        HTML_PAGE,
        company=COMPANY_NAME,
        bot_name=BOT_NAME,
        nationality=BOT_NATIONALITY,
        welcome=WELCOME_MSG
    )

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message', '').strip()
    if not user_msg:
        return jsonify({'response': 'الرجاء كتابة رسالة.'})
    reply = bot_reply(user_msg)
    return jsonify({'response': reply})

# ---------- تشغيل السيرفر ----------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
