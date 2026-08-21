from flask import Flask, request, jsonify, render_template_string
import random
import os

app = Flask(__name__)

# ==========================================================
# 📂 قاعدة بيانات الردود — كل شيء هنا تعدله بسهولة
# ==========================================================
DATABASE = {
    "تحية": {
        "keywords": ["السلام", "هلا", "مرحبا", "أهلا", "مساء", "صباح"],
        "replies": [
            "وعليكم السلام ورحمة الله! نورتنا 😊 كيف نقدر نخدمك؟",
            "أهلاً وسهلاً! تفضل، ما عندك أمر؟",
            "السلام عليكم! شرفتنا، حدد طلبك من فضلك."
        ]
    },
    "شكر": {
        "keywords": ["شكر", "مشكور", "تسلم", "يعطيك العافية"],
        "replies": [
            "العفو! في خدمتك دائماً 💙",
            "تحت أمرك! هل فيه شيء ثاني؟",
            "ما عليك زود، نحن هنا لخدمتك."
        ]
    },
    "وداع": {
        "keywords": ["وداع", "مع السلامة", "باي", "أشوفك"],
        "replies": [
            "مع السلامة! في أمان الله 🙏",
            "وداعاً، نتمنى نراك قريباً 😊",
            "في حفظ الله، تواصل معنا في أي وقت!"
        ]
    },
    "حكومي": {
        "keywords": ["جواز", "سفر", "إقامة", "مرور", "رخصة", "بلدية", "أمانة", "تأمينات", "وزارة", "أبشر"],
        "replies": [
            "الخدمات الحكومية متاحة عبر منصة أبشر والمنصات الرسمية 📋 حدد لي الخدمة بالضبط وأوجهك للطريق الصحيح.",
            "معظم الخدمات الحكومية تتم إلكترونياً الآن. اذكر لي اسم الخدمة وأفيدك بالتفاصيل ✅"
        ]
    },
    "مؤسسات": {
        "keywords": ["سجل تجاري", "مؤسسة", "شركة", "ترخيص", "زكاة", "ضريبة", "تأسيس"],
        "replies": [
            "للخدمات التجارية والمؤسسية: تأكد من منصة السجل التجاري والزكاة والضريبة 📊 حدد طلبك بالتفصيل.",
            "الخدمات المؤسسية عبر منصة وزارة التجارة. اذكر نوع طلبك وأوجهك للرابط المباشر 🔗"
        ]
    },
    "أفراد": {
        "keywords": ["دعم", "حساب مواطن", "ضمان", "معاش", "قرض", "تمويل", "سكني"],
        "replies": [
            "للخدمات الفردية والاجتماعية 💙 اذكر لي اسم البرنامج بالضبط وأعطيك كل التفاصيل.",
            "الخدمات الاجتماعية كثيرة (حساب مواطن، ضمان، سكني…). حدد لي اللي تبيه وأفيدك فوراً ✅"
        ]
    },
    "بناء": {
        "keywords": ["حديد", "اسمنت", "سباك", "كهرب", "خشب", "مواد بناء"],
        "replies": {
            "حديد": "سعر الحديد حالياً ٣٦٠٠-٣٧٥٠ ريال للطن 🏗️ كم طن تحتاج؟",
            "اسمنت": "سعر كيس الأسمنت ١٤ ريال 🧱 الكمية بكم؟",
            "سباك": "مواسير وجميع مستلزمات السباكة متوفرة 💧 حدد القطر والكمية.",
            "كهرب": "الكابلات والأسلاك متوفرة بأنواعها ⚡ حدد النوع والمقاس.",
            "خشب": "جميع أنواع الأخشاب متوفرة 🌲 اذكر النوع والمقاسات.",
            "افتراضي": "جميع مواد البناء متوفرة 📦 حدد النوع والكمية وأعطيك السعر فوراً."
        }
    },
    "مساعدة": {
        "keywords": ["مساعدة", "ماذا عندكم", "خدماتكم", "كيف"],
        "replies": [
            "نقدم خدمات في هذه المجالات — حدد ما تريد:\n🏛️ حكومي | 💼 مؤسسات | 👤 أفراد | 🏗️ مواد بناء",
            "يمكنني مساعدتك في:\n✅ الخدمات الحكومية\n✅ الأعمال والمؤسسات\n✅ الدعم والخدمات الاجتماعية\n✅ مواد البناء\n\nاكتب لي طلبك مباشرة 😊"
        ]
    }
}

