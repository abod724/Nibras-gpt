// Upload signed forms directly from the browser. Only the server holds the provider key.
function mediaCanceledError() { const e = new Error('تم إلغاء العملية.'); e.name = 'AbortError'; return e; }

async function mediaJson(url, options) {
    const controller = new AbortController();
    const externalSignal = options && options.signal;
    if (externalSignal && externalSignal.aborted) throw mediaCanceledError();
    const relay = () => controller.abort();
    if (externalSignal) externalSignal.addEventListener('abort', relay, {once:true});
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
        const response = await fetch(url, {...options, signal: controller.signal});
        const body = await response.json().catch(() => ({}));
        if (!response.ok) {
            const error = new Error(body.message || 'تعذّر الاتصال بخدمة التحويل.');
            if (response.status === 409 && body.active_job_id) error.activeJobId = body.active_job_id;
            throw error;
        }
        return body;
    } catch(error) {
        if (externalSignal && externalSignal.aborted) throw mediaCanceledError();
        throw error;
    } finally {
        clearTimeout(timeout);
        if (externalSignal) externalSignal.removeEventListener('abort', relay);
    }
}

function uploadMedia(form, file, index, onProgress, signal) {
    const body = new FormData();
    Object.entries(form.parameters).forEach(([key, value]) => body.append(key, value));
    const extension = file.name.split('.').pop().toLowerCase();
    body.append('file', file, 'attachment-' + (index + 1) + '.' + extension);
    return new Promise((resolve, reject) => {
        if (signal && signal.aborted) return reject(mediaCanceledError());
        const xhr = new XMLHttpRequest();
        let lastUpdate = Date.now();
        const abortUpload = () => xhr.abort();
        if (signal) signal.addEventListener('abort', abortUpload, {once:true});
        xhr.upload.onprogress = event => {
            lastUpdate = Date.now();
            if (event.lengthComputable && event.total > 0) {
                onProgress(Math.floor(file.size * event.loaded / event.total));
            }
        };
        xhr.upload.onload = () => { lastUpdate = Date.now(); onProgress(file.size); };
        xhr.onload = () => xhr.status >= 200 && xhr.status < 300 ? resolve() :
            reject(new Error('خدمة التحويل ما أكّدت استلام الملف.'));
        xhr.onerror = () => reject(new Error('انقطع الاتصال أثناء رفع الملف.'));
        xhr.onabort = () => reject(signal && signal.aborted ? mediaCanceledError() : new Error('انتهت مهلة انتظار الرفع.'));
        xhr.open('POST', form.url);
        if (signal && signal.aborted) { signal.removeEventListener('abort', abortUpload); return reject(mediaCanceledError()); }
        // Slow uploads may run for many minutes. Stop only after two minutes without an update.
        const watchdog = setInterval(() => {
            if (Date.now() - lastUpdate >= 120000) xhr.abort();
        }, 5000);
        xhr.onloadend = () => { clearInterval(watchdog); if (signal) signal.removeEventListener('abort', abortUpload); };
        try { xhr.send(body); } catch (error) { clearInterval(watchdog); reject(error); }
    });
}

async function mediaResult(id, onPhase, signal) {
    let delay = 1800, errors = 0;
    for (;;) {
        if (signal && signal.aborted) throw mediaCanceledError();
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => { if (signal) signal.removeEventListener('abort', stop); resolve(); }, delay);
            const stop = () => { clearTimeout(timer); reject(mediaCanceledError()); };
            if (signal) signal.addEventListener('abort', stop, {once:true});
        });
        try {
            const result = await mediaJson('/media/jobs/' + id, {signal});
            if (result.state !== 'pending') return result;
            errors = 0;
            onPhase(result.phase || 'checking');
        } catch (error) {
            if (signal && signal.aborted) throw mediaCanceledError();
            onPhase('reconnecting');
            if (++errors >= 5) throw new Error('تعذّر تحديث حالة التحويل. تقدر تراجع سجل المحادثة بعد رجوع الاتصال إذا كان الحفظ مفعّل.');
        }
        delay = Math.min(10000, delay + 1200);
    }
}

