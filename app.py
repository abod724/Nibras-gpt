import streamlit as st
from ai import ask

st.set_page_config(page_title="نبراس", page_icon="🤖")
st.title("🤖 نبراس")

if "messages" not in st.session_state:
    st.session_state.messages=[]

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt:=st.chat_input("اكتب رسالتك..."):
    st.session_state.messages.append({"role":"user","content":prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    ans=ask(st.session_state.messages)
    st.session_state.messages.append({"role":"assistant","content":ans})
    with st.chat_message("assistant"):
        st.markdown(ans)
