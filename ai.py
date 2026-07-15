import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()
client=OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def ask(messages):
    r=client.responses.create(model="gpt-5",input=messages)
    return r.output_text
