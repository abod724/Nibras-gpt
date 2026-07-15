import streamlit as st
from ai import ask

st.set_page_config(page_title="Nibras AI", page_icon="🤖", layout="wide")

# ====== CSS واجهة نظيفة ======
st.markdown("""
<style>

body {
    background-color: #ffffff;
}

.chat-wrapper {
    max-width: 800px;
    margin: auto;
    padding: 10px;
}

.title {
    text-align: center;
    font-size: 30px;
    font-weight: bold;
    color: #222;
    margin-bottom: 20px;
}

.message-box {
    background: #f7f7f7;
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 10px;
    color: #333;
    font-weight: 500;
}

.user-msg {
    background: #e8f0fe;
    color: #1a73e8;
}

.bot-msg {
    background: #f1f3f4;
    color: #333;
}

input, textarea {
    border-radius: 10px !important;
}

.send-btn {
    background: #1a73e8;
    color: white;
    padding: 10px 18px;
    border-radius: 10px;
    font-weight: bold;
    cursor: pointer;
}

.send-btn:hover {
    background: #155fc4;
}

.bottom-bar {
    display: flex;
    gap: 10px;
    margin-top: 20px;
}

.icon-btn {
    background: #f1f3f4;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 20px;
}

.icon-btn:hover {
    background: #e8e8e8;
}

</style>
""", unsafe_allow_html=True)

# ====== واجهة ======
st.markdown("<div class='chat-wrapper'>", unsafe_allow_html=True)
st.markdown("<div class='title'>Nibras AI 🤖</div>", unsafe_allow_html=True)

# ====== صندوق الكتابة ======
user_input = st.text_input("اكتب رسالتك هنا:")

col1, col2, col3 = st.columns([1, 0.2, 0.2])

with col1:
    send = st.button("إرسال", key="send_btn")

with col2:
    st.button("🎤", key="voice_btn")

with col3:
    st.button("📁", key="upload_btn")

# ====== الرد ======
if send and user_input:
    st.markdown(f"<div class='message-box user-msg'>👤 أنت: {user_input}</div>", unsafe_allow_html=True)
    reply = ask(user_input)
    st.markdown(f"<div class='message-box bot-msg'>🤖 نبراس: {reply}</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
