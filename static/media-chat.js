// The signed form sends originals directly to CloudConvert. The API key stays on Render.
async function mediaJson(url, options) {
    const response = await fetch(url, options);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || 'تعذّر الاتصال بخدمة التحويل.');
    return body;
}

async function uploadMedia(form, file, index) {
    const body = new FormData();
    Object.entries(form.parameters).forEach(([key, value]) => body.append(key, value));
    const extension = file.name.split('.').pop().toLowerCase();
    body.append('file', file, 'attachment-' + (index + 1) + '.' + extension);
    const response = await fetch(form.url, {method: 'POST', body, credentials: 'omit'});
    if (!response.ok) throw new Error('تعذّر رفع المرفق إلى خدمة التحويل.');
}

async function mediaResult(id) {
    let delay = 1800;
    let errors = 0;
    while (true) {
        await new Promise(resolve => setTimeout(resolve, delay));
        let result;
        try {
            result = await mediaJson('/media/jobs/' + id);
            errors = 0;
        } catch (error) {
            if (++errors >= 5) throw error;
        }
        if (result && result.state !== 'pending') return result;
        delay = Math.min(10000, delay + 1200);
    }
}
