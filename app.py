# ====================================================
# ملف app.py - بوت خدمة عملاء مواد البناء (نسخة شاملة)
# ====================================================

import os
import secrets
import random
from flask import Flask, request, jsonify, render_template_string

# ------------------ تهيئة التطبيق ------------------
app = Flask(__name__)
# توليد مفتاح سري تلقائياً (يعمل بدون الحاجة لإضافته في ريندر)
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# متغيرات بيئية اختيارية (كلها لها قيم افتراضية)
DEBUG_MODE = os.environ.get('DEBUG', 'False').lower() == 'true'
COMPANY_NAME = os.environ.get('COMPANY_NAME', 'مؤسسة البناء المتين')

# ------------------ واجهة المستخدم (HTML مضمن) ------------------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>مساعد مواد البناء</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI',sans-serif; }
        body { background:#f0f2f5; display:flex; justify-content:center; align-items:center; height:100vh; }
        .chat-container { width:420px; max-width:100%; height:700px; background:white; border-radius:28px; box-shadow:0 15px 40px rgba(0,0,0,0.2); display:flex; flex-direction:column; overflow:hidden; }
        .chat-header { background:#1a2a3a; color:white; padding:18px 20px; display:flex; align-items:center; gap:12px; border-bottom:3px solid #f39c12; }
        .chat-header i { font-size:28px; color:#f39c12; }
        .chat-header .info h3 { font-size:18px; }
        .chat-header .info p { font-size:12px; opacity:0.8; }
        .chat-header .status { margin-right:auto; background:#2ecc71; padding:4px 12px; border-radius:30px; font-size:11px; font-weight:bold; }
        .chat-messages { flex:1; padding:18px 15px; overflow-y:auto; background:#f8fafc; display:flex; flex-direction:column; gap:8px; }
        .message { max-width:80%; padding:12px 16px; border-radius:18px; font-size:15px; line-height:1.6; word-wrap:break-word; animation:fadeIn 0.3s ease; }
        .message.user { background:#1a2a3a; color:white; align-self:flex-end; border-bottom-left-radius:4px; }
        .message.bot { background:#e9edf2; color:#1e2a36; align-self:flex-start; border-bottom-right-radius:4px; }
        .timestamp { font-size:10px; opacity:0.5; margin-top:3px; text-align:left; }
        @keyframes fadeIn { from { opacity:0; transform:translateY(10px); } to { opacity:1; transform:translateY(0); } }
        .chat-input { background:white; padding:12px 18px; border-top:1px solid #ddd; display:flex; gap:10px; }
        .chat-input input { flex:1; padding:12px 16px; border:2px solid #e2e8f0; border-radius:50px; outline:none; font-size:15px; background:#f1f5f9; }
        .chat-input input:focus { border-color:#f39c12; background:white; }
        .chat-input button { background:#f39c12; border:none; color:white; width:50px; height:50px; border-radius:50%; font-size:20px; cursor:pointer; }
        .chat-input button:hover { background:#d68910; }
        .quick-actions { display:flex; gap:8px; padding:5px 15px 10px 15px; background:white; flex-wrap:wrap; border-bottom:1px solid #f0f0f0; }
        .quick-actions button { background:#ecf0f3; border:1px solid #d0d7de; padding:6px 14px; border-radius:30px; font-size:13px; cursor:pointer; transition:0.2s; }
        .quick-actions button:hover { background:#f39c12; color:white; border-color:#f39c12; }
        .chat-messages::-webkit-scrollbar { width:5px; }
        .chat-messages::-webkit-scrollbar-thumb { background:#cbd5e1; border-radius:10px; }
    </style>
</head>
<body>
<div class="chat-container">
    <div class="chat-header">
        <i class="fas fa-hard-hat"></i>
        <div class="info"><h3>مساعد البناء الذكي</h3><p>{{ company }}</p></div>
        <span class="status"><i class="fas fa-circle" style="font-size:10px;"></i> متصل</span>
    </div>
    <div class="quick-actions">
        <button onclick="sendQuick('سعر الحديد اليوم')">⚙️ سعر الحديد</button>
        <button onclick="sendQuick('سعر الاسمنت')">🧱 سعر الاسمنت</button>
        <button onclick="sendQuick('مواسير سباكة')">🔧 سباكة</button>
        <button onclick="sendQuick('كابلات كهرباء')">⚡ كهرباء</button>
        <button onclick="sendQuick('خشب بناء')">🪵 خشب</button>
    </div>
    <div class="chat-messages" id="chatMessages">
        <div class="message bot"><i class="fas fa-robot"></i> أهلاً بك! 👋 اختر سؤالاً سريعاً أو اكتب استفسارك عن الأسعار والتوفر.<div class="timestamp">الآن</div></div>
    </div>
    <div class="chat-input">
        <input type="text" id="userInput" placeholder="اكتب استفسارك..." onkeydown="if(event.key==='Enter') sendMessage();">
        <button onclick="sendMessage()"><i class="fas fa-paper-plane"></i></button>
    </div>
</div>
<script>
    const messagesDiv = document.getElementById('chatMessages');
    const userInput = document.getElementById('userInput');
    function addMessage(text, sender) {
        const msgDiv = document.createElement('div');
        msgDiv.classList.add('message', sender);
        msgDiv.innerHTML = text;
        const time = new Date().toLocaleTimeString('ar-SA', { hour:'2-digit', minute:'2-digit' });
        const timeSpan = document.createElement('div');
        timeSpan.classList.add('timestamp');
        timeSpan.innerText = time;
        msgDiv.appendChild(timeSpan);
        messagesDiv.appendChild(msgDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    }
    async function getBotReply(userMsg) {
        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userMsg })
            });
            const data = await response.json();
            return data.response;
        } catch (error) {
            return '⚠️ عذراً، حدث خطأ في الاتصال. حاول مرة أخرى.';
        }
    }
    async function sendMessage() {
        const msg = userInput.value.trim();
        if (!msg) return;
        addMessage(msg, 'user');
        userInput.value = '';
        userInput.disabled = true;
        const typingDiv = document.createElement('div');
        typingDiv.classList.add('message', 'bot');
        typingDiv.id = 'typingIndicator';
        typingDiv.innerHTML = 'جاري التفكير <i class="fas fa-ellipsis-h"></i>';
        messagesDiv.appendChild(typingDiv);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
        const botReply = await getBotReply(msg);
        document.getElementById('typingIndicator')?.remove();
        addMessage(botReply, 'bot');
        userInput.disabled = false;
        userInput.focus();
    }
    function sendQuick(text) {
        userInput.value = text;
        sendMessage();
    }
    window.onload = () => userInput.focus();
</script>
</body>
</html>
"""

# ------------------ منطق البوت (مخصص لمواد البناء) ------------------
def get_bot_response(user_message):
    msg = user_message.strip().lower()
    
    # ردود ذكية حسب الكلمات المفتاحية
    if "سعر" in msg and ("حديد" in msg or "steel" in msg):
        return "🌩️ سعر طن الحديد اليوم يتراوح بين **٣٦٠٠ - ٣٧٥٠ ريال** حسب المصنع. هل تريد عرض سعر الجملة؟"
    
    elif "سعر" in msg and ("اسمنت" in msg or "cement" in msg):
        return "🧱 سعر كيس الأسمنت (٥٠ كجم) يبدأ من **١٤ ريال** للمشتريات الكبيرة. كم طن تحتاج؟"
    
    elif "سباكة" in msg or "pvc" in msg or "مواسير" in msg:
        return "🔧 نعم، عندنا جميع أقطار مواسير PVC واللدائن الصحية. أرسل القطر المطلوب وعدد القطع لحساب الخصم."
    
    elif "كهرباء" in msg or "سلك" in msg or "كابل" in msg:
        return "⚡ متوفر كابلات النحاس والسلك المعزول (سعودي ومستورد). هل تفضل النحاس أم الألمنيوم؟"
    
    elif "خشب" in msg or "ابلكاش" in msg or "أبلكاش" in msg:
        return "🪵 لدينا خشب زان وبامبو وأبلكاش مقاوم للرطوبة. السماكات المتوفرة: ٦مم، ١٢مم، ١٨مم."
    
    elif "شكرا" in msg or "تمام" in msg or "ok" in msg:
        return "🤝 عفواً، تحت أمرك! إذا احتجت عرض سعر مفصل، ارسل لي قائمة الكميات."
    
    elif "السلام" in msg or "هلا" in msg or "مرحب" in msg:
        return f"أهلاً وسهلاً بك في **{COMPANY_NAME}**! 🌟 أنا مساعدك الذكي. اسألني عن الأسعار أو التوفر أو الخصومات."
    
    else:
        # ردود عامة عند عدم التعرف على الطلب
        return random.choice([
            "📦 شكراً لتواصلك! هل تقصد الاستفسار عن الأسعار أم التوفر في المخزون؟",
            "🏗️ عذراً، أنا مخصص لخدمة عملاء مواد البناء. حدد المنتج (حديد، اسمنت، سباكة، كهرباء، خشب).",
            "🛠️ راسلني بالقائمة المطلوبة مع الكميات، وسأرد عليك بعرض سعر خلال دقائق.",
            "📞 إذا تفضلت بالتواصل المباشر، يمكننا تحويل طلبك لمندوب المبيعات."
        ])

# ------------------ مسارات التطبيق ------------------
@app.route('/')
def index():
    # تمرير اسم الشركة للقالب
    return render_template_string(HTML_TEMPLATE, company=COMPANY_NAME)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'response': 'الرجاء كتابة رسالة.'})
    
    bot_reply = get_bot_response(user_message)
    return jsonify({'response': bot_reply})

# ------------------ تشغيل السيرفر ------------------
if __name__ == '__main__':
    # المنفذ الذي يوفره ريندر أو 5000 افتراضياً
    port = int(os.environ.get('PORT', 5000))
    # تشغيل التطبيق (debug قابلة للتغيير عبر المتغير البيئي)
    app.run(host='0.0.0.0', port=port, debug=DEBUG_MODE)
