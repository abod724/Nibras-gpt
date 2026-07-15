from flask import Flask, request, render_template_string, jsonify
from openai import OpenAI
import os

app = Flask(__name__)

# ─── قراءة المفتاح من متغيرات البيئة ───
API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    raise Exception("❌ OPENAI_API_KEY غير موجود في متغيرات البيئة")

client = OpenAI(api_key=API_KEY)

# ─── واجهة HTML (مضمنة) ───
HTML_PAGE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نبراس</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #fff; color: #111; max-width: 700px; margin: 40px auto; padding: 0 20px; }
        .chat-box { border: 1px solid #ddd; border-radius: 12px; padding: 16px; height: 400px; overflow-y: auto; background: #f9f9f9; }
        .msg { margin: 8px 0; padding: 10px 14px; border-radius: 18px; max-width: 80%; }
        .user { background: #000; color: #fff; margin-left: auto; text-align: right; }
        .bot { background: #eaeaea; color: #000; margin-right: auto; }
        .input-area { display: flex; gap: 8px; margin-top: 12px; }
        .input-area input { flex: 1; padding: 12px; border-radius: 30px; border: 1px solid #ddd; }
        .input-area button { padding: 12px 24px; border-radius: 30px; background: #000; color: #fff; border: none; cursor: pointer; }
        .typing { color: #888; font-style: italic; }
    </style>
</head>
<body>
    <h1>💬 نبراس</h1>
    <div class="chat-box" id="chatBox">
        <div class="msg bot">مرحباً! أنا نبراس، كيف أساعدك؟</div>
    </div>
    <div class="input-area">
        <input type="text" id="userInput" placeholder="اكتب سؤالك...">
        <button onclick="sendMessage()">إرسال</button>
    </div>

    <script>
        async function sendMessage() {
            const input = document.getElementById('userInput');
            const msg = input.value.trim();
            if (!msg) return;

            const chatBox = document.getElementById('chatBox');
            chatBox.innerHTML += `<div class="msg user">${msg}</div>`;
            input.value = '';
            chatBox.scrollTop = chatBox.scrollHeight;

            const typing = document.createElement('div');
            typing.className = 'msg bot typing';
            typing.textContent = 'نبراس يكتب...';
            chatBox.appendChild(typing);
            chatBox.scrollTop = chatBox.scrollHeight;

            try {
                const res = await fetch('/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg })
                });
                const data = await res.json();
                typing.remove();
                chatBox.innerHTML += `<div class="msg bot">${data.reply}</div>`;
                chatBox.scrollTop = chatBox.scrollHeight;
            } catch (e) {
                typing.remove();
                chatBox.innerHTML += `<div class="msg bot">⚠️ خطأ في الاتصال</div>`;
            }
        }

        document.getElementById('userInput').addEventListener('keydown', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_PAGE)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "الرجاء كتابة رسالة"})
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "أنت نبراس، مساعد ذكي مختصر. أجب بجمل قصيرة."},
                {"role": "user", "content": user_message}
            ],
            max_tokens=200,
            temperature=0.3
        )
        return jsonify({"reply": response.choices[0].message.content})
    except Exception as e:
        return jsonify({"reply": f"⚠️ خطأ: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
