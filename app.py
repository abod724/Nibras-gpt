from flask import Flask, request, jsonify, render_template_string
import random
import os

app = Flask(__name__)

# ==========================================================
# 📂 قاعدة بيانات الردود — هنا تضيف وتعدل كل شيء بسهولة
# ==========================================================
# ملاحظة: كل قسم له "كلمات مفتاحية" و "ردود"
# هذا أسهل وأوضح طريقة لتنظيم البيانات — تعلمها!

DATABASE = {
    # 👋 التحيات
    "تحية": {
        "keywords": ["السلام", "هلا", "مرحبا", "أهلا", "مساء", "صباح"],
        "replies": [
            "وعليكم السلام ورحمة الله! نورتنا 😊 كيف نقدر نخدمك؟",
            "أهلاً وسهلاً! تفضل، ما عندك أمر؟",
            "السلام عليكم! شرفتنا، حدد طلبك من فضلك."
        ]
    },

    # 🙏 الشكر والوداع
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

    # 🏛️ الخدمات الحكومية
    "حكومي": {
        "keywords": [
            "جواز", "سفر", "إقامة", "مرور", "رخصة", "بلدية", "أمانة",
            "تأمينات", "وزارة", "أبشر", "منصة", "إصدار", "تجديد"
        ],
        "replies": [
            "الخدمات الحكومية متاحة عبر منصة أبشر والمنصات الرسمية 📋 حدد لي الخدمة بالضبط وأوجهك للطريق الصحيح.",
            "معظم الخدمات الحكومية تتم إلكترونياً الآن. اذكر لي اسم الخدمة وأفيدك بالتفاصيل ✅"
        ]
    },

    # 💼 المؤسسات والشركات
    "مؤسسات": {
        "keywords": [
            "سجل تجاري", "مؤسسة", "شركة", "ترخيص", "ملف", "زكاة",
            "ضريبة", "هيئة", "استثمار", "تأسيس", "تجديد سجل"
        ],
        "replies": [
            "للخدمات التجارية والمؤسسية: تأكد من منصة السجل التجاري والزكاة والضريبة 📊 حدد طلبك بالتفصيل من فضلك.",
            "الخدمات المؤسسية عبر منصة وزارة التجارة والزكاة والدخل. اذكر نوع طلبك وأوجهك للرابط المباشر 🔗"
        ]
    },

    # 👤 خدمات الأفراد والدعم
    "أفراد": {
        "keywords": [
            "دعم", "حساب مواطن", "ضمان", "معاش", "تأمين اجتماعي",
            "قرض", "تمويل", "مساعدة", "إعانة", "سكني", "زكاة الفرد"
        ],
        "replies": [
            "للخدمات الفردية والاجتماعية — تختلف التفاصيل حسب البرنامج 💙 اذكر لي اسم البرنامج بالضبط وأعطيك كل التفاصيل.",
            "الخدمات الاجتماعية كثيرة (حساب مواطن، ضمان، سكني…). حدد لي اللي تبيه وأفيدك فوراً ✅"
        ]
    },

    # 🏗️ مواد البناء والمقاولات
    "بناء": {
        "keywords": [
            "حديد", "اسمنت", "أسمنت", "سباك", "مواسير", "كهرب", "كابل",
            "سلك", "خشب", "طوب", "رمل", "بلوك", "مواد بناء"
        ],
        "replies": {
            "حديد": "سعر الحديد حالياً يتراوح بين ٣٦٠٠ و ٣٧٥٠ ريال للطن 🏗️ كم طن تحتاج؟",
            "اسمنت": "سعر كيس الأسمنت ١٤ ريال 🧱 الكمية بكم؟",
            "سباك": "مواسير PVC وجميع مستلزمات السباكة متوفرة 💧 حدد القطر والكمية من فضلك.",
            "كهرب": "الكابلات والأسلاك متوفرة بأنواعها ⚡ حدد النوع والمقاس.",
            "خشب": "جميع أنواع الأخشاب متوفرة 🌲 اذكر النوع والمقاسات.",
            "افتراضي": "جميع مواد البناء متوفرة 📦 حدد النوع والكمية وأعطيك السعر فوراً."
        }
    },

    # 📞 المساعدة العامة
    "مساعدة": {
        "keywords": ["مساعدة", "ماذا عندكم", "خدماتكم", "استفسار", "كيف"],
        "replies": [
            "نقدم خدمات في هذه المجالات — حدد ما تريد:\n🏛️ حكومي | 💼 مؤسسات | 👤 أفراد | 🏗️ مواد بناء",
            "يمكنني مساعدتك في:\n✅ الخدمات الحكومية\n✅ الأعمال والمؤسسات\n✅ الدعم والخدمات الاجتماعية\n✅ مواد البناء\n\nاكتب لي طلبك مباشرة 😊"
        ]
    }
}

