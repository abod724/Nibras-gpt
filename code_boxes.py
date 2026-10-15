# ==========================================================
#  code_boxes.py
#  تصميم وربط صناديق نبراس (يُستورد في app.py)
# ==========================================================

CODE_BOXES_HEAD = ""
CODE_BOXES_CSS = ""

CODE_BOXES_JS = """
(() => {
    "use strict";

    const STYLE_ID = "nibras-copy-box-styles";

    function addStyles() {
        if (document.getElementById(STYLE_ID)) return;
        const style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = `
            .nibras-box {
                direction: rtl;
                margin: 18px 0;
                overflow: hidden;
                border: 1px solid var(--border-color, #dedede);
                border-radius: 14px;
                background: var(--box-bg, #fff);
                color: var(--text-color, #222);
            }
            .nibras-box-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 12px;
                padding: 11px 14px;
                background: var(--header-bg, #f5f6f8);
                border-bottom: 1px solid var(--border-color, #dedede);
            }
            .nibras-box-title {
                font-size: 13px;
                font-weight: 700;
                color: var(--primary-color, #4a6a8a);
            }
            .nibras-box-copy {
                border: 1px solid var(--border-color, #ddd);
                border-radius: 9px;
                background: var(--box-bg, #fff);
                color: inherit;
                padding: 7px 12px;
                font-size: 12px;
                cursor: pointer;
                font-family: inherit;
            }
            .nibras-box-copy:hover { opacity: .75; }
            .nibras-box-content {
                padding: 15px;
                line-height: 1.9;
                overflow-wrap: anywhere;
                white-space: pre-wrap;
            }
            .nibras-box pre {
                margin: 0;
                padding: 15px;
                overflow-x: auto;
                direction: ltr;
                text-align: left;
                white-space: pre;
                background: var(--code-bg, #f7f8fa);
                font-size: 13px;
                line-height: 1.7;
                border-radius: 8px;
            }
            .nibras-box pre code {
                padding: 0;
                background: transparent;
                font-family: Consolas, Monaco, monospace;
            }
            .nibras-box blockquote {
                margin: 0;
                padding: 12px 14px;
                border: none;
                background: var(--code-bg, #f7f8fa);
                border-right: 4px solid var(--primary-color, #4a6a8a);
                font-style: normal;
                color: inherit;
                line-height: 1.9;
                border-radius: 8px;
            }
            @media (max-width: 600px) {
                .nibras-box { border-radius: 11px; }
                .nibras-box-content, .nibras-box pre { padding: 11px; }
            }
        `;
        document.head.appendChild(style);
    }

    async function copyText(text, button) {
        try {
            if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(text);
            } else {
                const area = document.createElement("textarea");
                area.value = text;
                area.style.position = "fixed";
                area.style.opacity = "0";
                document.body.appendChild(area);
                area.select();
                const success = document.execCommand("copy");
                area.remove();
                if (!success) throw new Error("Copy failed");
            }
            button.textContent = "تم النسخ ✓";
        } catch {
            button.textContent = "تعذر النسخ";
        }
        setTimeout(() => { button.textContent = "نسخ"; }, 1800);
    }

    function bindCopyButtons(root) {
        root = root || document;
        root.querySelectorAll?.(".nibras-box-copy").forEach(btn => {
            if (btn.dataset.nibrasBound === "1") return;
            btn.dataset.nibrasBound = "1";
            btn.addEventListener("click", function(){
                const box = btn.closest(".nibras-box");
                const content = box ? box.querySelector(".nibras-box-content") : null;
                const text = content ? content.innerText : "";
                copyText(text, btn);
            });
        });
    }

    function init() {
        addStyles();
        bindCopyButtons();
        const observer = new MutationObserver(muts => {
            muts.forEach(m => {
                m.addedNodes.forEach(n => {
                    if (n.nodeType === Node.ELEMENT_NODE) bindCopyButtons(n);
                });
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
"""
