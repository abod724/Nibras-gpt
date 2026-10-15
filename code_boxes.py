
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

            @media (max-width: 600px) {
                .nibras-box {
                    border-radius: 11px;
                }

                .nibras-box-content,
                .nibras-box pre {
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

    // تحويل كتل الأكواد إلى صناديق
    function enhanceCodeBlocks(root = document) {
        const blocks = [];

        if (root.matches?.("pre")) blocks.push(root);

        root.querySelectorAll?.("pre").forEach(pre => {
            blocks.push(pre);
        });

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

    // إنشاء صندوق نص أو درس باستخدام نص عادي آمن
    window.NibrasCopyBox = {
        create: function (title, content) {
            const box = document.createElement("div");
            box.className = "nibras-box";

            const head = document.createElement("div");
            head.className = "nibras-box-head";

            const heading = document.createElement("span");
            heading.className = "nibras-box-title";
            heading.textContent = title || "نص جاهز";

            const button = document.createElement("button");
            button.type = "button";
            button.className = "nibras-box-copy";
            button.textContent = "نسخ";

            const body = document.createElement("div");
            body.className = "nibras-box-content";
            body.textContent = content || "";

            button.addEventListener("click", () => {
                copyText(body.innerText, button);
            });

            head.append(heading, button);
            box.append(head, body);

            return box;
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
