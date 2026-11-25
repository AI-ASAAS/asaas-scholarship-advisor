/**
 * DRAFT TERMS OF USE PAGE — NOT LEGAL ADVICE.
 * Marked as a DRAFT requiring review and approval by ASAAS management and legal counsel before launch.
 */
import { Card, Icon, Swash } from '../asaas-ui';
import { useLang } from '../lib/i18n';

export default function TermsPage() {
  const { lang, t } = useLang();
  const isEn = lang === 'en';

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('termsPageTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('legalDraftBanner')}
          </p>
        </div>
        <span className="pill pill--partial" aria-label={t('legalDraftBadge')}>
          <Icon name="alert" />
          {t('legalDraftBadge')}
        </span>
      </div>

      <Card title={isEn ? '1. Official Sources & Changing Scholarship Terms' : '1. المصادر الرسمية وتغيّر شروط المنح'} icon="checkCircle">
        <p className="prose" style={{ margin: 0 }}>
          {isEn
            ? 'Curated scholarship records are extracted with verbatim verification quotes from official provider pages; however, deadlines, funding amounts, and eligibility rules can change or close at any time without notice. You must always confirm every requirement and deadline directly on the official scholarship portal before submitting an application.'
            : 'تُستخلص بيانات المنح المعتمدة باقتباسات حرفية موثّقة من الصفحات الرسمية للمانحين، ومع ذلك قد تتغير المواعيد النهائية أو شروط التمويل والأهلية دون إشعار مسبق. يجب عليك دائماً التحقق مباشرة من البوابة الرسمية للمنحة قبل التقديم.'}
        </p>
      </Card>

      <Card title={isEn ? '2. Match Percentages & Eligibility Gates' : '2. نسب التطابق وبوابات الأهلية'} icon="trend">
        <p className="prose" style={{ margin: 0 }}>
          {isEn
            ? 'Match percentages measure how many published scholarship conditions your stated profile currently satisfies (computed deterministically in code). They are NOT admission probabilities, acceptance odds, or official pre-approvals. Missing profile information is marked as unknown rather than assumed eligible.'
            : 'تقيس نسبة التطابق عدد الشروط المنشورة التي يطابقها ملفك الحالي (بحساب برمجي حتمي)، ولا تمثّل إطلاقاً احتمال القبول أو ضمانه. البيانات غير المدخلة في ملفك تُعامل كـ«غير معروفة» ولا تُحتسب استيفاءً أو رفضاً.'}
        </p>
      </Card>

      <Card title={isEn ? '3. External Deep Search Results' : '3. نتائج البحث الخارجي العميق'} icon="search">
        <p className="prose" style={{ margin: 0 }}>
          {isEn
            ? 'Opportunities returned by the External Deep Search tool come directly from third-party websites fetched in real time and are marked "Outside the platform, not reviewed by ASAAS". ASAAS does not endorse or verify external search results before an administrator reviews and publishes them.'
            : 'الفرص التي يعرضها محرك البحث الخارجي تُجلب مباشرة من مواقع الجهات الخارجية وقت البحث وتُوسَم بعبارة «خارج المنصة — لم تراجعه أساس بعد»، ولا تُعد معتمدة أو مراجعة من فريق أساس ما لم تُدرَج لاحقاً في المنصة.'}
        </p>
      </Card>

      <Card title={isEn ? '4. Application Documents & Student Responsibility' : '4. مسودات المستندات ومسؤولية الطالب'} icon="receipt">
        <p className="prose" style={{ margin: 0 }}>
          {isEn
            ? 'CV outlines, motivation letter drafts, and recommendation briefs are writing aids grounded in the facts you provide. Unverified numbers or claims are flagged for your confirmation. You are solely responsible for reviewing, editing, and verifying the accuracy of every document you submit. Using this platform or its tools does not guarantee scholarship admission.'
            : 'مسودات السيرة الذاتية ورسالة الدافع وملخص التوصية هي أدوات مساعدة لصياغة حقائقك الحقيقية فقط، وتُميَّز أي أرقام أو وقائع غير موثقة لمراجعتك. أنت وحدك المسؤول عن دقة ومراجعة جميع مستنداتك قبل التقديم الرسمي، ولا يضمن استخدام المنصة القبول في أي منحة.'}
        </p>
      </Card>
    </div>
  );
}
