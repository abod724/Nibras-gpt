# research_agent.py
import os
import logging
from openai import OpenAI

# إعداد السجلات (Logging) لنعرف ماذا يحدث
logger = logging.getLogger(__name__)

# جلب مفتاح API من متغيرات البيئة
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.warning("⚠️ OPENAI_API_KEY غير موجود، وكيل البحث لن يعمل!")

# تهيئة العميل
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# النموذج المخصص للبحث (يفضل أن يدعم web_search)
# يمكنك تغييره إلى gpt-5.6-luna أو gpt-4o
RESEARCH_MODEL = os.environ.get("RESEARCH_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o"))

def perform_research(query: str) -> str:
    """
    وكيل البحث: يتصل بالويب، يجمع المعلومات، ويرجع نصاً منسقاً.
    """
    if not client:
        logger.error("لا يمكن البحث: عميل OpenAI غير مهيأ.")
        return ""
        
    if not query or len(query.strip()) < 3:
        return ""

    try:
        logger.info(f"🕵️ وكيل البحث يبحث الآن عن: {query}")
        
        # استخدام Responses API مع أداة البحث
        response = client.responses.create(
            model=RESEARCH_MODEL,
            instructions=(
                "أنت وكيل بحث (Research Agent) دقيق وسريع. "
                "مهمتك هي البحث في الويب عن المعلومات الحديثة. "
                "قم بتلخيص النتائج واستخراج الحقائق والأرقام. "
                "اذكر أسماء المصادر والروابط (URLs) بوضوح في نهاية النص."
            ),
            input=f"ابحث عن أحدث المعلومات حول: {query}",
            tools=[{"type": "web_search"}],
            timeout=25.0, # مهلة قصوى لتجنب تعليق السيرفر
            max_output_tokens=1200 # حد التكلفة
        )
        
        # استخراج النص من الرد
        result_text = ""
        if hasattr(response, "output_text") and response.output_text:
            result_text = response.output_text.strip()
        elif getattr(response, "output", None):
            parts = []
            for item in response.output:
                if hasattr(item, "content"):
                    for content in item.content:
                        if getattr(content, "type", "") == "output_text":
                            parts.append(getattr(content, "text", ""))
            result_text = "\n".join(parts).strip()
            
        logger.info("✅ وكيل البحث أنهى مهمته بنجاح.")
        return result_text
        
    except Exception as e:
        logger.error(f"❌ فشل وكيل البحث: {type(e).__name__}: {e}")
        return "" # نرجع نص فارغ في حال الفشل لكي لا ينهار التطبيق
