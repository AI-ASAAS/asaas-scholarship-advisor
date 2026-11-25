import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Button,
  Card,
  ConfirmDialog,
  ErrorState,
  Field,
  FormError,
  Icon,
  Select,
  Skeleton,
  Swash,
  TextArea,
  TextInput,
  useToast,
} from '../asaas-ui';
import {
  api,
  type StudentLanguageItem,
  type StudentProfileUpsertPayload,
} from '../lib/api';
import { useLang } from '../lib/i18n';

const COUNTRY_OPTIONS = [
  { code: 'YE', ar: 'اليمن (YE)', en: 'Yemen (YE)' },
  { code: 'SA', ar: 'السعودية (SA)', en: 'Saudi Arabia (SA)' },
  { code: 'EG', ar: 'مصر (EG)', en: 'Egypt (EG)' },
  { code: 'JO', ar: 'الأردن (JO)', en: 'Jordan (JO)' },
  { code: 'AE', ar: 'الإمارات (AE)', en: 'UAE (AE)' },
  { code: 'QA', ar: 'قطر (QA)', en: 'Qatar (QA)' },
  { code: 'KW', ar: 'الكويت (KW)', en: 'Kuwait (KW)' },
  { code: 'OM', ar: 'عُمان (OM)', en: 'Oman (OM)' },
  { code: 'IQ', ar: 'العراق (IQ)', en: 'Iraq (IQ)' },
  { code: 'SY', ar: 'سوريا (SY)', en: 'Syria (SY)' },
  { code: 'PS', ar: 'فلسطين (PS)', en: 'Palestine (PS)' },
  { code: 'SD', ar: 'السودان (SD)', en: 'Sudan (SD)' },
  { code: 'MA', ar: 'المغرب (MA)', en: 'Morocco (MA)' },
  { code: 'TN', ar: 'تونس (TN)', en: 'Tunisia (TN)' },
  { code: 'DZ', ar: 'الجزائر (DZ)', en: 'Algeria (DZ)' },
  { code: 'TR', ar: 'تركيا (TR)', en: 'Türkiye (TR)' },
  { code: 'DE', ar: 'ألمانيا (DE)', en: 'Germany (DE)' },
  { code: 'FR', ar: 'فرنسا (FR)', en: 'France (FR)' },
  { code: 'GB', ar: 'المملكة المتحدة (GB)', en: 'United Kingdom (GB)' },
  { code: 'US', ar: 'الولايات المتحدة (US)', en: 'United States (US)' },
  { code: 'MY', ar: 'ماليزيا (MY)', en: 'Malaysia (MY)' },
  { code: 'ID', ar: 'إندونيسيا (ID)', en: 'Indonesia (ID)' },
  { code: 'PK', ar: 'باكستان (PK)', en: 'Pakistan (PK)' },
  { code: 'IN', ar: 'الهند (IN)', en: 'India (IN)' },
];