# ==========================================================
# 🧠 دالة الرد الذكي — هنا تتم المعالجة
# ==========================================================
def get_bot_response(user_message):
    """
    دالة استلام الرسالة والبحث عن الرد المناسب
    هذه الطريقة منظمة جداً وتسهل عليك التوسيع لاحقاً
    """
    # نحول الرسالة لأحرف صغيرة عشان المقارنة تكون دقيقة
    msg = user_message.lower().strip()

    # 🔁 نمر على كل قسم في قاعدة البيانات
    for category, data in DATABASE.items():
        # نتحقق هل كلمة من كلمات القسم موجودة في رسالة المستخدم
        if any(keyword in msg for keyword in data["keywords"]):
            
            # ✅ الحالة الأولى: الرد قاموس (مثل مواد البناء — كل منتج له سعر خاص)
            if isinstance(data["replies"], dict):
                # نبحث عن اسم المنتج بالضبط
                for product, reply_text in data["replies"].items():
                    if product in msg and product != "افتراضي":
                        return reply_text
                # لو ماوجدنا نرد بالافتراضي
                return data["replies"]["افتراضي"]
            
            # ✅ الحالة الثانية: الرد قائمة — نختار رد عشوائي
            else:
                return random.choice(data["replies"])

    # ❌ لو ماوجدنا أي تطابق — نعرض المساعدة
    return "عذراً 😅 لم أفهم طلبك بالضبط! الرجاء التحديد:\n🏛️ حكومي | 💼 مؤسسات | 👤 أفراد | 🏗️ بناء\nأو اكتب 'مساعدة' لعرض الخدمات."

# ==========================================================
# 🎨 واجهة المستخدم — جاهزة ومتجاوبة مع الجوال
# ==========================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>خدمة العملاء — مساعدك الشامل</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, sans-serif;
        }
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .chat-container {
            width: 100%;
            max-width: 420px;
            background: #ffffff;
            border-radius: 24px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            height: 85vh;
            max-height: 750px;
        }
        .chat-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        .chat-header h2 {
            font-size: 18px;
            margin-bottom: 4px;
        }
        .chat-header p {
            font-size: 13px;
            opacity: 0.9;
        }
        .chat-messages {
            flex: 1;
            padding: 20px;
            overflow-y: auto;
            background: #f8f9fa;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        .msg {
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 18px;
            line-height: 1.5;
            font-size: 15px;
            white-space: pre-wrap;
        }
        .msg.user {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            align-self: flex-end;
            border-bottom-right-radius: 6px;
        }
        .msg.bot {
            background: #ffffff;
            color: #333;
            align-self: flex-start;
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
            border-bottom-left-radius: 6px;
        }
        .msg.typing {
            background: #e9ecef;
            color: #6c757d;
            font-size: 14px;
        }
        .time {
            font-size: 10px;
            opacity: 0.6;
            margin-top: 6px;
            text-align: right;
        }
        .chat-input-area {
            padding: 16px;
            background: white;
            border-top: 1px solid #eee;
            display: flex;
            gap: 10px;
            align-items: center;
        }
        .chat-input-area input {
            flex: 1;
            padding: 14px 20px;
            border: 2px solid #e9ecef;
            border-radius: 30px;
            font-size: 15px;
            outline: none;
            transition: border-color 0.3s;
        }
        .chat-input-area input:focus {
            border-color: #667eea;
        }
        .chat-input-area button {
            width: 46px;
            height: 46px;
            border-radius: 50%;
            border: none;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 20px;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .chat-input-area button:active {
            transform: scale(0.95);
        }
        @media (max-width: 480px) {
            body { padding: 0; }
            .chat-container { height: 100vh; max-height: 100vh; border-radius: 0; }
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <h2>🤖 مساعدك الشامل</h2>
            <p>حكومي • مؤسسات • أفراد • بناء</p>
        </div>
        
        <div class="chat-messages" id="messages">
            <div class="msg bot">أهلاً وسهلاً! 👋 أنا مساعدك الشامل. اكتب لي طلبك أو اكتب "مساعدة" لعرض الخدمات.</div>
        </div>
        
        <div class="chat-input-area">
            <input type="text" id="userInput" placeholder="اكتب طلبك هنا…" onkeydown="if(event.key === 'Enter') sendMessage()">
            <button onclick="sendMessage()">➤</button>
        </div>
    </div>

    <script>
        let isBusy = false;

        function addMessage(text, isUser) {
            const container = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = `msg ${isUser ? 'user' : 'bot'}`;
            
            const time = new Date().toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' });
            div.innerHTML = text + `<div class="time">${time}</div>`;
            
            container.appendChild(div);
            container.scrollTop = container.scrollHeight;
        }

        async function sendMessage() {
            if (isBusy) return;
            
            const input = document.getElementById('userInput');
            const message = input.value.trim();
            if (!message) return;

            // إضافة رسالة المستخدم
            addMessage(message, true);
            input.value = '';
            isBusy = true;

            // مؤشر الكتابة
            const container = document.getElementById('messages');
            const typing = document.createElement('div');
            typing.className = 'msg bot typing';
            typing.textContent = '⌛ جاري التفكير...';
            container.appendChild(typing);
            container.scrollTop = container.scrollHeight;

            // إرسال للخادم
            try {
                const response = await fetch('/get-response', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: message })
                });
                
                const data = await response.json();
                typing.remove();
                addMessage(data.reply, false);
                
            } catch (error) {
                typing.remove();
                addMessage('⚠️ حدث خطأ، حاول مرة أخرى.', false);
            }

            isBusy = false;
            input.focus();
        }
    </script>
</body>
</html>
"""

# ==========================================================
# 🌐 المسارات — ربط الواجهة بالمنطق
# ==========================================================
@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/get-response', methods=['POST'])
def get_response():
    data = request.get_json()
    user_msg = data.get('message', '').strip()
    
    if not user_msg:
        return jsonify({'reply': '⚠️ الرجاء كتابة رسالة!'})
    
    bot_reply_text = get_bot_response(user_msg)
    return jsonify({'reply': bot_reply_text})

# ==========================================================
# 🚀 تشغيل التطبيق
# ==========================================================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("✅ التطبيق يعمل! افتح الرابط: http://localhost:5000")
    app.run(host='0.0.0.0', port=port, debug=True)
