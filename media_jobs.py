"""CloudConvert chat tools. Only server-defined operations and signed uploads are exposed."""
import hashlib
import hmac
import os
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from flask import jsonify, request, session

API = "https://api.cloudconvert.com/v2"
IMAGES = set("jpg jpeg png webp heic heif gif bmp tif tiff avif".split())
VIDEOS = set("mp4 mov mkv webm avi m4v mpg mpeg mts m2ts 3gp".split())
AUDIO = set("mp3 wav m4a aac ogg opus flac amr weba".split())
DOCUMENTS = {"pdf", "docx"}
# Files are uploaded directly from the browser to CloudConvert, not through Flask.
MEDIA_MAX_BYTES = {"image": 15 * 1024 * 1024, "video": 200 * 1024 * 1024,
                   "audio": 50 * 1024 * 1024, "document": 20 * 1024 * 1024}


def media_category(ext):
    if ext in IMAGES:
        return "image"
    if ext in VIDEOS:
        return "video"
    if ext in AUDIO:
        return "audio"
    return "document" if ext in DOCUMENTS else None

LIMIT_MESSAGES = {
    "exhausted": "استخدمت حصتك المتاحة لتحويل الملفات.",
    "busy": "عندك تحويل جارٍ. انتظر نتيجته قبل طلب تحويل جديد.",
    "duplicate": "هذا الطلب مسجّل بالفعل.",
}


def operations(exts):
    if len(exts) > 1:
        return ["merge_pdf"] if all(e in IMAGES | DOCUMENTS for e in exts) else []
    ext = exts[0]
    if ext in IMAGES:
        return ["image_jpg", "image_png", "image_webp", "image_compress", "merge_pdf"]
    if ext in VIDEOS:
        return ["video_mp4", "video_compress", "audio_mp3", "transcript"]
    if ext in AUDIO:
        return ["audio_mp3", "transcript"]
    return ["pdf_compress"] if ext == "pdf" else ["merge_pdf"]


def basic_intent(prompt, allowed):
    """Fast path for common instructions. Other wording gets a semantic decision."""
    normalized = prompt.lower().translate(str.maketrans("أإآى", "اااي"))
    normalized = re.sub(r"[ً-ْ؟?!.,،]", "", normalized).strip()
    if normalized in {"لخصه", "لخص لي الملف", "لخص لي المستند", "وش في الصورة", "اشرح الصورة", "وش هذا", "وش هذي"}:
        return "ordinary"
    phrases = {
        "image_jpg": ("حولها jpg", "حولها الى jpg", "خلها jpg", "حولها جي بي جي"),
        "image_png": ("حولها png", "خلها png"),
        "image_webp": ("حولها webp", "خلها webp"),
        "image_compress": ("اضغطها", "خفف حجمها", "صغر الصوره", "صغرها", "اضغط الصورة"),
        "video_mp4": ("خله mp4", "حوله mp4", "حول المقطع الى mp4", "حول الفيديو الى mp4"),
        "video_compress": ("اضغطه", "اضغط الفيديو", "خفف حجمه", "خفف حجم المقطع"),
        "audio_mp3": ("طلع الصوت", "طلع لي الصوت", "ابي الصوت لحاله", "حوله mp3", "طلع الصوت mp3"),
        "transcript": ("فرغه كتابة", "اكتب لي كلام المقطع", "اكتب الكلام اللي فيه", "فرغ التسجيل"),
        "merge_pdf": ("اجمعها", "اجمعها في ملف واحد", "اجمعها pdf", "ادمجها", "حولها pdf"),
        "pdf_compress": ("اضغطه", "خفف حجمه", "اضغط الملف"),
    }
    return next((key for key in allowed if normalized in phrases[key]), None)


