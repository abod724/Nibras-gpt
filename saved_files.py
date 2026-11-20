"""Private, expiring saved-file library for Nibras GP.
All storage access is server-side using the service role; files are never public.
"""
import hashlib
import io
import math
import mimetypes
import os
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from flask import jsonify, request, session, redirect
import requests

BUCKET = "nibras-private-library"
EXTENSIONS = {"pdf", "docx", "txt", "eml", "jpg", "jpeg", "png", "webp",
              "mp3", "wav", "m4a", "ogg", "mp4", "mov", "webm"}
_last_cleanup = 0.0


def register_saved_files(app, sb, role_for, get_user_id, admin_email,
                         trial_available=None, trial_claim=None):
    def auth():
        email = str(session.get("user_email") or "").strip().lower()
        admin = bool(session.get("is_admin"))
        if not admin and not email:
            return None
        is_admin = admin or bool(email and role_for(email) == "admin")
        uid = get_user_id()
        account = admin_email.strip().lower() if admin else email
        return uid, account, is_admin

    def limits(identity):
        return (100, 50 * 1024 * 1024) if identity[2] else (5, 2 * 1024 * 1024)

    def nowiso():
        return datetime.now(timezone.utc).isoformat()

    def filename(name):
        clean = str(name or "ملف").replace("\\", "/").split("/")[-1]
        clean = re.sub(r"[\x00-\x1f\x7f]", "", clean).strip(" .")
        return clean[:180] or "ملف"

    def file_ext(name):
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""

    def meta(row):
        expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        seconds = (expiry - datetime.now(timezone.utc)).total_seconds()
        return {
            "id": row["id"], "name": row["filename"], "size": row["size_bytes"],
            "type": row["content_type"], "source": row["source"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "days_left": max(0, math.ceil(seconds / 86400)),
            "warning": ("expired" if seconds <= 0 else
                        "tomorrow" if seconds <= 86400 else
                        "week" if seconds <= 7 * 86400 else None),
        }

    def active(uid):
        return (sb.table("nibras_saved_files")
                .select("id,filename,storage_path,size_bytes,content_type,source,source_job,created_at,expires_at")
                .eq("user_id", uid).gt("expires_at", nowiso())
                .order("created_at", desc=True).limit(150).execute().data or [])

    def quota_check(identity, size):
        rows = active(identity[0])
        max_count, max_bytes = limits(identity)
        used = sum(int(row["size_bytes"]) for row in rows)
        if len(rows) >= max_count:
            return "مكتبتك ممتلئة. احذف ملفًا محفوظًا قبل إضافة ملف جديد."
        if size + used > max_bytes:
            return "المساحة المتبقية في مكتبتك لا تكفي لهذا الملف."
        return None

    def remove_file(row):
        # Storage deletion must succeed BEFORE deleting DB metadata.
        sb.storage.from_(BUCKET).remove([row["storage_path"]])
        sb.table("nibras_saved_files").delete().eq("id", row["id"]).eq("storage_path", row["storage_path"]).execute()

    def cleanup_expired(limit=80):
        expired = (sb.table("nibras_saved_files").select("id,storage_path")
                   .lte("expires_at", nowiso()).limit(limit).execute().data or [])
        for row in expired:
            try:
                remove_file(row)
            except Exception as exc:
                app.logger.warning("saved library cleanup: %s", type(exc).__name__)
        return len(expired)

    def periodic_cleanup():
        # Render may sleep on the free plan: whenever app is active, run cleanup
        # every six hours. Library reads also run a cleanup right away.
        nonlocal app
        import gevent
        def loop():
            try:
                cleanup_expired()
            except Exception as exc:
                app.logger.warning("saved library periodic cleanup: %s", type(exc).__name__)
            finally:
                gevent.spawn_later(6 * 3600, loop)
        gevent.spawn_later(120, loop)

    periodic_cleanup()

    def run_cleanup_if_due():
        global _last_cleanup
        clock = time.monotonic()
        if clock - _last_cleanup > 3600:
            _last_cleanup = clock
            try:
                cleanup_expired()
            except Exception as exc:
                app.logger.warning("saved library on-demand cleanup: %s", type(exc).__name__)

    def store_bytes(identity, raw, name, source, job_id=None):
        max_count, max_bytes = limits(identity)
        if not raw or len(raw) > max_bytes:
            return None, "الملف يتجاوز مساحة الحفظ المتاحة لحسابك."
        ext = file_ext(name)
        if ext not in EXTENSIONS:
            return None, "هذه الصيغة غير مدعومة في مكتبتي."
        violation = quota_check(identity, len(raw))
        if violation:
            return None, violation
        safe = filename(name)
        path = hashlib.sha256(identity[0].encode()).hexdigest()[:24] + "/" + uuid.uuid4().hex + "." + ext
        content_type = mimetypes.guess_type(safe)[0] or "application/octet-stream"
        try:
            sb.storage.from_(BUCKET).upload(
                path=path, file=raw,
                file_options={"content-type": content_type, "cache-control": "0", "upsert": "false"})
            try:
                res = sb.table("nibras_saved_files").insert({
                    "user_id": identity[0], "filename": safe, "storage_path": path,
                    "size_bytes": len(raw), "content_type": content_type,
                    "source": source, "source_job": job_id,
                }).execute()
            except Exception:
                sb.storage.from_(BUCKET).remove([path])
                raise
            return meta(res.data[0]), None
        except Exception as exc:
            app.logger.warning("save to private library: %s", type(exc).__name__)
            return None, "تعذّر حفظ الملف. حاول مرة ثانية."

    def owned(identity, file_id):
        result = (sb.table("nibras_saved_files").select("*").eq("user_id", identity[0])
                  .eq("id", str(file_id)).gt("expires_at", nowiso()).limit(1).execute().data)
        return result[0] if result else None

    @app.get("/library/files")
    def saved_list():
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك للوصول لمكتبتك."), 401
        run_cleanup_if_due()
        rows = active(identity[0])
        max_count, max_bytes = limits(identity)
        items = [meta(row) for row in rows]
        return jsonify(files=items,
                       quota={"count": len(items), "max_count": max_count,
                              "used": sum(int(row["size_bytes"]) for row in rows),
                              "max_bytes": max_bytes},
                       alerts=[item for item in items if item["warning"]])

    @app.post("/library/files/upload")
    def saved_upload():
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك أولًا."), 401
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify(message="اختر ملفًا للحفظ."), 400
        # Flask's global request cap remains 22MB. Admin can store more in
        # aggregate and can save a 50MB provider result through save-job.
        maximum = limits(identity)[1]
        data = uploaded.read(maximum + 1)
        item, error = store_bytes(identity, data, uploaded.filename, "upload")
        return (jsonify(file=item), 201) if item else (jsonify(message=error), 413 if len(data)>maximum else 400)

    @app.post("/library/files/save-job")
    def save_converted():
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك أولًا."), 401
        payload = request.get_json(silent=True) or {}
        try:
            job_id = str(uuid.UUID(str(payload.get("job_id"))))
        except (ValueError, TypeError):
            return jsonify(message="معرّف التحويل غير صالح."), 400
        existing = (sb.table("nibras_saved_files").select("*")
                    .eq("user_id", identity[0]).eq("source_job", job_id).limit(1).execute().data or [])
        if existing:
            if datetime.fromisoformat(existing[0]["expires_at"].replace("Z", "+00:00")) > datetime.now(timezone.utc):
                return jsonify(file=meta(existing[0]), already_saved=True)
        jobs = (sb.table("nibras_media_jobs").select("state,result_url,result_name")
                .eq("id", job_id).eq("account", identity[1]).limit(1).execute().data or [])
        if not jobs or jobs[0]["state"] != "finished" or not jobs[0].get("result_url"):
            return jsonify(message="ملف التحويل غير متاح للحفظ. قد يكون رابط التحميل مؤقتًا أو المهمة في وضع التخفي."), 404
        name = filename(jobs[0].get("result_name") or "ملف")
        if file_ext(name) not in EXTENSIONS:
            return jsonify(message="صيغة الملف غير مدعومة في مكتبتي."), 400
        url = jobs[0]["result_url"]
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not (host == "storage.cloudconvert.com" or host.endswith(".storage.cloudconvert.com")) or parts.username or parts.password:
            return jsonify(message="مصدر التحميل غير مسموح."), 400
        maximum = limits(identity)[1]
        # Do not follow redirects to other hosts or accept client-supplied URLs.
        try:
            with requests.get(url, stream=True, timeout=(5, 30), allow_redirects=False) as remote:
                if remote.status_code != 200:
                    return jsonify(message="انتهت صلاحية رابط التحويل. أعد التحويل لتنزيل نسخة جديدة."), 410
                if int(remote.headers.get("Content-Length") or 0) > maximum:
                    return jsonify(message="حجم الملف أكبر من مساحة مكتبتي. يمكنك تحميله مباشرة بدل حفظه."), 413
                data = bytearray()
                for chunk in remote.iter_content(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > maximum:
                        return jsonify(message="الملف أكبر من مساحة مكتبتي. حمّله على جهازك."), 413
        except requests.RequestException:
            return jsonify(message="تعذّر تنزيل الملف من خدمة التحويل. قد تكون صلاحية الرابط انتهت."), 502
        item, error = store_bytes(identity, bytes(data), name, "converted", job_id)
        return (jsonify(file=item), 201) if item else (jsonify(message=error), 409)

    @app.get("/library/files/<uuid:file_id>/download")
    def saved_download(file_id):
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك أولًا."), 401
        row = owned(identity, file_id)
        if not row:
            return jsonify(message="الملف غير موجود أو انتهت صلاحيته."), 404
        try:
            result = sb.storage.from_(BUCKET).create_signed_url(row["storage_path"], 120)
            url = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
            if url and url.startswith("/"):
                url = os.environ.get("SUPABASE_URL","").rstrip("/") + url
            if not url:
                return jsonify(message="تعذّر تجهيز رابط التحميل."), 502
            return redirect(url, code=302)
        except Exception:
            return jsonify(message="تعذّر تجهيز رابط التحميل."), 502

    @app.post("/library/files/<uuid:file_id>/delete")
    def saved_delete(file_id):
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك أولًا."), 401
        row = owned(identity, file_id)
        if not row:
            return jsonify(message="الملف غير موجود."), 404
        try:
            remove_file(row)
            return jsonify(status="ok")
        except Exception:
            return jsonify(message="تعذّر حذف الملف من التخزين."), 503

    @app.post("/library/files/<uuid:file_id>/use")
    def saved_use(file_id):
        identity = auth()
        if not identity:
            return jsonify(message="سجّل دخولك أولًا."), 401
        row = owned(identity, file_id)
        if not row:
            return jsonify(message="الملف غير موجود أو انتهت صلاحيته."), 404
        ext = file_ext(row["filename"])
        if ext not in {"pdf", "docx", "eml", "txt"}:
            return jsonify(message="الاستخدام داخل المحادثة متاح للمستندات النصية حاليًا."), 400
        if not identity[2] and trial_available and not trial_available(identity[1]):
            return jsonify(message="استخدمت مهمة المستندات التجريبية. يمكنك تنزيل الملف من مكتبتك."), 429
        try:
            blob = sb.storage.from_(BUCKET).download(row["storage_path"])
            raw = blob if isinstance(blob, bytes) else blob.content
            text = ""
            if ext == "pdf":
                import fitz
                doc = fitz.open(stream=raw, filetype="pdf")
                if len(doc) > 100:
                    doc.close()
                    return jsonify(message="المستند يتجاوز 100 صفحة."), 400
                text = "\n".join(page.get_text("text") for page in doc)
                doc.close()
            elif ext == "docx":
                from docx import Document
                text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
            elif ext == "txt":
                text = raw.decode("utf-8", errors="replace")
            else:
                import email
                from email import policy
                parsed = email.message_from_bytes(raw, policy=policy.default)
                text = "\n".join(str(part.get_content()) for part in parsed.walk() if part.get_content_type()=="text/plain")
            if not text.strip():
                return jsonify(message="لم أجد نصًا قابلًا للاستخراج في هذا الملف."), 400
            chunks = [text[i:i+1500] for i in range(0, len(text), 1500)]
            sb.table("user_files").delete().eq("user_id", identity[0]).execute()
            sb.table("user_files").insert({"user_id": identity[0], "filename": row["filename"], "chunks": chunks}).execute()
            if not identity[2] and trial_claim and not trial_claim(identity[1]):
                return jsonify(message="انتهت حصة المستندات التجريبية."), 429
            return jsonify(status="ok", filename=row["filename"])
        except Exception as exc:
            app.logger.warning("library use: %s", type(exc).__name__)
            return jsonify(message="تعذّر تجهيز الملف للمحادثة."), 500

    # Return cleanup helper for future external cron integration.
    return cleanup_expired
