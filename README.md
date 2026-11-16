# Autonomous Discovery & Web Research Sub-Agent
وكيل الاستكشاف والبحث المستقل للمنح الدراسية (للطلاب اليمنيين)

نظام وكلاء ذكاء اصطناعي مستقل لاستكشاف المنح الدراسية والتحقق منها وإدارتها وفق فلسفة صارمة ضد الهلوسة: **"الكود يتحقق والموديل ينقل"**.

---

## 🏛️ الهيكلية المعمارية (4-Layer Architecture)

1. **طبقة نقاط الدخول (Entrypoints)**: الإدارة (استخلاص رابط)، ملف الطالب (بحث عميق)، المجدول الآلي (فحص دوري).
2. **طبقة الوكلاء (Agents)**:
   - `ingestion_sub_agent.py`: وكيل الاستخلاص الآلي من الروابط الرسمية (Task 2).
   - `external_search_sub_agent.py`: وكيل البحث العميق بنمط ReAct (Task 4).
   - `monitor_service.py`: مراقب التحديثات وتغيير المواعيد (Task 9).
   - `integrations/telegram_watcher.py`: راصد قنوات التيليجرام لاستخراج الروابط (Creative / Optional).
3. **طبقة التحقق ومنع الهلوسة (Verification Layer)**:
   - `utils/url_validator.py`: فحص النطاق الرسمي ومطابقة المحتوى وHTTP 200.
   - `utils/evidence_check.py`: مطابقة الاقتباسات الحرفية وإلغاء أي حقل غير موثق.
   - `utils/llm_extractor.py`: استخراج مهيكل بـ temperature=0 ومخطط Pydantic صارم.
4. **طبقة البيانات (Data Layer)**:
   - `core/models.py`: نماذج Grant وUpdateLog وGrantStatus.
   - `core/db.py`: محرك قاعدة البيانات وجلسات الاتصال.
   - `core/repository.py`: عمليات الاسترجاع السريع لأفضل 10 منح وحفظ المسودات وسجلات التحديث.

---

## 🚀 التثبيت والتشغيل

1. **إنشاء البيئة الافتراضية وتفعيلها**:
   ```bash
   python -m venv .venv
   # Windows PowerShell:
   .venv\Scripts\Activate.ps1
   ```

2. **تثبيت الاعتماديات**:
   ```bash
   pip install -r requirements.txt
   ```

3. **إعداد المتغيرات في ملف البيئة**:
   قم بنسخ `.env.example` إلى `.env` وقم بتعبئة المفاتيح المطلوبة:
   ```bash
   cp .env.example .env
   ```

4. **تشغيل الاختبارات**:
   ```bash
   pytest tests/
   ```
