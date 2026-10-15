# ==========================================================
#  memory_page.py — صفحة الذاكرة
#  تُستدعى من app.py وتُدمج داخل الإعدادات (subPage 'memory')
# ==========================================================

MEMORY_CSS = """
.memory-page{display:flex;flex-direction:column;gap:14px}
.memory-toggle-card{background:var(--bg-app);border-radius:16px;padding:16px;box-shadow:0 1px 3px var(--shadow-color)}
.memory-toggle-row{display:flex;justify-content:space-between;align-items:center;gap:12px}
.memory-toggle-info{flex:1;min-width:0}
.memory-toggle-title{font-size:15px;font-weight:700;color:var(--text-primary);margin-bottom:4px}
.memory-toggle-desc{font-size:12.5px;color:var(--text-secondary);line-height:1.6}
.memory-switch{position:relative;display:inline-block;width:50px;height:28px;flex-shrink:0}
.memory-switch input{opacity:0;width:0;height:0}
.memory-slider{position:absolute;cursor:pointer;inset:0;background:var(--border-color);border-radius:28px;transition:.3s}
.memory-slider:before{position:absolute;content:"";height:22px;width:22px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;box-shadow:0 2px 4px rgba(0,0,0,0.15)}
.memory-switch input:checked+.memory-slider{background:var(--primary-color)}
.memory-switch input:checked+.memory-slider:before{transform:translateX(-22px)}
.memory-field{background:var(--bg-app);border-radius:16px;padding:14px 16px;box-shadow:0 1px 3px var(--shadow-color)}
.memory-field-label{font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-align:right}
.memory-field-input{width:100%;padding:12px 0;border:none;background:transparent;font-size:15px;color:var(--text-primary);font-family:inherit;outline:none;text-align:right;box-sizing:border-box;font-weight:500}
.memory-field-input::placeholder{color:var(--placeholder-color)}
.memory-field-textarea{min-height:100px;resize:none;line-height:1.7}
.memory-auto-section{background:var(--bg-app);border-radius:16px;padding:16px;box-shadow:0 1px 3px var(--shadow-color)}
.memory-auto-title{font-size:14px;font-weight:700;color:var(--text-primary);margin-bottom:12px;display:flex;align-items:center;gap:8px}
.memory-auto-title svg{width:16px;height:16px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}
.memory-auto-empty{font-size:13px;color:var(--text-secondary);text-align:center;padding:20px 0;line-height:1.7}
.memory-group{margin-bottom:14px}
.memory-group:last-child{margin-bottom:0}
.memory-group-title{font-size:12px;font-weight:700;color:var(--text-secondary);letter-spacing:.5px;margin-bottom:8px;text-align:right}
.memory-tag-row{display:flex;flex-wrap:wrap;gap:6px}
.memory-tag{display:inline-block;padding:5px 12px;background:var(--bg-hover);border-radius:20px;font-size:12.5px;color:var(--text-primary);font-weight:500}
.memory-tag.primary{background:rgba(74,106,138,0.12);color:var(--primary-color)}
.memory-save-btn{width:100%;padding:14px;background:var(--primary-color);color:#fff;border:none;border-radius:14px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;margin-top:4px}
.memory-save-btn:active{transform:scale(0.98)}
.memory-save-btn:disabled{opacity:0.6;cursor:not-allowed}
"""

MEMORY_HTML = """
<div class="memory-page">
  <div class="memory-toggle-card">
    <div class="memory-toggle-row">
      <div class="memory-toggle-info">
        <div class="memory-toggle-title">تفعيل الذاكرة</div>
        <div class="memory-toggle-desc">اسمح لنبراس بتخصيص تجربتك بناءً على محادثاتك وملفاتك</div>
      </div>
      <label class="memory-switch">
        <input type="checkbox" id="memoryToggle" onchange="toggleMemoryEnabled(this.checked)">
        <span class="memory-slider"></span>
      </label>
    </div>
  </div>
  <div class="memory-field">
    <div class="memory-field-label">اسمك المستعار</div>
    <input type="text" id="mem-nickname" class="memory-field-input" placeholder="الاسم المفضل" maxlength="100">
  </div>
  <div class="memory-field">
    <div class="memory-field-label">مهنتك</div>
    <input type="text" id="mem-job" class="memory-field-input" placeholder="مهندس، طالب، إلخ." maxlength="200">
  </div>
  <div class="memory-field">
    <div class="memory-field-label">المزيد عنك</div>
    <textarea id="mem-more" class="memory-field-input memory-field-textarea" placeholder="الاهتمامات أو القيم أو التفضيلات التي يجب مراعاتها" maxlength="1000"></textarea>
  </div>
  <div class="memory-auto-section">
    <div class="memory-auto-title">
      <svg viewBox="0 0 24 24"><path d="M12 2a5 5 0 0 0-5 5c0 1.5.7 2.8 1.8 3.7A5 5 0 0 0 7 15a5 5 0 0 0 5 5 5 5 0 0 0 5-5 5 5 0 0 0-1.8-4.3A5 5 0 0 0 17 7a5 5 0 0 0-5-5z"/></svg>
      <span>ما يعرفه نبراس عنك تلقائياً</span>
    </div>
    <div id="autoMemoryContent"><div class="memory-auto-empty">لا توجد معلومات بعد</div></div>
  </div>
  <button type="button" class="memory-save-btn" id="mem-save-btn" onclick="saveManualMemory()">حفظ</button>
</div>
"""

