HT = r"""<!DOCTYPE html><html lang="ar" dir="rtl"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=5.0"/><meta name="screen-orientation" content="portrait"><meta name="x5-orientation" content="portrait"><meta name="full-screen" content="no"><meta name="x5-fullscreen" content="false"><meta name="browsermode" content="application"><meta name="x5-page-mode" content="app"><title>نبراس GP مساعد ذكي</title><link rel="manifest" href="/static/manifest.json"><link rel="icon" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="180x180" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="192x192" href="/static/icon-192.png"><link rel="apple-touch-icon" sizes="512x512" href="/static/icon-512.png"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="نبراس"><meta name="theme-color" content="#ffffff">
<script src="https://html2canvas.hertzen.com/dist/html2canvas.min.js"></script>
<style>:root{--bg-body:#f4f7fc;--bg-app:#fff;--bg-header:#fff;--border-color:#eaeef2;--text-primary:#111;--text-secondary:#5a6b7c;--bg-input:#f5f7fa;--bg-bot-msg:transparent;--bg-user-msg:#e0f2fa;--bg-dropdown:#fff;--bg-hover:#f5f7fa;--shadow-color:rgba(0,0,0,0.08);--primary-color:#4a6a8a;--primary-hover:#3a5a7a;--send-shadow:rgba(74,106,138,0.2);--danger-bg:#fde8e8;--danger-color:#a33;--placeholder-color:#9aabbc;--icon-color:#4a6a8a;--border-input:#dce1e8;--send-bg:#4a6a8a;--send-hover:#3a5a7a;--modal-bg:rgba(0,0,0,0.5);--accent-color:#4a6a8a;--font-size-base:16px;--font-size-small:14px}html.dark-mode{--bg-body:#0d1117;--bg-app:#161b22;--bg-header:#161b22;--border-color:#30363d;--text-primary:#c9d1d9;--text-secondary:#8b949e;--bg-input:#21262d;--bg-user-msg:#1a3a4a;--bg-dropdown:#161b22;--bg-hover:#21262d;--shadow-color:rgba(0,0,0,0.5);--primary-color:#58a6ff;--primary-hover:#79c0ff;--send-shadow:rgba(88,166,255,0.2);--danger-bg:#2d1b1b;--danger-color:#f85149;--placeholder-color:#484f58;--icon-color:#58a6ff;--border-input:#30363d;--send-bg:#238636;--send-hover:#2ea043;--modal-bg:rgba(0,0,0,0.7);--accent-color:#58a6ff}html[data-font="small"]{--font-size-base:14px;--font-size-small:12.5px}html[data-font="medium"]{--font-size-base:16px;--font-size-small:14px}html[data-font="large"]{--font-size-base:18px;--font-size-small:16px}html[data-font="xlarge"]{--font-size-base:20px;--font-size-small:18px}*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI',Arial,sans-serif;-webkit-tap-highlight-color:transparent;-webkit-touch-callout:none}html{-webkit-tap-highlight-color:transparent}body{-webkit-tap-highlight-color:transparent}html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:var(--bg-body)}body{display:flex;justify-content:center;align-items:center;position:relative}.app{position:fixed;top:0;left:0;right:0;bottom:0;width:100%;max-width:450px;margin:0 auto;background:var(--bg-app);display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 20px var(--shadow-color)}@media(min-width:600px){.app{top:50%;left:50%;transform:translate(-50%,-50%);bottom:auto;right:auto;height:100dvh;max-height:100dvh;border-radius:20px}}.header{display:flex;justify-content:space-between;align-items:center;padding:14px 18px;flex-shrink:0;background:var(--bg-header)}.header-right{display:flex;align-items:center;gap:6px}.header-left{display:flex;align-items:center;gap:6px}.icon-btn{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:6px;border-radius:10px;display:flex;align-items:center;justify-content:center;transition:background .2s,opacity .2s}.icon-btn:hover{background:var(--bg-hover)}.icon-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}.icon-btn.voice-on{color:var(--primary-color);opacity:1}.icon-btn.voice-off{color:var(--icon-color);opacity:0.5}.dropdown{position:absolute;top:68px;left:12px;right:12px;background:var(--bg-dropdown);border-radius:24px;box-shadow:0 20px 60px rgba(0,0,0,0.15),0 4px 12px rgba(0,0,0,0.08);display:none;flex-direction:column;z-index:100;border:1px solid var(--border-color);max-height:78vh;overflow-y:auto;padding:10px;opacity:0;transform:translateY(-8px);transition:opacity .2s ease,transform .2s ease}.dropdown.show{display:flex;opacity:1;transform:translateY(0)}.dropdown::-webkit-scrollbar{width:4px}.dropdown::-webkit-scrollbar-thumb{background:var(--border-color);border-radius:4px}.dropdown .item{display:flex;align-items:center;gap:14px;padding:13px 16px;font-size:15px;color:var(--text-primary);background:transparent;border:none;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-weight:600;border-radius:14px;transition:background .15s ease,transform .1s ease;letter-spacing:-0.2px}.dropdown .item:hover{background:var(--bg-hover)}.dropdown .item:active{transform:scale(0.98)}.dropdown .item svg{width:20px;height:20px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0;stroke-linecap:round;stroke-linejoin:round;opacity:.85}.dropdown .section-title{padding:16px 16px 6px;font-size:11px;font-weight:700;color:var(--text-secondary);letter-spacing:.8px;text-transform:uppercase;opacity:.7}.dropdown .conv-item{display:flex;align-items:center;gap:8px;padding:11px 16px;border:none;background:transparent;width:100%;text-align:right;cursor:pointer;font-family:inherit;font-size:14px;color:var(--text-primary);font-weight:500;border-radius:14px;transition:background .15s ease;letter-spacing:-0.1px;position:relative;user-select:none}.dropdown .conv-item:hover{background:var(--bg-hover)}.dropdown .conv-item .conv-title{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.dropdown .conv-item::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--primary-color);opacity:.4;flex-shrink:0}.dropdown .conv-item .pin-btn{background:transparent;border:none;cursor:pointer;padding:4px;border-radius:8px;display:flex;align-items:center;justify-content:center;opacity:0.5;transition:opacity .2s,background .2s;flex-shrink:0}.dropdown .conv-item .pin-btn:hover{opacity:1;background:var(--bg-hover)}.dropdown .conv-item .pin-btn svg{width:16px;height:16px;stroke:var(--text-primary);stroke-width:2;fill:none}.dropdown .conv-item .pin-btn.pinned svg{fill:var(--primary-color);stroke:var(--primary-color)}.dropdown .pinned-item{padding:11px 16px;display:flex;align-items:center;gap:8px;border-radius:14px;transition:background .15s ease}.dropdown .pinned-item:hover{background:var(--bg-hover)}.dropdown .conv-item.long-pressing{transform:scale(0.96);background:var(--bg-hover);transition:all .2s;}
.gender-option{flex:1;padding:9px 12px;border-radius:12px;border:1px solid var(--border-color);background:transparent;font-size:13px;font-weight:600;color:var(--text-secondary);cursor:pointer;transition:all .2s ease;font-family:inherit}.gender-option.active{background:var(--primary-color);color:#fff;border-color:var(--primary-color);box-shadow:0 4px 12px rgba(74,106,138,0.3)}.dropdown .item.danger{color:#d32f2f}.dropdown .item.danger svg{stroke:#d32f2f;opacity:1}.dropdown .item.danger:hover{background:rgba(211,47,47,0.08)}.settings-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:99999;display:none;flex-direction:column;overflow-y:auto}.settings-overlay.show{display:flex}.settings-page{max-width:500px;width:100%;margin:0 auto;min-height:100dvh;display:flex;flex-direction:column;background:var(--bg-body)}.settings-header{display:flex;justify-content:space-between;align-items:center;padding:16px;background:var(--bg-app);position:sticky;top:0;z-index:10;border-bottom:1px solid var(--border-color)}.settings-header h2{font-size:18px;color:var(--text-primary);font-weight:700;margin:0}.settings-body{padding:16px;display:flex;flex-direction:column;gap:14px}.settings-card{background:var(--bg-app);border-radius:18px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.settings-item{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.settings-item:last-child{border-bottom:none}.settings-item:hover{background:var(--bg-hover)}.settings-item .item-right{display:flex;align-items:center;gap:14px;color:var(--text-primary);font-size:15px;font-weight:600}.settings-item .item-right svg{width:22px;height:22px;stroke:var(--text-primary);stroke-width:1.8;fill:none;flex-shrink:0}.settings-item .chevron{width:18px;height:18px;stroke:var(--text-secondary);stroke-width:2;fill:none}.sub-page{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:100000;display:none;align-items:center;justify-content:center;padding:20px}.sub-page.show{display:flex}.sub-page .modal-box{background:var(--bg-app);width:100%;max-width:420px;max-height:80vh;border-radius:22px;overflow:hidden;display:flex;flex-direction:column;animation:modalIn .25s ease;border:1px solid var(--border-color)}.sub-page-header{display:none}.sub-page-body{padding:20px;overflow-y:auto;flex:1}.sub-page-body::-webkit-scrollbar{width:4px}.sub-page-body::-webkit-scrollbar-thumb{background:var(--border-color);border-radius:4px}.modal-title{text-align:center;font-size:17px;font-weight:700;color:var(--text-primary);padding:18px 20px;border-bottom:1px solid var(--border-color)}.modal-confirm{width:100%;padding:16px;background:transparent;border:none;border-top:1px solid var(--border-color);font-size:16px;font-weight:700;color:var(--primary-color);cursor:pointer;font-family:inherit}.modal-confirm:active{background:var(--bg-hover)}@keyframes modalIn{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:scale(1)}}.info-box{background:var(--bg-hover);padding:16px;border-radius:14px;font-size:14px;color:var(--text-secondary);line-height:1.8}.option-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.option-row{padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}.option-row:last-child{border-bottom:none}.option-row:active{background:var(--bg-hover)}.option-label{display:flex;justify-content:space-between;align-items:center;font-size:15px;color:var(--text-primary);font-weight:500}.check-icon{width:22px;height:22px;stroke:var(--primary-color);stroke-width:2.5;fill:none;opacity:0;transition:opacity .25s}.option-row.selected .check-icon{opacity:1}.color-grid{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}.color-row{padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;display:flex;justify-content:space-between;align-items:center;transition:background .2s}.color-row:last-child{border-bottom:none}.color-row:active{background:var(--bg-hover)}.color-row-left{display:flex;align-items:center;gap:14px;font-size:15px;color:var(--text-primary);font-weight:500}.color-circle{width:26px;height:26px;border-radius:50%;box-shadow:0 2px 6px rgba(0,0,0,0.15);flex-shrink:0}.color-row .check-icon{opacity:0;transition:opacity .25s}.color-row.selected .check-icon{opacity:1}.lang-list{display:flex;flex-direction:column;gap:12px}.lang-card{display:flex;align-items:center;gap:16px;padding:18px 20px;background:var(--bg-app);border-radius:18px;cursor:pointer;border:2px solid var(--border-color);transition:all .25s cubic-bezier(.4,0,.2,1);box-shadow:0 1px 3px var(--shadow-color)}.lang-card:hover{border-color:var(--primary-color);transform:translateY(-2px);box-shadow:0 8px 24px rgba(74,106,138,0.15)}.lang-card.selected{border-color:var(--primary-color);background:linear-gradient(135deg,var(--bg-app) 0%,rgba(74,106,138,0.06) 100%);box-shadow:0 6px 20px rgba(74,106,138,0.18)}.lang-flag{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;flex-shrink:0;letter-spacing:-0.5px;box-shadow:0 2px 6px rgba(0,0,0,0.15);color:#fff}.lang-info{flex:1;display:flex;flex-direction:column;gap:3px}.lang-name{font-size:17px;font-weight:700;color:var(--text-primary);letter-spacing:-0.2px}.lang-sub{font-size:13px;color:var(--text-secondary)}.lang-check{width:26px;height:26px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;transition:opacity .3s ease,transform .35s cubic-bezier(.34,1.56,.64,1);flex-shrink:0;transform:scale(0.5)}.lang-card.selected .lang-check{opacity:1;transform:scale(1)}
.personality-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}
.personality-row{display:flex;justify-content:space-between;align-items:center;padding:16px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}
.personality-row:last-child{border-bottom:none}
.personality-row:active{background:var(--bg-hover)}
.personality-text{display:flex;flex-direction:column;gap:3px;flex:1;min-width:0}
.personality-name{font-size:15px;color:var(--text-primary);font-weight:500;letter-spacing:-0.1px;transition:color .2s ease}
.personality-sub{font-size:12.5px;color:var(--text-secondary);letter-spacing:-0.1px}
.personality-row .check-icon{opacity:0;transition:opacity .25s ease;flex-shrink:0;margin-right:8px}
.personality-row.selected .personality-name{color:var(--primary-color);font-weight:700}
.personality-row.selected .check-icon{opacity:1}
.fontsize-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color)}
.fontsize-row{display:flex;justify-content:space-between;align-items:center;padding:18px 20px;border-bottom:1px solid var(--border-color);cursor:pointer;transition:background .2s}
.fontsize-row:last-child{border-bottom:none}
.fontsize-row:active{background:var(--bg-hover)}
.fontsize-row-left{display:flex;flex-direction:column;gap:4px}
.fontsize-label{font-size:15px;color:var(--text-primary);font-weight:500;transition:color .2s ease}
.fontsize-sample{color:var(--text-secondary);transition:color .2s ease}
.fontsize-row .check-icon{opacity:0;transition:opacity .25s ease;flex-shrink:0}
.fontsize-row.selected .fontsize-label{color:var(--primary-color);font-weight:700}
.fontsize-row.selected .check-icon{opacity:1}
.memory-card{background:var(--bg-app);border-radius:16px;overflow:hidden;box-shadow:0 1px 3px var(--shadow-color);margin-bottom:14px}
.memory-header{padding:14px 18px;background:var(--bg-hover);display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--border-color)}
.memory-header svg{width:18px;height:18px;stroke:var(--primary-color);stroke-width:2;fill:none;flex-shrink:0}
.memory-header span{font-size:14px;color:var(--text-primary);font-weight:700}
.memory-item{padding:14px 18px;border-bottom:1px solid var(--border-color);display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.memory-item:last-child{border-bottom:none}
.memory-key{font-size:14px;color:var(--text-secondary);font-weight:500;flex-shrink:0}
.memory-val{font-size:14.5px;color:var(--text-primary);font-weight:600;text-align:left;word-wrap:break-word;overflow-wrap:anywhere;max-width:60%}
.memory-empty{padding:24px 18px;text-align:center;color:var(--text-secondary);font-size:14px;line-height:1.8}
.memory-note{padding:14px 18px;background:var(--bg-hover);font-size:13px;color:var(--text-secondary);line-height:1.8;border-radius:0 0 16px 16px;margin-top:-14px;margin-bottom:14px}#chat{flex:1;overflow-y:auto;padding:20px 24px;display:flex;flex-direction:column;gap:12px;background:var(--bg-app);font-size:var(--font-size-base);min-height:0}.msg{max-width:90%;padding:12px 20px;border-radius:20px;font-size:var(--font-size-base);font-weight:500;line-height:1.7;word-wrap:break-word;color:var(--text-primary);position:relative}.msg.user{align-self:flex-end;background:var(--msg-user-bg,var(--bg-user-msg));color:var(--msg-user-text,#111);border-bottom-left-radius:6px}.msg.bot{align-self:flex-start;background:var(--bg-bot-msg);border-bottom-right-radius:6px}.msg .time{font-size:10px;opacity:.5;display:block;margin-top:4px;color:var(--text-secondary)}.msg.error{background:var(--danger-bg);color:var(--danger-color);align-self:center;max-width:90%}.msg .image-upload{max-width:100%;max-height:200px;border-radius:12px;margin:4px 0;border:1px solid var(--border-color);display:block}.msg .generated-image{max-width:100%;border-radius:12px;margin:8px 0;border:1px solid var(--border-color);display:block}.typing-indicator{align-self:flex-start;background:var(--bg-bot-msg);padding:12px 18px;border-radius:20px;font-size:16px;color:var(--text-secondary)}.typing-dots::after{content:'...';animation:dotAnimation 1.2s steps(4,end) infinite}@keyframes dotAnimation{0%,20%{content:''}40%{content:'.'}60%{content:'..'}80%,100%{content:'...'}}
/* 🔴 تنسيقات كبسولة البحث الجديدة 🔴 */
.web-search-bar { display: flex; justify-content: flex-start; padding: 0 18px 6px; background: var(--bg-app); }
.web-search-toggle { display: inline-flex; align-items: center; gap: 6px; padding: 6px 14px; background: var(--bg-input); border: 1px solid var(--border-color); border-radius: 20px; font-size: 12.5px; font-weight: 600; color: var(--text-secondary); cursor: pointer; font-family: inherit; transition: all 0.2s ease; }
.web-search-toggle svg { width: 15px; height: 15px; }
.web-search-toggle.active { background: rgba(74,106,138,0.1); border-color: var(--primary-color); color: var(--primary-color); }
html.dark-mode .web-search-toggle.active { background: rgba(88,166,255,0.15); }
/* 🔴 نهاية تنسيقات البحث 🔴 */

.input-area{display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:center;gap:6px;padding:8px 12px;margin:8px 14px 16px;background:var(--bg-input);border-radius:28px;border:1px solid var(--border-color);flex-shrink:0;min-height:56px;position:relative;transition:border-color .2s,box-shadow .2s,transform .2s}
.input-area:focus-within{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.08)}
.input-area textarea{flex:1;border:none;background:0 0;padding:12px 0;font-size:var(--font-size-base);font-weight:800;outline:0;color:#000000;direction:rtl;resize:none;overflow-y:hidden;min-height:22px;max-height:150px;font-family:inherit;line-height:1.5;width:100%}
html.dark-mode .input-area textarea{color:#ffffff;}
.input-area textarea::placeholder{color:var(--placeholder-color)}
#imagePreviewContainer{display:none;width:100%;padding:8px 4px 4px;}
#imagePreviewContainer.show{display:block;}
.image-preview-wrapper{position:relative;display:inline-block;border-radius:14px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.15);animation:previewIn .25s cubic-bezier(.34,1.56,.64,1);}
@keyframes previewIn{from{opacity:0;transform:scale(.75);}to{opacity:1;transform:scale(1);}}
.image-preview-wrapper img{display:block;max-height:76px;max-width:120px;object-fit:cover;border-radius:14px;border:1px solid var(--border-color);}
.image-preview-wrapper .remove-img-btn{position:absolute;top:5px;left:5px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,0.65);color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;padding:0;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);transition:background .2s,transform .15s;box-shadow:0 2px 8px rgba(0,0,0,0.25);}
.image-preview-wrapper .remove-img-btn:hover{background:rgba(220,38,38,0.95);transform:scale(1.1);}
.image-preview-wrapper .remove-img-btn:active{transform:scale(.9);}
.image-preview-wrapper .remove-img-btn svg{width:11px;height:11px;stroke:#fff;stroke-width:3;fill:none;stroke-linecap:round;stroke-linejoin:round;pointer-events:none;}
.input-area .btn-icon{background:0 0;border:none;color:var(--icon-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}
.input-area .btn-icon:hover{background:var(--bg-hover)}
.input-area .btn-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.input-area .mic-btn{color:var(--primary-color)}
.input-area .mic-btn.listening{color:#c33;background:#fde8e8}
.input-area .send{background:var(--send-bg);color:#fff;border:none;width:42px;height:42px;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 4px 14px rgba(74,106,138,0.35);transition:background .2s,transform .15s}
.input-area .send:hover{background:var(--send-hover);transform:scale(1.05)}
.input-area .send svg{width:20px;height:20px;stroke:#fff;stroke-width:2.5;fill:none;stroke-linecap:round;stroke-linejoin:round}
.plus-btn{background:0 0;border:none;color:var(--primary-color);cursor:pointer;padding:0;border-radius:50%;width:36px;height:36px;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:transform .3s}
.plus-btn:hover{background:var(--bg-hover)}
.plus-btn svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.plus-btn.rotate{transform:rotate(45deg)}
.plus-options{display:none;position:absolute;bottom:70px;right:0;background:var(--bg-dropdown);border-radius:20px;box-shadow:0 8px 30px var(--shadow-color);padding:8px;gap:8px;flex-direction:row;border:1px solid var(--border-color);z-index:50}
.plus-options.show{display:flex}
.plus-options .option-btn{background:var(--bg-hover);border:none;border-radius:50%;width:44px;height:44px;display:flex;align-items:center;justify-content:center;cursor:pointer;color:var(--text-primary)}
.plus-options .option-btn:hover{background:var(--border-color)}
.plus-options .option-btn svg{width:20px;height:20px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.toast{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.8);color:#fff;padding:10px 24px;border-radius:30px;font-size:14px;z-index:99999}.share-modal{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:var(--modal-bg);z-index:9999;justify-content:center;align-items:center;padding:20px}.share-modal.show{display:flex}.share-modal .box{background:var(--bg-app);padding:28px 24px;border-radius:24px;max-width:360px;width:100%;text-align:center;border:1px solid var(--border-color)}.share-modal .box h3{font-size:20px;color:var(--text-primary);margin-bottom:18px}.share-modal .box .share-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:18px}.share-modal .box .share-btn{display:flex;align-items:center;gap:8px;padding:10px 16px;border-radius:14px;text-decoration:none;font-size:14px;font-weight:600;border:none;cursor:pointer;flex:1 0 auto;justify-content:center;min-width:70px;color:#fff;font-family:inherit}.share-modal .box .share-btn.whatsapp{background:#25D366}.share-modal .box .share-btn.facebook{background:#1877F2}.share-modal .box .share-btn.twitter{background:#000}.share-modal .box .share-btn.snapchat{background:#FFFC00;color:#000}.share-modal .box .close-btn{background:var(--bg-hover);border:none;padding:10px 30px;border-radius:14px;font-size:15px;color:var(--text-primary);cursor:pointer;margin-top:4px;width:100%;font-weight:600;font-family:inherit}.copy-btn{background:0 0;border:none;color:var(--text-secondary);cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center;transition:opacity .2s}.copy-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.copy-btn:hover{opacity:1;background:var(--bg-hover)}.copy-btn.copied{color:#28a745;opacity:1}.msg .content-wrapper{display:flex;flex-direction:column;width:100%}.msg .content-text{width:100%}.msg .actions{display:flex;gap:4px;margin-top:8px;flex-wrap:wrap}.msg .actions .del-msg-btn{background:0 0;border:none;color:#e74c3c;cursor:pointer;padding:4px 8px;border-radius:8px;opacity:.75;display:flex;align-items:center}.msg .actions .del-msg-btn svg{width:15px;height:15px;stroke:currentColor;stroke-width:2;fill:none}.msg .actions .del-msg-btn:hover{opacity:1;background:rgba(231,76,60,0.1)}.msg-actions{display:flex;gap:2px;margin-top:12px;align-items:center;opacity:0.5;transition:opacity .3s ease}.msg:hover .msg-actions,.msg-actions.touched{opacity:1}.msg-actions button{background:transparent;border:none;cursor:pointer;width:34px;height:34px;border-radius:999px;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);transition:background .2s ease,color .2s ease,transform .15s cubic-bezier(.4,0,.2,1)}.msg-actions button:hover{background:var(--bg-hover);color:var(--text-primary)}.msg-actions button:active{transform:scale(0.88)}.msg-actions button svg{width:18px;height:18px;stroke:currentColor;stroke-width:1.9;fill:none;stroke-linecap:round;stroke-linejoin:round;transition:fill .2s ease,stroke .2s ease,transform .2s cubic-bezier(.34,1.56,.64,1)}.msg-actions button.liked{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.liked svg{fill:#10b981;stroke:#10b981;transform:scale(1.08)}.msg-actions button.disliked{color:#ef4444;background:rgba(239,68,68,0.1)}.msg-actions button.disliked svg{fill:#ef4444;stroke:#ef4444;transform:scale(1.08)}.msg-actions button.copied{color:#10b981;background:rgba(16,185,129,0.1)}.msg-actions button.copied svg{stroke:#10b981}.msg-actions button.speaking{color:var(--primary-color);background:var(--bg-hover)}.msg-actions button.speaking svg{fill:currentColor}.msg-actions button.speaking svg polygon{animation:speakerPulse 0.9s ease-in-out infinite}@keyframes speakerPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.12)}}@media(max-width:420px){.header{padding:12px 14px}.btn{font-size:12px;padding:5px 12px}#chat{padding:14px 16px}.input-area{margin:6px 10px 12px;padding:6px 10px;min-height:50px}.input-area textarea{font-size:14px}.input-area .send{width:38px;height:38px}.input-area .btn-icon{width:32px;height:32px}.plus-btn{width:32px;height:32px}}#oauth-overlay{position:fixed;inset:0;background:var(--bg-body);z-index:999999;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;text-align:center;padding:20px}#oauth-overlay.show{display:flex}#oauth-overlay .oauth-spinner{width:52px;height:52px;border:4px solid var(--border-color);border-top-color:var(--primary-color);border-radius:50%;animation:oauthSpin 1s linear infinite}@keyframes oauthSpin{to{transform:rotate(360deg)}}#oauth-overlay .oauth-title{font-size:19px;color:var(--text-primary);font-weight:700}#oauth-overlay .oauth-msg{font-size:14px;color:var(--text-secondary);line-height:1.7}#oauth-overlay .oauth-title.ok{color:#00b894}#oauth-overlay .oauth-title.err{color:#d63031}
.assistant-bar{padding:6px 14px 0;flex-shrink:0;display:none;justify-content:flex-start}
.assistant-bar.show{display:flex}
.assistant-pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px 6px 14px;background:var(--bg-input);border:1px solid var(--border-color);border-radius:20px;font-size:12.5px;font-weight:600;color:var(--text-primary);cursor:pointer;font-family:inherit;transition:all .15s;-webkit-tap-highlight-color:transparent;max-width:200px}
.assistant-pill:hover{background:var(--bg-hover)}
.assistant-pill:active{transform:scale(0.97)}
.assistant-pill .a-dot{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;flex-shrink:0}
.assistant-pill .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}
.assistant-pill svg{width:11px;height:11px;stroke:var(--text-secondary);stroke-width:2.5;fill:none;flex-shrink:0}
.assistant-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:200;min-width:220px;max-width:260px;display:none;max-height:60vh;overflow-y:auto}
.assistant-menu.show{display:block;animation:modalIn .18s ease}
.assistant-menu-item{display:flex;align-items:center;gap:10px;padding:9px 12px;border-radius:11px;cursor:pointer;font-size:14px;font-weight:600;color:var(--text-primary);border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .15s}
.assistant-menu-item:hover{background:var(--bg-hover)}
.assistant-menu-item .a-dot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:700;flex-shrink:0}
.assistant-menu-item .a-name{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.assistant-menu-item .a-check{width:15px;height:15px;stroke:var(--primary-color);stroke-width:3;fill:none;opacity:0;flex-shrink:0}
.assistant-menu-item.selected .a-check{opacity:1}
.assistant-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}
.assistant-menu-add{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:11px;cursor:pointer;font-size:13px;font-weight:600;color:var(--primary-color);border:none;background:transparent;width:100%;text-align:right;font-family:inherit;transition:background .15s}
.assistant-menu-add:hover{background:var(--bg-hover)}
.assistant-menu-add svg{width:16px;height:16px;stroke:currentColor;stroke-width:2.5;fill:none;flex-shrink:0}
.assistants-list{display:flex;flex-direction:column;gap:10px}
.assistant-card{display:flex;align-items:center;gap:14px;padding:14px 16px;background:var(--bg-app);border-radius:16px;box-shadow:0 1px 3px var(--shadow-color);border:1px solid var(--border-color)}
.assistant-card .a-dot{width:42px;height:42px;border-radius:12px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:17px;font-weight:700;flex-shrink:0}
.assistant-card-info{flex:1;min-width:0}
.assistant-card-name{font-size:15px;font-weight:700;color:var(--text-primary);margin-bottom:3px}
.assistant-card-sub{font-size:12.5px;color:var(--text-secondary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.5}
.assistant-card-del{background:transparent;border:none;cursor:pointer;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:var(--text-secondary);flex-shrink:0;padding:0;transition:color .2s}
.assistant-card-del:hover{color:#ef4444}
.assistant-card-del svg{width:16px;height:16px;stroke:currentColor;stroke-width:2;fill:none}
.assistant-add-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;background:var(--bg-app);border:1.5px dashed var(--border-color);border-radius:16px;cursor:pointer;font-size:14px;font-weight:600;color:var(--primary-color);font-family:inherit;transition:all .2s;margin-top:12px;width:100%}
.assistant-add-btn:hover{border-color:var(--primary-color);background:var(--bg-hover)}
.assistant-add-btn svg{width:18px;height:18px;stroke:currentColor;stroke-width:2.5;fill:none}
.assistant-form-field{margin-bottom:18px}
.assistant-form-field label{display:block;font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:8px;text-align:right}
.assistant-form-field input,.assistant-form-field textarea{width:100%;padding:13px 16px;border:1.5px solid var(--border-input);border-radius:14px;font-size:14.5px;background:var(--bg-input);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;resize:none;font-weight:500}
.assistant-form-field input:focus,.assistant-form-field textarea:focus{border-color:var(--primary-color);background:var(--bg-app);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.assistant-form-field textarea{min-height:110px;line-height:1.7}
.assistant-form-hint{font-size:11.5px;color:var(--text-secondary);margin-top:6px;text-align:right;line-height:1.6}
.assistant-color-picker{display:flex;gap:12px;flex-wrap:wrap;justify-content:flex-start}
.assistant-color-dot{width:38px;height:38px;border-radius:50%;border:2px solid transparent;cursor:pointer;transition:all .15s;padding:0;position:relative}
.assistant-color-dot.selected{border-color:var(--text-primary);transform:scale(1.08)}
.assistant-form-actions{display:flex;gap:10px;margin-top:22px}
.assistant-form-actions button{flex:1;padding:13px;border-radius:14px;border:none;font-size:14.5px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .15s}
.assistant-form-actions .btn-cancel{background:var(--bg-hover);color:var(--text-primary)}
.assistant-form-actions .btn-save{background:var(--primary-color);color:#fff}
.assistant-form-actions .btn-save:disabled{opacity:0.6;cursor:not-allowed}
.sp-input{width:100%;padding:14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background:var(--bg-app);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;font-weight:500}
.sp-input:focus{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.sp-input::placeholder{color:var(--placeholder-color)}
.sp-input:disabled{opacity:0.55;cursor:not-allowed}
.sp-select{width:100%;padding:14px 44px 14px 16px;border:1.5px solid var(--border-color);border-radius:14px;font-size:15px;background-color:var(--bg-app);color:var(--text-primary);font-family:inherit;transition:all .2s;box-sizing:border-box;outline:none;font-weight:500;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%235a6b7c' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:left 14px center;background-size:18px;cursor:pointer}
.sp-select:focus{border-color:var(--primary-color);box-shadow:0 0 0 3px rgba(74,106,138,0.1)}
.sp-field{margin-bottom:16px}
.sp-field:last-child{margin-bottom:0}
.sp-label{display:block;font-size:13px;font-weight:600;color:var(--text-secondary);margin-bottom:8px;text-align:right}
.sp-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;border:none;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .15s;width:100%;-webkit-tap-highlight-color:transparent;outline:none}
.sp-btn:active{transform:scale(0.98)}
.sp-btn-primary{background:var(--primary-color);color:#fff}
.sp-btn-primary:hover{filter:brightness(1.08)}
.sp-btn-danger{background:rgba(211,47,47,0.08);color:#d32f2f}
.sp-btn-danger:hover{background:rgba(211,47,47,0.15)}
html.dark-mode .sp-btn-danger{background:rgba(248,81,73,0.12);color:#f85149}
html.dark-mode .sp-btn-danger:hover{background:rgba(248,81,73,0.2)}
.sp-btn-row{display:flex;gap:10px}
.sp-btn-row .sp-btn{flex:1}
.sp-link-btn{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-radius:14px;background:var(--bg-app);color:var(--text-primary);text-decoration:none;font-size:15px;font-weight:600;border:1.5px solid var(--border-color);transition:all .15s;text-align:center;width:100%;box-sizing:border-box}
.sp-link-btn:hover{background:var(--bg-hover);border-color:var(--primary-color);color:var(--primary-color)}
.sp-note{font-size:14.5px;color:var(--text-secondary);line-height:1.9}
.sp-note b{color:var(--text-primary);font-weight:700;display:block;margin-bottom:6px;font-size:15px}
.sp-list{display:flex;flex-direction:column;background:var(--bg-app);border-radius:14px;border:1px solid var(--border-color);overflow:hidden}
.sp-list-item{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--border-color);font-size:15px}
.sp-list-item:last-child{border-bottom:none}
.sp-list-key{color:var(--text-secondary);font-weight:500}
.sp-list-val{color:var(--text-primary);font-weight:700;text-align:left;max-width:60%;word-wrap:break-word}
.sp-hero{display:flex;align-items:center;gap:14px;padding:16px;background:var(--bg-app);border-radius:16px;border:1px solid var(--border-color);margin-bottom:16px}
.sp-hero-icon{width:46px;height:46px;border-radius:13px;background:var(--bg-hover);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--primary-color)}
.sp-hero-icon svg{width:22px;height:22px;stroke:currentColor;stroke-width:2;fill:none}
.sp-hero-title{font-size:15.5px;font-weight:700;color:var(--text-primary);margin:0 0 3px}
.sp-hero-sub{font-size:12.5px;color:var(--text-secondary);margin:0;line-height:1.5}
.nibras-response{font-size:var(--font-size-base);line-height:1.9;color:var(--text-primary);max-width:100%}
.nibras-response h2{font-size:1.25em;font-weight:800;color:var(--primary-color);margin:4px 0 16px;padding-bottom:10px;border-bottom:2px solid var(--border-color);line-height:1.5}
.nibras-response h3{font-size:1.05em;font-weight:750;margin:16px 0 8px;background:var(--bg-hover);padding:10px 14px;border-right:4px solid var(--primary-color);border-radius:8px;color:var(--text-primary);line-height:1.5}
.nibras-response p{margin:0 0 10px;color:var(--text-primary)}
.nibras-response em{color:var(--text-secondary);font-size:0.9em;display:inline-block;margin-bottom:6px;font-style:normal}
.nibras-response hr{border:0;height:1px;background:var(--border-color);margin:18px 0}
.nibras-response strong{font-weight:800;color:var(--text-primary)}
.nibras-response a{color:var(--primary-color);text-decoration:none;font-weight:600;display:inline-block;padding:4px 0}
.nibras-response a:hover{text-decoration:underline}
.nibras-response ul,.nibras-response ol{padding-right:22px;padding-left:0;margin:8px 0 14px}
.nibras-response li{margin-bottom:8px}
.nibras-response blockquote{border-right:4px solid var(--primary-color);margin:10px 0;padding:8px 14px;background:var(--bg-hover);border-radius:8px}
.nibras-response img{display:block;max-width:100%;height:auto;border-radius:12px;margin:10px 0;border:1px solid var(--border-color)}
.agents-grid{display:flex;flex-direction:column;gap:12px}
.agent-card{position:relative;padding:16px;background:var(--bg-app);border:1px solid var(--border-color);border-radius:18px;transition:all .22s cubic-bezier(.4,0,.2,1);overflow:hidden}
.agent-card::before{content:'';position:absolute;top:0;right:0;left:0;height:3px;background:linear-gradient(90deg,var(--primary-color),transparent);opacity:0;transition:opacity .25s}
.agent-card:hover{border-color:var(--primary-color);transform:translateY(-2px);box-shadow:0 10px 26px rgba(74,106,138,0.14)}
.agent-card:hover::before{opacity:1}
.agent-head{display:flex;align-items:center;gap:14px;margin-bottom:12px}
.agent-avatar{width:50px;height:50px;flex-shrink:0;border-radius:15px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:20px;font-weight:800;letter-spacing:-.5px;box-shadow:0 6px 16px rgba(0,0,0,0.15);position:relative;overflow:hidden}
.agent-avatar::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,0.25),transparent 60%);pointer-events:none}
.agent-info{flex:1;min-width:0}
.agent-name{font-size:16px;font-weight:800;color:var(--text-primary);margin-bottom:3px;letter-spacing:-.2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.agent-role{font-size:12.5px;color:var(--text-secondary);font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.agent-desc{font-size:13px;color:var(--text-secondary);line-height:1.75;padding:10px 12px;background:var(--bg-hover);border-radius:11px;margin-bottom:12px;border-right:3px solid var(--primary-color)}
.agent-actions{display:flex;gap:8px}
.agent-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;border-radius:12px;border:none;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;transition:all .18s cubic-bezier(.4,0,.2,1);-webkit-tap-highlight-color:transparent;outline:none}
.agent-btn svg{flex-shrink:0}
.agent-btn:active{transform:scale(0.97)}
.agent-btn-add{background:var(--primary-color);color:#fff;box-shadow:0 4px 14px rgba(74,106,138,0.3);flex:1}
.agent-btn-add:hover{filter:brightness(1.08);transform:translateY(-1px);box-shadow:0 6px 18px rgba(74,106,138,0.4)}
.agent-btn-add:disabled{opacity:.75;cursor:not-allowed;transform:none;box-shadow:none}
.agent-btn-added{background:rgba(16,185,129,0.12)!important;color:#10b981!important;box-shadow:none!important;border:1px solid rgba(16,185,129,0.3)!important}
html.dark-mode .agent-btn-added{background:rgba(16,185,129,0.18)!important;color:#34d399!important}
.agent-btn-edit{background:var(--bg-hover);color:var(--text-primary);padding:9px 14px}
.agent-btn-edit:hover{background:var(--border-color)}
.agent-btn-del{background:rgba(239,68,68,0.08);color:#ef4444;padding:9px 14px}
.agent-btn-del:hover{background:rgba(239,68,68,0.16)}
html.dark-mode .agent-btn-del{color:#f87171}
.agent-btn-new{width:100%;margin-top:14px;padding:14px;background:transparent;color:var(--primary-color);border:1.5px dashed var(--border-color);border-radius:14px;font-size:14px}
.agent-btn-new:hover{border-color:var(--primary-color);background:var(--bg-hover);border-style:solid}
.agent-spinner{animation:agentSpin .8s linear infinite}
@keyframes agentSpin{to{transform:rotate(360deg)}}
.lib-loading{display:flex;flex-direction:column;align-items:center;gap:12px;padding:50px 20px;color:var(--text-secondary);font-size:14px}
.lib-spinner{width:34px;height:34px;border:3px solid var(--border-color);border-top-color:var(--primary-color);border-radius:50%;animation:agentSpin .8s linear infinite}
.lib-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:50px 20px;color:var(--text-secondary)}
.lib-empty svg{color:var(--border-color);margin-bottom:14px;stroke-width:1.4}
.lib-empty h4{font-size:15px;color:var(--text-primary);font-weight:700;margin-bottom:6px}
.lib-empty p{font-size:13px;line-height:1.7;margin:0}
.context-menu-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.3); z-index: 99998; display: none; opacity: 0; transition: opacity 0.2s; }
.context-menu-backdrop.show { display: block; opacity: 1; }
.context-menu{position:fixed;background:var(--bg-dropdown);border-radius:16px;box-shadow:0 10px 40px rgba(0,0,0,0.2);border:1px solid var(--border-color);padding:6px;z-index:99999;display:none;flex-direction:column;min-width:180px;animation:modalIn .15s ease}
.context-menu.show{display:flex}
.context-menu-item{display:flex;align-items:center;gap:12px;padding:12px 16px;border:none;background:transparent;font-size:14px;font-weight:600;color:var(--text-primary);border-radius:10px;cursor:pointer;font-family:inherit;text-align:right;transition:background .15s}
.context-menu-item:hover{background:var(--bg-hover)}
.context-menu-item.danger{color:#ef4444}
.context-menu-item.danger svg{stroke:#ef4444}
.context-menu-item svg{width:18px;height:18px;stroke:currentColor;stroke-width:2;fill:none;flex-shrink:0}
.context-menu-sep{height:1px;background:var(--border-color);margin:4px 8px}
html[data-theme="neon"] {
    --bg-body: #07090e;
    --bg-app: #0a0d14;
    --bg-header: #121723;
    --border-color: #1f293d;
    --text-primary: #e2e8f0;
    --text-secondary: #94a3b8;
    --bg-input: #121723;
    --bg-bot-msg: transparent;
    --bg-user-msg: rgba(var(--primary-rgb, 0, 242, 254), 0.12);
    --msg-user-text: #e2e8f0;
    --bg-dropdown: #121723;
    --bg-hover: #1a2030;
    --shadow-color: rgba(var(--primary-rgb, 0, 242, 254), 0.08);
    --primary-color: #00f2fe;
    --primary-hover: #00d4e0;
    --primary-rgb: 0, 242, 254;
    --send-shadow: rgba(var(--primary-rgb, 0, 242, 254), 0.3);
    --danger-bg: #2d1b1b;
    --danger-color: #f85149;
    --placeholder-color: #64748b;
    --icon-color: var(--primary-color);
    --border-input: #1f293d;
    --send-bg: var(--primary-color);
    --send-hover: var(--primary-hover);
    --modal-bg: rgba(0,0,0,0.7);
    --accent-color: var(--primary-color);
}

html[data-theme="neon"] .input-area textarea { color: #ffffff !important; }
html[data-theme="neon"] .input-area textarea::placeholder { color: #94a3b8 !important; }

html[data-theme="neon"] body {
    background: radial-gradient(circle at 20% 0%, rgba(var(--primary-rgb), 0.08) 0%, transparent 40%),
                radial-gradient(circle at 80% 100%, rgba(121, 40, 202, 0.08) 0%, transparent 40%),
                #07090e;
}
html[data-theme="neon"] .app { box-shadow: 0 0 40px rgba(var(--primary-rgb), 0.12), 0 0 80px rgba(121, 40, 202, 0.08); }
html[data-theme="neon"] .header { background: linear-gradient(180deg, #121723 0%, #0a0d14 100%); border-bottom: 1px solid rgba(var(--primary-rgb), 0.15); position: relative; }
html[data-theme="neon"] .header::after {
    content: ''; position: absolute; bottom: 0; left: 10%; right: 10%; height: 1px;
    background: linear-gradient(90deg, transparent, var(--primary-color), transparent);
    animation: headerGlow 3s ease-in-out infinite;
}
@keyframes headerGlow { 0%, 100% { opacity: 0.3; } 50% { opacity: 0.7; } }
html[data-theme="neon"] .icon-btn { background: rgba(var(--primary-rgb), 0.05); border: 1px solid rgba(var(--primary-rgb), 0.15); border-radius: 12px; width: 40px; height: 40px; transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); position: relative; }
html[data-theme="neon"] .icon-btn:hover { background: rgba(var(--primary-rgb), 0.12); border-color: rgba(var(--primary-rgb), 0.6); transform: translateY(-2px); box-shadow: 0 0 20px rgba(var(--primary-rgb), 0.35); }
html[data-theme="neon"] .icon-btn:active { transform: translateY(0) scale(0.95); }
html[data-theme="neon"] .icon-btn svg { stroke: var(--primary-color); filter: drop-shadow(0 0 4px rgba(var(--primary-rgb), 0.7)); transition: filter 0.25s ease; width: 20px; height: 20px; }
html[data-theme="neon"] .icon-btn:hover svg { filter: drop-shadow(0 0 8px rgba(var(--primary-rgb), 1)); }
html[data-theme="neon"] .icon-btn.voice-on { background: rgba(var(--primary-rgb), 0.2); border-color: var(--primary-color); box-shadow: 0 0 15px rgba(var(--primary-rgb), 0.4); }
html[data-theme="neon"] .icon-btn.voice-off { opacity: 0.6; }
html[data-theme="neon"] .icon-btn.accent-btn { background: linear-gradient(135deg, rgba(var(--primary-rgb), 0.18), rgba(121, 40, 202, 0.18)); border-color: rgba(var(--primary-rgb), 0.4); }
html[data-theme="neon"] .icon-btn.accent-btn:hover { background: linear-gradient(135deg, rgba(var(--primary-rgb), 0.3), rgba(121, 40, 202, 0.3)); box-shadow: 0 0 25px rgba(var(--primary-rgb), 0.5); }
html[data-theme="neon"] .input-area { background: #121723; border: 1px solid rgba(var(--primary-rgb), 0.2); box-shadow: 0 0 15px rgba(var(--primary-rgb), 0.05); transition: all 0.25s ease; }
html[data-theme="neon"] .input-area:focus-within { border-color: rgba(var(--primary-rgb), 0.5); box-shadow: 0 0 30px rgba(var(--primary-rgb), 0.2); }
html[data-theme="neon"] .input-area .btn-icon, html[data-theme="neon"] .input-area .plus-btn { background: rgba(var(--primary-rgb), 0.05); border: 1px solid rgba(var(--primary-rgb), 0.15); width: 38px; height: 38px; transition: all 0.25s ease; }
html[data-theme="neon"] .input-area .btn-icon:hover, html[data-theme="neon"] .input-area .plus-btn:hover { background: rgba(var(--primary-rgb), 0.15); border-color: rgba(var(--primary-rgb), 0.4); box-shadow: 0 0 12px rgba(var(--primary-rgb), 0.3); }
html[data-theme="neon"] .input-area .btn-icon svg, html[data-theme="neon"] .input-area .plus-btn svg { stroke: var(--primary-color); filter: drop-shadow(0 0 3px rgba(var(--primary-rgb), 0.5)); }
html[data-theme="neon"] .input-area .mic-btn.listening { background: rgba(255, 0, 128, 0.15); border-color: rgba(255, 0, 128, 0.5); animation: micPulse 1s ease-in-out infinite; }
html[data-theme="neon"] .input-area .mic-btn.listening svg { stroke: #ff0080; filter: drop-shadow(0 0 6px rgba(255, 0, 128, 0.8)); }
@keyframes micPulse { 0%, 100% { box-shadow: 0 0 10px rgba(255, 0, 128, 0.3); } 50% { box-shadow: 0 0 25px rgba(255, 0, 128, 0.7); } }
html[data-theme="neon"] .input-area .send { background: linear-gradient(135deg, var(--primary-color) 0%, #7928ca 100%); box-shadow: 0 0 20px rgba(var(--primary-rgb), 0.5), 0 0 40px rgba(121, 40, 202, 0.3); animation: sendPulse 2s ease-in-out infinite; }
html[data-theme="neon"] .input-area .send:hover { background: linear-gradient(135deg, var(--primary-hover) 0%, #8b3fe0 100%); transform: scale(1.08); box-shadow: 0 0 30px rgba(var(--primary-rgb), 0.8), 0 0 60px rgba(121, 40, 202, 0.5); }
html[data-theme="neon"] .input-area .send svg { stroke: #ffffff; filter: drop-shadow(0 0 2px rgba(255, 255, 255, 0.8)); }
@keyframes sendPulse { 0%, 100% { box-shadow: 0 0 20px rgba(var(--primary-rgb), 0.5), 0 0 40px rgba(121, 40, 202, 0.3); } 50% { box-shadow: 0 0 30px rgba(var(--primary-rgb), 0.8), 0 0 60px rgba(121, 40, 202, 0.5); } }
html[data-theme="neon"] .plus-options { background: #121723; border: 1px solid rgba(var(--primary-rgb), 0.2); box-shadow: 0 8px 30px rgba(var(--primary-rgb), 0.15); }
html[data-theme="neon"] .plus-options .option-btn { background: rgba(var(--primary-rgb), 0.05); border: 1px solid rgba(var(--primary-rgb), 0.15); }
html[data-theme="neon"] .plus-options .option-btn:hover { background: rgba(var(--primary-rgb), 0.15); box-shadow: 0 0 15px rgba(var(--primary-rgb), 0.3); }
html[data-theme="neon"] .plus-options .option-btn svg { stroke: var(--primary-color); filter: drop-shadow(0 0 3px rgba(var(--primary-rgb), 0.5)); }
html[data-theme="neon"] .dropdown .item svg { stroke: var(--primary-color); filter: drop-shadow(0 0 2px rgba(var(--primary-rgb), 0.4)); }
html[data-theme="neon"] .dropdown .item.danger svg { stroke: #f85149; filter: drop-shadow(0 0 2px rgba(248, 81, 73, 0.4)); }
html[data-theme="neon"] .settings-item .item-right svg { stroke: var(--primary-color); filter: drop-shadow(0 0 2px rgba(var(--primary-rgb), 0.3)); }
html[data-theme="neon"] .msg-actions button svg { stroke: #94a3b8; transition: all 0.2s ease; }
html[data-theme="neon"] .msg-actions button:hover svg { stroke: var(--primary-color); filter: drop-shadow(0 0 4px rgba(var(--primary-rgb), 0.6)); }
html[data-theme="neon"] .msg.user { background: linear-gradient(135deg, rgba(var(--primary-rgb), 0.18), rgba(121, 40, 202, 0.18)); color: #e2e8f0; border: 1px solid rgba(var(--primary-rgb), 0.25); }
html[data-theme="neon"] .nibras-response h2 { color: var(--primary-color); border-bottom-color: rgba(var(--primary-rgb), 0.3); }
html[data-theme="neon"] .nibras-response h3 { background: rgba(var(--primary-rgb), 0.05); border-right-color: var(--primary-color); }
html[data-theme="neon"] .nibras-response a { color: var(--primary-color); }
html[data-theme="neon"] .typing-dots { color: var(--primary-color); }
html[data-theme="neon"] ::-webkit-scrollbar-thumb { background: rgba(var(--primary-rgb), 0.3); }
html[data-theme="neon"] ::-webkit-scrollbar-thumb:hover { background: rgba(var(--primary-rgb), 0.6); }
/* تنسيقات لوحة الإيموجي */
.emoji-menu {
    display: none; position: absolute; bottom: 65px; right: 10px; 
    background: var(--bg-dropdown); border: 1px solid var(--border-color); 
    border-radius: 16px; box-shadow: 0 10px 30px var(--shadow-color); 
    z-index: 999; width: 290px; overflow: hidden;
}
.emoji-tabs {
    display: flex; background: var(--bg-hover); border-bottom: 1px solid var(--border-color); 
    overflow-x: auto; scrollbar-width: none; padding: 5px;
}
.emoji-tabs::-webkit-scrollbar { display: none; }
.emoji-tab-btn {
    background: transparent; border: none; font-size: 18px; padding: 6px 10px; 
    cursor: pointer; border-radius: 8px; opacity: 0.5; transition: all 0.2s;
}
.emoji-tab-btn.active { opacity: 1; background: var(--bg-app); box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
.emoji-content {
    padding: 10px; display: grid; grid-template-columns: repeat(7, 1fr); 
    gap: 4px; max-height: 220px; overflow-y: auto; font-size: 22px; text-align: center;
}
.emoji-content::-webkit-scrollbar { width: 6px; }
.emoji-content::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 6px; }
.emoji-content span { cursor: pointer; padding: 2px; border-radius: 6px; transition: background 0.15s; display: inline-block; }
.emoji-content span:hover { background: var(--bg-hover); transform: scale(1.1); }
{{ memory_css|safe }}
</style></head><body>
<div class="app">

<div class="header">
    <div class="header-right">
        <button class="icon-btn" id="menuToggle" title="القائمة">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <line x1="3" y1="9" x2="21" y2="9"/>
                <line x1="3" y1="15" x2="14" y2="15"/>
            </svg>
        </button>
    </div>
    <div class="header-left">
        <button class="icon-btn voice-off" id="voiceToggle" title="تشغيل/إيقاف الصوت" type="button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                <line x1="23" y1="9" x2="17" y2="15"/>
                <line x1="17" y1="9" x2="23" y2="15"/>
            </svg>
        </button>
        <button class="icon-btn accent-btn" id="newChatBtn" title="محادثة جديدة" type="button">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="9" opacity="0.35"/>
                <line x1="12" y1="8" x2="12" y2="16"/>
                <line x1="8" y1="12" x2="16" y2="12"/>
            </svg>
        </button>
    </div>
</div>
<div class="context-menu-backdrop" id="ctxBackdrop" onclick="hideContextMenu()"></div>
<div class="context-menu" id="convContextMenu">
    <button class="context-menu-item" onclick="ctxAction('pin', event)">
        <svg viewBox="0 0 24 24"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V6h1a2 2 0 0 0 0-4H8a2 2 0 0 0 0 4h1v4.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>
        <span id="ctxPinText">تثبيت</span>
    </button>
    <button class="context-menu-item" onclick="ctxAction('rename', event)">
        <svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
        <span>إعادة تسمية</span>
    </button>
    <div class="context-menu-sep"></div>
    <button class="context-menu-item danger" onclick="ctxAction('delete', event)">
        <svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
        <span>حذف المحادثة</span>
    </button>
</div>
