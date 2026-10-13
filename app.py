# ═══════════════════════════════════════════════════════════
#  القسم 1/8 — Imports + إعدادات Flask
# ═══════════════════════════════════════════════════════════

from flask import (
    Flask, request, jsonify, render_template_string,
    session, redirect, url_for, send_from_directory,
    Response, stream_with_context
)
import openai, os, secrets, json, asyncio, base64, re, requests, time
from datetime import datetime, timedelta, date as _date
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import create_client
from markupsafe import escape
import io
import urllib.parse
from gtts import gTTS


app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError("يجب ضبط SECRET_KEY كمتغير بيئة ثابت بطول 32 حرفًا على الأقل")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_NAME='nibras_session',
    SESSION_COOKIE_DOMAIN=None
)


ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "abdullaha0569361@gmail.com")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise Exception("OPENAI_API_KEY غير موجود!")

OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
if not OPENAI_MODEL:
    raise Exception("OPENAI_MODEL غير موجود!")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise Exception("SUPABASE_URL و SUPABASE_KEY مطلوبان!")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or SUPABASE_KEY
sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


LIMITS = {
    "guest": {"chat": 15,  "search": 0,   "image": 0},
    "user":  {"chat": 15,  "search": 2,   "image": 1},
    "admin": {"chat": 9999, "search": 9999, "image": 9999},
}


def get_user_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return get_remote_address()


limiter = Limiter(
    key_func=get_user_ip,
    default_limits=["500 per day", "300 per hour"]
)
limiter.init_app(app)


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    allowed = [
        'https://abod724.github.io',
        'https://nibras-al.onrender.com',
        'https://test-bot-001.onrender.com'
    ]
    if origin in allowed:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/robots.txt')
def serve_robots():
    return send_from_directory('static', 'robots.txt')


@app.route('/sitemap.xml')
def serve_sitemap():
    return send_from_directory('static', 'sitemap.xml')


@app.route('/.well-known/<path:filename>')
def serve_well_known(filename):
    return send_from_directory('.well-known', filename)


@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js', mimetype='application/javascript')

# ═══════════════════════════════════════════════════════════
#  نهاية القسم 1
# ═══════════════════════════════════════════════════════════
