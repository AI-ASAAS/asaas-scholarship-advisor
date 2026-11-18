# Autonomous Discovery & Web Research Sub-Agent
وكيل الاستكشاف والبحث المستقل للمنح الدراسية (للطلاب اليمنيين)

نظام وكلاء ذكاء اصطناعي مستقل لاستكشاف المنح الدراسية والتحقق منها وإدارتها وفق فلسفة صارمة ضد الهلوسة: **"الكود يتحقق والموديل ينقل"**، وباتباع معايير [AI-ASAAS/skills](https://github.com/AI-ASAAS/skills).

---

## 🏛️ الهيكلية المعمارية (4-Layer Architecture)

```
Entrypoints (Admin / Student Profile / Scheduler)
        │
        ▼
Agents Layer:
  ├── ingestion_sub_agent.py        (Task 2: Agentic Scraper & Sub-link Crawler)
  ├── external_search_sub_agent.py  (Task 4: ReAct Deep Search Agent - max 5 steps)
  ├── monitor_service.py            (Task 9: Freshness Hash Monitor & Closing Alerts)
  └── integrations/telegram_watcher.py (Optional Creative Task)
        │
        ▼
Verification & Anti-Hallucination Layer:
  ├── utils/url_validator.py        (HTTP 200 + Trusted Domain + Content Match)
  ├── utils/evidence_check.py       (Normalized Verbatim Quote Grounding)
  ├── utils/llm_extractor.py        (Pydantic v2 + temperature=0 + 1 Retry)
  └── prompts/*.md                  (Versioned Prompt Files)
        │
        ▼
Data Layer (SQLite WAL / PostgreSQL Portable):
  ├── core/config.py                (.env Typed Settings)
  ├── core/models.py                (Grant, GrantStatus, YemeniEligibilityStatus, UpdateLog)
  ├── core/db.py                    (WAL Mode + Foreign Keys + Busy Timeout)
  └── core/repository.py            (get_top_10_grants, save_draft, publish, log_update)
```

---

## 🛡️ منظومة منع الهلوسة (Anti-Hallucination Guarantees)

1. **التثبيت بالمصدر (`Source Grounding`)**: الاستخراج يتم حصراً من نص الصفحة المجلوب بـ `temperature = 0` ومخرجات JSON مطابقة لمخطط Pydantic صارم.
2. **التدقيق بالاقتباس الحرفي (`verify_evidence`)**: كل حقل مستخرج يجب أن يرافقه اقتباس حرفي من الصفحة؛ إذا كان الاقتباس مختلقاً أو مفقوداً يُصفَّر الحقل فوراً إلى `null` ويوسم بـ `unverified`.
3. **مسودة قبل النشر (`Writes are Proposals`)**: كل منحة تدخل النظام بحالة `draft` فقط، والنشر بيد الإدارة البشرية.
4. **انضباط وكيل البحث ReAct**: حد أقصى 5 خطوات، لا يُرجع أي رابط من ذاكرة النموذج، ولا يقبل نتيجة إلا بعد زيارة صفحتها والتحقق من رسميتها بالكود وفحص قبول اليمنيين بنص صريح.
5. **المراقبة بالكود**: مقارنة بصمة `SHA-256` والمواعيد برمجياً، وتسجيل التغييرات في `UpdateLog` دون تعديل المنحة المنشورة تلقائياً.

---

## 🚀 التثبيت والإعداد

```bash
# 1. إنشاء البيئة الافتراضية وتفعيلها
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1

# 2. تثبيت الاعتماديات الأساسية
pip install -r requirements.txt

# 3. تجهيز ملف البيئة
cp .env.example .env
# ثم أضف مفاتيحك (LLM_API_KEY, TAVILY_API_KEY أو SERPER_API_KEY) داخل .env
```

---

## 💻 أمثلة تشغيل كل وكيل

### 1. تهيئة قاعدة البيانات وتعبئة أول 10 منح حقيقية (المهمة 1)
```bash
# تعبئة المنح كمسودات (DRAFT) للمراجعة الإدارية:
python seed/seed_db.py

# تعبئة المنح ونشرها وعرض أفضل 10 منح مرتبة بأقرب موعد:
python seed/seed_db.py --publish
```

### 2. وكيل الاستخلاص الذاتي من الرابط الرسمي (المهمة 2)
```python
from ingestion_sub_agent import ingest

# يحول أي رابط رسمي إلى مسودة منحة كاملة موثقة بالاقتباسات (DRAFT)
draft_grant = ingest("https://www.turkiyeburslari.gov.tr/")
print(draft_grant.title, draft_grant.status, draft_grant.field_verification)
```

### 3. وكيل البحث الخارجي العميق ReAct (المهمة 4)
```bash
python external_search_sub_agent.py --major "Computer Science" --degree "Master" --country "Germany"
```
أو برمجياً:
```python
from external_search_sub_agent import search_external_scholarships

report = search_external_scholarships(
    major="Computer Science",
    degree_level="Master",
    target_country="Germany",
)
for grant in report.results:
    print(grant.title, grant.official_url, grant.accepts_yemeni)
```

### 4. مراقب التحديثات وتنبيهات الإغلاق القريب (المهمة 9)
```bash
# تنفيذ دورة فحص فورية لجميع المنح المنشورة:
python monitor_service.py --now

# تشغيل المجدول اليومي الآلي (كل 24 ساعة عبر APScheduler):
python monitor_service.py --schedule --interval 24
```

### 5. قارئ قنوات التيليجرام الإبداعي (المرحلة 8)
```bash
# قراءة آخر 20 منشوراً من القنوات المعتمدة في TELEGRAM_CHANNELS وتحويل الروابط الرسمية الجديدة إلى مسودات:
python integrations/telegram_watcher.py --limit 20
```
*(يستخرج الروابط الرسمية فقط ويمررها إلى `ingest()`، ولا يأخذ أي معلومة من نص المنشور تفادياً لأي معلومات غير دقيقة).*

### 6. تشغيل الواجهة الأمامية (ASAAS UI + FastAPI)
```bash
# 1. بناء الواجهة الأمامية (React + Vite + TypeScript + asaas-ui):
cd frontend
npm install
npm run build
cd ..

# 2. تشغيل خادم FastAPI (يخدم الـ API والواجهة المبنية معاً):
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
# ثم افتح المتصفح على: http://127.0.0.1:8001
```

---

## 🧪 تشغيل الاختبارات الشاملة

```bash
pytest -v
```
تغطي الاختبارات جميع الطبقات:
* `tests/test_repository.py`: استرجاع أفضل 10 منح، استبعاد المسودات والمنتهية، والترتيب.
* `tests/test_url_validator.py`: رفض المجمّعات الإعلانية والروابط الميتة وغير المطابقة.
* `tests/test_evidence_check.py`: تطبيع النصوص وتصفير الحقول ذات الاقتباسات المختلقة.
* `tests/test_llm_extractor.py`: تحميل البرومبتات المرقّمة ومخطط Pydantic.
* `tests/test_ingestion.py`: الاستخلاص بصفحة HTML محلية وتتبع الرابط الفرعي والصفحات الناقصة.
* `tests/test_seed.py`: تعبئة المنح الـ 10 ونشرها.
* `tests/test_monitor.py`: اكتشاف تغيير البصمة والمواعيد وتنبيهات الـ 7 أيام والـ 3 أيام والانتهاء.
* `tests/test_external_search.py`: حلقة ReAct، حد الـ 5 خطوات، وفحص أهلية اليمنيين.
* `tests/test_e2e_pipeline.py`: سيناريو كامل من البداية للنهاية (رابط ← مسودة ← نشر ← Top 10 ← مراقب ← انتهاء).
* `tests/test_telegram_watcher.py`: استخراج الروابط من منشورات التيليجرام، الفلترة، منع التكرار، والتسليم لوكيل الاستخلاص.

---

## ✅ قائمة التسليم النهائية (Delivery Checklist)
- [x] قاعدة بيانات مهيأة تحتوي على أول 10 منح حقيقية بروابط رسمية وأهلية موثقة لليمنيين (`seed/seed_db.py`)
- [x] كل حقل مهم له `evidence` يتحقق منه الكود فعلياً في نص الصفحة
- [x] الوكيل يرجع `null` ويعلّم الحقل `unverified` عند نقص أو اختلاق المعلومة
- [x] كل المنح الجديدة تدخل بحالة `draft` ولا يوجد نشر تلقائي
- [x] المراقب يكتشف تغيير المواعيد ويسجلها وينبه قبل الإغلاق بـ 7 و 3 أيام (`monitor_service.py`)
- [x] وكيل البحث يرفض الروابط الوهمية وغير الرسمية ولا يتجاوز 5 خطوات (`external_search_sub_agent.py`)
- [x] قارئ قنوات التيليجرام الإبداعي يستخرج الروابط الرسمية ويمررها للاستخلاص بدون نسخ يدوي (`integrations/telegram_watcher.py`)
- [x] لا مفاتيح مكشوفة في المستودع (`.env` خارج Git)
- [x] ملف `README.md` كامل مع التثبيت والتشغيل ومثال لكل وكيل
- [x] كافة الاختبارات (الوحدة والتكامل E2E) تمر بنسبة 100%
