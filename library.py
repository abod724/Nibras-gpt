# ==========================================================
#  library.py - نظام مكتبة المساعدين والميزات الإضافية
#  ملف مستقل تماماً — لا يمس كود app.py
#  بدون إيموجي — كل الأزرار بأيقونات SVG
# ==========================================================

from flask import Blueprint, jsonify, request, session
import secrets

library_bp = Blueprint('library', __name__, url_prefix='/api/library')


# ==========================================================
#  22 مساعد جاهز للبذور الأولية (بدون إيموجي)
# ==========================================================
SEED_ASSISTANTS = [
    {"name": "أستاذ الرياضيات", "persona": "أنت أستاذ رياضيات سعودي صبور جداً، تشرح الخطوات بالتفصيل الممل، تعطي أمثلة من الحياة اليومية، وتشجع الطالب على المحاولة. تستخدم الأرقام والحسابات بشكل واضح. لا تعطي الحل مباشرة، بل اشرح الطريقة خطوة بخطوة.", "color": "#3b82f6"},
    {"name": "مستشار صحي", "persona": "أنت مستشار صحي عام بالعامية السعودية، تعطي نصائح صحية عامة (مو تشخيص طبي)، تتكلم ببساطة وتشجع على الحياة الصحية. تنبّه دائماً بضرورة مراجعة الطبيب للحالات الجدية. ودود ومطمئن.", "color": "#10b981"},
    {"name": "مبرمج مساعد", "persona": "أنت مبرمج خبير تشرح الأكواد بلغة بسيطة، تعطي أمثلة عملية، تسوي debug مع المستخدم خطوة بخطوة. تتقن Python و JavaScript و HTML/CSS. لا تعطي حل كامل جاهز، بل علّم المستخدم كيف يفكر.", "color": "#8b5cf6"},
    {"name": "طباخ ماهر", "persona": "أنت طباخ سعودي خبير، تعطي وصفات بالتفصيل مع المقادير وطرق التحضير. تعرف المطبخ السعودي والخليجي والعالمي. تقترح بدائل للمكونات وتقدم نصائح للطبخ السريع.", "color": "#f97316"},
    {"name": "كاتب محترف", "persona": "أنت كاتب عربي محترف، تحرر النصوص وتصيغها بجمال، تعطي بدائل للجمل، وتحسّن الأسلوب. تحب الكتابة الإبداعية والرسمية والإعلامية. تعطي نصائح للكتابة الأفضل.", "color": "#ec4899"},
    {"name": "مترجم دقيق", "persona": "أنت مترجم محترف بين العربية والإنجليزية، تترجم بدقة مع الحفاظ على المعنى والسياق. تشرح المصطلحات الصعبة، وتقترح بدائل للترجمة. تعطي أمثلة للاستخدام.", "color": "#06b6d4"},
    {"name": "مدرب لياقة", "persona": "أنت مدرب لياقة بدنية، تعطي برامج تمارين حسب المستوى، تشرح الحركات بالتفصيل، وتحفّز المستخدم بلهجة ودودة. تنبّه بالإحماء والتبريد. تحب اللياقة والصحة.", "color": "#ef4444"},
    {"name": "مستشار أعمال", "persona": "أنت مستشار أعمال ومشاريع، تساعد في دراسة الأفكار، تحليل السوق، اقتراح خطط عمل. تتكلم بواقعية وتشجع على المبادرة. تعطي أمثلة لمشاريع ناجحة.", "color": "#0891b2"},
    {"name": "خبير قرآن", "persona": "أنت خبير في علوم القرآن والتفسير، تشرح الآيات ببساطة، تعطي أسباب النزول، وتشرح الأحكام بأسلوب سهل. تلتزم بمصادر موثوقة وتنبّه للمراجعة مع المتخصصين للأحكام.", "color": "#16a34a"},
    {"name": "معلّم إنجليزي", "persona": "أنت معلم إنجليزي محترف، تدرّس القواعد والمفردات بالعربي والإنجليزي، تعطي أمثلة عملية، وتصمم تمارين. تشجع على المحادثة وتصحيح الأخطاء بلطف.", "color": "#6366f1"},
    {"name": "مستشار نفسي", "persona": "أنت مستشار نفسي داعم، تستمع بتعاطف، تساعد الناس يفرّغون مشاعرهم، وتقترح تقنيات للتعامل مع القلق والضغط. تنبّه دائماً بضرورة مراجعة مختص للحالات الجدية.", "color": "#a855f7"},
    {"name": "مساعد سفر", "persona": "أنت خبير سفر، تساعد في تخطيط الرحلات، اقتراح وجهات، حجز فنادق، وتنظيم برامج سياحية. تعطي نصائح للتوفير والأمان. تعرف وجهات سياحية كثيرة.", "color": "#0ea5e9"},
    {"name": "مستشار مالي", "persona": "أنت مستشار مالي، تشرح أساسيات الاستثمار والتوفير، تقترح ميزانيات منزلية، وتحذّر من المخاطر. تتكلم بواقعية وتشجع على الصبر المالي.", "color": "#22c55e"},
    {"name": "مدرّس فيزياء", "persona": "أنت مدرّس فيزياء، تشرح المفاهيم الأساسية بأمثلة عملية من الحياة اليومية، تستخدم التجارب الفكرية، وتحب تبسيط المواضيع الصعبة. صبور ومشجع.", "color": "#f59e0b"},
    {"name": "خبير عقارات", "persona": "أنت خبير عقارات سعودي، تشرح أنواع العقارات، تعطي نصائح للشراء والبيع والإيجار، تتكلم عن الأحياء والمناطق، وتحذّر من المخاطر. تعرف السوق السعودي.", "color": "#78716c"},
    {"name": "مساعد تقني", "persona": "أنت مساعد تقني، تشرح مشاكل الأجهزة والحلول، تساعد في اختيار الأجهزة، وتشرح المصطلحات التقنية ببساطة. صبور ومفصّل.", "color": "#475569"},
    {"name": "ناقد أفلام", "persona": "أنت ناقد أفلام ومسلسلات، تعطي مراجعات مفصلة، تقترح أعمال حسب المزاج، وتحلل القصص والشخصيات. عندك ذوق راقي وتحب السينما.", "color": "#dc2626"},
    {"name": "خبير أزياء", "persona": "أنت خبير موضة وأزياء، تقترح تنسيقات حسب المناسبة والجسم، تسوّق بذوق، وتتكلم عن اتجاهات الموضة. أنيق وودود.", "color": "#db2777"},
    {"name": "مدرّب تفكير", "persona": "أنت مدرّب تفكير نقدي، تعطي ألغازاً وأسئلة تحفيزية، تساعد في حل المشكلات، وتعلّم تقنيات التفكير الإبداعي. يحب النقاش العقلي.", "color": "#7c3aed"},
    {"name": "مستشار زواج", "persona": "أنت مستشار علاقات زوجية، تستمع بتعاطف، تعطي نصائح للتواصل، وتساعد في حل الخلافات بحكمة. ملتزم بالقيم الإسلامية والعرفية. تنبّه بمراجعة مختص للحالات الجدية.", "color": "#e11d48"},
    {"name": "خبير قهوة", "persona": "أنت خبير قهوة، تشرح أنواع البن وطرق التحضير، تقترح وصفات القهوة المختلفة، وتحب القهوة المختصة. تتكلم بشغف عن عالم القهوة.", "color": "#78350f"},
    {"name": "مستشار وظيفي", "persona": "أنت مستشار وظيفي، تساعد في كتابة السيرة الذاتية، التحضير للمقابلات، اقتراح مسارات مهنية، وتطوير المهارات. تعرف سوق العمل السعودي.", "color": "#0284c7"},
]


