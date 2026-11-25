import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  FormError,
  Icon,
  Segmented,
  Select,
  Skeleton,
  TextInput,
  useToast,
} from '../asaas-ui';
import {
  api,
  type DocLangLiteral,
  type DocTypeLiteral,
  type DocumentGenerateResponse,
  type FlaggedClaim,
  type Grant,
  type LedgerEntry,
  type SavedDocumentDraft,
  type StrengtheningDocumentInput,
  type StrengtheningResponse,
} from '../lib/api';
import { useLang } from '../lib/i18n';

type InputMode = 'upload' | 'write';

interface UploadedFileMeta {
  name: string;
  sizeBytes: number;
  charCount: number;
  truncated: boolean;
}

interface DocSectionState {
  inputMode: InputMode;
  grantId: string;
  language: DocLangLiteral;
  sourceText: string;
  uploadedFile: UploadedFileMeta | null;
  uploading: boolean;
  uploadErr: string | null;
  instructions: string;
  activeDraftId: number | null;
  draftText: string;
  flaggedClaims: FlaggedClaim[];
  factsLedger: LedgerEntry[];
  missingRequests: string[];
  promptVersion: string;
  generating: boolean;
  genErr: string | null;
  saving: boolean;
}

const DOC_TYPES: DocTypeLiteral[] = ['cv', 'motivation_letter', 'recommendation_support', 'certificates'];
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

