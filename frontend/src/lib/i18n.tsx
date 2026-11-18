import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import type { KitLang } from '../asaas-ui';

const ar = {
  brandName: 'منح أساس',
  brandTag: 'وكيل الاستكشاف الذكي',
  navTop10: 'أفضل 10 منح',
  navSearch: 'البحث العميق',
  navAdmin: 'الإدارة والاستخلاص',
  navMonitor: 'المراقب والتحديثات',
  tabNavTop10: 'المنح',
  tabNavSearch: 'البحث',
  tabNavAdmin: 'الإدارة',
  tabNavMonitor: 'المراقب',
  themeToggle: 'تبديل الوضع',
  langToggle: 'English',

  // Top 10 Page
  top10Title: 'أفضل 10 منح متاحة حالياً',
  top10Subtitle: 'منح دراسية رسمية موثّقة بالاقتباس الحرفي للطلاب اليمنيين — مرتبة تلقائياً بأقرب موعد إغلاق.',
  statPublished: 'منح منشورة',
  statDrafts: 'مسودات للمراجعة',
  statYemenReady: 'تقبل اليمنيين',
  statLogs: 'سجلات التحديث',
  unitGrant: 'منحة',
  unitLog: 'سجل',
  filterPlaceholder: 'ابحث باسم المنحة أو التخصص أو الدولة…',
  yemenYes: 'تقبل اليمنيين',
  yemenNo: 'لا تقبل اليمنيين',
  yemenUnclear: 'غير محدد صراحةً',
  statusPublished: 'منشورة',
  statusDraft: 'مسودة',
  statusExpired: 'منتهية',
  deadlineLabel: 'آخر موعد',
  rollingDeadline: 'مفتوح / مستمر',
  daysLeft: 'يوم متبقٍ',
  viewDetails: 'التفاصيل والأدلة',
  officialPortal: 'الموقع الرسمي',
  verifiedFields: 'حقل موثق',
  noGrantsTitle: 'لا توجد منح مطابقة',
  noGrantsBody: 'جرّب تعديل كلمة البحث أو أضف منحاً جديدة من بوابة الإدارة.',

  // Grant Modal
  modalDescription: 'نبذة عن المنحة',
  modalFunding: 'التمويل والمزايا',
  modalEligibility: 'الشروط والأهلية',
  modalFields: 'التخصصات المشمولة',
  modalDocuments: 'الوثائق المطلوبة',
  modalHowToApply: 'طريقة التقديم',
  modalEvidenceTitle: 'أدلة منع الهلوسة (الاقتباسات الحرفية من المصدر)',
  modalVerified: 'موثّق بالكود',
  modalUnverified: 'غير موثّق',
  modalClose: 'إغلاق',

  // Search Page (ReAct)
  searchTitle: 'وكيل البحث الخارجي العميق',
  searchSubtitle: 'وكيل ReAct مستقل بحد أقصى 5 خطوات — يزور الصفحات الرسمية ويتحقق من الرابط وأهلية الطلاب اليمنيين قبل إرجاع أي نتيجة.',
  fieldMajor: 'التخصص الدراسي',
  fieldMajorPh: 'مثال: Computer Science أو هندسة برمجيات',
  fieldDegree: 'الدرجة العلمية',
  fieldCountry: 'الدولة المستهدفة (اختياري)',
  fieldCountryPh: 'مثال: Germany أو UK أو اتركه فارغاً',
  btnRunSearch: 'بدء البحث العميق',
  searchKeyMissing: 'لتفعيل البحث الخارجي الحي، أضف TAVILY_API_KEY أو SERPER_API_KEY في ملف .env وأعد تشغيل الخادم.',
  reactTraceTitle: 'سجل تفكير الوكيل (ReAct Trace)',
  reactResultsTitle: 'النتائج الرسمية الموثّقة',
  reactNoResults: 'لم تُعرض نتائج بعد — أدخل ملف الطالب واضغط بدء البحث.',
  stepLabel: 'خطوة',
  thoughtLabel: 'تفكير',
  actionLabel: 'إجراء',
  observationLabel: 'ملاحظة',

  // Admin Page
  adminTitle: 'بوابة الإدارة والاستخلاص الذاتي',
  adminSubtitle: 'أدخل الرابط الرسمي لأي منحة ليحولها الوكيل إلى مسودة موثقة، أو راجع المسودات واعتمد نشرها للطلاب.',
  ingestCardTitle: 'وكيل الاستخلاص بالرابط (مهمة 2)',
  fieldOfficialUrl: 'الرابط الرسمي للمنحة',
  fieldOfficialUrlHint: 'يقبل النطاقات الرسمية فقط ويرفض المجمّعات الإعلانية.',
  btnIngest: 'استخلاص كمسودة (Draft)',
  ingestKeyNotice: 'أضف LLM_API_KEY في .env لتفعيل الاستخلاص الحي بالذكاء الاصطناعي.',
  reviewCardTitle: 'مراجعة واعتماد المنح',
  tabAll: 'الكل',
  tabDraft: 'مسودات',
  tabPublished: 'منشورة',
  tabExpired: 'منتهية',
  btnPublish: 'اعتماد ونشر',
  publishSuccess: 'تم اعتماد المنحة ونشرها للطلاب بنجاح.',
  telegramCardTitle: 'راصد قنوات التيليجرام الإبداعي (المرحلة 8)',
  telegramHint: 'ألصق منشوراً أو أكثر من قنوات المنح؛ سيستخرج النظام الروابط الرسمية فقط، يرفض روابط t.me والمجمّعات، ويزيل المكرر.',
  btnTelegramScan: 'فحص المنشورات واستخراج الروابط الرسمية',
  telegramSampleBtn: 'مثال تجريبي',

  // Monitor Page
  monitorTitle: 'مراقب التحديثات والمواعيد (مهمة 9)',
  monitorSubtitle: 'يفحص الروابط الرسمية دورياً عبر بصمة SHA-256، يرصد تغيير المواعيد دون تعديل المنحة المنشورة تلقائياً، وينبّه قبل الإغلاق بـ 7 و 3 أيام.',
  btnRunMonitor: 'تشغيل فحص التحديثات الآن',
  monitorSuccess: 'اكتملت دورة الفحص الحي للمواقع الرسمية.',
  readinessCardTitle: 'جاهزية مفاتيح الوكلاء (.env)',
  logsCardTitle: 'سجل التحديثات والتغييرات (UpdateLog)',
  colGrant: 'المنحة',
  colField: 'الحقل',
  colOld: 'القيمة السابقة',
  colNew: 'القيمة الجديدة',
  colDate: 'وقت الرصد',
  noLogsTitle: 'لا توجد تحديثات مسجّلة بعد',
  noLogsBody: 'اضغط "تشغيل فحص التحديثات الآن" لفحص الروابط الرسمية وتسجيل بصماتها.',
  readyYes: 'مفعّل',
  readyNo: 'غير مضبوط',
  apiKeysTitle: 'إعداد مفاتيح الـ API (إدخال يدوي)',
  apiKeysBtn: 'إدخال المفاتيح',
  apiKeysSubtitle: 'أدخل مفاتيحك هنا مباشرة؛ تُفعَّل فوراً دون إعادة تشغيل الخادم وتُحفظ محلياً بأمان.',
  apiKeyLlm: 'مفتاح الذكاء الاصطناعي (LLM API Key)',
  apiKeyLlmHint: 'يدعم Google Gemini (AIza...) أو OpenAI (sk-...) أو OpenRouter.',
  apiKeyModel: 'نموذج الذكاء الاصطناعي (LLM Model)',
  apiKeyTavily: 'مفتاح محرك بحث Tavily (أساسي)',
  apiKeyTavilyHint: 'لوصول وكيل البحث العميق ReAct إلى الإنترنت (tvly-...).',
  apiKeySerper: 'مفتاح محرك بحث Serper (بديل اختياري)',
  apiKeySerperHint: 'يُستخدم تلقائياً إذا لم تضف مفتاح Tavily.',
  apiKeyTgId: 'Telegram API ID (اختياري)',
  apiKeyTgHash: 'Telegram API Hash (اختياري)',
  apiKeyTgChannels: 'قنوات التيليجرام المعتمدة (اختياري)',
  apiKeyTgChannelsHint: 'افصل بين أسماء القنوات بفاصلة، مثال: @grants_ye, @scholarships',
  btnSaveKeys: 'حفظ وتفعيل المفاتيح',
  keysSavedSuccess: 'تم حفظ وتفعيل مفاتيح الـ API بنجاح — الوكلاء جاهزون الآن!',
} as const;

