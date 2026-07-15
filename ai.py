import os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def ask(prompt):

    # رد ثابت إذا أحد سأل عن المبرمج
    keywords = [
        "من برمجك", "مين برمجك", "من سواك", "مين سواك",
        "من طورك", "مين طورك", "المبرمج", "من صممك",
        "من صنعك", "مين صنعك", "من جهزك"
    ]

    if any(k in prompt for k in keywords):
        return "تم تطويري وبرمجتي من قبل أبو مشعل المطيري يعمل بالتأهيل الشامل قسم الاتصالات الإدارية."

    # الرد الطبيعي من الذكاء الاصطناعي
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "أنت مساعد ذكي اسمه نبراس."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content