# ==========================================================
# 🧠 دالة الرد الذكي
# ==========================================================
def get_bot_response(user_message):
    msg = user_message.lower().strip()
    for category, data in DATABASE.items():
        if any(keyword in msg for keyword in data["keywords"]):
            if isinstance(data["replies"], dict):
                for product, reply_text in data["replies"].items():
                    if product in msg and product != "افتراضي":
                        return reply_text
                return data["replies"]["افتراضي"]
            else:
                return random.choice(data["replies"])
    return "عذراً 😅 لم أفهم طلبك! الرجاء التحديد:\n🏛️ حكومي | 💼 مؤسسات | 👤 أفراد | 🏗️ بناء\nأو اكتب 'مساعدة'."

# ==========================================================
# 🎨 الصفحة الرئيسية + البوت العائم
# ==========================================================
HTML_PAGE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>موقع تجريبي — بوت عائم</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', Tahoma, sans-serif; }
        
        /* ===== محتوى الموقع العادي ===== */
        body { background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); min-height: 200vh; }
        .page-content { padding: 40px 20px; max-width: 900px; margin: 0 auto; }
        h1 { color: #1e40af; font-size: 32px; margin-bottom: 15px; }
        .card { background: white; padding: 25px; border-radius: 16px; box-shadow: 0 4px 20px rgba(0,0,0,0.05); margin-bottom: 20px; }
        p { color: #475569; font-size: 17px; line-height: 1.8; margin-bottom: 10px; }
        
        /* ==============================================
           🤖 البوت العائم — هنا كل السحر!
           ============================================== */
        
        /* 🔘 زر البوت الدائري الثابت في الزاوية */
        .chat-toggle-btn {
            position: fixed;  /* ✅ يبقى ثابت دائماً — سر البوت! */
            bottom: 25px;
            left: 25px;
            width: 65px;
            height: 65px;
            border-radius: 50%;
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: white;
            border: none;
            font-size: 30px;
            cursor: pointer;
            box-shadow: 0 4px 20px rgba(37, 99, 235, 0.4);
            z-index: 9999;  /* ✅ يطلع فوق كل شيء */
            transition: all 0.3s ease;
        }
        .chat-toggle-btn:hover { transform: scale(1.15); }
        
        /* 💬 مربع المحادثة — مخفي افتراضياً */
        .chat-box {
            position: fixed;
            bottom: 105px;
            left: 25px;
            width: 380px;
            max-width: 92vw;
            height: 520px;
            max-height: 80vh;
            background: white;
            border-radius: 18px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            display: none;  /* ✅ مخفي */
            flex-direction: column;
            z-index: 9998;
            overflow: hidden;
            animation: slideUp 0.3s ease;
        }
        .chat-box.open { display: flex; }  /* ✅ يظهر لما نضغط */
        
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* 🎨 رأس المحادثة */
        .chat-header {
            background: linear-gradient(135deg, #2563eb, #1d4ed8);
            color: white;
            padding: 16px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .chat-header h3 { font-size: 16px; }
        .chat-header button {
            background: none;
            border: none;
            color: white;
            font-size: 22px;
            cursor: pointer;
            opacity: 0.8;
        }
        .chat-header button:hover { opacity: 1; }
        
        /* 💬 منطقة الرسائل */
        .chat-messages {
            flex: 1;
            padding: 16px;
            overflow-y: auto;
            background: #f8fafc;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .msg {
            max-width: 82%;
            padding: 12px 16px;
            border-radius: 18px;
            line-height: 1.5;
            font-size: 15px;
            white-space: pre-wrap;
        }
        .msg.user {
            background: #2563eb;
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 6px;
        }
        .msg.bot {
            background: white;
            color: #1e293b;
            align-self: flex-start;
            border-bottom-left-radius: 6px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .msg.typing {
            background: #e2e8f0;
            color: #64748b;
            font-size: 14px;
        }
        
        /* ⌨️ منطقة الإدخال */
        .chat-input-area {
            padding: 14px;
            background: white;
            border-top: 1px solid #e2e8f0;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .chat-input-area input {
            flex: 1;
            padding: 12px 18px;
            border: 2px solid #e2e8f0;
            border-radius: 25px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s;
        }
        .chat-input-area input:focus { border-color: #2563eb; }
        .chat-input-area button {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            border: none;
            background: #2563eb;
            color: white;
            font-size: 18px;
            cursor: pointer;
        }
        
        /* 📱 للجوال */
        @media (max-width: 480px) {
            .chat-box {
                width: 100%;
                height: 100vh;
                bottom: 0;
                left: 0;
                max-height: 100vh;
                border-radius: 0;
            }
            .chat-toggle-btn { bottom: 20px; left: 20px; }
        }
    </style>
</head>
<body>

    <!-- ===== محتوى الصفحة الرئيسية ===== -->
    <div class="page-content">
        <h1>🇸🇦 منصة الخدمات الشاملة</h1>
        <div class="card">
            <p>مرحباً بك في منصتنا الإلكترونية 🤝</p>
            <p>نقدم لك جميع الخدمات في مكان واحد — خدمات حكومية، تجارية، فردية، ومواد بناء.</p>
            <p>📌 لاحظ الزر في الزاوية اليسرى السفلية ⬇️ — هذا بوت الخدمات الذكي! اضغط عليه وتحدث معه 😊</p>
        </div>
        <div class="card">
            <p>🔄 اسحب الصفحة للأسفل ولاحظ أن زر البوت يبقى ثابتاً في مكانه — مهما تحركت الصفحة!</p>
            <p>هذه خاصية <code>position: fixed</code> اللي تعلمنا عنها ✅</p>
        </div>
        <div class="card">
            <p>🏛️ خدمات حكومية: جوازات، إقامة، مرور، بلدية...</p>
            <p>💼 مؤسسات: سجل تجاري، تراخيص، زكاة وضريبة...</p>
            <p>👤 أفراد: دعم، حساب مواطن، قروض...</p>
            <p>🏗️ بناء: حديد، أسمنت، كهرباء، سباكة...</p>
        </div>
        <div class="card">
            <p>👇 استمر بالسحب للأسفل...</p>
            <p style="height: 300px;">المزيد من محتوى الموقع...</p>
            <p>✅ شفت؟ البوت ما تحرك! يبقى ثابت دائماً في الزاوية.</p>
        </div>
    </div>

    <!-- ==============================================
         🤖 البوت العائم — يظهر في كل الصفحة!
         ============================================== -->
    
    <!-- 🔘 زر الفتح والإغلاق -->
    <button class="chat-toggle-btn" id="chatToggle">💬</button>
    
    <!-- 💬 نافذة المحادثة -->
    <div class="chat-box" id="chatBox">
        <div class="chat-header">
            <h3>🤖 مساعد الخدمات</h3>
            <button id="closeChat">✕</button>
        </div>
        <div class="chat-messages" id="chatMessages">
            <div class="msg bot">أهلاً وسهلاً! 👋 أنا مساعدك الذكي. اكتب لي طلبك أو اكتب "مساعدة" لعرض الخدمات.</div>
        </div>
        <div class="chat-input-area">
            <input type="text" id="chatInput" placeholder="اكتب رسالتك هنا...">
            <button id="sendBtn">➤</button>
        </div>
    </div>

    <script>
        // 🧠 فتح وإغلاق البوت
        const toggleBtn = document.getElementById('chatToggle');
        const chatBox = document.getElementById('chatBox');
        const closeBtn = document.getElementById('closeChat');
        
        toggleBtn.addEventListener('click', () => {
            chatBox.classList.toggle('open');
        });
        closeBtn.addEventListener('click', () => {
            chatBox.classList.remove('open');
        });

        // 📨 إرسال الرسائل
        const input = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendBtn');
        const messages = document.getElementById('chatMessages');
        let isBusy = false;

        function addMessage(text, isUser) {
            const div = document.createElement('div');
            div.className = `msg ${isUser ? 'user' : 'bot'}`;
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        async function sendMessage() {
            if (isBusy) return;
            const text = input.value.trim();
            if (!text) return;
            
            addMessage(text, true);
            input.value = '';
            isBusy = true;

            // مؤشر الكتابة
            const typing = document.createElement('div');
            typing.className = 'msg typing bot';
            typing.textContent = '⌛ جاري التفكير...';
            messages.appendChild(typing);
            messages.scrollTop = messages.scrollHeight;

            // إرسال للخادم
            try {
                const res = await fetch('/get-reply', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text })
                });
                const data = await res.json();
                typing.remove();
                addMessage(data.reply, false);
            } catch (err) {
                typing.remove();
                addMessage('⚠️ حدث خطأ، حاول مرة أخرى.', false);
            }

            isBusy = false;
            input.focus();
        }

        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keydown', (e) => e.key === 'Enter' && sendMessage());
    </script>

</body>
</html>
"""

# ==========================================================
# 🌐 المسارات
# ==========================================================
@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

@app.route('/get-reply', methods=['POST'])
def get_reply():
    data = request.get_json()
    user_msg = data.get('message', '').strip()
    if not user_msg:
        return jsonify({'reply': '⚠️ الرجاء كتابة رسالة!'})
    return jsonify({'reply': get_bot_response(user_msg)})

# ==========================================================
# 🚀 تشغيل
# ==========================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("✅ البوت العائم جاهز! افتح الرابط: http://localhost:5000")
    app.run(host='0.0.0.0', port=port, debug=True)