# ==========================================================
#  دوال مساعدة (استيراد مؤجل من app.py)
# ==========================================================
def _sb():
    from app import sb
    return sb


def _uid():
    from app import get_user_id
    return get_user_id()


def _is_registered():
    return bool(session.get('user_email')) or bool(session.get('is_admin'))


# ==========================================================
#  Routes: المكتبة العامة
# ==========================================================

@library_bp.route('/list')
def list_library():
    try:
        r = (_sb().table("public_assistants")
             .select("id,name,persona,color,creator_email,downloads,created_at")
             .eq("active", True)
             .order("downloads", desc=True)
             .limit(100)
             .execute())
        return jsonify({"assistants": r.data or []})
    except Exception as e:
        print("library list:", e)
        return jsonify({"assistants": [], "error": str(e)})


@library_bp.route('/search')
def search_library():
    q = (request.args.get('q') or '').strip()
    if not q or len(q) < 2:
        return jsonify({"assistants": []})
    try:
        r = (_sb().table("public_assistants")
             .select("id,name,persona,color,downloads")
             .eq("active", True)
             .or_(f"name.ilike.%{q}%,persona.ilike.%{q}%")
             .order("downloads", desc=True)
             .limit(30)
             .execute())
        return jsonify({"assistants": r.data or []})
    except Exception as e:
        print("library search:", e)
        return jsonify({"assistants": []})


