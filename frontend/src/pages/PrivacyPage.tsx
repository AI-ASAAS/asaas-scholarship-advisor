/**
 * DRAFT PRIVACY NOTICE PAGE — NOT LEGAL ADVICE.
 * Marked as a DRAFT requiring review and approval by ASAAS management and legal counsel before launch.
 */
import { Card, Icon, Swash } from '../asaas-ui';
import { useLang } from '../lib/i18n';

export default function PrivacyPage() {
  const { lang, t } = useLang();
  const isEn = lang === 'en';

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('privacyPageTitle')}</Swash>
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

      <Card title={isEn ? '1. Minimal Academic Data We Collect' : '1. الحد الأدنى من البيانات الأكاديمية التي نجمعها'} icon="users">
        <p className="prose" style={{ marginTop: 0 }}>
          {isEn
            ? 'ASAAS Scholarship Advisor operates anonymously via a server-issued HttpOnly session cookie without student accounts. Only academic and preference fields you choose to provide are stored: nationality, optional country of residence, current and target degree level, major, GPA/scale, languages/scores, target countries/fields, funding preference, years of experience, anonymized experience notes, publications count, and optional integer age.'
            : 'يعمل مستشار المنح عبر جلسة مجهولة الهوية صادرة من الخادم داخل ملف تعريف ارتباط HttpOnly دون إنشاء حسابات أو جمع بيانات تواصل. تُخزَّن فقط البيانات الأكاديمية التي تختار إدخالها: الجنسية، بلد الإقامة الاختياري، الدرجة الحالية والمستهدفة، التخصص، المعدل الأكاديمي ونظامه، اللغات ودرجاتها، الدول والتخصصات المستهدفة، نوع التمويل المطلوب، سنوات الخبرة، ملاحظات الخبرة المجرّدة من المعرّفات، عدد الأبحاث، والعمر كعدد صحيح اختياري.'}
        </p>
        <p className="prose" style={{ marginBottom: 0 }}>
          {isEn
            ? 'We intentionally do NOT collect your full name, email address, phone number, national ID, passport number, date of birth, or street address.'
            : 'نحن لا نجمع اسمك الكامل، ولا بريدك الإلكتروني، ولا رقم هاتفك، ولا رقم الهوية الوطنية أو جواز السفر، ولا تاريخ الميلاد أو عنوان السكن.'}
        </p>
      </Card>

      <Card title={isEn ? '2. Explicit Consent & AI Provider Boundary' : '2. الموافقة الصريحة وحدود مزوّد الذكاء الاصطناعي'} icon="sparkle">
        <p className="prose" style={{ marginTop: 0 }}>
          {isEn
            ? 'Your profile, saved drafts, application plan, and notification preferences are stored and processed only after your explicit consent (version privacy-v1). Student identifiers (session IDs, cookies, or accidentally typed emails/phones/ID numbers) are scrubbed before any academic text or prompt is sent to the configured AI provider.'
            : 'لا يُحفظ ملفك الشخصي أو مسوداتك أو خطتك أو تفضيلات التنبيهات إلا بعد موافقتك الصريحة (الإصدار privacy-v1). يتم تنقيح أي معرّفات أو أرقام هواتف أو بريد إلكتروني يُكتب عرضاً في النصوص قبل إرسال البيانات الأكاديمية المجردة إلى مزوّد الذكاء الاصطناعي المهيأ.'}
        </p>
        <p className="prose" style={{ marginBottom: 0 }}>
          {isEn
            ? 'AI processing runs through the configured OpenAI-compatible provider (by default OpenRouter with zero-data-collection flags enabled where supported, or configured Google Gemini). Prompts and student profile payloads are never recorded in application logs.'
            : 'تتم معالجة الذكاء الاصطناعي عبر المزوّد المهيأ على الخادم (OpenRouter افتراضياً مع تفعيل خيار منع احتفاظ المزوّد بالبيانات data_collection=deny متى أمكن، أو Google Gemini المهيأ). لا تُسجَّل نصوص المحادثات أو ملفات الطلاب في سجلات الخادم.'}
        </p>
      </Card>

      <Card title={isEn ? '3. Data Retention, Export & Immediate Deletion' : '3. مدة الاحتفاظ، التصدير، والحذف الفوري'} icon="trash">
        <ul className="detail-list" style={{ margin: 0 }}>
          <li>
            {isEn
              ? 'Inactive anonymous student sessions and all linked records are purged automatically after 90 days of inactivity.'
              : 'تُحذف جلسات الطلاب غير النشطة وجميع سجلاتها المرتبطة تلقائياً بعد مرور 90 يوماً على آخر نشاط.'}
          </li>
          <li>
            {isEn
              ? 'Advisor chat messages are retained for 30 days; saved document drafts and read alerts for 90 days; anonymized external search cache entries for 24 hours.'
              : 'تُحفظ رسائل المستشار لمدة 30 يوماً، ومسودات المستندات والتنبيهات المقروءة لمدة 90 يوماً، وذاكرة البحث الخارجي المجهولة لمدة 24 ساعة.'}
          </li>
          <li>
            {isEn
              ? 'From the Profile page you can export all stored JSON data or click "Delete All My Data" for immediate atomic deletion across active tables (sessions, consents, profiles, chat, drafts, plans, notifications) and cookie clearing. Encrypted database backups, if enabled by hosting, follow standard backup rotation.'
              : 'من صفحة «ملفي» يمكنك تنزيل نسخة كاملة من بياناتك أو اختيار «حذف جميع بياناتي» للحذف الذري الفوري من كل الجداول النشطة ومسح ملف الجلسة. إذا فعّلت الاستضافة نسخاً احتياطية مشفرة، تخضع لسياسة تدوير النسخ المعتمدة.'}
          </li>
        </ul>
      </Card>
    </div>
  );
}