def tasks_for(action, exts):
    names = [f"source-{n}" for n in range(len(exts))]
    tasks = {name: {"operation": "import/upload"} for name in names}
    ext = exts[0]
    specs = {
        "image_jpg": {"operation": "convert", "output_format": "jpg"},
        "image_png": {"operation": "convert", "output_format": "png"},
        "image_webp": {"operation": "convert", "output_format": "webp"},
        "video_mp4": {"operation": "convert", "output_format": "mp4", "video_codec": "x264"},
        "video_compress": {"operation": "command", "engine": "ffmpeg", "command": "ffmpeg",
            "arguments": f"-i /input/source-0/attachment-1.{ext} -c:v libx264 -crf 29 -preset fast "
                         "-c:a aac -b:a 96k -movflags +faststart /output/video.mp4"},
        "audio_mp3": {"operation": "convert", "output_format": "mp3"},
        "transcript": {"operation": "ai/stt", "output_format": "txt"},
        "pdf_compress": {"operation": "optimize", "input_format": "pdf", "profile": "web"},
        "merge_pdf": {"operation": "merge" if len(exts) > 1 else "convert", "output_format": "pdf"},
    }
    specs["image_compress"] = (
        {"operation": "optimize", "input_format": "jpg" if ext == "jpeg" else ext, "quality": 72}
        if ext in {"jpeg", "jpg", "png"} else
        {"operation": "convert", "output_format": "webp", "quality": 72}
    )
    tasks["process"] = dict(specs[action], input=names if len(names) > 1 else names[0])
    tasks["download"] = {"operation": "export/url", "input": "process"}
    return tasks


def provider(method, path, **kwargs):
    response = requests.request(method, API + path, headers={
        "Authorization": "Bearer " + os.environ["CLOUDCONVERT_API_KEY"]
    }, timeout=(5, 20), **kwargs)
    response.raise_for_status()
    return None if response.status_code == 204 else response.json()["data"]


