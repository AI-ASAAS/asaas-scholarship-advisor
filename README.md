# منح أساس — مستشار المنح الدراسية (ASAAS Scholarship Advisor Agent)

منصة ويب عربية أولاً (`RTL`، مصممة للجوال `375px` أولاً مع تبديل للإنجليزية `LTR`) تساعد الطلاب — اليمنيين كجمهور أساسي وجميع الجنسيات عبر نموذج أهلية عام — في استكشاف المنح الرسمية الموثقة، وحساب التطابق بشفافية، وتحليل الملف وتقويته، وإعداد مسودات المستندات وبناء خطة تقديم شخصية، مع مراقبة التحديثات والتنبيهات ومحادثة مستشار ذكي مقيد بالمجال.

---

## القدرات العشر المنجزة

1. **أفضل 10 منح معتمدة (`/`)**: منح منشورة غير منتهية مرتبة بالأولوية المنسّقة (`featured_rank`) ثم أقرب موعد إغلاق، مع نافذة تفاصيل واقتباسات حرفية موثّقة بالكود (`evidence`).
2. **إضافة المنح للمشرف بالرابط الرسمي (`/admin`)**: استخلاص آلي محمي ضد SSRF (`extraction@2.0` + `verify_evidence`) يُحفظ كمسودة `DRAFT` فقط ولا يُنشر إلا باعتماد المشرف.
3. **الملف الشخصي وحساب التطابق (`/profile`, `/matches`)**: جلسة طالب مجهولة الهوية في كوكي `HttpOnly` مع موافقة صريحة (`privacy-v1`)، تقييم بوابات الأهلية والجنسيات والمعدل بلغة بايثون حتمية بالكود دون تدخل النموذج في الدرجات.
4. **البحث الخارجي الواعي بالملف (`/search`)**: بحث مقيد بالسقوف (استعلامات/صفحات/خطوات/وقت/رموز) عبر `modules/search/`، فحص النطاقات وSSRF، التحقق بالاقتباس، ذاكرة 24 ساعة، وترقية للمشرف كمسودة فقط.
5. **تحليل الملف الشخصي (`/matches`)**: نقاط القوة والضعف والفجوات مستخرجة بالكود ومصاغة بالعربية مع بديل حتمي.
6. **توصيات تقوية الملف (`/documents`)**: فجوات عملية مرتبطة بشروط المنح وتقديرات تحضيرية موسومة كافتراضات.
7. **مساعدة مستندات التقديم (`/documents`)**: سيرة ذاتية، رسالة دافع، ودعم التوصية (طلب + ملخص للموصي دون كتابة خطاب موقّع) مع سجل حقائق (`FactsLedger`) يميّز أي ادعاء غير موثق.
8. **خطة التقديم الشخصية (`/plan`)**: ترتيب المنح المختارة حسب التطابق والموعد، قائمة متطلبات ومراحل مقترحة، كشف تداخل المواعيد، وتصدير تقويم `.ics`.
9. **المراقبة والتنبيهات (`/notifications`, `/admin`, `monitor_service.py`)**: رصد التغييرات عبر `SHA-256` ووضعها في طابور مراجعة المشرف (`GrantChangeReview`) قبل إشعار الطلاب، تذكيرات `14/7/3/1` أيام داخل التطبيق، قفل جدولة أحادي، وراصد تيليغرام مسجّل/اختياري.
10. **مستشار المنح الذكي (أداة المحادثة العائمة)**: مساعد حواري مقيّد بأدوات القراءة والاقتراحات المؤكدة من الطالب ورفض عربي ثابت لأي طلب خارج المنح.

---

## التثبيت والتشغيل المحلي

### 1. البيئة الخلفية والترحيل والبذر
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install -r requirements-dev.txt
copy .env.example .env

# تشغيل الترحيلات المرتبة وبذر أول 10 منح منشورة
python -c "from core.db import engine; from migrations.runner import run_migrations; run_migrations(engine)"
python seed/seed_db.py --publish

# تشغيل الخادم الخلفي (يخدم API و frontend/dist معاً)
$env:PYTHONPATH = ".;src"
uvicorn api.main:app --host 127.0.0.1 --port 8000 --reload
```

### 2. بناء الواجهة الأمامية وتشغيلها للتطوير
```powershell
cd frontend
npm ci
npm run lint
npm run build
# أو وضع التطوير مع HMR:
npm run dev
```

### 3. الاختبارات والتقييمات والمراقب
```powershell
# تشغيل حزمة الاختبارات الكاملة معزولة دون أي شبكة:
$env:PYTHONPATH = ".;src;.venv\Lib\site-packages"
$env:AGENT_OFFLINE = "1"
python -m pytest -q

# تشغيل تقييمات الذكاء الاصطناعي (استخدم --stub بدون مفتاح، أو --save مع مفتاح حي):
python -m evals.run_eval extraction --stub
python -m evals.run_eval profile_analysis --stub
python -m evals.run_eval advisor --stub
python -m evals.run_eval documents --stub
python -m evals.run_eval external_search --stub

# تشغيل دورة المراقبة + تنبيهات الطلاب + تنظيف الاحتفاظ بالبيانات:
python -m monitor_service --now
# أو في الإنتاج كعملية جدولة مستقلة واحدة:
python -m monitor_service --schedule --interval 24
```

---

## الوثائق الهندسية والتشغيلية

- [المعمارية وحدود الثقة (`docs/architecture.md`)](docs/architecture.md)
- [دليل العمليات والحدود والنسخ الاحتياطي (`docs/operations.md`)](docs/operations.md)
- [دليل المشرف لإضافة ومراجعة المنح (`docs/add-a-grant.md`)](docs/add-a-grant.md)
- [دليل النشر والتحضير للإطلاق (`docs/deploy.md`)](docs/deploy.md)
- [تقرير التدقيق الأمني الشامل (`docs/security/audit-report.md`)](docs/security/audit-report.md)
- [سجل القرارات الهندسية (`docs/decisions.md`)](docs/decisions.md)
