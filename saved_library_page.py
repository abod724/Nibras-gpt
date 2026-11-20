"""Mobile-first Arabic file library with private downloads and 30-day expiry."""
SAVED_LIBRARY_HTML = r'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>مكتبتي | نبراس GP</title>
<style>
:root{color-scheme:light;--ink:#172234;--muted:#657487;--primary:#3b698c;--bg:#f4f7fa;--line:#e2e8f0}
*{box-sizing:border-box}body{background:var(--bg);color:var(--ink);margin:0;font-family:system-ui,'Segoe UI',Tahoma,Arial,sans-serif}
main{max-width:820px;margin:auto;padding:18px 14px 60px}.head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:12px 0 22px}
h1{margin:0;font-size:24px}.back{color:var(--primary);text-decoration:none;border:1px solid var(--line);padding:10px 14px;border-radius:12px;background:white}
.panel{background:white;border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:15px}
h2{margin:0 0 12px;font-size:18px}p{line-height:1.7}small,.muted{color:var(--muted)}
.bar{background:#e6edf2;border-radius:14px;overflow:hidden;height:10px;margin:12px 0}.used{height:100%;width:0;background:#378b80;transition:width .2s}
.row{display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap}.hint{font-size:13px;color:var(--muted);margin-top:12px}
button,.action{cursor:pointer;background:white;border:1px solid var(--line);border-radius:10px;color:var(--primary);padding:9px 12px;font:inherit;font-size:13px;text-decoration:none;display:inline-block}
.primary{background:var(--primary);color:white;border-color:var(--primary)}button:disabled{opacity:.5;cursor:wait}
.file{padding:13px 0;border-top:1px solid var(--line);display:flex;align-items:flex-start;gap:11px}.file:first-child{border-top:0}
.file-icon{background:#f0f5fa;border-radius:12px;padding:11px;font-size:24px;line-height:1}
.file-info{flex:1;min-width:0}.file-name{font-weight:650;overflow-wrap:anywhere}.file-meta{font-size:12px;color:var(--muted);margin:6px 0}
.actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.danger{color:#be2b38}
.alert{background:#fffbeb;border:1px solid #f3de9c;padding:12px;border-radius:13px;color:#835715;margin-bottom:13px;font-size:13px;line-height:1.7}
input[type=file]{display:none}.empty{text-align:center;color:var(--muted);padding:28px 12px}
.legacy{display:flex;gap:10px;overflow-x:auto;padding:8px 0}.legacy img{width:110px;height:95px;object-fit:cover;border-radius:12px}
.toast{position:fixed;bottom:18px;right:15px;left:15px;max-width:600px;margin:auto;background:#172234;color:white;border-radius:12px;padding:13px 16px;text-align:center;box-shadow:0 5px 25px #0003;z-index:100}
</style></head><body><main>
<div class="head"><h1>مكتبتي</h1><a class="back" href="/" aria-label="رجوع للمحادثة">رجوع</a></div>
<section class="panel">
 <div class="row"><h2>المساحة</h2><span id="usage" class="muted"></span></div>
 <div class="bar"><div class="used" id="usageBar"></div></div>
 <div class="row"><button class="primary" id="uploadBtn">+ إضافة ملف</button></div>
 <input id="fileInput" type="file" accept=".pdf,.docx,.txt,.eml,.jpg,.jpeg,.png,.webp,.mp3,.wav,.m4a,.ogg,.mp4,.mov,.webm">
</section>
<div id="alerts"></div>
<section class="panel"><h2>الملفات</h2><div id="files" class="empty">جاري التحميل...</div></section>
<section class="panel" id="legacySection" hidden><h2>الصور</h2><div class="legacy" id="oldImages"></div></section>
</main>
<script>
const $=id=>document.getElementById(id);
const fmtSize=bytes=>(bytes/1048576).toFixed(bytes>=1048576?1:2)+' MB';
function toast(t){const el=document.createElement('div');el.className='toast';el.textContent=t;document.body.appendChild(el);setTimeout(()=>el.remove(),4500);}
function make(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function button(text,fn,cls){const b=make('button',cls||'',text);b.onclick=fn;return b;}
async function api(url,opts){const response=await fetch(url,{credentials:'same-origin',...opts});const data=await response.json().catch(()=>({}));if(!response.ok)throw Error(data.message||'تعذّر تنفيذ الطلب');return data;}
async function load(){
 try{
 const data=await api('/library/files'),q=data.quota;
 $('usage').textContent=q.count+' / '+q.max_count+' · '+fmtSize(q.used)+' من '+fmtSize(q.max_bytes);
 $('usageBar').style.width=Math.min(100,100*q.used/q.max_bytes)+'%';
 const alerts=$('alerts');alerts.replaceChildren();
 (data.alerts||[]).forEach(f=>{
   const d=make('div','alert','⚠️ «'+f.name+'» · الحذف بعد '+(f.days_left===1?'يوم':' '+f.days_left+' أيام'));
   alerts.appendChild(d);
 });
 const host=$('files');host.replaceChildren();
 if(!data.files.length){host.appendChild(make('div','empty','لا توجد ملفات'));return;}
 data.files.forEach(f=>{
  const item=make('div','file'),icon=make('div','file-icon',/\.(jpe?g|png|webp)$/i.test(f.name)?'🖼️':/\.(mp4|mov|webm)$/i.test(f.name)?'🎞️':/\.(mp3|wav|ogg|m4a)$/i.test(f.name)?'🎧':'📄');
  const info=make('div','file-info'),name=make('div','file-name',f.name),meta=make('div','file-meta',fmtSize(f.size)+' · متبقي '+f.days_left+' يوم');
  const actions=make('div','actions'),dl=make('a','action','تحميل');
  dl.href='/library/files/'+encodeURIComponent(f.id)+'/download';dl.target='_blank';dl.rel='noopener noreferrer';
  actions.appendChild(dl);
  if(/\.(pdf|docx|txt|eml)$/i.test(f.name))
    actions.appendChild(button('استخدام',async()=>{
      try{await api('/library/files/'+encodeURIComponent(f.id)+'/use',{method:'POST'});
          sessionStorage.setItem('nibras-library-open',f.name);window.location.href='/';}
      catch(e){toast(e.message);}
    }));
  actions.appendChild(button('حذف',async()=>{
    if(!confirm('هل تريد حذف «'+f.name+'» نهائيًا من مكتبتي؟'))return;
    try{await api('/library/files/'+encodeURIComponent(f.id)+'/delete',{method:'POST'});toast('تم حذف الملف');load();}
    catch(e){toast(e.message);}
  },'danger'));
  info.append(name,meta,actions);item.append(icon,info);host.appendChild(item);
 });
 }catch(e){$('files').textContent=e.message||'تعذر تحميل الملفات';}
}
async function legacy(){
 try{const r=await api('/library/images'),host=$('oldImages');host.replaceChildren();
 (r.images||[]).forEach(img=>{const src=img.image_url||img.image_data;if(typeof src!=='string'||!(src.startsWith('https://')||src.startsWith('data:image/')))return;
 const a=make('a');a.href=src;a.target='_blank';a.rel='noopener noreferrer';const pic=make('img');pic.src=src;pic.alt=String(img.title||'صورة');pic.loading='lazy';a.appendChild(pic);host.appendChild(a);});
 $('legacySection').hidden=!host.children.length;
 }catch(e){$('legacySection').hidden=true;}
}
$('uploadBtn').onclick=()=>$('fileInput').click();
$('fileInput').onchange=async e=>{
 const file=e.target.files[0];e.target.value='';if(!file)return;
 const btn=$('uploadBtn');btn.disabled=true;btn.textContent='جاري الحفظ...';
 try{const fd=new FormData();fd.append('file',file);await api('/library/files/upload',{method:'POST',body:fd});toast('تم حفظ الملف لمدة 30 يومًا');await load();}
 catch(e){toast(e.message);}
 finally{btn.disabled=false;btn.textContent='+ إضافة ملف';}
};
load();legacy();
</script></body></html>'''