type DictKey = keyof typeof ar;

const en: Record<DictKey, string> = {
  brandName: 'Asaas Grants',
  brandTag: 'Autonomous Discovery Agent',
  navTop10: 'Top 10 Grants',
  navSearch: 'Deep Search',
  navAdmin: 'Admin & Scraper',
  navMonitor: 'Monitor & Logs',
  tabNavTop10: 'Grants',
  tabNavSearch: 'Search',
  tabNavAdmin: 'Admin',
  tabNavMonitor: 'Monitor',
  themeToggle: 'Toggle theme',
  langToggle: 'العربية',

  top10Title: 'Top 10 Active Scholarships',
  top10Subtitle: 'Official scholarships grounded with verbatim quotes for Yemeni students — ordered by closest deadline.',
  statPublished: 'Published Grants',
  statDrafts: 'Pending Drafts',
  statYemenReady: 'Accepts Yemeni',
  statLogs: 'Update Logs',
  unitGrant: 'grants',
  unitLog: 'logs',
  filterPlaceholder: 'Filter by title, major, or country…',
  yemenYes: 'Accepts Yemeni',
  yemenNo: 'Excludes Yemen',
  yemenUnclear: 'Eligibility Unclear',
  statusPublished: 'Published',
  statusDraft: 'Draft',
  statusExpired: 'Expired',
  deadlineLabel: 'Deadline',
  rollingDeadline: 'Rolling / Open',
  daysLeft: 'days left',
  viewDetails: 'Details & Evidence',
  officialPortal: 'Official Portal',
  verifiedFields: 'verified fields',
  noGrantsTitle: 'No matching scholarships',
  noGrantsBody: 'Try adjusting your search query or ingest new grants in the Admin panel.',

  modalDescription: 'Overview',
  modalFunding: 'Funding & Benefits',
  modalEligibility: 'Eligibility Criteria',
  modalFields: 'Fields of Study',
  modalDocuments: 'Required Documents',
  modalHowToApply: 'How to Apply',
  modalEvidenceTitle: 'Anti-Hallucination Evidence (Verbatim Source Quotes)',
  modalVerified: 'Code Verified',
  modalUnverified: 'Unverified',
  modalClose: 'Close',

  searchTitle: 'External ReAct Deep Search Agent',
  searchSubtitle: 'Bounded 5-step ReAct agent — visits official portals, validates domains, and verifies explicit Yemeni eligibility.',
  fieldMajor: 'Academic Major',
  fieldMajorPh: 'e.g. Computer Science, Renewable Energy',
  fieldDegree: 'Degree Level',
  fieldCountry: 'Target Country (Optional)',
  fieldCountryPh: 'e.g. Germany, UK, or leave blank',
  btnRunSearch: 'Start Deep Search',
  searchKeyMissing: 'Add TAVILY_API_KEY or SERPER_API_KEY in .env and restart the server to run live web search.',
  reactTraceTitle: 'Agent Reasoning Log (ReAct Trace)',
  reactResultsTitle: 'Verified Official Results',
  reactNoResults: 'No results yet — enter a student profile and start deep search.',
  stepLabel: 'Step',
  thoughtLabel: 'Thought',
  actionLabel: 'Action',
  observationLabel: 'Observation',

  adminTitle: 'Admin Review & Autonomous Ingestion',
  adminSubtitle: 'Submit any official scholarship URL to create a verified DRAFT, review quotes, and publish to students.',
  ingestCardTitle: 'Agentic URL Scraper (Task 2)',
  fieldOfficialUrl: 'Official Scholarship URL',
  fieldOfficialUrlHint: 'Accepts trusted official domains only and rejects ad aggregators.',
  btnIngest: 'Ingest as Draft',
  ingestKeyNotice: 'Configure LLM_API_KEY in .env to enable live LLM extraction.',
  reviewCardTitle: 'Review & Publish Grants',
  tabAll: 'All',
  tabDraft: 'Drafts',
  tabPublished: 'Published',
  tabExpired: 'Expired',
  btnPublish: 'Approve & Publish',
  publishSuccess: 'Scholarship approved and published successfully.',
  telegramCardTitle: 'Telegram Channel Watcher (Phase 8 Creative)',
  telegramHint: 'Paste scholarship Telegram posts; extracts official URLs only, blocks t.me & aggregators, and deduplicates.',
  btnTelegramScan: 'Scan Posts & Extract Official URLs',
  telegramSampleBtn: 'Load Sample Post',

  monitorTitle: 'Freshness Monitor & Deadline Alerts (Task 9)',
  monitorSubtitle: 'Checks official portals via SHA-256 hashes, logs changes without auto-overwriting published grants, and fires 7-day & 3-day closing alerts.',
  btnRunMonitor: 'Run Monitor Check Now',
  monitorSuccess: 'Live monitoring cycle completed.',
  readinessCardTitle: 'Agent API Readiness (.env)',
  logsCardTitle: 'Detected Changes Audit Trail (UpdateLog)',
  colGrant: 'Scholarship',
  colField: 'Field',
  colOld: 'Old Value',
  colNew: 'New Value',
  colDate: 'Detected At',
  noLogsTitle: 'No updates recorded yet',
  noLogsBody: 'Click "Run Monitor Check Now" to scan official portals and record content hashes.',
  readyYes: 'Configured',
  readyNo: 'Not Set',
  apiKeysTitle: 'API Keys Configuration (Manual Entry)',
  apiKeysBtn: 'Enter API Keys',
  apiKeysSubtitle: 'Enter your keys directly here; they activate immediately with zero server restart and are stored locally.',
  apiKeyLlm: 'LLM API Key',
  apiKeyLlmHint: 'Supports Google Gemini (AIza...), OpenAI (sk-...), or OpenRouter.',
  apiKeyModel: 'LLM Model',
  apiKeyTavily: 'Tavily Search API Key (Primary)',
  apiKeyTavilyHint: 'Powers the External ReAct Deep Search Agent (tvly-...).',
  apiKeySerper: 'Serper Search API Key (Optional Fallback)',
  apiKeySerperHint: 'Used automatically if Tavily key is not provided.',
  apiKeyTgId: 'Telegram API ID (Optional)',
  apiKeyTgHash: 'Telegram API Hash (Optional)',
  apiKeyTgChannels: 'Approved Telegram Channels (Optional)',
  apiKeyTgChannelsHint: 'Comma-separated usernames, e.g. @grants_ye, @scholarships',
  btnSaveKeys: 'Save & Activate Keys',
  keysSavedSuccess: 'API keys saved and activated — agents are ready now!',
};

interface LangContextValue {
  lang: KitLang;
  toggleLang: () => void;
  t: (key: DictKey) => string;
}

const LangContext = createContext<LangContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<KitLang>(() => (document.documentElement.lang === 'en' ? 'en' : 'ar'));

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === 'en' ? 'ltr' : 'rtl';
    try {
      localStorage.setItem('asaas-lang', lang);
    } catch {
      // ignore storage errors
    }
  }, [lang]);

  const toggleLang = () => setLang((prev) => (prev === 'ar' ? 'en' : 'ar'));
  const t = (key: DictKey) => (lang === 'en' ? en[key] : ar[key]);

  return <LangContext.Provider value={{ lang, toggleLang, t }}>{children}</LangContext.Provider>;
}

export function useLang() {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error('useLang must be used inside LanguageProvider');
  return ctx;
}