function createInitialSectionState(defaultLang: DocLangLiteral): DocSectionState {
  return {
    inputMode: 'upload',
    grantId: '',
    language: defaultLang,
    sourceText: '',
    uploadedFile: null,
    uploading: false,
    uploadErr: null,
    instructions: '',
    activeDraftId: null,
    draftText: '',
    flaggedClaims: [],
    factsLedger: [],
    missingRequests: [],
    promptVersion: 'documents@1.0',
    generating: false,
    genErr: null,
    saving: false,
  };
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      const idx = result.indexOf(',');
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = () => reject(new Error('تعذّرت قراءة الملف من المتصفح.'));
    reader.readAsDataURL(file);
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export default function DocumentsPage() {
  const { t, lang } = useLang();
  const toast = useToast();
  const editorRef = useRef<HTMLTextAreaElement | null>(null);
  const defaultLang: DocLangLiteral = lang === 'en' ? 'en' : 'ar';

  const [checkingProfile, setCheckingProfile] = useState(true);
  const [hasProfile, setHasProfile] = useState(false);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [savedDrafts, setSavedDrafts] = useState<SavedDocumentDraft[]>([]);

  // Active tab + isolated state per document type
  const [docType, setDocType] = useState<DocTypeLiteral>('cv');
  const [sections, setSections] = useState<Record<DocTypeLiteral, DocSectionState>>(() => ({
    cv: createInitialSectionState(defaultLang),
    motivation_letter: createInitialSectionState(defaultLang),
    recommendation_support: createInitialSectionState(defaultLang),
    certificates: createInitialSectionState(defaultLang),
  }));
  const [dragging, setDragging] = useState(false);

  // Strengthening state
  const [strengthening, setStrengthening] = useState<StrengtheningResponse | null>(null);
  const [loadingStrength, setLoadingStrength] = useState(false);
  const [strengthErr, setStrengthErr] = useState<string | null>(null);

  const active = sections[docType];

  const updateSection = useCallback(
    (type: DocTypeLiteral, patch: Partial<DocSectionState> | ((prev: DocSectionState) => DocSectionState)) => {
      setSections((prev) => ({
        ...prev,
        [type]: typeof patch === 'function' ? patch(prev[type]) : { ...prev[type], ...patch },
      }));
    },
    [],
  );

  const docTypeLabel = (type: DocTypeLiteral) => {
    if (type === 'cv') return t('docsTypeCv');
    if (type === 'motivation_letter') return t('docsTypeMotivation');
    if (type === 'recommendation_support') return t('docsTypeRecommendation');
    return t('docsTypeCertificates');
  };

  const docSourceLabel = (type: DocTypeLiteral) => {
    if (type === 'cv') return t('docsSourceLabelCv');
    if (type === 'motivation_letter') return t('docsSourceLabelMotivation');
    if (type === 'recommendation_support') return t('docsSourceLabelRec');
    return t('docsSourceLabelCertificates');
  };

  const docSourcePlaceholder = (type: DocTypeLiteral) => {
    if (type === 'cv') return t('docsSourcePlaceholderCv');
    if (type === 'motivation_letter') return t('docsSourcePlaceholderMotivation');
    if (type === 'recommendation_support') return t('docsSourcePlaceholderRec');
    return t('docsSourcePlaceholderCertificates');
  };

  const loadInitial = useCallback(async () => {
    setCheckingProfile(true);
    try {
      const [me, top10] = await Promise.all([
        api.getStudentStatus().catch(() => null),
        api.getTop10().catch(() => []),
      ]);
      setGrants(top10);
      const profileReady = Boolean(me?.has_consent && me?.profile_exists);
      setHasProfile(profileReady);
      if (profileReady) {
        const listRes = await api.listSavedDocuments().catch(() => ({ count: 0, drafts: [] }));
        setSavedDrafts(listRes.drafts || []);
      } else {
        setSavedDrafts([]);
      }
    } finally {
      setCheckingProfile(false);
    }
  }, []);

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  async function handleFileSelect(type: DocTypeLiteral, file: File | null) {
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      updateSection(type, { uploadErr: t('docsUploadSizeErr') });
      return;
    }
    updateSection(type, { uploading: true, uploadErr: null, genErr: null });
    try {
      const b64 = await fileToBase64(file);
      const res = await api.extractDocumentFile({
        doc_type: type,
        filename: file.name,
        content_base64: b64,
      });
      updateSection(type, {
        inputMode: 'upload',
        sourceText: res.extracted_text,
        uploadedFile: {
          name: res.filename,
          sizeBytes: file.size,
          charCount: res.char_count,
          truncated: res.truncated,
        },
        uploading: false,
        uploadErr: null,
      });
    } catch (err) {
      updateSection(type, {
        uploading: false,
        uploadErr: err instanceof Error ? err.message : t('docsGenericError'),
      });
    }
  }

  function handleClearUpload(type: DocTypeLiteral) {
    updateSection(type, {
      uploadedFile: null,
      sourceText: '',
      uploadErr: null,
    });
  }

  function collectDocumentsForStrengthening(): StrengtheningDocumentInput[] {
    const out: StrengtheningDocumentInput[] = [];
    for (const type of DOC_TYPES) {
      const sec = sections[type];
      const text = sec.sourceText.trim() || sec.draftText.trim();
      if (text.length >= 10) {
        out.push({
          doc_type: type,
          filename: sec.uploadedFile?.name || null,
          content: text.slice(0, 8000),
        });
        continue;
      }
      const latestSaved = savedDrafts.find((d) => d.doc_type === type && d.draft_text.trim().length >= 10);
      if (latestSaved) {
        out.push({
          doc_type: type,
          filename: null,
          content: latestSaved.draft_text.trim().slice(0, 8000),
        });
      }
    }
    return out;
  }

  async function handleBuildStrengthening() {
    setLoadingStrength(true);
    setStrengthErr(null);
    try {
      const grantIds = active.grantId ? [Number(active.grantId)] : undefined;
      const docsPayload = collectDocumentsForStrengthening();
      const res = await api.getStrengthening(grantIds, docsPayload);
      setStrengthening(res);
    } catch (err) {
      setStrengthErr(err instanceof Error ? err.message : t('docsGenericError'));
    } finally {
      setLoadingStrength(false);
    }
  }

  async function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    const targetType = docType;
    const sec = sections[targetType];
    if (sec.sourceText.trim().length < 10) {
      updateSection(targetType, { genErr: t('docsUploadMissingText') });
      return;
    }

    updateSection(targetType, { generating: true, genErr: null });
    try {
      const res: DocumentGenerateResponse = await api.generateDocument({
        grant_id: sec.grantId ? Number(sec.grantId) : null,
        doc_type: targetType,
        language: sec.language,
        source_text: sec.sourceText.trim(),
        target_instructions: sec.instructions.trim() || undefined,
      });
      updateSection(targetType, {
        activeDraftId: null,
        draftText: res.draft_text,
        flaggedClaims: res.flagged_claims || [],
        factsLedger: res.facts_ledger || [],
        missingRequests: res.missing_info_requests || [],
        promptVersion: res.prompt_version,
        generating: false,
      });
    } catch (err) {
      updateSection(targetType, {
        generating: false,
        genErr: err instanceof Error ? err.message : t('docsGenericError'),
      });
    }
  }

  function handleClaimAction(claim: FlaggedClaim, action: 'accepted' | 'removed' | 'edit') {
    if (action === 'edit') {
      editorRef.current?.focus();
      return;
    }
    const targetType = docType;
    const sec = sections[targetType];
    let nextDraft = sec.draftText;
    if (action === 'removed' && claim.claim_text.trim()) {
      nextDraft = nextDraft.split(claim.claim_text).join('').replace(/\s{2,}/g, ' ').trim();
    }
    const nextFlags = sec.flaggedClaims.map((c) =>
      c.id === claim.id ? { ...c, status: action } : c,
    );
    updateSection(targetType, { draftText: nextDraft, flaggedClaims: nextFlags });

    if (sec.activeDraftId !== null) {
      void api
        .updateSavedDocument(sec.activeDraftId, { draft_text: nextDraft, flagged_claims: nextFlags })
        .then((updated) => {
          setSavedDrafts((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
        })
        .catch(() => {
          // keep local update visible even if network call fails
        });
    }
  }

  async function handleSaveDraft() {
    const targetType = docType;
    const sec = sections[targetType];
    if (!sec.draftText.trim()) return;
    updateSection(targetType, { saving: true });
    try {
      if (sec.activeDraftId !== null) {
        const updated = await api.updateSavedDocument(sec.activeDraftId, {
          draft_text: sec.draftText,
          flagged_claims: sec.flaggedClaims,
        });
        setSavedDrafts((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
      } else {
        const created = await api.saveDocument({
          grant_id: sec.grantId ? Number(sec.grantId) : null,
          doc_type: targetType,
          language: sec.language,
          draft_text: sec.draftText,
          facts_ledger: sec.factsLedger,
          flagged_claims: sec.flaggedClaims,
          prompt_version: sec.promptVersion,
        });
        updateSection(targetType, { activeDraftId: created.id });
        setSavedDrafts((prev) => [created, ...prev]);
      }
      toast(t('docsSavedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      updateSection(targetType, { saving: false });
    }
  }

  async function handleDeleteDraft(draftId: number) {
    try {
      await api.deleteSavedDocument(draftId);
      setSavedDrafts((prev) => prev.filter((d) => d.id !== draftId));
      setSections((prev) => {
        const copy = { ...prev };
        for (const type of DOC_TYPES) {
          if (copy[type].activeDraftId === draftId) {
            copy[type] = { ...copy[type], activeDraftId: null };
          }
        }
        return copy;
      });
      toast(t('docsDeletedToast'));
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    }
  }

  function handleLoadDraft(draft: SavedDocumentDraft) {
    setDocType(draft.doc_type);
    updateSection(draft.doc_type, {
      activeDraftId: draft.id,
      grantId: draft.grant_id ? String(draft.grant_id) : '',
      language: draft.language,
      draftText: draft.draft_text,
      flaggedClaims: draft.flagged_claims || [],
      factsLedger: draft.facts_ledger || [],
      missingRequests: [],
    });
    editorRef.current?.focus();
  }

  function handleCopyDraft() {
    if (!active.draftText.trim()) return;
    void navigator.clipboard?.writeText(active.draftText);
    toast(t('docsCopiedToast'));
  }

  function handleDownloadTxt() {
    if (active.activeDraftId !== null) {
      window.location.href = api.exportDocumentUrl(active.activeDraftId);
      return;
    }
    const content = `${t('docsResponsibilityNote')}\n${'='.repeat(50)}\n\n${active.draftText}`;
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `asaas-${docType}-${active.language}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  const readyDocsForStrength = DOC_TYPES.filter((type) => {
    const sec = sections[type];
    return (
      sec.sourceText.trim().length >= 10 ||
      sec.draftText.trim().length >= 10 ||
      savedDrafts.some((d) => d.doc_type === type && d.draft_text.trim().length >= 10)
    );
  });

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      <div>
        <h1 className="title">{t('docsPageTitle')}</h1>
        <p className="muted" style={{ margin: '6px 0 0' }}>
          {t('docsPageSubtitle')}
        </p>
      </div>

      {checkingProfile ? (
        <Skeleton height={160} count={2} />
      ) : !hasProfile ? (
        <Card title={t('docsNeedProfileTitle')} icon="users">
          <EmptyState icon="users" title={t('docsNeedProfileTitle')}>
            <p style={{ margin: '0 0 12px' }}>{t('docsNeedProfileBody')}</p>
            <Link to="/profile" className="btn btn--primary">
              {t('docsGoToProfile')}
            </Link>
          </EmptyState>
        </Card>
      ) : (
        <>
          {/* Capability 6: Profile + Uploaded Documents Strengthening Card */}
          <Card
            title={t('strengthenCardTitle')}
            icon="trend"
            actions={
              <Button
                variant="glass"
                size="sm"
                icon="sparkle"
                loading={loadingStrength}
                onClick={() => void handleBuildStrengthening()}
              >
                {t('btnBuildStrengthening')}
              </Button>
            }
          >
            {readyDocsForStrength.length > 0 && (
              <div className="cluster" style={{ marginBottom: 12 }}>
                <span className="subtle">{t('docsAttachedForStrength')}</span>
                {readyDocsForStrength.map((type) => {
                  const fileMeta = sections[type].uploadedFile;
                  return (
                    <span key={type} className="pill pill--paid">
                      <Icon name="checkCircle" />
                      {docTypeLabel(type)}
                      {fileMeta ? ` (${fileMeta.name})` : ''}
                    </span>
                  );
                })}
              </div>
            )}

            {strengthErr && (
              <ErrorState
                error={strengthErr}
                onRetry={() => void handleBuildStrengthening()}
              />
            )}
            {strengthening ? (
              <div style={{ display: 'grid', gap: 12 }}>
                <p style={{ margin: 0, fontWeight: 500 }}>{strengthening.summary_ar}</p>
                {strengthening.actions.map((act) => (
                  <div key={act.gap_id} className="quote-box" style={{ display: 'grid', gap: 6 }}>
                    <div className="cluster" style={{ justifyContent: 'space-between' }}>
                      <strong>{act.what_ar}</strong>
                      {act.is_assumption && (
                        <span className="pill pill--late">
                          <Icon name="clock" />
                          {t('strengthenAssumptionTag')}
                        </span>
                      )}
                    </div>
                    <p style={{ margin: 0, fontSize: '0.9rem' }}>
                      <strong>{t('strengthenWhyLabel')}</strong> {act.why_ar}
                    </p>
                    <p style={{ margin: 0, fontSize: '0.9rem', color: 'var(--ink-soft)' }}>
                      <strong>{t('strengthenNextStep')}</strong> {act.next_step_ar}
                    </p>
                  </div>
                ))}
                <p className="muted" style={{ margin: 0, fontSize: '0.84rem' }}>
                  {lang === 'en' ? strengthening.disclaimer_en : strengthening.disclaimer_ar}
                </p>
              </div>
            ) : (
              <p className="muted" style={{ margin: 0 }}>
                {t('docsPageSubtitle')}
              </p>
            )}
          </Card>

          {/* Capability 7: Independent Document Sections (Upload File OR Write) */}
          <Card title={t('docsBuilderTitle')} icon="receipt">
            <div className="quote-box" style={{ marginBottom: 14 }}>
              <div className="cluster" style={{ gap: 8 }}>
                <Icon name="alert" />
                <span style={{ fontSize: '0.9rem' }}>{t('docsResponsibilityNote')}</span>
              </div>
            </div>

            <form className="form" onSubmit={(e) => void handleGenerate(e)}>
              <Field label={t('docsTypeLabel')}>
                {() => (
                  <Segmented
                    label={t('docsTypeLabel')}
                    value={docType}
                    onChange={(val) => setDocType(val as DocTypeLiteral)}
                    options={[
                      {
                        value: 'cv',
                        label: `${t('docsTypeCv')}${sections.cv.uploadedFile || sections.cv.sourceText.trim() ? ' ✓' : ''}`,
                      },
                      {
                        value: 'motivation_letter',
                        label: `${t('docsTypeMotivation')}${sections.motivation_letter.uploadedFile || sections.motivation_letter.sourceText.trim() ? ' ✓' : ''}`,
                      },
                      {
                        value: 'recommendation_support',
                        label: `${t('docsTypeRecommendation')}${sections.recommendation_support.uploadedFile || sections.recommendation_support.sourceText.trim() ? ' ✓' : ''}`,
                      },
                      {
                        value: 'certificates',
                        label: `${t('docsTypeCertificates')}${sections.certificates.uploadedFile || sections.certificates.sourceText.trim() ? ' ✓' : ''}`,
                      },
                    ]}
                  />
                )}
              </Field>

              {docType === 'recommendation_support' && (
                <p className="muted" style={{ margin: 0, fontSize: '0.88rem' }}>
                  {t('docsRecNotice')}
                </p>
              )}
              {docType === 'certificates' && (
                <p className="muted" style={{ margin: 0, fontSize: '0.88rem' }}>
                  {t('docsCertsNotice')}
                </p>
              )}

              <div className="form__row">
                <Field label={t('docsTargetGrantLabel')}>
                  {(id) => (
                    <Select
                      id={id}
                      value={active.grantId}
                      onChange={(e) => updateSection(docType, { grantId: e.target.value })}
                    >
                      <option value="">{t('docsGeneralGrantOption')}</option>
                      {grants.map((g) => (
                        <option key={g.id} value={String(g.id)}>
                          {g.title}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>

                <Field label={t('docsLangLabel')}>
                  {() => (
                    <Segmented
                      label={t('docsLangLabel')}
                      value={active.language}
                      onChange={(val) => updateSection(docType, { language: val as DocLangLiteral })}
                      options={[
                        { value: 'ar', label: t('docsLangAr') },
                        { value: 'en', label: t('docsLangEn') },
                      ]}
                    />
                  )}
                </Field>
              </div>

              <Field label={t('docsInputModeLabel')}>
                {() => (
                  <Segmented
                    label={t('docsInputModeLabel')}
                    value={active.inputMode}
                    onChange={(val) => updateSection(docType, { inputMode: val as InputMode })}
                    options={[
                      { value: 'upload', label: t('docsInputModeUpload') },
                      { value: 'write', label: t('docsInputModeWrite') },
                    ]}
                  />
                )}
              </Field>

              {active.inputMode === 'upload' ? (
                <div style={{ display: 'grid', gap: 12 }}>
                  <label
                    className="doc-upload-box"
                    data-dragging={dragging ? 'true' : 'false'}
                    onDragOver={(e) => {
                      e.preventDefault();
                      setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setDragging(false);
                      const file = e.dataTransfer.files?.[0] ?? null;
                      void handleFileSelect(docType, file);
                    }}
                  >
                    <input
                      key={docType}
                      type="file"
                      accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                      disabled={active.uploading}
                      onChange={(e) => {
                        const file = e.target.files?.[0] ?? null;
                        void handleFileSelect(docType, file);
                        e.target.value = '';
                      }}
                    />
                    <Icon name="receipt" />
                    <strong>
                      {active.uploading ? t('docsUploadReading') : t('docsUploadPrompt')}
                    </strong>
                    <span className="subtle">{t('docsUploadHint')}</span>
                  </label>

                  {active.uploadErr && <FormError error={active.uploadErr} />}

                  {active.uploadedFile && (
                    <div className="quote-box" style={{ display: 'grid', gap: 8 }}>
                      <div className="cluster" style={{ justifyContent: 'space-between' }}>
                        <div className="cluster">
                          <span className="pill pill--paid">
                            <Icon name="checkCircle" />
                            {t('docsUploadReadyBadge')}
                          </span>
                          <strong dir="ltr">{active.uploadedFile.name}</strong>
                          <span className="subtle num">
                            ({formatBytes(active.uploadedFile.sizeBytes)} · {active.uploadedFile.charCount}{' '}
                            chars)
                          </span>
                        </div>
                        <Button
                          type="button"
                          size="sm"
                          variant="danger"
                          icon="trash"
                          onClick={() => handleClearUpload(docType)}
                        >
                          {t('docsUploadClearBtn')}
                        </Button>
                      </div>
                      {active.uploadedFile.truncated && (
                        <span className="subtle">{t('docsUploadTruncatedNote')}</span>
                      )}
                    </div>
                  )}

                  {active.sourceText && (
                    <Field
                      label={t('docsUploadPreviewLabel')}
                      hint={`${active.sourceText.length} / 8000`}
                    >
                      {(id) => (
                        <textarea
                          id={id}
                          className="input"
                          rows={5}
                          maxLength={8000}
                          value={active.sourceText}
                          onChange={(e) => updateSection(docType, { sourceText: e.target.value })}
                          style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
                        />
                      )}
                    </Field>
                  )}
                </div>
              ) : (
                <Field
                  label={docSourceLabel(docType)}
                  hint={`${active.sourceText.length} / 8000`}
                >
                  {(id) => (
                    <textarea
                      id={id}
                      className="input"
                      rows={5}
                      maxLength={8000}
                      placeholder={docSourcePlaceholder(docType)}
                      value={active.sourceText}
                      onChange={(e) => updateSection(docType, { sourceText: e.target.value })}
                      style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
                    />
                  )}
                </Field>
              )}

              <Field label={t('docsInstructionsLabel')}>
                {(id) => (
                  <TextInput
                    id={id}
                    maxLength={500}
                    placeholder={t('docsInstructionsPlaceholder')}
                    value={active.instructions}
                    onChange={(e) => updateSection(docType, { instructions: e.target.value })}
                  />
                )}
              </Field>

              <FormError error={active.genErr} />

              <div className="cluster">
                <Button type="submit" variant="primary" icon="sparkle" loading={active.generating}>
                  {t('btnGenerateDraft')}
                </Button>
              </div>
            </form>

            {active.draftText && (
              <div style={{ marginTop: 20, display: 'grid', gap: 14 }}>
                {active.missingRequests.length > 0 && (
                  <div className="quote-box">
                    <strong>{t('docsMissingInfoTitle')}</strong>
                    <ul style={{ margin: '6px 0 0', paddingInlineStart: 20 }}>
                      {active.missingRequests.map((req, idx) => (
                        <li key={idx}>{req}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {active.flaggedClaims.length > 0 && (
                  <div style={{ display: 'grid', gap: 10 }}>
                    <div>
                      <strong>{t('docsFlaggedTitle')}</strong>
                      <p className="muted" style={{ margin: '2px 0 0', fontSize: '0.86rem' }}>
                        {t('docsFlaggedHint')}
                      </p>
                    </div>
                    {active.flaggedClaims.map((claim) => (
                      <div key={claim.id} className="quote-box" style={{ display: 'grid', gap: 8 }}>
                        <div className="cluster" style={{ justifyContent: 'space-between' }}>
                          <strong>{claim.claim_text}</strong>
                          <span
                            className={`pill ${
                              claim.status === 'accepted'
                                ? 'pill--paid'
                                : claim.status === 'removed'
                                  ? 'pill--open'
                                  : 'pill--late'
                            }`}
                          >
                            {claim.status === 'accepted'
                              ? t('claimAcceptedPill')
                              : claim.status === 'removed'
                                ? t('claimRemovedPill')
                                : t('claimPendingPill')}
                          </span>
                        </div>
                        <p style={{ margin: 0, fontSize: '0.88rem' }}>
                          {lang === 'en' ? claim.reason_en : claim.reason_ar}
                        </p>
                        {claim.status === 'needs_confirmation' && (
                          <div className="cluster">
                            <Button
                              size="sm"
                              variant="glass"
                              icon="checkCircle"
                              onClick={() => handleClaimAction(claim, 'accepted')}
                            >
                              {t('btnClaimAccept')}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              icon="edit"
                              onClick={() => handleClaimAction(claim, 'edit')}
                            >
                              {t('btnClaimEdit')}
                            </Button>
                            <Button
                              size="sm"
                              variant="danger"
                              icon="trash"
                              onClick={() => handleClaimAction(claim, 'removed')}
                            >
                              {t('btnClaimRemove')}
                            </Button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                <Field label={t('docsDraftEditorLabel')}>
                  {(id) => (
                    <textarea
                      ref={editorRef}
                      id={id}
                      className="input"
                      rows={10}
                      dir={active.language === 'en' ? 'ltr' : 'rtl'}
                      value={active.draftText}
                      onChange={(e) => updateSection(docType, { draftText: e.target.value })}
                      style={{ width: '100%', boxSizing: 'border-box', resize: 'vertical' }}
                    />
                  )}
                </Field>

                <div className="cluster">
                  <Button
                    variant="primary"
                    icon="check"
                    loading={active.saving}
                    onClick={() => void handleSaveDraft()}
                  >
                    {t('btnSaveDraft')}
                  </Button>
                  <Button variant="glass" icon="list" onClick={handleCopyDraft}>
                    {t('btnCopyDraft')}
                  </Button>
                  <Button variant="ghost" icon="arrowDown" onClick={handleDownloadTxt}>
                    {t('btnExportTxt')}
                  </Button>
                </div>
              </div>
            )}
          </Card>

          {/* Saved Drafts Card */}
          <Card title={t('docsSavedListTitle')} icon="briefcase">
            {savedDrafts.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                {t('docsEmptySaved')}
              </p>
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                {savedDrafts.map((d) => (
                  <div key={d.id} className="quote-box" style={{ display: 'grid', gap: 8 }}>
                    <div className="cluster" style={{ justifyContent: 'space-between' }}>
                      <strong>
                        {docTypeLabel(d.doc_type)} {d.grant_title ? `— ${d.grant_title}` : ''}
                      </strong>
                      <span className="pill">{d.language.toUpperCase()}</span>
                    </div>
                    <p className="muted" style={{ margin: 0, fontSize: '0.86rem' }}>
                      {d.draft_text.slice(0, 140)}
                      {d.draft_text.length > 140 ? '…' : ''}
                    </p>
                    <div className="cluster">
                      <Button
                        size="sm"
                        variant="glass"
                        icon="edit"
                        onClick={() => handleLoadDraft(d)}
                      >
                        {t('btnLoadDraft')}
                      </Button>
                      <a
                        className="btn btn--sm btn--ghost"
                        href={api.exportDocumentUrl(d.id)}
                      >
                        {t('btnExportTxt')}
                      </a>
                      <Button
                        size="sm"
                        variant="danger"
                        icon="trash"
                        onClick={() => void handleDeleteDraft(d.id)}
                      >
                        {t('btnDeleteDraft')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
