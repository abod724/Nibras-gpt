# -*- coding: utf-8 -*-
"""
سكربت لإضافة زر "مكتبة المساعدين" في الإعدادات تلقائياً
"""
import re
import sys
import os

FILE = 'app.py'

if not os.path.exists(FILE):
    print("❌ ما لقيت ملف app.py في نفس المجلد")
    sys.exit(1)

with open(FILE, 'r', encoding='utf-8') as f:
    content = f.read()

# تحقق إذا الزر موجود مسبقاً
if 'openAssistantLibrary()' in content:
    print("✅ الزر موجود مسبقاً! ما تحتاج تعديل.")
    sys.exit(0)

# البحث عن سطر "مساعدي الخاص"
target = """<div class="settings-item" onclick="openSubPage('assistants')"><div class="item-right"><svg viewBox="0 0 24 24"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg><span>مساعدي الخاص</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>"""

if target not in content:
    print("❌ ما لقيت سطر 'مساعدي الخاص' — تأكد من نسخة الكود")
    sys.exit(1)

# الزر الجديد (كتابان مفتوحان)
new_button = """
                <div class="settings-item" onclick="openAssistantLibrary()"><div class="item-right"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg><span>مكتبة المساعدين</span></div><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div>"""

# استبدال (إضافة الزر بعد "مساعدي الخاص")
new_content = content.replace(target, target + new_button, 1)

# نسخة احتياطية
with open('app.py.backup', 'w', encoding='utf-8') as f:
    f.write(content)
print("✅ تم إنشاء نسخة احتياطية: app.py.backup")

# حفظ التعديل
with open(FILE, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("✅ تم إضافة زر 'مكتبة المساعدين' بنجاح!")
print("")
print("الخطوات التالية:")
print("1. أعد تشغيل السيرفر")
print("2. افتح الإعدادات")
print("3. راح تلقى 'مكتبة المساعدين' بعد 'مساعدي الخاص' مباشرة")