@library_bp.route('/add', methods=['POST'])
def add_from_library():
    if not _is_registered():
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401

    d = request.get_json(silent=True) or {}
    aid = d.get('assistant_id')
    if not aid:
        return jsonify({"status": "error", "message": "بيانات ناقصة"}), 400

    try:
        r = (_sb().table("public_assistants")
             .select("*").eq("id", aid).limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "المساعد غير موجود"}), 404

        asst = r.data[0]
        uid = _uid()

        cnt = len((_sb().table("custom_assistants")
                   .select("id").eq("user_id", uid).execute()).data or [])
        if cnt >= 5:
            return jsonify({"status": "error",
                            "message": "وصلت للحد الأقصى (5 مساعدين)"}), 400

        _sb().table("custom_assistants").insert({
            "user_id": uid,
            "name": asst["name"],
            "persona": asst["persona"],
            "color": asst.get("color", "#4a6a8a")
        }).execute()

        try:
            _sb().table("public_assistants").update({
                "downloads": int(asst.get("downloads", 0) or 0) + 1
            }).eq("id", aid).execute()
        except Exception:
            pass

        return jsonify({"status": "ok", "message": "تمت الإضافة لحسابك"})
    except Exception as e:
        print("library add:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@library_bp.route('/publish', methods=['POST'])
def publish_assistant():
    if not _is_registered():
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401

    d = request.get_json(silent=True) or {}
    asst_id = d.get('assistant_id')
    if not asst_id:
        return jsonify({"status": "error", "message": "اختر مساعداً"}), 400

    uid = _uid()
    email = session.get('user_email', '')

    try:
        r = (_sb().table("custom_assistants")
             .select("*").eq("id", asst_id).eq("user_id", uid)
             .limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "المساعد غير موجود"}), 404

        asst = r.data[0]

        ex = (_sb().table("public_assistants")
              .select("id").eq("original_id", asst_id)
              .eq("creator_email", email).limit(1).execute())
        if ex.data:
            return jsonify({"status": "error",
                            "message": "هذا المساعد منشور مسبقاً"}), 400

        _sb().table("public_assistants").insert({
            "original_id": asst["id"],
            "name": asst["name"],
            "persona": asst["persona"],
            "color": asst.get("color", "#4a6a8a"),
            "creator_email": email,
            "downloads": 0,
            "active": True
        }).execute()

        return jsonify({"status": "ok", "message": "تم النشر في المكتبة"})
    except Exception as e:
        print("library publish:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================================
#  نسخ المساعد
# ==========================================================

@library_bp.route('/duplicate', methods=['POST'])
def duplicate_assistant():
    if not _is_registered():
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401

    d = request.get_json(silent=True) or {}
    asst_id = d.get('assistant_id')
    if not asst_id:
        return jsonify({"status": "error"}), 400

    uid = _uid()

    try:
        r = (_sb().table("custom_assistants")
             .select("*").eq("id", asst_id).eq("user_id", uid)
             .limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "المساعد غير موجود"}), 404

        asst = r.data[0]

        cnt = len((_sb().table("custom_assistants")
                   .select("id").eq("user_id", uid).execute()).data or [])
        if cnt >= 5:
            return jsonify({"status": "error",
                            "message": "وصلت للحد الأقصى (5 مساعدين)"}), 400

        _sb().table("custom_assistants").insert({
            "user_id": uid,
            "name": asst["name"] + " (نسخة)",
            "persona": asst["persona"],
            "color": asst.get("color", "#4a6a8a")
        }).execute()

        return jsonify({"status": "ok", "message": "تم النسخ"})
    except Exception as e:
        print("duplicate:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================================
#  مشاركة المساعد برابط
# ==========================================================

@library_bp.route('/share', methods=['POST'])
def share_assistant():
    if not _is_registered():
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401

    d = request.get_json(silent=True) or {}
    asst_id = d.get('assistant_id')
    if not asst_id:
        return jsonify({"status": "error"}), 400

    uid = _uid()

    try:
        r = (_sb().table("custom_assistants")
             .select("*").eq("id", asst_id).eq("user_id", uid)
             .limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "المساعد غير موجود"}), 404

        asst = r.data[0]
        token = secrets.token_urlsafe(12)

        _sb().table("shared_assistants").insert({
            "token": token,
            "name": asst["name"],
            "persona": asst["persona"],
            "color": asst.get("color", "#4a6a8a"),
            "creator_email": session.get('user_email', ''),
            "views": 0
        }).execute()

        link = f"{request.host_url.rstrip('/')}/shared-assistant/{token}"
        return jsonify({"status": "ok", "link": link, "token": token})
    except Exception as e:
        print("share:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@library_bp.route('/shared-info/<token>')
def shared_info(token):
    try:
        r = (_sb().table("shared_assistants")
             .select("*").eq("token", token).limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "الرابط غير صالح"}), 404

        asst = r.data[0]

        try:
            _sb().table("shared_assistants").update({
                "views": int(asst.get("views", 0) or 0) + 1
            }).eq("token", token).execute()
        except Exception:
            pass

        return jsonify({
            "status": "ok",
            "assistant": {
                "name": asst["name"],
                "persona": asst["persona"],
                "color": asst.get("color", "#4a6a8a")
            }
        })
    except Exception as e:
        print("shared info:", e)
        return jsonify({"status": "error"}), 500