async function trackMediaTransfer(container, id, forms, files, options) {
    options = options || {};
    const signal = options.signal;
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.textContent = 'إلغاء الرفع';
    cancel.setAttribute('aria-label', 'إلغاء رفع أو تحويل الملف');
    cancel.style.cssText = 'display:block;margin-top:10px;border:1px solid #dc2626;border-radius:10px;padding:8px 14px;color:#dc2626;background:transparent;font:inherit;cursor:pointer';
    cancel.onclick = () => { cancel.disabled = true; cancel.textContent = 'جاري الإلغاء...'; if (options.onCancel) options.onCancel(); };
    const title = document.createElement('div');
    title.setAttribute('role', 'status');
    const bar = document.createElement('progress');
    bar.setAttribute('aria-label', 'تقدّم رفع المرفقات');
    bar.max = 100;
    bar.style.cssText = 'display:block;width:100%;margin:8px 0;accent-color:#159b7e';
    const detail = document.createElement('small');
    container.replaceChildren(title, bar, detail, cancel);
    const total = files.reduce((sum, file) => sum + file.size, 0);
    const sizes = new Intl.NumberFormat('ar-SA', {maximumFractionDigits: 1});
    const number = new Intl.NumberFormat('ar-SA');
    let uploaded = 0, index = 0, phase = 'upload', lastProgress = Date.now();
    const started = Date.now();
    const headings = {
        upload: 'جاري رفع المرفق', checking: 'تم الرفع · نتحقق من حالة التحويل',
        receiving: 'أُرسلت البيانات · الخدمة تستلم المرفق', queued: 'اكتمل الرفع · بانتظار بدء التحويل',
        converting: 'جاري تحويل الملف', exporting: 'اكتمل التحويل · جاري تجهيز رابط التحميل',
        reconnecting: 'تعذّر تحديث الحالة · نحاول الاتصال من جديد'
    };
    function render() {
        if (signal && signal.aborted) return;
        cancel.textContent = phase === 'upload' ? 'إلغاء الرفع' : 'إلغاء التحويل';
        const now = Date.now(), elapsed = Math.floor((now - started) / 1000);
        const time = number.format(Math.floor(elapsed / 60)) + ':' + String(elapsed % 60).padStart(2, '0').replace(/\d/g, d => number.format(+d));
        let heading = headings[phase] || headings.checking;
        let info = 'الوقت المنقضي ' + time;
        if (phase === 'upload') {
            const percent = Math.floor(uploaded / total * 100);
            bar.value = percent;
            if (files.length > 1) heading += ' ' + number.format(index + 1) + ' من ' + number.format(files.length);
            if (uploaded === total) heading = 'أُرسلت البيانات · بانتظار تأكيد الاستلام';
            info = number.format(percent) + '٪ · ' + sizes.format(uploaded / 1000000) + ' من ' + sizes.format(total / 1000000) + ' م.ب · ' + info;
            if (now - lastProgress > 20000) info += ' · ما وصل تحديث للرفع. خلّ الصفحة مفتوحة وتأكد من الاتصال.';
        } else {
            bar.removeAttribute('value');
            bar.setAttribute('aria-label', heading);
        }
        if (title.textContent !== heading) title.textContent = heading;
        detail.textContent = info;
    }
    function setPhase(next) { phase = next; render(); }
    render();
    const clock = setInterval(render, 1000);
    try {
        let complete = 0;
        try {
            for (; index < files.length; index++) {
                if (signal && signal.aborted) throw mediaCanceledError();
                lastProgress = Date.now();
                render();
                await uploadMedia(forms[index], files[index], index, bytes => {
                    uploaded = complete + bytes;
                    lastProgress = Date.now();
                    render();
                }, signal);
                complete += files[index].size;
                uploaded = complete;
            }
        } catch (error) {
            if (signal && signal.aborted) throw mediaCanceledError();
            // A lost HTTP response can follow a successful upload. Reconcile before cancelling.
            const state = await mediaJson('/media/jobs/' + id).catch(() => null);
            if (state && state.state !== 'pending') return state;
            if (!state || !['queued','converting','exporting'].includes(state.phase)) {
                if (uploaded < total) {
                    const cancelled = await mediaJson('/media/jobs/' + id + '/cancel', {method:'POST'}).catch(() => null);
                    if (cancelled && cancelled.state === 'finished') return cancelled;
                    if (!cancelled || !['queued','converting','exporting'].includes(cancelled.phase)) {
                        throw new Error(error.message + (cancelled && cancelled.state === 'failed' ? ' تجربتك محفوظة، وتقدر ترفع الملف من جديد.' : ' تعذّر تأكيد حالة الطلب.'));
                    }
                }
            }
        }
        setPhase('checking');
        return await mediaResult(id, setPhase, signal);
    } finally {
        clearInterval(clock);
    }
}
