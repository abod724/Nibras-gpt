<!-- ==================================================
   🤖 بوت خدمة العملاء العائم — جاهز للتركيب!
   انسخ هذا الكود كله وضعه قبل </body> في الموقع
================================================== -->
<style>
/* 🔵 زر البوت الدائري — ثابت في الزاوية */
.chat-bot-btn {
    position: fixed;
    bottom: 25px;
    right: 25px;  /* ✅ زاوية أسفل اليمين — الأكثر شيوعاً */
    width: 60px;
    height: 60px;
    border-radius: 50%;
    background: #2563eb;
    color: white;
    border: none;
    font-size: 28px;
    cursor: pointer;
    box-shadow: 0 4px 15px rgba(37,99,235,0.4);
    z-index: 9999;  /* ✅ يطلع فوق كل شيء */
    transition: 0.3s;
}
.chat-bot-btn:hover { transform: scale(1.1); }

/* 💬 نافذة المحادثة — مخفية افتراضياً */
.chat-bot-box {
    position: fixed;
    bottom: 100px;
    right: 25px;
    width: 360px;
    height: 500px;
    background: white;
    border-radius: 16px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.15);
    display: none;
    flex-direction: column;
    z-index: 9998;
    overflow: hidden;
}
.chat-bot-box.open { display: flex; }

/* 🎨 تصميم الداخل */
.chat-bot-header {
    background: #2563eb;
    color: white;
    padding: 15px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.chat-bot-header button {
    background: none; border: none; color: white;
    font-size: 20px; cursor: pointer;
}
.chat-bot-messages {
    flex: 1; padding: 15px; overflow-y: auto; background: #f8fafc;
}
.chat-bot-msg {
    margin-bottom: 10px; padding: 10px 14px; border-radius: 16px;
    max-width: 80%; line-height: 1.5;
}
.chat-bot-msg.user {
    background: #2563eb; color: white; margin-left: auto;
}
.chat-bot-msg.bot {
    background: #e2e8f0; color: #1e293b; margin-right: auto;
}
.chat-bot-input {
    display: flex; padding: 12px; border-top: 1px solid #eee; gap: 8px;
}
.chat-bot-input input {
    flex: 1; padding: 10px 15px; border: 1px solid #ddd;
    border-radius: 20px; outline: none;
}
.chat-bot-input button {
    background: #2563eb; color: white; border: none;
    padding: 10px 16px; border-radius: 20px; cursor: pointer;
}

/* 📱 للجوال */
@media (max-width: 480px) {
    .chat-bot-box { width: 100%; height: 100vh; bottom: 0; right: 0; border-radius: 0; }
}
</style>

<!-- 🔘 الزر -->
<button class="chat-bot-btn" id="chatBotBtn">💬</button>

<!-- 💬 نافذة المحادثة -->
<div class="chat-bot-box" id="chatBotBox">
    <div class="chat-bot-header">
        <span>خدمة العملاء</span>
        <button id="chatBotClose">✕</button>
    </div>
    <div class="chat-bot-messages" id="chatBotMessages">
        <div class="chat-bot-msg bot">أهلاً بك! كيف نقدر نساعدك؟ 😊</div>
    </div>
    <div class="chat-bot-input">
        <input type="text" id="chatBotInput" placeholder="اكتب رسالتك...">
        <button id="chatBotSend">إرسال</button>
    </div>
</div>

<script>
// 🧠 فتح وإغلاق
const btn = document.getElementById('chatBotBtn');
const box = document.getElementById('chatBotBox');
const close = document.getElementById('chatBotClose');
const input = document.getElementById('chatBotInput');
const send = document.getElementById('chatBotSend');
const messages = document.getElementById('chatBotMessages');

btn.addEventListener('click', () => box.classList.toggle('open'));
close.addEventListener('click', () => box.classList.remove('open'));

// 📨 إرسال الرسائل
function addMsg(text, isUser) {
    const div = document.createElement('div');
    div.className = `chat-bot-msg ${isUser ? 'user' : 'bot'}`;
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
}

function sendMsg() {
    const text = input.value.trim();
    if (!text) return;
    addMsg(text, true);
    input.value = '';
    
    // ✅ هنا تضع ردود العميل — عدلها زي ما يبي!
    setTimeout(() => {
        let reply = 'شكراً لتواصلك معنا! سنتواصل معك قريباً 📩';
        if (text.includes('سعر')) reply = 'الأسعار تختلف حسب الخدمة، تواصل معنا لتفاصيل دقيقة 📞';
        if (text.includes('دوام') || text.includes('ساعات')) reply = 'دوامنا من 8 صباحاً إلى 6 مساءً 🕐';
        if (text.includes('موقع') || text.includes('عنوان')) reply = 'نحن في مدينة الرياض 📍 شارع الملك فهد';
        addMsg(reply, false);
    }, 600);
}

send.addEventListener('click', sendMsg);
input.addEventListener('keydown', (e) => e.key === 'Enter' && sendMsg());
</script>
<!-- ============== نهاية الكود ============== -->
