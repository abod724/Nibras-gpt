from flask import Flask, request, jsonify, render_template_string
import random, os
from personality import EXAMPLE_RESPONSES

app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>خدمة العملاء</title>
<style>
body {font-family:Arial; background:#f5f7fa; display:flex; justify-content:center; align-items:center; height:100vh; margin:0;}
.chat-box {width:400px; max-width:100%; background:white; border-radius:16px; padding:20px; box-shadow:0 4px 12px rgba(0,0,0,0.1);}
.header {text-align:center; border-bottom:2px solid #e2e8f0; padding-bottom:10px; margin-bottom:15px;}
.header h3 {margin:0; color:#1e293b; font-size:18px;}
.messages {height:400px; overflow-y:auto; padding:5px 0; display:flex; flex-direction:column; gap:8px;}
.user-msg {background:#2563eb; color:white; padding:10px 14px; border-radius:16px; align-self:flex-end; max-width:85%;}
.bot-msg {background:#f1f5f9; color:#1e293b; padding:10px 14px; border-radius:16px; align-self:flex-start; max-width:85%;}
.input-area {margin-top:12px;}
.input-area input {width:100%; padding:12px; border:2px solid #e2e8f0; border-radius:30px; outline:none; font-size:15px; box-sizing:border-box;}
.input-area input:focus {border-color:#2563eb;}
.timestamp {font-size:10px; opacity:0.6; margin-top:4px;}
</style>
</head>
<body>
<div class="chat-box">
<div class="header"><h3>🛒 خدمة العملاء</h3></div>
<div class="messages" id="msgArea"><div class="bot-msg">👋 أهلاً! كيف نقدر نساعدك؟</div></div>
<div class="input-area"><input type="text" id="userInput" placeholder="اكتب استفسارك..." oninput="sendMsg()"></div>
</div>
<script>
let lastMsg = "";
async function sendMsg() {
const input = document.getElementById('userInput');
const msg = input.value.trim();
if (!msg || msg === lastMsg) return;
lastMsg = msg;
addMsg(msg, 'user-msg');
input.value = '';
input.disabled = true;
const typing = document.createElement('div');
typing.className = 'bot-msg';
typing.id = 'typing';
typing.innerHTML = '⏳ جاري الرد...';
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
function addMsg(text, cls) {
const area = document.getElementById('msgArea');
const d = document.createElement('div');
d.className = cls;
d.innerHTML = text + '<div class="timestamp">' + new Date().toLocaleTimeString('ar-SA', {hour:'2-digit', minute:'2-digit'}) + '</div>';
area.appendChild(d);
area.scrollTop = area.scrollHeight;
}
</script>
</body>
</html>
"""

def bot_reply(msg):
    m = msg.lower()
    if any(w in m for w in ["السلام","هلا","مرحب"]):
        return random.choice([EXAMPLE_RESPONSES["ترحيب"], "وعليكم السلام! كيف نخدمك؟"])
    elif "شكر" in m:
        return random.choice([EXAMPLE_RESPONSES["شكر"], "العفو، تحت أمرك."])
    elif any(w in m for w in ["وداع","مع السلامة"]):
        return random.choice([EXAMPLE_RESPONSES["وداع"], "مع السلامة، في خدمتك."])
    elif "حديد" in m:
        return "سعر الحديد ٣٦٠٠-٣٧٥٠ ريال للطن. كم تريد؟"
    elif "اسمنت" in m:
        return "سعر الاسمنت ١٤ ريال للكيس. كم كيس؟"
    elif any(w in m for w in ["سباك","مواسير","pvc"]):
        return "مواسير PVC متوفرة. أرسل القطر والكمية."
    elif any(w in m for w in ["كهرب","كابل","سلك"]):
        return "الكابلات متوفرة. حدد النوع والقطر."
    elif "خشب" in m:
        return "الخشب متوفر. أخبرنا بالنوع والمقاسات."
    else:
        return random.choice([EXAMPLE_RESPONSES["عدم فهم"], "ما فهمت، اذكر المنتج (حديد، اسمنت، سباكة، كهرباء، خشب)."])

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/chat', methods=['POST'])
def chat():
    msg = request.json.get('message', '').strip()
    return jsonify({'response': bot_reply(msg) if msg else 'الرجاء كتابة رسالة.'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