def register_media(app, sb, client, model, role_for, save_message, admin_email, limiter):
    def ledger():
        return sb.table("nibras_media_jobs")

    def identity():
        email = str(session.get("user_email") or "").strip().lower()
        if session.get("is_admin"):
            email = admin_email.strip().lower()
        if not email:
            return None
        admin = session.get("is_admin") or role_for(email) == "admin"
        period = datetime.now(ZoneInfo("Asia/Riyadh")).date().isoformat() if admin else "lifetime"
        return email, period, 9 if admin else 1

    def sign(job_id):
        return hmac.new(app.secret_key.encode(), ("cc:"+job_id).encode(), hashlib.sha256).hexdigest()

    def fail(row):
        ledger().update({"state": "failed", "prompt": None}).eq("id", row["id"]).eq("state", "pending").execute()
        return {"state": "failed", "message": "ما اكتمل التحويل. تجربتك محفوظة."}

    def inspect(row, remote=None):
        if row["state"] == "finished" and row["result_url"]:
            return {"state": "finished", "url": row["result_url"], "name": row["result_name"]}
        if row["state"] == "failed":
            return {"state": "failed", "message": "تعذر إكمال التحويل. تجربتك محفوظة."}
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))).total_seconds()
        if not row["provider_id"]:
            return fail(row) if age > 180 else {"state": "pending"}
        if remote is None:
            try:
                remote = provider("GET", "/jobs/" + row["provider_id"])
            except requests.HTTPError as exc:
                if exc.response.status_code in (404, 410):
                    return fail(row)
                raise
        if remote["status"] in ("error", "canceled"):
            result = fail(row)
            codes = {str(t.get("code") or "").upper() for t in remote.get("tasks", [])}
            if "AI_DISABLED" in codes:
                result["message"] = "التفريغ الصوتي يحتاج تفعيل AI في حساب CloudConvert. تجربتك محفوظة."
            return result
        if remote["status"] != "finished":
            process = next((t for t in remote["tasks"] if t["name"] == "process"), {})
            if age > 7200 and process.get("status") == "waiting":
                provider("POST", "/tasks/" + process["id"] + "/cancel")
            if any(t.get("status") != "finished" for t in remote["tasks"] if t["name"].startswith("source-")):
                phase = "receiving"
            else:
                phase = {"processing": "converting", "finished": "exporting"}.get(process.get("status"), "queued")
            return {"state": "pending", "phase": phase}
        export = next(t for t in remote["tasks"] if t["name"] == "download")
        file = export["result"]["files"][0]
        url = file["url"]
        if urlsplit(url).scheme != "https":
            return fail(row)
        filename = file["filename"]
        result = {"state": "finished", "url": url, "name": filename}
        if row["state"] == "finished":
            return result
        won = ledger().update({"state": "finished", "result_url": url if row["chat_id"] else None,
                               "result_name": filename if row["chat_id"] else None,
                               "prompt": None}).eq("id", row["id"]).eq("state", "pending").execute()
        if won.data and row["chat_id"] and row["prompt"]:
            private_admin = row["chat_id"].startswith("admin:")
            owner_id = "admin_page" if private_admin else "user_" + row["account"]
            save_message(owner_id, row["prompt"], "[تحميل الملف المحوّل](" + url + ")", row["chat_id"].split(":", 1)[1])
        return result

    def pending(account):
        rows = ledger().select("*").eq("account", account).eq("state", "pending").limit(1).execute().data
        return rows[0] if rows else None

    def safe(fn):
        from functools import wraps
        @wraps(fn)
        def handle(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                app.logger.warning("media %s: %s", fn.__name__, type(exc).__name__)
                return jsonify(message="تعذّر الاتصال بخدمة التحويل. جرّب بعد قليل."), 503
        return handle

    @app.get("/media/quota")
    @safe
    def media_quota():
        who = identity()
        if not who:
            return jsonify(remaining=0)
        account, period, limit = who
        rows = ledger().select("id", count="exact").eq("account", account).eq("quota_period", period).eq("state", "finished").execute()
        return jsonify(remaining=max(0, limit-rows.count))

    @app.post("/media/jobs")
    @limiter.limit("12 per minute")
    @safe
    def media_start():
        who = identity()
        if not who:
            return jsonify(message="سجّل دخولك عشان تجرّب تحويل الملفات."), 403
        if not os.getenv("CLOUDCONVERT_API_KEY"):
            return jsonify(message="تحويل الملفات غير مفعّل حالياً."), 503
        d = request.get_json() or {}
        if not isinstance(d, dict):
            return jsonify(message="بيانات الطلب غير صالحة."), 400
        try:
            job_id = str(uuid.UUID(str(d.get("id"))))
        except ValueError:
            return jsonify(message="معرّف الطلب غير صالح."), 400
        files = d.get("files")
        if not isinstance(files, list) or not 1 <= len(files) <= 10:
            return jsonify(message="اختر من ملف واحد إلى ١٠ ملفات."), 400
        exts = [str(f.get("ext", "")).lower() if isinstance(f, dict) else "" for f in files]
        if any(media_category(ext) is None for ext in exts):
            return jsonify(message="هذه الصيغة غير مدعومة للتحويل. يمكنك قراءة PDF وWord وTXT وEML كمستندات."), 400
        if any(not isinstance(f, dict) or type(f.get("size")) is not int or f["size"] <= 0
               for f in files):
            return jsonify(message="حجم المرفق غير صالح."), 400
        for f, ext in zip(files, exts):
            category = media_category(ext)
            if f["size"] > MEDIA_MAX_BYTES[category]:
                maximum = MEDIA_MAX_BYTES[category] // (1024 * 1024)
                return jsonify(message=f"حجم {category} يتجاوز الحد المسموح ({maximum} ميجابايت)."), 413
        prompt = str(d.get("message", "")).strip()[:2000]
        allowed = operations(exts)
        if not prompt:
            return jsonify(state="ordinary")
        # Only send the instruction and file types to the router, never the files.
        action = basic_intent(prompt, allowed)
        if not action:
            choice = client.chat.completions.create(model=model, messages=[
                {"role": "system", "content": (
                    "Classify the user's current Arabic or English request for attached files. "
                    "Return exactly one allowed operation name, ordinary, or unsupported. "
                    "ordinary for questions about content, normal chat, summary, negation, or no requested file transformation. "
                    "transcript means transcribe speech verbatim. merge_pdf combines images/documents into PDF. "
                    "Only select a conversion actually requested. Use unsupported for requested transformations outside the list, "
                    "including exact byte-size or resolution targets and extra edits you cannot perform. "
                    "Allowed operations: " + ", ".join(allowed) + ". File extensions: " + ", ".join(exts))},
                {"role": "user", "content": prompt}], max_completion_tokens=80)
            action = (choice.choices[0].message.content or "").strip().lower()
        if action == "ordinary":
            return jsonify(state="ordinary")
        if action not in allowed:
            return jsonify(message="ما قدرت أحدد تحويل مدعوم بهالوصف. وضّح الصيغة أو التعديل المطلوب."), 422
        account, period, limit = who
        existing = pending(account)
        if existing and inspect(existing)["state"] == "pending":
            return jsonify(message=LIMIT_MESSAGES["busy"], active_job_id=existing["id"]), 409
        chat_id = str(d.get("chat_id") or "")[:100] if not d.get("incognito") else None
        if chat_id:
            chat_id = ("admin:" if session.get("is_admin") else "user:") + chat_id
        reserved = sb.rpc("reserve_nibras_media", {"p_id":job_id, "p_account":account, "p_period":period,
            "p_limit":limit, "p_chat":chat_id, "p_prompt":prompt if chat_id else None}).execute().data
        if reserved != "reserved":
            return jsonify(message=LIMIT_MESSAGES.get(reserved, "تعذر حجز المهمة.")), 429
        try:
            tasks = tasks_for(action, exts)
            base = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
            payload = {"tasks": tasks, "tag": job_id}
            if base.startswith("https://"):
                payload["webhook_url"] = base + "/media/events/" + job_id + "/" + sign(job_id)
            remote = provider("POST", "/jobs", json=payload)
            by_name = {t["name"]: t for t in remote["tasks"]}
            forms = [by_name[f"source-{n}"]["result"]["form"] for n in range(len(files))]
            ledger().update({"provider_id":remote["id"]}).eq("id",job_id).eq("state","pending").execute()
        except requests.HTTPError as exc:
            fail({"id": job_id})
            if exc.response.status_code == 402:
                return jsonify(message="رصيد نبراس في خدمة التحويل غير كافٍ. تجربتك محفوظة."), 503
            raise
        except Exception:
            fail({"id": job_id})
            raise
        return jsonify(id=job_id, forms=forms, state="upload")

    @app.post("/media/jobs/<uuid:job_id>/cancel")
    @limiter.limit("12 per minute")
    @safe
    def media_cancel(job_id):
        who = identity()
        if not who:
            return jsonify(message="سجّل دخولك أولاً"), 403
        rows = ledger().select("*").eq("id", str(job_id)).eq("account", who[0]).limit(1).execute().data
        if not rows:
            return jsonify(message="لم يتم العثور على المهمة"), 404
        row = rows[0]
        if row["state"] == "finished":
            return jsonify(inspect(row))
        if row["state"] == "failed":
            return jsonify(state="canceled", message="المهمة متوقفة بالفعل. يمكنك رفع ملف آخر.")

        # Cancel provider tasks AND release our pending reservation. Previously,
        # cancellation only worked while the processor was waiting.
        stopped = True
        provider_id = row.get("provider_id")
        if provider_id:
            remote = None
            try:
                remote = provider("GET", "/jobs/" + provider_id)
            except requests.HTTPError as exc:
                if exc.response.status_code not in (404, 410):
                    stopped = False
            except requests.RequestException:
                stopped = False
            if remote and remote.get("status") == "finished":
                return jsonify(inspect(row, remote))
            if remote:
                # CloudConvert supports cancelling waiting AND processing tasks.
                for task in remote.get("tasks", []):
                    if task.get("status") in ("waiting", "processing") and task.get("id"):
                        try:
                            provider("POST", "/tasks/" + task["id"] + "/cancel")
                        except requests.HTTPError as exc:
                            if exc.response.status_code not in (404, 410):
                                stopped = False
                        except requests.RequestException:
                            stopped = False
                # Delete the provider job and any uploaded data where possible.
                try:
                    provider("DELETE", "/jobs/" + provider_id)
                except requests.HTTPError as exc:
                    if exc.response.status_code not in (404, 410):
                        stopped = False
                except requests.RequestException:
                    stopped = False

        updated = (ledger().update({"state": "failed", "prompt": None,
                                   "result_url": None, "result_name": None})
                   .eq("id", str(job_id)).eq("account", who[0])
                   .eq("state", "pending").execute())
        if not updated.data:
            current = ledger().select("*").eq("id", str(job_id)).limit(1).execute().data
            if current and current[0]["state"] == "finished":
                return jsonify(inspect(current[0]))
        message = ("تم إلغاء المهمة. يمكنك رفع ملف جديد." if stopped
                   else "أوقفنا الطلب في نبراس ويمكنك رفع ملف آخر، لكن تعذّر تأكيد إيقاف المعالجة لدى خدمة التحويل.")
        return jsonify(state="canceled", message=message)

    @app.get("/media/jobs/<uuid:job_id>")
    @limiter.limit("60 per minute")
    @safe
    def media_status(job_id):
        who = identity()
        if not who:
            return jsonify(message="سجل دخولك أولاً"), 403
        rows = ledger().select("*").eq("id",str(job_id)).eq("account",who[0]).limit(1).execute().data
        if not rows:
            return jsonify(message="لم يتم العثور على المهمة"), 404
        return jsonify(inspect(rows[0]))

    @app.post("/media/events/<uuid:job_id>/<token>")
    @limiter.exempt
    @safe
    def media_event(job_id, token):
        if not hmac.compare_digest(sign(str(job_id)), token):
            return "", 404
        rows = ledger().select("*").eq("id",str(job_id)).limit(1).execute().data
        if rows and rows[0]["provider_id"]:
            inspect(rows[0])  # Verify the result with CloudConvert, not the incoming body.
        return "", 204
