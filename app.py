from flask import Flask, request, jsonify
import os
from openai import OpenAI

app = Flask(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.post("/ask")
def ask_ai():
    data = request.json
    prompt = data["prompt"]

    keywords = [
        "من برمجك", "مين برمجك", "من سواك", "مين سواك",
        "من طورك", "مين طورك", "المبرمج", "من صممك",
        "من صنعك", "مين صنعك", "من جهزك"
    ]
    if any(k in prompt for k in keywords):
        return jsonify({
            "reply": "تم تطويري وبرمجتي من قبل أبو مشعل المطيري يعمل بالتأهيل الشامل قسم الاتصالات الإدارية."
        })

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "أنت مساعد ذكي اسمه نبراس."},
            {"role": "user", "content": prompt}
        ]
    )

    return jsonify({"reply": response.choices[0].message.content})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
