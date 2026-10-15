# ==========================================================
#  code_boxes.py
#  ملف بايثون يحتوي على كود JavaScript الخاص بصناديق الأكواد
#  يدعم: الأكواد + الاقتباسات + الدروس (:::lesson)
# ==========================================================

CODE_BOXES_HEAD = ""
CODE_BOXES_CSS = ""

CODE_BOXES_JS = """
(() => {
    "use strict";

    const STYLE_ID = "nibras-copy-box-styles";

    // تصميم صناديق نبراس
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
            }

            .nibras-box-copy {
                border: 1px solid var(--border-color, #ddd);
                border-radius: 9px;
                background: var(--box-bg, #fff);
                color: inherit;
                padding: 7px 12px;
                font-size: 12px;
                cursor: pointer;
            }

            .nibras-box-copy:hover {
                opacity: .75;
            }

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
            }

            .nibras-box pre code {
                padding: 0;
                background: transparent;
                font-family: Consolas, Monaco, monospace;
            }

            .nibras-box blockquote {
                margin: 0;
                padding: 15px;
                border: none;
                background: var(--code-bg, #f7f8fa);
                border-right: 4px solid var(--primary-color, #4a6a8a);
                font-style: normal;
                color: inherit;
                line-height: 1.9;
            }

            .nibras-lesson-box .nibras-box-title {
                color: var(--primary-color, #4a6a8a);
            }

            @media (max-width: 600px) {
                .nibras-box {
                    border-radius: 11px;
                }

                .nibras-box-content,
                .nibras-box pre,
                .nibras-box blockquote {
                    padding: 11px;
                }
            }
        `;

        document.head.appendChild(style);
    }

    // إنشاء زر النسخ
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

        setTimeout(() => {
            button.textContent = "نسخ";
        }, 1800);
    }

    // دالة مساعدة لإنشاء صندوق
    function createBox(titleText, contentHTML, contentText, boxClass) {
        const box = document.createElement("div");
        box.className = "nibras-box" + (boxClass ? " " + boxClass : "");

        const head = document.createElement("div");
        head.className = "nibras-box-head";

        const title = document.createElement("span");
        title.className = "nibras-box-title";
        title.textContent = titleText;

        const button = document.createElement("button");
        button.type = "button";
        button.className = "nibras-box-copy";
        button.textContent = "نسخ";

        button.addEventListener("click", () => {
            copyText(contentText, button);
        });

        head.append(title, button);

        const body = document.createElement("div");
        body.className = "nibras-box-content";
        if (contentHTML) {
            body.innerHTML = contentHTML;
        } else {
            body.textContent = contentText || "";
        }

        box.append(head, body);
        return box;
    }

    // ✅ معالجة الأكواد (pre > code)
    function enhancePreBlocks(root) {
        const blocks = [];
        if (root.matches?.("pre")) blocks.push(root);
        root.querySelectorAll?.("pre").forEach(pre => blocks.push(pre));

        blocks.forEach(pre => {
            if (pre.closest(".nibras-box")) return;

            const code = pre.querySelector("code");
            if (!code || !pre.parentNode) return;

            const languageClass = [...code.classList].find(
                name => name.startsWith("language-")
            );

            const language = languageClass
                ? languageClass.replace("language-", "")
                : "كود";

            const box = document.createElement("div");
            box.className = "nibras-box";

            const head = document.createElement("div");
            head.className = "nibras-box-head";

            const title = document.createElement("span");
            title.className = "nibras-box-title";
            title.textContent = "{" + language + "}";

            const button = document.createElement("button");
            button.type = "button";
            button.className = "nibras-box-copy";
            button.textContent = "نسخ";

            button.addEventListener("click", () => {
                copyText(code.textContent, button);
            });

            head.append(title, button);

            pre.parentNode.insertBefore(box, pre);
            box.append(head, pre);
        });
    }

    // ✅ معالجة الاقتباسات (blockquote)
    function enhanceBlockquotes(root) {
        const blocks = [];
        if (root.matches?.("blockquote")) blocks.push(root);
        root.querySelectorAll?.("blockquote").forEach(bq => blocks.push(bq));

        blocks.forEach(bq => {
            if (bq.closest(".nibras-box")) return;
            if (!bq.parentNode) return;

            const contentText = (bq.innerText || bq.textContent || "").trim();
            const box = createBox("{اقتباس}", null, contentText, "nibras-quote-box");

            // انقل الـ blockquote داخل الصندوق
            bq.parentNode.insertBefore(box, bq);
            const body = box.querySelector(".nibras-box-content");
            body.innerHTML = "";
            body.appendChild(bq);
        });
    }

    // ✅ معالجة الدروس (:::lesson title ... :::)
    function enhanceLessonMarkers(root) {
        const markers = [];
        if (root.matches?.(".nibras-lesson-marker")) markers.push(root);
        root.querySelectorAll?.(".nibras-lesson-marker").forEach(m => markers.push(m));

        markers.forEach(marker => {
            if (!marker.parentNode) return;
            if (marker.closest(".nibras-box")) return;

            const title = marker.getAttribute("data-title") || "درس";
            const content = marker.getAttribute("data-content") || "";

            const box = createBox("📚 " + title, null, content, "nibras-lesson-box");
            marker.parentNode.replaceChild(box, marker);
        });
    }

    // ✅ الدالة الرئيسية لتشغيل كل التحسينات
    function enhanceCodeBlocks(root = document) {
        enhancePreBlocks(root);
        enhanceBlockquotes(root);
        enhanceLessonMarkers(root);
    }

    // إنشاء صندوق نص أو درس برمجياً
    window.NibrasCopyBox = {
        create: function (title, content) {
            return createBox(
                title || "نص جاهز",
                null,
                content || "",
                null
            );
        }
    };

    function init() {
        addStyles();
        enhanceCodeBlocks();

        const observer = new MutationObserver(mutations => {
            mutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        enhanceCodeBlocks(node);
                    }
                });
            });
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, {
            once: true
        });
    } else {
        init();
    }
})();
"""
