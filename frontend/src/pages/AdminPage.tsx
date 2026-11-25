import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Field,
  FormError,
  Icon,
  Modal,
  Segmented,
  Skeleton,
  Swash,
  TextInput,
  formatDate,
  useToast,
} from '../asaas-ui';
import { ApiKeysForm } from '../components/ApiKeysForm';
import { ApiKeysModal } from '../components/ApiKeysModal';
import { GrantModal } from '../components/GrantModal';
import { ManualGrantForm } from '../components/ManualGrantForm';
import {
  api,
  type Grant,
  type GrantChangeReviewItem,
  type GrantCounts,
  type GrantIngestPreviewResponse,
  type KeyTestResponse,
  type SystemStatus,
} from '../lib/api';
import { useLang } from '../lib/i18n';

type StatusTab = 'all' | 'draft' | 'published' | 'expired';
type AddMode = 'ai' | 'manual';

export default function AdminPage() {
  const { t } = useLang();
  const toast = useToast();

  // Grants list state
  const [tab, setTab] = useState<StatusTab>('all');
  const [grants, setGrants] = useState<Grant[]>([]);
  const [counts, setCounts] = useState<GrantCounts>({
    total: 0,
    published: 0,
    draft: 0,
    expired: 0,
    update_logs: 0,
  });
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Grant | null>(null);
  const [editingGrant, setEditingGrant] = useState<Grant | null>(null);
  const [confirmDeleteGrant, setConfirmDeleteGrant] = useState<Grant | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [publishingId, setPublishingId] = useState<number | null>(null);
  const [featuringId, setFeaturingId] = useState<number | null>(null);

  // Add Grant mode + AI URL Ingestion state
  const [addMode, setAddMode] = useState<AddMode>('ai');
  const [ingestUrl, setIngestUrl] = useState('');
  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<unknown>(null);
  const [ingestPreview, setIngestPreview] = useState<GrantIngestPreviewResponse | null>(null);

  // System readiness & AI/Search keys
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);
  const [showKeysCard, setShowKeysCard] = useState(false);
  const [showKeysModal, setShowKeysModal] = useState(false);
  const [testingKeys, setTestingKeys] = useState(false);
  const [keyTestResult, setKeyTestResult] = useState<KeyTestResponse | null>(null);

  // Monitor change reviews
  const [reviews, setReviews] = useState<GrantChangeReviewItem[]>([]);
  const [reviewBusyId, setReviewBusyId] = useState<number | null>(null);

  const loadGrants = useCallback(async (statusFilter: StatusTab) => {
    setLoadingList(true);
    setListError(null);
    try {
      const [res, st, revRes] = await Promise.all([
        api.listGrants(statusFilter),
        api.getSystemStatus(),
        api.listMonitorReviews('pending').catch(() => ({ count: 0, reviews: [] })),
      ]);
      setGrants(res.grants);
      setCounts(res.counts);
      setSysStatus(st);
      setReviews(revRes.reviews);
    } catch (err) {
      setListError(err);
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void loadGrants(tab);
  }, [tab, loadGrants]);

  async function handleIngest(e: FormEvent) {
    e.preventDefault();
    setIngestError(null);
    setIngesting(true);
    try {
      const preview = await api.previewIngestUrl({ official_url: ingestUrl });
      setIngestPreview(preview);
    } catch (err) {
      setIngestError(err);
    } finally {
      setIngesting(false);
    }
  }

  async function handlePublish(grantId: number) {
    setPublishingId(grantId);
    try {
      const updated = await api.publishGrant(grantId);
      toast(t('publishSuccess'));
      setSelected(updated);
      await loadGrants(tab);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'تعذّر اعتماد المنحة، حاول مجدداً.', 'error');
    } finally {
      setPublishingId(null);
    }
  }

  async function handleSetFeatured(grantId: number, rawValue: string) {
    const parsedRank = rawValue === '' ? null : Number(rawValue);
    setFeaturingId(grantId);
    try {
      const updated = await api.setFeaturedRank(grantId, parsedRank);
      toast(t('featuredSaved'));
      if (selected?.id === grantId) {
        setSelected(updated);
      }
      await loadGrants(tab);
    } catch (err) {
      toast(err instanceof Error ? err.message : 'تعذّر تحديث الأولوية.', 'error');
    } finally {
      setFeaturingId(null);
    }
  }

  async function handleDeleteGrant(grant: Grant) {
    setDeletingId(grant.id);
    try {
      await api.deleteGrant(grant.id);
      toast(t('grantDeletedToast'));
      setConfirmDeleteGrant(null);
      if (selected?.id === grant.id) {
        setSelected(null);
      }
      await loadGrants(tab);
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setDeletingId(null);
    }
  }

  async function handleReviewDecision(reviewId: number, decision: 'approve' | 'reject') {
    setReviewBusyId(reviewId);
    try {
      if (decision === 'approve') {
        await api.approveMonitorReview(reviewId);
        toast(t('reviewApprovedToast'));
      } else {
        await api.rejectMonitorReview(reviewId);
        toast(t('reviewRejectedToast'));
      }
      setReviews((prev) => prev.filter((item) => item.id !== reviewId));
      await loadGrants(tab);
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setReviewBusyId(null);
    }
  }

  async function handleTestActiveKeys() {
    setTestingKeys(true);
    try {
      const res = await api.testActiveKeys();
      setKeyTestResult(res);
      toast(res.llm_message, res.llm_ok ? undefined : 'error');
    } catch (err) {
      toast(err instanceof Error ? err.message : t('docsGenericError'), 'error');
    } finally {
      setTestingKeys(false);
    }
  }

  return (
    <div className="page">
      <div className="toolbar">
        <div>
          <h1 className="title" style={{ margin: 0 }}>
            <Swash>{t('adminTitle')}</Swash>
          </h1>
          <p className="muted" style={{ margin: '6px 0 0' }}>
            {t('adminSubtitle')}
          </p>
        </div>
        {sysStatus?.dev_keys_enabled && (
          <Button
            variant="glass"
            icon="vault"
            onClick={() => setShowKeysCard((prev) => !prev)}
          >
            {t('apiKeysBtn')}
          </Button>
        )}
      </div>

      {/* AI & Deep Search Keys Configuration Card */}
      {sysStatus && (
        <Card
          title={t('apiKeysTitle')}
          icon="vault"
          actions={
            <div className="cluster">
              <Button
                size="sm"
                variant="glass"
                icon="checkCircle"
                loading={testingKeys}
                onClick={() => void handleTestActiveKeys()}
              >
                {t('apiKeyTestBtn')}
              </Button>
              {sysStatus.dev_keys_enabled && (
                <Button
                  size="sm"
                  variant="glass"
                  onClick={() => setShowKeysCard((prev) => !prev)}
                >
                  {showKeysCard ? t('btnCancelAddLanguage') : t('apiKeysBtn')}
                </Button>
              )}
            </div>
          }
        >
          <div className="cluster" style={{ marginBottom: showKeysCard || keyTestResult ? 12 : 0 }}>
            <span className={sysStatus.llm_configured ? 'pill pill--paid' : 'pill pill--partial'}>
              <Icon name={sysStatus.llm_configured ? 'checkCircle' : 'alert'} />
              {sysStatus.llm_configured ? t('readyYes') : t('readyNo')}: {sysStatus.llm_provider || 'gemini'} ·{' '}
              <span dir="ltr">{sysStatus.llm_model}</span>
              {sysStatus.llm_key_hint ? (
                <span dir="ltr"> ({sysStatus.llm_key_hint})</span>
              ) : null}
            </span>
            <span className={sysStatus.search_configured ? 'pill pill--paid' : 'pill pill--partial'}>
              <Icon name={sysStatus.search_configured ? 'checkCircle' : 'alert'} />
              {t('navSearch')}: {sysStatus.search_provider ?? t('readyNo')}
              {sysStatus.tavily_key_hint
                ? ` (${sysStatus.tavily_key_hint})`
                : sysStatus.serper_key_hint
                  ? ` (${sysStatus.serper_key_hint})`
                  : ''}
            </span>
          </div>

          {keyTestResult && (
            <div className="quote-box" style={{ marginBottom: showKeysCard ? 12 : 0, display: 'grid', gap: 4 }}>
              <strong style={{ color: keyTestResult.llm_ok ? 'var(--ok, #1a7f37)' : 'var(--danger)' }}>
                {keyTestResult.llm_message}
              </strong>
              <span className="subtle">{keyTestResult.search_message}</span>
            </div>
          )}

          {sysStatus.dev_keys_enabled && showKeysCard && (
            <ApiKeysForm
              status={sysStatus}
              onSaved={(updated) => {
                setSysStatus(updated);
                setKeyTestResult(null);
                setShowKeysCard(false);
              }}
            />
          )}
        </Card>
      )}

      {/* Dual Add Grant Card: AI URL Scrape OR Manual Entry */}
      <Card
        title={t('ingestCardTitle')}
        icon="sparkle"
        actions={
          <Segmented
            label={t('adminAddModeLabel')}
            value={addMode}
            onChange={(val) => setAddMode(val as AddMode)}
            options={[
              { value: 'ai', label: t('adminAddModeAi') },
              { value: 'manual', label: t('adminAddModeManual') },
            ]}
          />
        }
      >
        {addMode === 'ai' ? (
          <form className="form" onSubmit={handleIngest}>
            <Field label={t('fieldOfficialUrl')} hint={t('fieldOfficialUrlHint')}>
              {(id) => (
                <TextInput
                  id={id}
                  type="url"
                  required
                  placeholder="https://www.chevening.org/scholarships/"
                  value={ingestUrl}
                  onChange={(e) => setIngestUrl(e.target.value)}
                  dir="ltr"
                />
              )}
            </Field>
            <FormError error={ingestError} />
            <div className="cluster">
              <Button type="submit" variant="primary" icon="plus" loading={ingesting}>
                {t('btnIngest')}
              </Button>
            </div>
          </form>
        ) : (
          <ManualGrantForm
            mode="create"
            onSaved={async (created) => {
              setSelected(created);
              await loadGrants(tab);
            }}
          />
        )}
      </Card>

      {/* Monitor Change Review Queue */}
      <Card title={t('reviewQueueTitle')} icon="alert">
        {reviews.length === 0 ? (
          <EmptyState icon="checkCircle" title={t('reviewQueueTitle')}>
            {t('reviewQueueEmpty')}
          </EmptyState>
        ) : (
          <div className="list">
            {reviews.map((rev) => (
              <div key={rev.id} className="row row--stack">
                <div className="row__main">
                  <div className="row__title">{rev.grant_title || `Grant #${rev.grant_id}`}</div>
                  <div className="subtle" style={{ marginTop: 4 }}>
                    {rev.summary_ar}
                  </div>
                  <div className="row__meta row__meta--wrap" style={{ marginTop: 6 }}>
                    <span className="pill pill--neutral">{rev.field_name}</span>
                    {rev.new_value && (
                      <code className="subtle" style={{ wordBreak: 'break-all' }}>
                        {rev.new_value}
                      </code>
                    )}
                  </div>
                </div>
                <div className="row__actions">
                  <Button
                    size="sm"
                    variant="primary"
                    icon="check"
                    loading={reviewBusyId === rev.id}
                    onClick={() => void handleReviewDecision(rev.id, 'approve')}
                  >
                    {t('reviewApproveBtn')}
                  </Button>
                  <Button
                    size="sm"
                    variant="glass"
                    icon="close"
                    loading={reviewBusyId === rev.id}
                    onClick={() => void handleReviewDecision(rev.id, 'reject')}
                  >
                    {t('reviewRejectBtn')}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Grant Management Queue (All / Drafts / Published / Expired) */}
      <Card
        title={t('reviewCardTitle')}
        icon="briefcase"
        actions={
          <Segmented
            label={t('reviewCardTitle')}
            value={tab}
            onChange={setTab}
            options={[
              { value: 'all', label: t('tabAll'), count: counts.total },
              { value: 'draft', label: t('tabDraft'), count: counts.draft },
              { value: 'published', label: t('tabPublished'), count: counts.published },
              { value: 'expired', label: t('tabExpired'), count: counts.expired },
            ]}
          />
        }
      >
        {tab === 'expired' && (
          <div className="notice-banner" style={{ marginBottom: 14 }}>
            <span className="subtle">{t('expiredAutoNotice')}</span>
          </div>
        )}

        {loadingList && <Skeleton height={64} count={4} />}
        {!loadingList && listError ? (
          <ErrorState error={listError} onRetry={() => void loadGrants(tab)} />
        ) : null}

        {!loadingList && !listError && grants.length === 0 && (
          <EmptyState icon="file" title={t('noGrantsTitle')}>
            {t('noGrantsBody')}
          </EmptyState>
        )}

        {!loadingList && !listError && grants.length > 0 && (
          <div className="list">
            {grants.map((grant) => (
              <div key={grant.id} className="row row--stack">
                <div className="row__main">
                  <div className="row__title">{grant.title}</div>
                  <div className="row__meta row__meta--wrap">
                    <span
                      className={
                        grant.status === 'published'
                          ? 'pill pill--paid'
                          : grant.status === 'draft'
                            ? 'pill pill--partial'
                            : 'pill pill--unpaid'
                      }
                    >
                      {grant.status === 'published'
                        ? t('statusPublished')
                        : grant.status === 'draft'
                          ? t('statusDraft')
                          : t('statusExpired')}
                    </span>
                    <span className="subtle">
                      {t('deadlineLabel')}:{' '}
                      <span className="num">
                        {grant.deadline ? formatDate(grant.deadline) : t('rollingDeadline')}
                      </span>
                    </span>
                    {grant.featured_rank != null && (
                      <span className="pill pill--paid">
                        {t('featuredBadge')} <span className="num">#{grant.featured_rank}</span>
                      </span>
                    )}
                  </div>
                </div>
                <div className="row__actions">
                  <select
                    className="input featured-select"
                    aria-label={`${t('featuredRankLabel')}: ${grant.title}`}
                    value={grant.featured_rank ?? ''}
                    disabled={featuringId === grant.id || grant.status === 'expired'}
                    onChange={(e) => void handleSetFeatured(grant.id, e.target.value)}
                  >
                    <option value="">{t('featuredAuto')}</option>
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((rank) => (
                      <option key={rank} value={rank}>
                        {t('featuredRankLabel')} #{rank}
                      </option>
                    ))}
                  </select>
                  <Button size="sm" variant="glass" onClick={() => setSelected(grant)}>
                    {t('viewDetails')}
                  </Button>
                  <Button
                    size="sm"
                    variant="glass"
                    icon="edit"
                    onClick={() => setEditingGrant(grant)}
                  >
                    {t('btnEditGrant')}
                  </Button>
                  {grant.status === 'draft' && (
                    <Button
                      size="sm"
                      variant="primary"
                      icon="checkCircle"
                      loading={publishingId === grant.id}
                      onClick={() => void handlePublish(grant.id)}
                    >
                      {t('btnPublish')}
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="danger"
                    icon="trash"
                    loading={deletingId === grant.id}
                    onClick={() => setConfirmDeleteGrant(grant)}
                  >
                    {t('btnDeleteGrant')}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {selected && (
        <GrantModal
          grant={selected}
          onClose={() => setSelected(null)}
          onPublish={(id) => void handlePublish(id)}
          publishing={publishingId === selected.id}
        />
      )}

      {ingestPreview && (
        <Modal
          wide
          title={`${t('ingestPreviewModalTitle')}: ${ingestPreview.title}`}
          onClose={() => setIngestPreview(null)}
        >
          <div style={{ display: 'grid', gap: 16 }}>
            <div className="quote-box" style={{ display: 'grid', gap: 6 }}>
              <strong>
                {ingestPreview.already_exists_id
                  ? t('ingestPreviewAlreadyExistsHint')
                  : t('ingestPreviewHint')}
              </strong>
              {Object.keys(ingestPreview.evidence || {}).length > 0 && (
                <div style={{ display: 'grid', gap: 4, marginTop: 4 }}>
                  <span className="subtle" style={{ fontWeight: 600 }}>
                    {t('ingestPreviewEvidenceTitle')}:
                  </span>
                  {Object.entries(ingestPreview.evidence).map(([field, quote]) => (
                    <div key={field} className="subtle" style={{ fontSize: 13 }}>
                      <code dir="ltr">{field}</code>: &ldquo;{quote}&rdquo;
                    </div>
                  ))}
                </div>
              )}
            </div>

            <ManualGrantForm
              key={`${ingestPreview.official_url}-${ingestPreview.already_exists_id ?? 'new'}`}
              mode={ingestPreview.already_exists_id ? 'edit' : 'create'}
              submitLabel={
                ingestPreview.already_exists_id ? undefined : t('ingestPreviewSubmitCreate')
              }
              initialGrant={{
                id: ingestPreview.already_exists_id ?? 0,
                title: ingestPreview.title,
                official_url: ingestPreview.official_url,
                description: ingestPreview.description ?? null,
                eligibility: ingestPreview.eligibility ?? null,
                criteria: ingestPreview.criteria ?? null,
                fields_of_study: ingestPreview.fields_of_study ?? null,
                funding: ingestPreview.funding ?? null,
                required_documents: ingestPreview.required_documents ?? null,
                deadline: ingestPreview.deadline ?? null,
                how_to_apply: ingestPreview.how_to_apply ?? null,
                accepts_yemeni: ingestPreview.accepts_yemeni,
                provider_name: ingestPreview.provider_name ?? null,
                host_country: ingestPreview.host_country ?? null,
                allowed_degrees: ingestPreview.allowed_degrees ?? null,
                min_gpa_value: ingestPreview.min_gpa_value ?? null,
                min_gpa_scale: ingestPreview.min_gpa_scale ?? null,
                min_gpa_normalized_4: ingestPreview.min_gpa_normalized_4 ?? null,
                funding_type: ingestPreview.funding_type ?? null,
                evidence: ingestPreview.evidence || {},
                field_verification: ingestPreview.field_verification || {},
                status: ingestPreview.already_exists_status || 'draft',
                content_hash: null,
                last_checked_at: null,
                created_at: null,
                updated_at: null,
              }}
              onSaved={async (saved) => {
                setIngestPreview(null);
                setIngestUrl('');
                setSelected(saved);
                await loadGrants(tab);
              }}
              onCancel={() => setIngestPreview(null)}
            />
          </div>
        </Modal>
      )}

      {editingGrant && (
        <Modal
          wide
          title={`${t('editGrantModalTitle')}: ${editingGrant.title}`}
          onClose={() => setEditingGrant(null)}
        >
          <ManualGrantForm
            mode="edit"
            initialGrant={editingGrant}
            onSaved={async () => {
              setEditingGrant(null);
              await loadGrants(tab);
            }}
            onCancel={() => setEditingGrant(null)}
          />
        </Modal>
      )}

      {confirmDeleteGrant && (
        <ConfirmDialog
          title={t('deleteGrantConfirmTitle')}
          confirmLabel={t('btnDeleteGrant')}
          pending={deletingId === confirmDeleteGrant.id}
          onConfirm={() => void handleDeleteGrant(confirmDeleteGrant)}
          onClose={() => setConfirmDeleteGrant(null)}
        >
          {t('deleteGrantConfirmBody')} (<strong>{confirmDeleteGrant.title}</strong>)
        </ConfirmDialog>
      )}

      {showKeysModal && sysStatus?.dev_keys_enabled && (
        <ApiKeysModal
          status={sysStatus}
          onClose={() => setShowKeysModal(false)}
          onSaved={(updated) => setSysStatus(updated)}
        />
      )}
    </div>
  );
}
