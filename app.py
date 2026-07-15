import streamlit as st
from ai import ask

st.set_page_config(page_title="Nibras AI", page_icon="🤖", layout="wide")

# ====== CSS للمنسدلات ======
st.markdown("""
<style>

.top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 5px;
    background-color: #ffffff;
    border-bottom: 1px solid #e0e0e0;
}

.menu-btn {
    font-size: 26px;
    font-weight: bold;
    cursor: pointer;
    padding: 5px 12px;
    border-radius: 8px;
    background: #f1f3f4;
    color: #333;
}

.menu-btn:hover {
    background: #e8e8e8;
}

.plus-btn {
    font-size: 26px;
    font-weight: bold;
    cursor: pointer;
    padding: 5px 12px;
    border-radius: 8px;
    background: #e8f0fe;
    color: #1a73e8;
}

.plus-btn:hover {
    background: #dbe6fd;
}

.chat-wrapper {
    max-width: 800px;
    margin: auto;
    padding: 20px;
}

.title {
    text-align: center;
    font-size: 32px;
    font-weight: bold;
    color: #222;
    margin-bottom: 5px;
}

.subtitle {
    text-align: center;
    font-size: 16px;
    color: #666;
    margin-bottom: 25px;
}

.user-msg {
    background: #e8f0fe;
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 10px;
    color: #1a73e8;
    font-weight: 500;
}

.bot-msg {
    background: #f1f3f4;
    padding: 12px 18px;
    border-radius: 10px;
    margin-bottom: 10px;
    color: #333;
    font-weight: 500;
}

</style>
""", unsafe_allow_html=True)

# ====== شريط علوي فيه المنسدلات ======
st.markdown("""
<div class="top-bar">
    <div class="menu-btn">☰</div>
    <div class="plus-btn">+</div>
    <div class="menu-btn">≡</div>
</div>
""", unsafe_allow_html=True)

# ====== واجهة نبراس ======
st.markdown("<div class='chat-wrapper'>", unsafe_allow_html=True)
st.markdown("<div class='title'>Nibras AI 🤖</div>", unsafe_allow_html=True)
st.markdown("<div class='subtitle'>مساعدك الذكي — واجهة احترافية بيضاء</div>", unsafe_allow_html=True)

user_input = st.text_input("اكتب رسالتك هنا:")

if user_input:
    st.markdown(f"<div class='user-msg'>👤 أنت: {user_input}</div>", unsafe_allow_html=True)
    reply = ask(user_input)
    st.markdown(f"<div class='bot-msg'>🤖 نبراس: {reply}</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