MEMORY_JS = """
async function loadMemory(){
    const nn=document.getElementById('mem-nickname');
    const jb=document.getElementById('mem-job');
    const mr=document.getElementById('mem-more');
    const tg=document.getElementById('memoryToggle');
    const ac=document.getElementById('autoMemoryContent');
    if(!nn||!ac)return;
    if(!IS_REGISTERED){
        if(tg)tg.disabled=true;
        if(nn)nn.disabled=true;
        if(jb)jb.disabled=true;
        if(mr)mr.disabled=true;
        ac.innerHTML='<div class="memory-auto-empty">سجّل دخولك لحفظ ذاكرتك بشكل دائم.</div>';
        return;
    }
    try{
        const r=await fetch('/get_memory');
        const d=await r.json();
        nn.value=d.nickname||'';
        jb.value=d.job||'';
        mr.value=d.more_about||'';
        if(tg)tg.checked=d.memory_enabled!==false;
        const ps=d.profile_summary||{};
        const w=ps.work||{}, sk=ps.skills||{}, it=ps.interests||{};
        let html='';
        const tags=(arr,cls)=>'<div class="memory-tag-row">'+(arr||[]).map(x=>'<span class="memory-tag '+(cls||'')+'">'+escapeHtml(String(x))+'</span>').join('')+'</div>';
        if(w.current_role||w.field) html+='<div class="memory-group"><div class="memory-group-title">العمل</div>'+tags([w.current_role,w.field,w.company_type].filter(Boolean),'primary')+'</div>';
        if(w.projects&&w.projects.length) html+='<div class="memory-group"><div class="memory-group-title">مشاريع</div>'+tags(w.projects)+'</div>';
        if(w.tools_used&&w.tools_used.length) html+='<div class="memory-group"><div class="memory-group-title">أدوات</div>'+tags(w.tools_used)+'</div>';
        if(sk.technical&&sk.technical.length) html+='<div class="memory-group"><div class="memory-group-title">مهارات تقنية</div>'+tags(sk.technical,'primary')+'</div>';
        if(sk.learning_now&&sk.learning_now.length) html+='<div class="memory-group"><div class="memory-group-title">يتعلم حالياً</div>'+tags(sk.learning_now)+'</div>';
        if(it.topics&&it.topics.length) html+='<div class="memory-group"><div class="memory-group-title">اهتمامات</div>'+tags(it.topics,'primary')+'</div>';
        if(it.goals&&it.goals.length) html+='<div class="memory-group"><div class="memory-group-title">أهداف</div>'+tags(it.goals)+'</div>';
        if(it.hobbies&&it.hobbies.length) html+='<div class="memory-group"><div class="memory-group-title">هوايات</div>'+tags(it.hobbies)+'</div>';
        if(!html) html='<div class="memory-auto-empty">لا توجد معلومات تلقائية بعد.<br>سولف مع نبراس وهو بيتعلم عنك.</div>';
        ac.innerHTML=html;
    }catch(e){ac.innerHTML='<div class="memory-auto-empty">تعذر التحميل.</div>';}
}

async function saveManualMemory(){
    const btn=document.getElementById('mem-save-btn');
    const nn=(document.getElementById('mem-nickname').value||'').trim();
    const jb=(document.getElementById('mem-job').value||'').trim();
    const mr=(document.getElementById('mem-more').value||'').trim();
    if(btn){btn.disabled=true;btn.textContent='جاري الحفظ...';}
    try{
        const r=await fetch('/update_manual_memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nickname:nn,job:jb,more_about:mr})});
        const d=await r.json();
        if(d.status==='ok'){
            showToast('تم الحفظ');
            if(btn){btn.textContent='✓ تم الحفظ';setTimeout(()=>{btn.textContent='حفظ';btn.disabled=false;},1200);}
        } else {
            showToast(d.message||'فشل الحفظ');
            if(btn){btn.textContent='حفظ';btn.disabled=false;}
        }
    }catch(e){
        showToast('تعذر الاتصال');
        if(btn){btn.textContent='حفظ';btn.disabled=false;}
    }
}

async function toggleMemoryEnabled(enabled){
    try{
        await fetch('/toggle_memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});
        showToast(enabled?'تم تفعيل الذاكرة':'تم إيقاف الذاكرة');
    }catch(e){showToast('تعذر الاتصال');}
}

window.loadMemory=loadMemory;
window.saveManualMemory=saveManualMemory;
window.toggleMemoryEnabled=toggleMemoryEnabled;
"""
