'use client';

import { useState } from 'react';
import { Check, ExternalLink, Pause } from 'lucide-react';
import { Candidate, feeLabel, formatDate, publicWebUrl } from '@/lib/portal';

export function CandidateCard({
  candidate,
  saving,
  onReview,
}: {
  candidate: Candidate;
  saving: boolean;
  onReview: (
    id: string,
    action: string,
    reason: string,
    version?: number,
    corrections?: Record<string, string>,
    evidence?: Record<string, string>,
  ) => void;
}) {
  const [reason, setReason] = useState(candidate.reason || '');
  const [edits, setEdits] = useState<Record<string, string>>({
    title: candidate.data.title || '',
    provider: candidate.data.provider || '',
    start_date: candidate.data.start_date || '',
    venue: candidate.data.venue || '',
    city: candidate.data.city || '',
    fee: candidate.data.fee == null ? '' : String(candidate.data.fee),
    points: candidate.data.points == null ? '' : String(candidate.data.points),
  });
  const [excerpts, setExcerpts] = useState<Record<string, string>>({
    title: candidate.data.evidence?.title || '',
    provider: candidate.data.evidence?.provider || '',
    start_date: candidate.data.evidence?.start_date || '',
    venue: candidate.data.evidence?.venue || '',
    city: candidate.data.evidence?.city || '',
    fee: candidate.data.evidence?.fee || '',
    points: candidate.data.evidence?.points || '',
  });
  const sourceHref = publicWebUrl(candidate.data.source_url);
  const original: Record<string, string> = {
    title: candidate.data.title || '',
    provider: candidate.data.provider || '',
    start_date: candidate.data.start_date || '',
    venue: candidate.data.venue || '',
    city: candidate.data.city || '',
    fee: candidate.data.fee == null ? '' : String(candidate.data.fee),
    points: candidate.data.points == null ? '' : String(candidate.data.points),
  };
  function publishPayload() {
    const corrections: Record<string, string> = {};
    const evidence: Record<string, string> = {};
    for (const field of Object.keys(edits)) {
      if ((edits[field] || '') !== (original[field] || '')) {
        corrections[field] = edits[field];
        // Trim to match publishReady + backend verbatim check (whitespace-only cannot pass).
        evidence[field] = (excerpts[field] || '').trim();
      }
    }
    return { corrections, evidence };
  }
  // Whitespace-only source_text is unusable for verbatim excerpts — treat as missing (backend parity).
  const sourceText = candidate.data.source_text || '';
  const hasSourceText = sourceText.trim().length > 0;
  function publishReady() {
    const { corrections, evidence } = publishPayload();
    const fields = Object.keys(corrections);
    if (!fields.length) return true;
    // Backend rejects corrections without a verbatim excerpt present in source_text.
    if (!hasSourceText) return false;
    return fields.every((field) => {
      const excerpt = (evidence[field] || '').trim();
      return excerpt.length > 0 && sourceText.includes(excerpt);
    });
  }
  const canPublish = publishReady();
  return (
    <section className="panel candidate">
      <div className="section-heading">
        <div>
          <h3>{candidate.data.title}</h3>
          <p>
            {candidate.data.provider} · {formatDate(candidate.data.start_date)} · {feeLabel(candidate.data)}
            {candidate.data.model_id ? ` · ${candidate.data.model_id}` : ''}
            {candidate.schema_version ? ` · schema ${candidate.schema_version}` : ''}
          </p>
        </div>
        <div className="button-row">
          {candidate.data._fixture ? <span className="status fixture">fixture</span> : null}
          <span className={'status ' + candidate.status}>{candidate.status}</span>
          {sourceHref ? (
            <a href={sourceHref} target="_blank" rel="noreferrer" className="text-btn">
              Open source <ExternalLink size={14} />
            </a>
          ) : (
            <span className="small-note">Original source URL is not available.</span>
          )}
        </div>
      </div>
      <p>{candidate.data.description}</p>
      <p className="small-note" data-testid="candidate-provenance">
        {candidate.data.retrieved_at
          ? `Retrieved ${candidate.data.retrieved_at}`
          : 'Retrieval time not recorded on this candidate.'}
        {hasSourceText ? ' · Source text kept for operator review.' : ' · Source text missing.'}
      </p>
      {candidate.data._judgment ? (
        <p className="small-note" data-testid="jev-judgment">
          Jev {candidate.data._judgment.decision || 'unknown'}
          {candidate.data._judgment.confidence != null ? ` · confidence ${candidate.data._judgment.confidence}` : ''}
          {candidate.data._judgment.probabilities
            ? ` · exists ${candidate.data._judgment.probabilities.exists ?? 0}, new ${candidate.data._judgment.probabilities.new ?? 0}, uncertain ${candidate.data._judgment.probabilities.uncertain ?? 0}`
            : ''}
          {candidate.data._judgment.warning ? ` — ${candidate.data._judgment.warning}` : ''}
        </p>
      ) : null}
      {candidate.data._refresh_diff?.length ? (
        <div className="refresh-diff" data-testid="refresh-diff">
          <p className="small-note">Proposed changes versus the published session. Review before overwriting.</p>
          <dl className="evidence">
            {candidate.data._refresh_diff.map((change) => (
              <div key={change.field}>
                <dt>{change.field.replaceAll('_', ' ')}</dt>
                <dd>
                  Published: {change.published == null || change.published === '' ? 'Unknown' : String(change.published)}
                  {' → '}
                  Proposed: {change.proposed == null || change.proposed === '' ? 'Unknown' : String(change.proposed)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}
      <dl className="evidence">
        {Object.entries(candidate.data.evidence || {}).map(([k, v]) => (
          <div key={k}>
            <dt>{k.replaceAll('_', ' ')}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {(
        [
          ['title', 'Corrected title'],
          ['provider', 'Corrected provider'],
          ['start_date', 'Corrected start date'],
          ['venue', 'Corrected venue'],
          ['city', 'Corrected city'],
          ['fee', 'Corrected fee'],
          ['points', 'Corrected points'],
        ] as const
      ).map(([field, label]) => (
        <div key={field}>
          <label>
            {label}
            <input value={edits[field]} onChange={(e) => setEdits({ ...edits, [field]: e.target.value })} />
          </label>
          {edits[field] !== original[field] ? (
            <label>
              {label.replace('Corrected ', '')} evidence excerpt
              <textarea
                rows={2}
                value={excerpts[field]}
                onChange={(e) => setExcerpts({ ...excerpts, [field]: e.target.value })}
                placeholder="Verbatim source sentence that supports this correction"
              />
            </label>
          ) : null}
        </div>
      ))}
      <label>
        Review reason
        <textarea
          maxLength={500}
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={candidate.status === 'held' ? 'Required to keep this on hold' : 'Required to hold or reject; optional for publish'}
        />
      </label>
      {candidate.reason ? <p className="small-note">Last reason: {candidate.reason}</p> : null}
      <p className="small-note">
        Confirm the extracted values match the source, including Malaysia eligibility. Publishing is not accreditation
        verification.
      </p>
      {!canPublish ? (
        <p className="small-note" data-testid="publish-needs-excerpts">
          {hasSourceText
            ? 'Add a verbatim source excerpt (copied from the stored source text) for each corrected field before publishing.'
            : 'Source text is missing, so field corrections cannot be published. Reject, hold, or ingest a better source.'}
        </p>
      ) : null}
      <div className="button-row">
        <button
          disabled={saving || !canPublish}
          className="primary"
          onClick={() => {
            const payload = publishPayload();
            onReview(candidate.id, 'publish', reason, candidate.version, payload.corrections, payload.evidence);
          }}
        >
          <Check size={16} /> Publish reviewed training
        </button>
        <button
          disabled={saving || reason.trim().length < 3}
          className="secondary"
          onClick={() => onReview(candidate.id, 'hold', reason, candidate.version)}
        >
          <Pause size={16} /> Hold
        </button>
        <button
          disabled={saving || reason.trim().length < 3}
          className="secondary"
          onClick={() => onReview(candidate.id, 'reject', reason, candidate.version)}
        >
          Reject
        </button>
      </div>
    </section>
  );
}