export default function ProfilePage() {
  const { t, lang } = useLang();
  const toast = useToast();
  const navigate = useNavigate();

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [hasConsent, setHasConsent] = useState(false);
  const [profileExists, setProfileExists] = useState(false);

  // Step 1
  const [nationalityChoice, setNationalityChoice] = useState('YE');
  const [customNationality, setCustomNationality] = useState('');
  const [residence, setResidence] = useState('');
  const [currentDegree, setCurrentDegree] = useState<'high_school' | 'bachelor' | 'master' | 'phd' | ''>('bachelor');
  const [gradYear, setGradYear] = useState('');
  const [targetDegree, setTargetDegree] = useState<'high_school' | 'bachelor' | 'master' | 'phd'>('master');

  // Step 2
  const [major, setMajor] = useState('');
  const [gpaScale, setGpaScale] = useState<'4.0' | '5.0' | '100' | 'label' | ''>('');
  const [gpaRaw, setGpaRaw] = useState('');
  const [englishTest, setEnglishTest] = useState('');
  const [englishScore, setEnglishScore] = useState('');
  const [englishCefr, setEnglishCefr] = useState<'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2' | ''>('');
  const [languages, setLanguages] = useState<StudentLanguageItem[]>([]);
  const [showOtherLangForm, setShowOtherLangForm] = useState(false);
  const [newLangName, setNewLangName] = useState('');
  const [newLangCefr, setNewLangCefr] = useState<'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2'>('C1');

  // Step 3
  const [targetCountriesText, setTargetCountriesText] = useState('');
  const [targetFieldsText, setTargetFieldsText] = useState('');
  const [fundingNeed, setFundingNeed] = useState<'full' | 'partial' | 'any' | ''>('full');
  const [workYears, setWorkYears] = useState('');
  const [ageYears, setAgeYears] = useState('');
  const [notesText, setNotesText] = useState('');
  const [consentChecked, setConsentChecked] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<unknown>(null);

  const loadExisting = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const status = await api.getStudentStatus();
      setHasConsent(status.has_consent);
      setConsentChecked(status.has_consent);
      setProfileExists(status.profile_exists);

      if (status.authenticated && status.profile_exists) {
        const prof = await api.getStudentProfile();
        const known = COUNTRY_OPTIONS.some((c) => c.code === prof.nationality);
        if (known) {
          setNationalityChoice(prof.nationality);
          setCustomNationality('');
        } else {
          setNationalityChoice('OTHER');
          setCustomNationality(prof.nationality);
        }
        setResidence(prof.country_of_residence || '');
        setCurrentDegree(prof.current_degree || '');
        setGradYear(prof.expected_graduation_year ? String(prof.expected_graduation_year) : '');
        setTargetDegree(prof.target_degree);
        setMajor(prof.major || '');
        setGpaScale(prof.gpa_scale || '');
        setGpaRaw(prof.gpa_raw || '');
        const allLangs = prof.languages || [];
        const primaryEnIdx = allLangs.findIndex(
          (l) => l.language.trim().toLowerCase() === 'english' || l.language.trim() === 'الإنجليزية',
        );
        if (primaryEnIdx >= 0) {
          const enItem = allLangs[primaryEnIdx];
          setEnglishTest(enItem.test_name || '');
          setEnglishScore(enItem.score != null ? String(enItem.score) : '');
          setEnglishCefr(enItem.self_assessed_cefr || '');
          setLanguages(allLangs.filter((_, idx) => idx !== primaryEnIdx));
        } else {
          setEnglishTest('');
          setEnglishScore('');
          setEnglishCefr('');
          setLanguages(allLangs);
        }
        setTargetCountriesText((prof.target_countries || []).join(', '));
        setTargetFieldsText((prof.target_fields || []).join(', '));
        setFundingNeed(prof.funding_need || '');
        setWorkYears(prof.work_experience_years != null ? String(prof.work_experience_years) : '');
        setAgeYears(prof.age_years != null ? String(prof.age_years) : '');
        setNotesText((prof.experience_notes || []).join('\n'));
      }
    } catch (err) {
      setLoadError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadExisting();
  }, [loadExisting]);

  function ratingLabelForCefr(cefr?: string | null): string {
    if (cefr === 'C2' || cefr === 'C1') return t('langRatingExcellent');
    if (cefr === 'B2') return t('langRatingVeryGood');
    if (cefr === 'B1') return t('langRatingGood');
    if (cefr === 'A2') return t('langRatingAcceptable');
    if (cefr === 'A1') return t('langRatingWeak');
    return t('langRatingGood');
  }

  function addLanguageEntry() {
    const trimmed = newLangName.trim();
    if (!trimmed) {
      toast(t('langNameRequiredToast'), 'error');
      return;
    }
    setLanguages((prev) => [
      ...prev,
      {
        language: trimmed,
        test_name: null,
        score: null,
        self_assessed_cefr: newLangCefr || 'B2',
        is_self_assessed: true,
      },
    ]);
    setNewLangName('');
    setShowOtherLangForm(false);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    setSaveError(null);

    if (!hasConsent && !consentChecked) {
      setSaveError(new Error(t('consentRequiredError')));
      return;
    }

    const effectiveNationality =
      nationalityChoice === 'OTHER' ? customNationality.trim().toUpperCase() : nationalityChoice;

    const scoreNum = englishScore.trim() ? Number(englishScore.trim()) : null;
    const hasOfficialEnglish =
      Boolean(englishTest.trim()) && scoreNum !== null && !Number.isNaN(scoreNum);
    const englishEntry: StudentLanguageItem | null = hasOfficialEnglish
      ? {
          language: 'English',
          test_name: englishTest.trim().toUpperCase(),
          score: scoreNum,
          self_assessed_cefr: null,
          is_self_assessed: false,
        }
      : englishCefr
        ? {
            language: 'English',
            test_name: null,
            score: null,
            self_assessed_cefr: englishCefr,
            is_self_assessed: true,
          }
        : null;

    const pendingOther: StudentLanguageItem[] =
      showOtherLangForm && newLangName.trim()
        ? [
            {
              language: newLangName.trim(),
              test_name: null,
              score: null,
              self_assessed_cefr: newLangCefr || 'B2',
              is_self_assessed: true,
            },
          ]
        : [];

    const languagesToSave: StudentLanguageItem[] = [
      ...(englishEntry ? [englishEntry] : []),
      ...languages,
      ...pendingOther,
    ];

    const payload: StudentProfileUpsertPayload = {
      nationality: effectiveNationality || 'YE',
      country_of_residence: residence.trim() ? residence.trim().toUpperCase() : null,
      current_degree: currentDegree || null,
      expected_graduation_year: gradYear.trim() ? Number(gradYear.trim()) : null,
      target_degree: targetDegree,
      major: major.trim() || null,
      gpa_raw: gpaRaw.trim() || null,
      gpa_scale: gpaScale || null,
      languages: languagesToSave,
      target_countries: targetCountriesText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean),
      target_fields: targetFieldsText
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean),
      funding_need: fundingNeed || null,
      work_experience_years: workYears.trim() ? Number(workYears.trim()) : null,
      age_years: ageYears.trim() ? Number(ageYears.trim()) : null,
      experience_notes: notesText
        .split('\n')
        .map((x) => x.trim())
        .filter(Boolean),
      publications_count: 0,
      consent_accepted: hasConsent ? true : consentChecked,
      consent_version: 'privacy-v1',
    };

    setSaving(true);
    try {
      await api.saveStudentProfile(payload);
      setHasConsent(true);
      setProfileExists(true);
      window.dispatchEvent(new Event('asaas-student-updated'));
      toast(t('profileSavedSuccess'));
      navigate('/matches');
    } catch (err) {
      setSaveError(err);
    } finally {
      setSaving(false);
    }
  }

  async function handleExport() {
    try {
      const data = await api.exportStudentData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'asaas-student-profile-export.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Error', 'error');
    }
  }

  async function handleDeleteData() {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.deleteStudentData();
      setShowDeleteConfirm(false);
      setHasConsent(false);
      setConsentChecked(false);
      setProfileExists(false);
      setMajor('');
      setGpaRaw('');
      setGpaScale('');
      setEnglishTest('');
      setEnglishScore('');
      setEnglishCefr('');
      setLanguages([]);
      setShowOtherLangForm(false);
      setNewLangName('');
      setNotesText('');
      setWorkYears('');
      setAgeYears('');
      window.dispatchEvent(new Event('asaas-student-deleted'));
      toast(t('deleteSuccess'));
    } catch (err) {
      setDeleteError(err);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('profileTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('profileSubtitle')}
          </p>
        </div>
        {profileExists && (
          <Link to="/matches" className="btn btn--glass">
            <Icon name="trend" />
            {t('ctaViewMatchesBtn')}
          </Link>
        )}
      </div>

      {loading && <Skeleton height={180} count={2} />}
      {!loading && loadError ? <ErrorState error={loadError} onRetry={() => void loadExisting()} /> : null}

      {!loading && !loadError && (
        <>
          <div className="wizard-steps" role="tablist" aria-label={t('profileTitle')}>
            <button
              type="button"
              className="wizard-step"
              aria-current={step === 1 ? 'step' : undefined}
              onClick={() => setStep(1)}
            >
              {t('stepIdentity')}
            </button>
            <button
              type="button"
              className="wizard-step"
              aria-current={step === 2 ? 'step' : undefined}
              onClick={() => setStep(2)}
            >
              {t('stepAcademics')}
            </button>
            <button
              type="button"
              className="wizard-step"
              aria-current={step === 3 ? 'step' : undefined}
              onClick={() => setStep(3)}
            >
              {t('stepGoalsConsent')}
            </button>
          </div>

          <Card title={step === 1 ? t('stepIdentity') : step === 2 ? t('stepAcademics') : t('stepGoalsConsent')} icon="users">
            <form className="form" onSubmit={(e) => void handleSave(e)}>
              {step === 1 && (
                <>
                  <div className="form__row">
                    <Field label={t('nationalityLabel')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={nationalityChoice}
                          onChange={(e) => setNationalityChoice(e.target.value)}
                        >
                          {COUNTRY_OPTIONS.map((c) => (
                            <option key={c.code} value={c.code}>
                              {lang === 'en' ? c.en : c.ar}
                            </option>
                          ))}
                          <option value="OTHER">{t('nationalityOtherLabel')}</option>
                        </Select>
                      )}
                    </Field>
                    {nationalityChoice === 'OTHER' && (
                      <Field label={t('nationalityOtherLabel')}>
                        {(id) => (
                          <TextInput
                            id={id}
                            value={customNationality}
                            onChange={(e) => setCustomNationality(e.target.value)}
                            maxLength={40}
                            placeholder="YE / DE / FR"
                            required
                          />
                        )}
                      </Field>
                    )}
                    <Field label={t('residenceLabel')}>
                      {(id) => (
                        <TextInput
                          id={id}
                          value={residence}
                          onChange={(e) => setResidence(e.target.value)}
                          maxLength={40}
                          placeholder="YE"
                        />
                      )}
                    </Field>
                  </div>

                  <div className="form__row">
                    <Field label={t('targetDegreeLabel')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={targetDegree}
                          onChange={(e) =>
                            setTargetDegree(e.target.value as 'high_school' | 'bachelor' | 'master' | 'phd')
                          }
                        >
                          <option value="bachelor">{t('degreeBachelor')}</option>
                          <option value="master">{t('degreeMaster')}</option>
                          <option value="phd">{t('degreePhd')}</option>
                          <option value="high_school">{t('degreeHighSchool')}</option>
                        </Select>
                      )}
                    </Field>
                    <Field label={t('currentDegreeLabel')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={currentDegree}
                          onChange={(e) =>
                            setCurrentDegree(
                              e.target.value as 'high_school' | 'bachelor' | 'master' | 'phd' | '',
                            )
                          }
                        >
                          <option value="">—</option>
                          <option value="high_school">{t('degreeHighSchool')}</option>
                          <option value="bachelor">{t('degreeBachelor')}</option>
                          <option value="master">{t('degreeMaster')}</option>
                          <option value="phd">{t('degreePhd')}</option>
                        </Select>
                      )}
                    </Field>
                  </div>

                  <Field label={t('gradYearLabel')}>
                    {(id) => (
                      <TextInput
                        id={id}
                        type="number"
                        min={1990}
                        max={2040}
                        value={gradYear}
                        onChange={(e) => setGradYear(e.target.value)}
                        placeholder="2026"
                      />
                    )}
                  </Field>
                </>
              )}

              {step === 2 && (
                <>
                  <Field label={t('majorLabel')}>
                    {(id) => (
                      <TextInput
                        id={id}
                        value={major}
                        onChange={(e) => setMajor(e.target.value)}
                        placeholder={t('majorPh')}
                        maxLength={160}
                      />
                    )}
                  </Field>

                  <div className="form__row">
                    <Field label={t('gpaScaleLabel')} hint={t('gpaLabelHint')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={gpaScale}
                          onChange={(e) =>
                            setGpaScale(e.target.value as '4.0' | '5.0' | '100' | 'label' | '')
                          }
                        >
                          <option value="">—</option>
                          <option value="100">{t('gpaScalePercent')}</option>
                          <option value="4.0">{t('gpaScale4')}</option>
                          <option value="5.0">{t('gpaScale5')}</option>
                          <option value="label">{t('gpaScaleYemeniLabel')}</option>
                        </Select>
                      )}
                    </Field>
                    <Field label={t('gpaValueLabel')}>
                      {(id) =>
                        gpaScale === 'label' ? (
                          <Select
                            id={id}
                            value={gpaRaw}
                            onChange={(e) => setGpaRaw(e.target.value)}
                          >
                            <option value="">—</option>
                            <option value="ممتاز">ممتاز (Excellent)</option>
                            <option value="جيد جداً">جيد جداً (Very Good)</option>
                            <option value="جيد">جيد (Good)</option>
                            <option value="مقبول">مقبول (Pass)</option>
                            <option value="ضعيف">ضعيف (Weak)</option>
                          </Select>
                        ) : (
                          <TextInput
                            id={id}
                            value={gpaRaw}
                            onChange={(e) => setGpaRaw(e.target.value)}
                            placeholder={gpaScale === '100' ? '85' : '3.5'}
                            maxLength={32}
                          />
                        )
                      }
                    </Field>
                  </div>

                  <div className="detail-section">
                    <h4>{t('languagesSectionTitle')}</h4>
                    <p className="subtle" style={{ margin: 0 }}>
                      {t('langSelfAssessedHint')}
                    </p>
                    <strong style={{ fontSize: '0.92rem' }}>{t('langEnglishPrimaryTitle')}</strong>
                    <div className="form__row">
                      <Field label={t('langTestLabel')}>
                        {(id) => (
                          <TextInput
                            id={id}
                            value={englishTest}
                            onChange={(e) => setEnglishTest(e.target.value)}
                            placeholder="IELTS / TOEFL"
                          />
                        )}
                      </Field>
                      <Field label={t('langScoreLabel')}>
                        {(id) => (
                          <TextInput
                            id={id}
                            type="number"
                            step="0.5"
                            value={englishScore}
                            onChange={(e) => setEnglishScore(e.target.value)}
                            placeholder="6.5"
                          />
                        )}
                      </Field>
                    </div>
                    <Field label={t('langCefrLabel')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={englishCefr}
                          onChange={(e) =>
                            setEnglishCefr(
                              e.target.value as 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2' | '',
                            )
                          }
                        >
                          <option value="">—</option>
                          <option value="C2">C2 — {t('langRatingExcellent')}</option>
                          <option value="C1">C1 — {t('langRatingExcellent')}</option>
                          <option value="B2">B2 — {t('langRatingVeryGood')}</option>
                          <option value="B1">B1 — {t('langRatingGood')}</option>
                          <option value="A2">A2 — {t('langRatingAcceptable')}</option>
                          <option value="A1">A1 — {t('langRatingWeak')}</option>
                        </Select>
                      )}
                    </Field>

                    {!showOtherLangForm ? (
                      <div>
                        <Button
                          type="button"
                          variant="glass"
                          size="sm"
                          icon="plus"
                          onClick={() => setShowOtherLangForm(true)}
                        >
                          {t('btnAddLanguage')}
                        </Button>
                      </div>
                    ) : (
                      <div className="quote-box" style={{ display: 'grid', gap: 12 }}>
                        <div className="form__row">
                          <Field label={t('langNameLabel')}>
                            {(id) => (
                              <TextInput
                                id={id}
                                value={newLangName}
                                onChange={(e) => setNewLangName(e.target.value)}
                                placeholder={t('langNamePlaceholder')}
                                maxLength={60}
                              />
                            )}
                          </Field>
                          <Field label={t('langRatingLabel')}>
                            {(id) => (
                              <Select
                                id={id}
                                value={newLangCefr}
                                onChange={(e) =>
                                  setNewLangCefr(
                                    e.target.value as 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2',
                                  )
                                }
                              >
                                <option value="C1">{t('langRatingExcellent')}</option>
                                <option value="B2">{t('langRatingVeryGood')}</option>
                                <option value="B1">{t('langRatingGood')}</option>
                                <option value="A2">{t('langRatingAcceptable')}</option>
                                <option value="A1">{t('langRatingWeak')}</option>
                              </Select>
                            )}
                          </Field>
                        </div>
                        <div className="cluster">
                          <Button
                            type="button"
                            variant="primary"
                            size="sm"
                            icon="plus"
                            onClick={addLanguageEntry}
                          >
                            {t('btnConfirmAddLanguage')}
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setShowOtherLangForm(false);
                              setNewLangName('');
                            }}
                          >
                            {t('btnCancelAddLanguage')}
                          </Button>
                        </div>
                      </div>
                    )}

                    {languages.length > 0 && (
                      <div className="list" style={{ marginTop: 8 }}>
                        {languages.map((l, idx) => (
                          <div key={`${l.language}-${idx}`} className="row">
                            <div className="row__main">
                              <div className="row__title">
                                {l.language}
                                {l.test_name && l.score != null
                                  ? ` — ${l.test_name} ${l.score}`
                                  : ` — ${ratingLabelForCefr(l.self_assessed_cefr)}`}
                              </div>
                              <div className="row__meta">
                                <span className={l.is_self_assessed ? 'pill pill--partial' : 'pill pill--paid'}>
                                  {l.is_self_assessed
                                    ? ratingLabelForCefr(l.self_assessed_cefr)
                                    : `${l.test_name} ${l.score}`}
                                </span>
                              </div>
                            </div>
                            <Button
                              type="button"
                              size="sm"
                              variant="ghost"
                              onClick={() => setLanguages((prev) => prev.filter((_, i) => i !== idx))}
                            >
                              {t('btnRemove')}
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}

              {step === 3 && (
                <>
                  <div className="form__row">
                    <Field label={t('workYearsLabelProfile')}>
                      {(id) => (
                        <TextInput
                          id={id}
                          type="number"
                          step="0.5"
                          min={0}
                          max={60}
                          value={workYears}
                          onChange={(e) => setWorkYears(e.target.value)}
                          placeholder="2"
                        />
                      )}
                    </Field>
                    <Field label={t('ageLabelProfile')}>
                      {(id) => (
                        <TextInput
                          id={id}
                          type="number"
                          min={14}
                          max={80}
                          value={ageYears}
                          onChange={(e) => setAgeYears(e.target.value)}
                          placeholder="24"
                        />
                      )}
                    </Field>
                  </div>

                  <div className="form__row">
                    <Field label={t('fundingNeedLabel')}>
                      {(id) => (
                        <Select
                          id={id}
                          value={fundingNeed}
                          onChange={(e) =>
                            setFundingNeed(e.target.value as 'full' | 'partial' | 'any' | '')
                          }
                        >
                          <option value="full">{t('fundingFull')}</option>
                          <option value="partial">{t('fundingPartial')}</option>
                          <option value="any">{t('fundingAny')}</option>
                        </Select>
                      )}
                    </Field>
                    <Field label={t('targetCountriesLabel')}>
                      {(id) => (
                        <TextInput
                          id={id}
                          value={targetCountriesText}
                          onChange={(e) => setTargetCountriesText(e.target.value)}
                          placeholder="Germany, UK, Turkey"
                        />
                      )}
                    </Field>
                  </div>

                  <Field label={t('targetFieldsLabel')}>
                    {(id) => (
                      <TextInput
                        id={id}
                        value={targetFieldsText}
                        onChange={(e) => setTargetFieldsText(e.target.value)}
                        placeholder="Artificial Intelligence, Public Policy"
                      />
                    )}
                  </Field>

                  <Field label={t('experienceNotesLabel')}>
                    {(id) => (
                      <TextArea
                        id={id}
                        rows={3}
                        value={notesText}
                        onChange={(e) => setNotesText(e.target.value)}
                      />
                    )}
                  </Field>

                  {hasConsent ? (
                    <div className="notice-banner">
                      <Icon name="checkCircle" />
                      <span>{t('consentAlreadyAccepted')}</span>
                    </div>
                  ) : (
                    <label className="consent-check">
                      <input
                        type="checkbox"
                        checked={consentChecked}
                        onChange={(e) => setConsentChecked(e.target.checked)}
                      />
                      <span>{t('consentCheckboxText')}</span>
                    </label>
                  )}
                </>
              )}

              <FormError error={saveError} />

              <div className="cluster" style={{ justifyContent: 'space-between' }}>
                <div className="cluster">
                  {step > 1 && (
                    <Button
                      type="button"
                      variant="glass"
                      onClick={() => setStep((s) => (s === 3 ? 2 : 1))}
                    >
                      {t('btnBack')}
                    </Button>
                  )}
                </div>
                <div className="cluster">
                  {step < 3 ? (
                    <Button
                      type="button"
                      variant="primary"
                      onClick={() => setStep((s) => (s === 1 ? 2 : 3))}
                    >
                      {t('btnNext')}
                    </Button>
                  ) : (
                    <Button type="submit" variant="primary" icon="checkCircle" loading={saving}>
                      {t('btnSaveProfile')}
                    </Button>
                  )}
                </div>
              </div>
            </form>
          </Card>

          {(profileExists || hasConsent) && (
            <Card title={t('privacyCardTitle')} icon="vault">
              <div className="cluster">
                <Button type="button" variant="glass" icon="arrowDown" onClick={() => void handleExport()}>
                  {t('btnExportData')}
                </Button>
                <Button
                  type="button"
                  variant="danger"
                  icon="trash"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  {t('btnDeleteData')}
                </Button>
              </div>
            </Card>
          )}
        </>
      )}

      {showDeleteConfirm && (
        <ConfirmDialog
          title={t('deleteConfirmTitle')}
          confirmLabel={t('btnDeleteData')}
          pending={deleting}
          error={deleteError}
          onClose={() => setShowDeleteConfirm(false)}
          onConfirm={() => void handleDeleteData()}
        >
          {t('deleteConfirmBody')}
        </ConfirmDialog>
      )}
    </div>
  );
}
