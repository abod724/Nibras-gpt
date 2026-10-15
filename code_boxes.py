# ==========================================================
#  code_boxes.py — صناديق الكود الأنيقة + ألوان برمجية
#  يُدمج تلقائياً في HT عبر index()
# ==========================================================

# يُضاف في <head>
CODE_BOXES_HEAD = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" defer></script>
"""


CODE_BOXES_CSS = """
/* ══════════════════════════════════════════════════════
   صناديق الكود — Nibras Code Boxes
   ══════════════════════════════════════════════════════ */
.nibras-copy-box{direction:rtl;margin:18px 0;border:1px solid var(--border-color);border-radius:14px;overflow:hidden;background:var(--bg-app);color:var(--text-primary);box-shadow:0 2px 8px rgba(0,0,0,0.04)}
.nibras-copy-header{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 14px;background:var(--bg-hover);border-bottom:1px solid var(--border-color)}
.nibras-copy-title{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:var(--text-secondary);letter-spacing:.3px}
.nibras-copy-title svg{width:16px;height:16px;flex-shrink:0;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.nibras-copy-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:6px 10px;border:1px solid var(--border-color);border-radius:9px;background:var(--bg-app);color:var(--text-primary);font-size:12px;font-weight:600;cursor:pointer;transition:background .2s,transform .2s,border-color .2s,color .2s;font-family:inherit;-webkit-tap-highlight-color:transparent}
.nibras-copy-button:hover{background:var(--bg-hover)}
.nibras-copy-button:active{transform:scale(.95)}
.nibras-copy-button.copied{color:#10b981;border-color:#10b981;background:rgba(16,185,129,0.08)}
.nibras-copy-button svg{width:14px;height:14px;flex-shrink:0;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.nibras-copy-content{padding:16px;line-height:1.9;overflow-wrap:anywhere}
.nibras-copy-content pre{margin:0;padding:16px;direction:ltr;text-align:left;overflow-x:auto;white-space:pre;background:var(--bg-hover);font-size:13px;line-height:1.7;border-radius:10px;font-family:Consolas,Monaco,'Courier New',monospace}
.nibras-copy-box code{font-family:Consolas,Monaco,'Courier New',monospace}
.nibras-copy-box pre code{background:transparent;padding:0;color:var(--text-primary);display:block}
.nibras-copy-content p code,
.nibras-response p code{direction:ltr;display:inline-block;padding:2px 6px;border-radius:6px;background:var(--bg-hover);border:1px solid var(--border-color);font-size:0.9em;font-family:Consolas,Monaco,monospace;color:var(--primary-color)}

/* ══════════════════════════════════════════════════════
   ألوان الكود البرمجية (Highlight.js tokens)
   ══════════════════════════════════════════════════════ */
.nibras-copy-box .hljs{color:var(--text-primary);background:transparent}
.nibras-copy-box .hljs-comment,
.nibras-copy-box .hljs-quote{color:#6a737d;font-style:italic}
.nibras-copy-box .hljs-keyword,
.nibras-copy-box .hljs-selector-tag,
.nibras-copy-box .hljs-literal,
.nibras-copy-box .hljs-doctag{color:#d73a49;font-weight:600}
.nibras-copy-box .hljs-string,
.nibras-copy-box .hljs-regexp,
.nibras-copy-box .hljs-addition{color:#032f62}
.nibras-copy-box .hljs-number,
.nibras-copy-box .hljs-symbol,
.nibras-copy-box .hljs-bullet,
.nibras-copy-box .hljs-link{color:#005cc5}
.nibras-copy-box .hljs-title,
.nibras-copy-box .hljs-section,
.nibras-copy-box .hljs-name,
.nibras-copy-box .hljs-selector-id,
.nibras-copy-box .hljs-selector-class{color:#6f42c1;font-weight:600}
.nibras-copy-box .hljs-built_in,
.nibras-copy-box .hljs-class .hljs-title,
.nibras-copy-box .hljs-type{color:#e36209}
.nibras-copy-box .hljs-attr,
.nibras-copy-box .hljs-attribute,
.nibras-copy-box .hljs-variable,
.nibras-copy-box .hljs-template-variable{color:#005cc5}
.nibras-copy-box .hljs-meta{color:#b31d28;font-weight:600}
.nibras-copy-box .hljs-operator,
.nibras-copy-box .hljs-punctuation{color:var(--text-secondary)}
.nibras-copy-box .hljs-emphasis{font-style:italic}
.nibras-copy-box .hljs-strong{font-weight:700}
.nibras-copy-box .hljs-deletion{color:#b31d28;background:#ffeef0}

/* ألوان الوضع الليلي (مستوحاة من GitHub Dark) */
html.dark-mode .nibras-copy-content pre{background:#0d1117;color:#c9d1d9}
html.dark-mode .nibras-copy-box .hljs{color:#c9d1d9}
html.dark-mode .nibras-copy-box .hljs-comment,
html.dark-mode .nibras-copy-box .hljs-quote{color:#8b949e}
html.dark-mode .nibras-copy-box .hljs-keyword,
html.dark-mode .nibras-copy-box .hljs-selector-tag,
html.dark-mode .nibras-copy-box .hljs-literal,
html.dark-mode .nibras-copy-box .hljs-doctag{color:#ff7b72}
html.dark-mode .nibras-copy-box .hljs-string,
html.dark-mode .nibras-copy-box .hljs-regexp,
html.dark-mode .nibras-copy-box .hljs-addition{color:#a5d6ff}
html.dark-mode .nibras-copy-box .hljs-number,
html.dark-mode .nibras-copy-box .hljs-symbol,
html.dark-mode .nibras-copy-box .hljs-bullet,
html.dark-mode .nibras-copy-box .hljs-link{color:#79c0ff}
html.dark-mode .nibras-copy-box .hljs-title,
html.dark-mode .nibras-copy-box .hljs-section,
html.dark-mode .nibras-copy-box .hljs-name,
html.dark-mode .nibras-copy-box .hljs-selector-id,
html.dark-mode .nibras-copy-box .hljs-selector-class{color:#d2a8ff}
html.dark-mode .nibras-copy-box .hljs-built_in,
html.dark-mode .nibras-copy-box .hljs-class .hljs-title,
html.dark-mode .nibras-copy-box .hljs-type{color:#ffa657}
html.dark-mode .nibras-copy-box .hljs-attr,
html.dark-mode .nibras-copy-box .hljs-attribute,
html.dark-mode .nibras-copy-box .hljs-variable,
html.dark-mode .nibras-copy-box .hljs-template-variable{color:#79c0ff}
html.dark-mode .nibras-copy-box .hljs-meta{color:#ff7b72}
html.dark-mode .nibras-copy-box .hljs-deletion{color:#ffdcd7;background:#67060c}
html.dark-mode .nibras-copy-content p code{background:#0d1117;color:#79c0ff}

@media(max-width:600px){
    .nibras-copy-box{border-radius:11px;margin:14px 0}
    .nibras-copy-header{padding:9px 10px}
    .nibras-copy-content,.nibras-copy-box pre{padding:12px}
    .nibras-copy-title{font-size:12px}
    .nibras-copy-title svg{width:14px;height:14px}
    .nibras-copy-button{padding:5px 9px;font-size:11px}
    .nibras-copy-button svg{width:13px;height:13px}
    .nibras-copy-content pre{font-size:12px;padding:12px}
}
"""


CODE_BOXES_JS = """
(function(){
    // ═══ أيقونات SVG للغات البرمجة ═══
    var LANG_ICONS = {
        python:     '<svg viewBox="0 0 24 24"><path d="M12 2c-2.5 0-4 .8-4 2.5V6h5v1H6.5C4.5 7 3 8.5 3 11s1.5 4 3.5 4H8v-2.5c0-1.7 1.5-2.5 4-2.5h3c1.5 0 2.5-1 2.5-2.5V4.5C17.5 2.8 15 2 12 2z"/><circle cx="10" cy="4.5" r=".7" fill="currentColor" stroke="none"/><path d="M12 22c2.5 0 4-.8 4-2.5V18h-5v-1h6.5c2 0 3.5-1.5 3.5-4s-1.5-4-3.5-4H16v2.5c0 1.7-1.5 2.5-4 2.5h-3c-1.5 0-2.5 1-2.5 2.5v3.5C6.5 21.2 9 22 12 22z"/><circle cx="14" cy="19.5" r=".7" fill="currentColor" stroke="none"/></svg>',
        javascript: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 10v6a1.5 1.5 0 0 1-3 0"/><path d="M13 16c0 1 .5 1.5 1.5 1.5S16 17 16 16c0-1.5-3-1-3-2.5 0-1 .5-1.5 1.5-1.5S16 12.5 16 13"/></svg>',
        js:         '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 10v6a1.5 1.5 0 0 1-3 0"/><path d="M13 16c0 1 .5 1.5 1.5 1.5S16 17 16 16c0-1.5-3-1-3-2.5 0-1 .5-1.5 1.5-1.5S16 12.5 16 13"/></svg>',
        typescript: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 11h5"/><path d="M10.5 11v5"/><path d="M15 16c0 1 .5 1.5 1.5 1.5S18 17 18 16c0-1.5-3-1-3-2.5 0-1 .5-1.5 1.5-1.5S18 12.5 18 13"/></svg>',
        ts:         '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M8 11h5"/><path d="M10.5 11v5"/><path d="M15 16c0 1 .5 1.5 1.5 1.5S18 17 18 16c0-1.5-3-1-3-2.5 0-1 .5-1.5 1.5-1.5S18 12.5 18 13"/></svg>',
        html:       '<svg viewBox="0 0 24 24"><path d="M9 8l-4 4 4 4"/><path d="M15 8l4 4-4 4"/></svg>',
        xml:        '<svg viewBox="0 0 24 24"><path d="M9 8l-4 4 4 4"/><path d="M15 8l4 4-4 4"/></svg>',
        css:        '<svg viewBox="0 0 24 24"><path d="M8 4h8"/><path d="M10 4l-1 8 3 2 3-2-1-8"/><path d="M10 16v4"/><path d="M14 16v4"/></svg>',
        scss:       '<svg viewBox="0 0 24 24"><path d="M8 4h8"/><path d="M10 4l-1 8 3 2 3-2-1-8"/><path d="M10 16v4"/><path d="M14 16v4"/></svg>',
        json:       '<svg viewBox="0 0 24 24"><path d="M8 4h-2a2 2 0 0 0-2 2v3a2 2 0 0 1-2 2 2 2 0 0 1 2 2v3a2 2 0 0 0 2 2h2"/><path d="M16 4h2a2 2 0 0 1 2 2v3a2 2 0 0 0 2 2 2 2 0 0 0-2 2v3a2 2 0 0 1-2 2h-2"/></svg>',
        bash:       '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/></svg>',
        shell:      '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/></svg>',
        sh:         '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/></svg>',
        java:       '<svg viewBox="0 0 24 24"><path d="M9 17c-2 0-3 1-3 2 0 1.5 2 2 5 2s6-1 6-2.5-1.5-1.5-3-1.5"/><path d="M14 3c0 2-2 3-2 5 0 1.5 1 2 1 3 0 .8-.6 1.3-1 1.5"/><path d="M11 3c0 1.5-1.5 2.5-1.5 4 0 1 .5 1.5.5 2.5"/></svg>',
        cpp:        '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9 10v4M7 12h4"/><path d="M15 11a3 3 0 1 0 0 4"/><path d="M17 10v4M15 12h4"/></svg>',
        'c++':      '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9 10v4M7 12h4"/><path d="M15 11a3 3 0 1 0 0 4"/><path d="M17 10v4M15 12h4"/></svg>',
        c:          '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15 11a3 3 0 1 0 0 4"/></svg>',
        csharp:     '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15 11a3 3 0 1 0 0 4"/><path d="M16 10v4M14 11h4M16 12h-4"/></svg>',
        'c#':       '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M15 11a3 3 0 1 0 0 4"/><path d="M16 10v4M14 11h4M16 12h-4"/></svg>',
        go:         '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="9" ry="6"/><circle cx="9" cy="11" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="11" r="1" fill="currentColor" stroke="none"/></svg>',
        golang:     '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="9" ry="6"/><circle cx="9" cy="11" r="1" fill="currentColor" stroke="none"/><circle cx="15" cy="11" r="1" fill="currentColor" stroke="none"/></svg>',
        rust:       '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>',
        php:        '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="10" ry="6"/><path d="M8 10h2c1 0 1.5.5 1.5 1.2S11 12.5 10 12.5H9l-.5 2"/><path d="M14 10h1.5c1 0 1.5.5 1.5 1.2S16.5 12.5 15.5 12.5H15l-.5 2"/></svg>',
        ruby:       '<svg viewBox="0 0 24 24"><path d="M12 4l8 6-8 10L4 10z"/><path d="M4 10h16"/><path d="M12 4l-3 6 3 10 3-10z"/></svg>',
        swift:      '<svg viewBox="0 0 24 24"><path d="M5 4l9 12c-1.5 2-3.5 3-5.5 3S5 18 5 16c0-2 1.5-3.5 3-4.5"/><path d="M10 4c3 4 6 7 9 8-1 3-4 6-8 6"/></svg>',
        kotlin:     '<svg viewBox="0 0 24 24"><path d="M5 5h14L12 12l7 7H5z"/></svg>',
        dart:       '<svg viewBox="0 0 24 24"><path d="M5 5v10l5 5h10V5z"/><path d="M5 15l9-9h6"/></svg>',
        sql:        '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>',
        yaml:       '<svg viewBox="0 0 24 24"><path d="M5 5v14"/><path d="M11 7h8"/><path d="M11 12h8"/><path d="M11 17h5"/></svg>',
        yml:        '<svg viewBox="0 0 24 24"><path d="M5 5v14"/><path d="M11 7h8"/><path d="M11 12h8"/><path d="M11 17h5"/></svg>',
        markdown:   '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M6 15v-6l2 3 2-3v6"/><path d="M14 15l-2-3h4z"/><path d="M16 12v3"/></svg>',
        md:         '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M6 15v-6l2 3 2-3v6"/><path d="M14 15l-2-3h4z"/><path d="M16 12v3"/></svg>',
        docker:     '<svg viewBox="0 0 24 24"><path d="M3 12h18a8 8 0 0 1-8 8H7a4 4 0 0 1-4-4z"/><path d="M6 10h3v2H6zM10 10h3v2h-3zM14 10h3v2h-3zM10 6h3v2h-3zM14 6h3v2h-3z"/></svg>',
        dockerfile: '<svg viewBox="0 0 24 24"><path d="M3 12h18a8 8 0 0 1-8 8H7a4 4 0 0 1-4-4z"/><path d="M6 10h3v2H6zM10 10h3v2h-3zM14 10h3v2h-3z"/></svg>',
        git:        '<svg viewBox="0 0 24 24"><circle cx="12" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><circle cx="6" cy="12" r="2"/><path d="M12 8v8M12 12H8"/></svg>',
        regex:      '<svg viewBox="0 0 24 24"><path d="M12 4v8"/><path d="M8 8h8"/><circle cx="6" cy="18" r="2"/><circle cx="12" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
        default:    '<svg viewBox="0 0 24 24"><path d="M9 8l-4 4 4 4"/><path d="M15 8l4 4-4 4"/></svg>'
    };

    var ICON_COPY  = '<svg viewBox="0 0 24 24"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>';
    var ICON_CHECK = '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>';

    function getLangIcon(lang){
        var key = String(lang || '').toLowerCase().trim();
        if(LANG_ICONS[key]) return LANG_ICONS[key];
        if(key === 'py') return LANG_ICONS.python;
        if(key === 'node' || key === 'nodejs') return LANG_ICONS.javascript;
        if(key === 'htm') return LANG_ICONS.html;
        if(key === 'cs') return LANG_ICONS.csharp;
        if(key === 'rs') return LANG_ICONS.rust;
        if(key === 'rb') return LANG_ICONS.ruby;
        if(key === 'kt') return LANG_ICONS.kotlin;
        return LANG_ICONS.default;
    }

    function getLangLabel(lang){
        var key = String(lang || '').toLowerCase().trim();
        if(!key) return 'كود';
        return key;
    }

    // ═══ تطبيق الألوان البرمجية ═══
    function highlightCode(codeEl, lang){
        if(!codeEl) return;
        if(typeof hljs === 'undefined') return;  // المكتبة ما تحمّلت
        try{
            if(lang && hljs.getLanguage(lang)){
                hljs.highlightElement(codeEl);
            } else {
                // كشف تلقائي
                hljs.highlightElement(codeEl);
            }
        }catch(e){ /* تجاهل الأخطاء */ }
    }

    function enhanceCodeBlocks(container){
        if(!container) return;
        var pres = container.querySelectorAll('pre');
        pres.forEach(function(pre){
            if(pre.closest('.nibras-copy-box')) return;
            var codeEl = pre.querySelector('code');
            if(!codeEl) return;

            var cls = codeEl.className || '';
            var langMatch = cls.match(/language-([a-z0-9+#-]+)/i);
            var lang = langMatch ? langMatch[1].toLowerCase() : '';

            // نحتفظ بالنص الأصلي قبل التلوين
            var codeText = codeEl.textContent;
            if(!codeText || !codeText.trim()) return;

            // نطبق الألوان أولاً
            if(lang){
                // تأكد أن hljs يعرف اللغة
                if(typeof hljs !== 'undefined' && !hljs.getLanguage(lang)){
                    codeEl.classList.add('language-plaintext');
                }
            }
            highlightCode(codeEl, lang);

            // ثم نبني الصندوق
            var wrapper = document.createElement('div');
            wrapper.className = 'nibras-copy-box';

            var header = document.createElement('div');
            header.className = 'nibras-copy-header';

            var title = document.createElement('span');
            title.className = 'nibras-copy-title';
            title.innerHTML = getLangIcon(lang) + '<span>' + getLangLabel(lang) + '</span>';

            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'nibras-copy-button';
            btn.innerHTML = ICON_COPY + '<span>نسخ</span>';

            header.appendChild(title);
            header.appendChild(btn);

            var content = document.createElement('div');
            content.className = 'nibras-copy-content';
            content.appendChild(pre.cloneNode(true));

            wrapper.appendChild(header);
            wrapper.appendChild(content);

            btn.addEventListener('click', function(){
                var done = function(){
                    btn.classList.add('copied');
                    btn.innerHTML = ICON_CHECK + '<span>تم</span>';
                    setTimeout(function(){
                        btn.classList.remove('copied');
                        btn.innerHTML = ICON_COPY + '<span>نسخ</span>';
                    }, 1500);
                };
                var fallback = function(){
                    var ta = document.createElement('textarea');
                    ta.value = codeText;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.select();
                    try{ document.execCommand('copy'); done(); }catch(e){}
                    document.body.removeChild(ta);
                };
                if(navigator.clipboard && navigator.clipboard.writeText){
                    navigator.clipboard.writeText(codeText).then(done).catch(fallback);
                } else {
                    fallback();
                }
            });

            pre.replaceWith(wrapper);
        });
    }

    window.enhanceCodeBlocks = enhanceCodeBlocks;
})();
"""
