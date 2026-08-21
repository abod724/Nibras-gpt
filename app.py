# ================================================
# app.py - بوت تجريبي لخدمة العملاء
# (نسخة تعليمية، تقدر تطورها بعدين لتجارية)
# ================================================

from flask import Flask, request, jsonify, render_template_string
import random

# ---------- متغيرات البوت (غير القيم بين علامات الاقتباس) ----------
COMPANY_NAME = "متجر المواد"          # اسم شركتك أو متجرك
WELCOME_MSG = "أهلاً! اسألني عن المنتجات والأسعار 🛒"
DEFAULT_REPLIES = [
    "شكراً لتواصلك! هل تقصد منتج معين؟",
    "عندنا عدة أصناف. حدد النوع (حديد، اسمنت، سباكة، كهرباء).",
    "أرسل اسم المنتج وسأرد بالسعر والتوفر."
]

# ---------- الكود الأساسي للبوت ----------
app = Flask(__name__)

# واجهة HTML بسيطة جداً (مضمنة)
CHAT_UI = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>بوت خدمة العملاء</title>
    <style>
        body { font-family: Arial; background: #f4f4f4; display: flex; justify-content: center; padding: 20px; }
        .chat-box { width: 400px; max-width: 100%; background: white; border-radius: 16px; padding: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .messages { height: 400px; overflow-y: auto; border-bottom: 1px solid #ddd; padding-bottom: 10px; margin-bottom: 10px; }
        .user-msg { background: #007bff; color: white; padding: 10px; border-radius: 12px; margin: 5px 0; text-align: right; }
        .bot-msg { background: #e9ecef; color: black; padding: 10px; border-radius: 12px; margin: 5px 0; text-align: left; }
        input[type="text"] { width: 80%; padding: 8px; border-radius: 20px; border: 1px solid #ccc; }
        button { padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 20px; cursor: pointer; }
        .quick-btns { margin-top: 10px; display: flex; gap: 5px; flex-wrap: wrap; }
        .quick-btns button { background: #28a745; padding: 5px 10px; font-size: 12px; }
    </style>
</head>
<body>
<div class="chat-box">
    <h3>{{ company }}</h3>
    <div class="messages" id="msg-area">
        <div class="bot-msg">👋 {{ welcome }}</div>
    </div>
    <div>
        <input type="text" id="userInput" placeholder="اكتب رسالتك..." onkeydown="if(event.key=='Enter') sendMsg()">
        <button onclick="sendMsg()">إرسال</button>
    </div>
    <div class="quick-btns">
        <button onclick="quick('سعر الحديد')">حديد</button>
        <button onclick="quick('سعر الاسمنت')">اسمنت</button>
        <button onclick="quick('مواسير سباكة')">سباكة</button>
        <button onclick="quick('كابلات كهرباء')">كهرباء</button>
    </div>
</div>
<script>
    function addMsg(text, cls) {
        const area = document.getElementById('msg-area');
        const div = document.createElement('div');
        div.className = cls;
        div.textContent = text;
        area.appendChild(div);
        area.scrollTop = area.scrollHeight;
    }
    async function sendMsg() {
        const input = document.getElementById('userInput');
        const msg = input.value.trim();
        if (!msg) return;
        addMsg(msg, 'user-msg');
        input.value = '';
        const res = await fetch('/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: msg})
        });
        const data = await res.json();
        addMsg(data.response, 'bot-msg');
    }
    function quick(text) {
        document.getElementById('userInput').value = text;
        sendMsg();
    }
</script>
</body>
</html>
"""

# منطق ردود البوت (مبسط للتعلم)
def bot_reply(user_msg):
    msg = user_msg.lower()
    if "حديد" in msg:
        return "سعر طن الحديد ٣٦٠٠ - ٣٧٥٠ ريال."
    elif "اسمنت" in msg:
        return "سعر كيس الاسمنت ١٤ ريال (كميات كبيرة خصم)."
    elif "سباكة" in msg:
        return "متوفر مواسير PVC بجميع الأقطار."
    elif "كهرباء" in msg:
        return "كابلات نحاسية وألمنيوم بجودة عالية."
    else:
        return random.choice(DEFAULT_REPLIES)

@app.route('/')
def index():
    return render_template_string(CHAT_UI, company=COMPANY_NAME, welcome=WELCOME_MSG)

@app.route('/chat', methods=['POST'])
def chat():
    user_msg = request.json.get('message', '').strip()
    if not user_msg:
        return jsonify({'response': 'الرجاء كتابة رسالة.'})
    reply = bot_reply(user_msg)
    return jsonify({'response': reply})

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