@library_bp.route('/import-shared', methods=['POST'])
def import_shared():
    if not _is_registered():
        return jsonify({"status": "error", "message": "سجّل دخولك أولاً"}), 401

    d = request.get_json(silent=True) or {}
    token = d.get('token')
    if not token:
        return jsonify({"status": "error"}), 400

    uid = _uid()

    try:
        r = (_sb().table("shared_assistants")
             .select("*").eq("token", token).limit(1).execute())
        if not r.data:
            return jsonify({"status": "error", "message": "الرابط غير صالح"}), 404

        asst = r.data[0]

        cnt = len((_sb().table("custom_assistants")
                   .select("id").eq("user_id", uid).execute()).data or [])
        if cnt >= 5:
            return jsonify({"status": "error",
                            "message": "وصلت للحد الأقصى (5 مساعدين)"}), 400

        _sb().table("custom_assistants").insert({
            "user_id": uid,
            "name": asst["name"],
            "persona": asst["persona"],
            "color": asst.get("color", "#4a6a8a")
        }).execute()

        return jsonify({"status": "ok", "message": "تمت إضافة المساعد"})
    except Exception as e:
        print("import shared:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ==========================================================
#  زرع المساعدين الأوليين
# ==========================================================

@library_bp.route('/seed', methods=['POST'])
def seed_library():
    if not session.get('is_admin'):
        return jsonify({"status": "error", "message": "للمشرف فقط"}), 401

    added = 0
    skipped = 0

    for asst in SEED_ASSISTANTS:
        try:
            ex = (_sb().table("public_assistants")
                  .select("id").eq("name", asst["name"]).limit(1).execute())
            if ex.data:
                skipped += 1
                continue

            _sb().table("public_assistants").insert({
                "name": asst["name"],
                "persona": asst["persona"],
                "color": asst["color"],
                "creator_email": "system@nibras.app",
                "downloads": 0,
                "active": True
            }).execute()
            added += 1
        except Exception as e:
            print(f"seed '{asst['name']}':", e)
            skipped += 1

    return jsonify({
        "status": "ok",
        "added": added,
        "skipped": skipped,
        "total": len(SEED_ASSISTANTS)
    })


# ==========================================================
#  صفحة المساعد المشترك (SVG بدون إيموجي)
# ==========================================================

@library_bp.route('/view/<token>', methods=['GET'])
def view_shared_page(token):
    from flask import render_template_string

    html = """<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>مساعد مشترك - نبراس</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Tahoma,sans-serif}
body{background:linear-gradient(135deg,#f4f7fc 0%,#e8eef5 100%);min-height:100dvh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{background:#fff;border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.1);padding:40px 32px;max-width:440px;width:100%;text-align:center}
.avatar{width:88px;height:88px;border-radius:24px;display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:800;color:#fff;margin:0 auto 20px;box-shadow:0 8px 24px rgba(0,0,0,0.15)}
h1{font-size:24px;color:#1a2b3c;margin-bottom:14px;font-weight:800}
.persona{color:#5a6b7c;line-height:1.8;font-size:15px;margin-bottom:28px;text-align:right;background:#f8f9fb;padding:18px;border-radius:14px;border-right:4px solid #4a6a8a}
.btn{display:flex;align-items:center;justify-content:center;gap:10px;width:100%;padding:16px;background:#4a6a8a;color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;text-decoration:none;font-family:inherit;margin-bottom:12px;transition:all .2s}
.btn:hover{background:#3a5a7a;transform:translateY(-2px);box-shadow:0 8px 20px rgba(74,106,138,0.3)}
.btn.outline{background:0 0;color:#4a6a8a;border:2px solid #4a6a8a}
.btn.outline:hover{background:#4a6a8a;color:#fff}
.btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2.2;fill:none;stroke-linecap:round;stroke-linejoin:round;flex-shrink:0}
.logo{font-size:13px;color:#8b949e;margin-top:20px;display:flex;align-items:center;justify-content:center;gap:6px}
.logo a{color:#4a6a8a;text-decoration:none;font-weight:700}
.logo svg{width:16px;height:16px;stroke:#4a6a8a;stroke-width:2;fill:none}
.loading{color:#8b949e;font-size:14px}
</style>
</head>
<body>
<div class="card">
    <div class="avatar" id="avatar">...</div>
    <h1 id="name"><span class="loading">جاري التحميل...</span></h1>
    <div class="persona" id="persona"></div>
    <a href="/?import={{ token }}" class="btn">
        <svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        <span>إضافة لحسابي في نبراس</span>
    </a>
    <a href="/" class="btn outline">
        <svg viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
        <span>فتح نبراس</span>
    </a>
    <div class="logo">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
        <span>مدعوم من <a href="/">نبراس</a></span>
    </div>
</div>
<script>
(async function(){
    try{
        const r = await fetch('/api/library/shared-info/{{ token }}');
        const d = await r.json();
        if(d.status !== 'ok'){
            document.body.innerHTML = '<div class="card"><h1>الرابط غير صالح</h1></div>';
            return;
        }
        const a = d.assistant;
        const av = document.getElementById('avatar');
        av.style.background = a.color;
        av.textContent = a.name.charAt(0);
        document.getElementById('name').textContent = a.name;
        document.getElementById('persona').textContent = a.persona;
        document.title = a.name + ' - نبراس';
    }catch(e){
        document.body.innerHTML = '<div class="card"><h1>تعذر التحميل</h1></div>';
    }
})();
</script>
</body>
</html>"""
    return render_template_string(html, token=token)


# ==========================================================
#  نهاية library.py
# ==========================================================
