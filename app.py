from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for, send_from_directory
import openai
import os
import secrets
import json
import hashlib
from datetime import datetime
import asyncio
import edge_tts
import base64
import re
import sqlite3

app = Flask(__name__, static_folder='static')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(16))
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود! يجب إضافته في متغيرات البيئة")
client = openai.OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_ENABLED = True

@app.route('/robots.txt')
def serve_robots():
    return send_from_directory('static', 'robots.txt')

DB_FILE = "conversations.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversations
                 (user_id TEXT, conv_id TEXT, messages TEXT, timestamp TEXT, title TEXT)''')
    conn.commit()
    conn.close()

def get_user_conversations(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT conv_id, messages, timestamp, title FROM conversations WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({"id": row[0], "messages": json.loads(row[1]), "timestamp": row[2], "title": row[3]})
    return result

def save_user_conversation(user_id, conversation, conv_id=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if conv_id is None:
        title = conversation[0]["content"][:30] + "..." if len(conversation[0]["content"]) > 30 else conversation[0]["content"]
        new_conv_id = hashlib.md5(f"{user_id}{datetime.now().isoformat()}".encode()).hexdigest()[:8]
        messages_json = json.dumps(conversation)
        c.execute("INSERT INTO conversations (user_id, conv_id, messages, timestamp, title) VALUES (?, ?, ?, ?, ?)",
                  (user_id, new_conv_id, messages_json, datetime.now().isoformat(), title))
        conn.commit(); conn.close(); return new_conv_id
    else:
        messages_json = json.dumps(conversation)
        c.execute("UPDATE conversations SET messages=?, timestamp=? WHERE user_id=? AND conv_id=?",
                  (messages_json, datetime.now().isoformat(), user_id, conv_id))
        conn.commit(); conn.close(); return conv_id

def load_conversation_by_id(user_id, conv_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT messages FROM conversations WHERE user_id=? AND conv_id=?", (user_id, conv_id))
    row = c.fetchone(); conn.close()
    if row: return json.loads(row[0])
    return None

init_db()
session_memory = {}
knowledge_content = ""
possible_names = ["Knowledge.md", "knowledge.md", "معرفة.md", "README.md", "ملف_المعرفة.md"]
for filename in possible_names:
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f: knowledge_content = f.read(); break
        except: pass
if not knowledge_content: knowledge_content = "أنت نبراس، مساعد ذكي."

SYSTEM_PROMPT = f"""
أنت "نبراس"، مساعد شخصي ذكي تتحدث باللهجة العامية البيضاء.

**مصادر معرفتك:**
1. **ملف المعرفة** (أدناه) هو مرجعك الأساسي.
2. **معرفتك العامة**.
3. **البحث بالويب** تستخدمه عندما يسألك عن أي شيء حديث أو غير موجود في ملف المعرفة.

**ملف المعرفة الخاص بك:**
{knowledge_content}

**⚠️ قواعد التنسيق الإلزامية:**
- اكتب ردك في فقرات نصية عادية متصلة.
- اترك **سطراً فارغاً بين كل فقرة وأخرى**.
- استخدم `**الخط العريض**` لعناوين الفقرات، و `-` للقوائم.

**تعليمات مهمة:**
- إذا سألك المستخدم عن أي شيء، حاول أولاً الإجابة من ملف المعرفة.
- إذا لم تجد المعلومة، قل بصراحة "ما عندي علم".
- دائماً حافظ على لهجتك العامية البيضاء.
"""

def remove_emoji(text):
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F" u"\U0001F300-\U0001F5FF" u"\U0001F680-\U0001F6FF" u"\U0001F1E0-\U0001F1FF"
    "]+", flags=re.UNICODE)
    return emoji_pattern.sub(r'', text)

def generate_image(prompt):
    try:
        response = client.images.generate(model="dall-e-3", prompt=prompt, n=1, size="1024x1024")
        return response.data[0].url
    except Exception as e:
        print(f"❌ فشل توليد الصورة: {e}"); return None

async def generate_speech(text, gender):
    voice_id = "ar-SA-HamedNeural" if gender == "male" else "ar-SA-ZariyahNeural"
    communicate = edge_tts.Communicate(remove_emoji(text), voice_id, rate='-15%')
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio": audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode('utf-8')
