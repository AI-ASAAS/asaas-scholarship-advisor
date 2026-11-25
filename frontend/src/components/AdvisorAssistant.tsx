import { useCallback, useEffect, useState } from 'react';
import { AssistantWidget, Button, Icon, useToast } from '../asaas-ui';
import {
  api,
  type AssistantProposalAttachment,
  type AssistantStatusResponse,
  type StudentLanguageItem,
  type StudentProfileUpsertPayload,
} from '../lib/api';
import { useLang } from '../lib/i18n';

const CHAT_STORAGE_KEY = 'asaas-ui:assistant:student';

function isProposalAttachment(raw: unknown): raw is AssistantProposalAttachment {
  return Boolean(
    raw &&
      typeof raw === 'object' &&
      (raw as { type?: string }).type === 'proposal' &&
      typeof (raw as { updates?: unknown }).updates === 'object',
  );
}

function ProposalConfirmCard({ proposal }: { proposal: AssistantProposalAttachment }) {
  const { t, lang } = useLang();
  const toast = useToast();
  const [applying, setApplying] = useState(false);
  const [applied, setApplied] = useState(false);
  const [errMsg, setErrMsg] = useState<string | null>(null);

  async function handleConfirm() {
    setApplying(true);
    setErrMsg(null);
    try {
      const existing = await api.getStudentProfile().catch(() => null);
      const u = proposal.updates || {};
      const nextLanguages: StudentLanguageItem[] = [...(existing?.languages || [])];
      if (u.add_language && typeof u.add_language === 'object') {
        nextLanguages.push(u.add_language as StudentLanguageItem);
      }

      const payload: StudentProfileUpsertPayload = {
        nationality: String(u.nationality ?? existing?.nationality ?? 'YE'),
        country_of_residence:
          (u.country_of_residence as string | undefined) ?? existing?.country_of_residence ?? null,
        current_degree:
          (u.current_degree as StudentProfileUpsertPayload['current_degree']) ??
          existing?.current_degree ??
          null,
        expected_graduation_year:
          (u.expected_graduation_year as number | undefined) ??
          existing?.expected_graduation_year ??
          null,
        target_degree:
          (u.target_degree as StudentProfileUpsertPayload['target_degree']) ??
          existing?.target_degree ??
          'master',
        major: (u.major as string | undefined) ?? existing?.major ?? null,
        gpa_raw: (u.gpa_raw as string | undefined) ?? existing?.gpa_raw ?? null,
        gpa_scale:
          (u.gpa_scale as StudentProfileUpsertPayload['gpa_scale']) ?? existing?.gpa_scale ?? null,
        languages: nextLanguages,
        target_countries:
          (u.target_countries as string[] | undefined) ?? existing?.target_countries ?? [],
        target_fields: (u.target_fields as string[] | undefined) ?? existing?.target_fields ?? [],
        funding_need:
          (u.funding_need as StudentProfileUpsertPayload['funding_need']) ??
          existing?.funding_need ??
          null,
        work_experience_years:
          (u.work_experience_years as number | undefined) ??
          existing?.work_experience_years ??
          null,
        age_years: (u.age_years as number | undefined) ?? existing?.age_years ?? null,
        experience_notes:
          (u.experience_notes as string[] | undefined) ?? existing?.experience_notes ?? [],
        publications_count: existing?.publications_count ?? 0,
        consent_accepted: Boolean(existing?.has_consent),
      };

      await api.saveStudentProfile(payload);
      setApplied(true);
      toast(t('assistantUpdateConfirmed'));
      window.dispatchEvent(new Event('asaas-student-updated'));
    } catch (err) {
      setErrMsg(err instanceof Error ? err.message : 'تعذّر حفظ التعديل.');
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="quote-box" style={{ marginTop: 8 }}>
      <div className="cluster" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
        <strong style={{ fontSize: '0.88rem' }}>{t('assistantProposalTitle')}</strong>
        {applied && (
          <span className="pill pill--paid">
            <Icon name="checkCircle" />
            {t('statusMet')}
          </span>
        )}
      </div>
      <p style={{ margin: '0 0 8px' }}>
        {lang === 'en' ? proposal.summary_en || proposal.summary_ar : proposal.summary_ar || proposal.summary_en}
      </p>
      {errMsg && (
        <p style={{ margin: '0 0 8px', color: 'var(--danger)', fontSize: '0.84rem' }}>{errMsg}</p>
      )}
      {!applied && (
        <Button
          size="sm"
          variant="primary"
          icon="checkCircle"
          loading={applying}
          onClick={() => void handleConfirm()}
        >
          {t('assistantConfirmUpdateBtn')}
        </Button>
      )}
    </div>
  );
}

export function AdvisorAssistant() {
  const { t, lang } = useLang();
  const [status, setStatus] = useState<AssistantStatusResponse | null>(null);
  const [chatEpoch, setChatEpoch] = useState(0);

  const loadStatus = useCallback(() => {
    api
      .getAssistantStatus()
      .then((res) => setStatus(res))
      .catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    loadStatus();
    const onDeleted = () => {
      try {
        sessionStorage.removeItem(CHAT_STORAGE_KEY);
      } catch {
        // ignore storage errors
      }
      setChatEpoch((n) => n + 1);
      loadStatus();
    };
    const onUpdated = () => loadStatus();

    window.addEventListener('asaas-student-deleted', onDeleted);
    window.addEventListener('asaas-student-updated', onUpdated);
    return () => {
      window.removeEventListener('asaas-student-deleted', onDeleted);
      window.removeEventListener('asaas-student-updated', onUpdated);
    };
  }, [loadStatus]);

  if (!status || !status.enabled || !status.configured) {
    return null;
  }

  return (
    <AssistantWidget
      key={`${lang}-${chatEpoch}`}
      user={{ id: 'student', displayName: t('assistantGreetingName') }}
      ask={(messages) => api.askAssistant(messages)}
      title={t('assistantTitle')}
      subtitle={t('assistantSubtitle')}
      intro={t('assistantIntro')}
      disclaimer={t('assistantDisclaimer')}
      suggestions={[t('assistantSuggest1'), t('assistantSuggest2'), t('assistantSuggest3')]}
      renderAttachment={(attachment, idx) =>
        isProposalAttachment(attachment) ? (
          <ProposalConfirmCard key={idx} proposal={attachment} />
        ) : null
      }
    />
  );
}
