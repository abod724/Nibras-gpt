import streamlit as st
from ai import ask

st.set_page_config(page_title="Nibras", page_icon="🤖", layout="wide")

# ====== CSS واجهة نظيفة جداً ======
st.markdown("""
<style>

body {
    background-color: #ffffff;
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

.chat-box {
    max-width: 800px;
    margin: auto;
    padding: 10px;
}

.msg {
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 10px;
    font-size: 17px;
}

.user {
    background: #e8f0fe;
    color: #1a73e8;
}

.bot {
    background: #f1f3f4;
    color: #333;
}

.input-area {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    background: white;
    padding: 10px;
    border-top: 1px solid #ddd;
}

.send-btn {
    background: #1a73e8;
    color: white;
    padding: 10px 18px;
    border-radius: 10px;
    font-weight: bold;
    cursor: pointer;
}

.icon-btn {
    background: #f1f3f4;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 20px;
}

</style>
""", unsafe_allow_html=True)

# ====== صندوق المحادثة ======
st.markdown("<div class='chat-box'>", unsafe_allow_html=True)

if "history" not in st.session_state:
    st.session_state.history = []

for role, text in st.session_state.history:
    css = "user" if role == "user" else "bot"
    st.markdown(f"<div class='msg {css}'>{text}</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)

# ====== منطقة الإدخال أسفل الشاشة ======
st.markdown("<div class='input-area'>", unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns([5, 1, 1, 1])

with col1:
    user_input = st.text_input("", placeholder="اكتب رسالتك…", key="input")

with col2:
    send = st.button("📨")

with col3:
    st.button("🎤")

with col4:
    st.button("📁")

st.markdown("</div>", unsafe_allow_html=True)

# ====== إرسال الرسالة ======
if send and user_input:
    st.session_state.history.append(("user", user_input))
    reply = ask(user_input)
    st.session_state.history.append(("bot", reply))
    st.experimental_rerun()
