FROM python:3.11-slim

# تثبيت espeak-ng (ضروري لمكتبة Piper)
RUN apt-get update && apt-get install -y espeak-ng wget && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# تحميل نموذج الصوت العربي (صوت كريم)
RUN wget -O ar_JO-kareem-medium.onnx "https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx" && \
    wget -O ar_JO-kareem-medium.onnx.json "https://huggingface.co/rhasspy/piper-voices/resolve/main/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json"

CMD ["gunicorn", "-b", "0.0.0.0:10000", "-k", "gthread", "app:app"]
