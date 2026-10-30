'use client';

import { FormEvent, MutableRefObject, useState } from 'react';
import { Loader2, Sparkles } from 'lucide-react';
import { AuditItem, Candidate, Job, publicWebUrl } from '@/lib/portal';
import { Empty, Loading } from '@/components/CourseList';
import { IntegrationStatus } from '@/components/IntegrationStatus';
import { CandidateCard } from '@/components/CandidateCard';

export function IngestionPanel({
  jobQuery,
  jobMaxResults,
  jobs,
  jobPage = 1,
  jobTotal,
  jobStatus = '',
  jobFilterOptions = [],
  candidates,
  candidatePage = 1,
  candidateTotal,
  candidateStatus = 'awaiting',
  candidateJobId = '',
  submitting,
  saving,
  jobKey,
  onJobQuery,
  onJobMaxResults,
  onSubmit,
  onRefresh,
  onRetry,
  onReview,
  onDailyScrape,
  onJobPage,
  onJobStatus,
  onCandidatePage,
  onCandidateStatus,
  onCandidateJobId,
  loading = false,
  jobsFailed = false,
  candidatesFailed = false,
  auditFailed = false,
  topicsFailed = false,
  topics = [],
  ceiling = null,
  scrapeDay = '',
  forceScrape = false,
  onForceScrape,
  scrapeResult,
  onRunDigests,
  digestResult,
  audits = [],
}: {
  jobQuery: string;
  jobMaxResults: number;
  jobs: Job[];
  jobPage?: number;
  jobTotal?: number;
  jobStatus?: string;
  /** Unpaginated (capped) job list for the candidate job filter — not the discovery-jobs page. */
  jobFilterOptions?: Job[];
  candidates: Candidate[];
  candidatePage?: number;
  candidateTotal?: number;
  candidateStatus?: string;
  candidateJobId?: string;
  submitting: boolean;
  saving: boolean;
  jobKey: MutableRefObject<string>;
  onJobQuery: (value: string) => void;
  onJobMaxResults: (value: number) => void;
  onSubmit: (event: FormEvent) => void;
  onRefresh: () => void;
  onRetry: (id: string) => void;
  onReview: (
    id: string,
    action: string,
    reason: string,
    version?: number,
    corrections?: Record<string, string>,
    evidence?: Record<string, string>,
  ) => void;
  onDailyScrape?: () => void;
  onJobPage?: (page: number) => void;
  onJobStatus?: (value: string) => void;
  onCandidatePage?: (page: number) => void;
  onCandidateStatus?: (value: string) => void;
  onCandidateJobId?: (value: string) => void;
  loading?: boolean;
  jobsFailed?: boolean;
  candidatesFailed?: boolean;
  auditFailed?: boolean;
  topicsFailed?: boolean;
  topics?: { query: string; max_results: number }[];
  ceiling?: number | null;
  scrapeDay?: string;
  forceScrape?: boolean;
  onForceScrape?: (next: boolean) => void;
  scrapeResult?: { enqueued: number; skipped: number; day: string; ceiling: number; topics: number } | null;
  onRunDigests?: () => void;
  digestResult?: { sent: number; failed: number; day: string } | null;
  audits?: AuditItem[];
}) {
  const [liveReady, setLiveReady] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);
  const paidBlocked = !liveReady || statusLoading;
  const awaitingFilter = candidateStatus === 'awaiting' || candidateStatus === 'pending,held';
  const countLabel = awaitingFilter ? 'awaiting review' : 'matching filter';
  // Candidate job filter must not be limited to the current discovery-jobs page.
  const candidateJobChoices = (() => {
    const base = jobFilterOptions.length ? jobFilterOptions : jobs;
    if (candidateJobId && !base.some((job) => job.id === candidateJobId)) {
      return [{ id: candidateJobId, query: candidateJobId } as Job, ...base];
    }
    return base;
  })();

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (paidBlocked) return;
    onSubmit(event);
  }

  return (
    <>
      <div className="page-title">
        <div>
          <p className="eyebrow">OPERATOR WORKSPACE</p>
          <h1>Bring useful training into view.</h1>
          <p>Tavily finds sources. An open-weight model extracts details. You review the evidence.</p>
        </div>
      </div>
      <form className="panel ingestion-form" onSubmit={handleSubmit}>
        <label>
          Malaysia training topic
          <input
            required
            minLength={3}
            maxLength={300}
            value={jobQuery}
            onChange={(e) => {
              onJobQuery(e.target.value);
              jobKey.current = '';
            }}
          />
        </label>
        <label>
          Source pages
          <select
            aria-label="Maximum source pages"
            value={jobMaxResults}
            onChange={(e) => {
              onJobMaxResults(Number(e.target.value));
              jobKey.current = '';
            }}
          >
            {[1, 2, 3, 4, 5].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <div className="button-row">
          <button className="primary" disabled={submitting || paidBlocked}>
            {submitting ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />} Start discovery
          </button>
          {onDailyScrape && (
            <button
              className="secondary"
              type="button"
              disabled={saving || submitting || paidBlocked}
              onClick={() => {
                if (paidBlocked) return;
                onDailyScrape();
              }}
            >
              Queue daily scrape
            </button>
          )}
          {onRunDigests && (
            <button className="secondary" type="button" disabled={saving || submitting} onClick={onRunDigests}>
              Send due digests
            </button>
          )}
        </div>
        {onDailyScrape && onForceScrape ? (
          <label className="check-row">
            <input type="checkbox" checked={forceScrape} onChange={(e) => onForceScrape(e.target.checked)} />
            <span>Re-queue idle interrupted/failed/partial jobs (force; never succeeded)</span>
          </label>
        ) : null}
        {scrapeResult ? (
          <p className="small-note">
            Daily scrape {scrapeResult.day}: {scrapeResult.enqueued} queued, {scrapeResult.skipped} skipped, ceiling{' '}
            {scrapeResult.ceiling}, {scrapeResult.topics} topics.
          </p>
        ) : null}
        {digestResult ? (
          <p className="small-note">
            Digest {digestResult.day}: {digestResult.sent} sent, {digestResult.failed} failed. Catalogue and progress
            only — no Tavily call.
          </p>
        ) : null}
        {topicsFailed && topics.length ? (
          <p className="small-note" data-testid="scrape-topics-stale">
            Couldn't refresh curated daily topics. Showing the last loaded list.{' '}
            <button className="text-btn" type="button" onClick={onRefresh}>
              Retry
            </button>
          </p>
        ) : null}
        {topicsFailed && !topics.length ? (
          <p className="small-note" data-testid="scrape-topics-failed">
            Couldn't load curated daily topics. Check your connection, then try again.{' '}
            <button className="text-btn" type="button" onClick={onRefresh}>
              Retry
            </button>
          </p>
        ) : topics.length ? (
          <div className="small-note">
            <p>
              Curated daily topics ({topics.length}
              {ceiling != null ? ` · ceiling ${ceiling}` : ''}
              {scrapeDay ? ` · ${scrapeDay}` : ''}). Edit config/scrape_topics.json to change the list.
            </p>
            <ul className="source-list">
              {topics.map((topic) => (
                <li key={topic.query}>
                  {topic.query} · up to {topic.max_results}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <p className="small-note">
          {liveReady
            ? 'A live run uses Tavily Search and Extract for up to five sources. Missing Tavily credentials fail honestly. Structured candidates still need a configured open-weight model.'
            : 'Live discovery stays off until Tavily and the open-weight model are ready. Claim returns 204 not_ready so queued jobs stay idle without spend. Review the fixture queue without spending credits.'}
        </p>
        <IntegrationStatus
          onLiveReady={(ready, loading) => {
            setLiveReady(ready);
            setStatusLoading(loading);
          }}
        />
      </form>
      <div className="section-heading">
        <h2>Discovery jobs</h2>
        <span>
          {loading && !jobs.length
            ? 'Loading…'
            : jobsFailed
              ? "Couldn't load…"
              : `${jobTotal ?? jobs.length} matching`}
        </span>
        <button className="text-btn" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      {onJobStatus ? (
        <div className="filter-row" data-testid="operator-job-filters">
          <label>
            Status
            <select
              aria-label="Job status filter"
              value={jobStatus}
              onChange={(e) => onJobStatus(e.target.value)}
              disabled={saving}
            >
              <option value="">All statuses</option>
              <option value="queued,running">Active</option>
              <option value="interrupted">Interrupted</option>
              <option value="succeeded,partial">Finished</option>
              <option value="failed">Failed</option>
            </select>
          </label>
        </div>
      ) : null}
      {jobsFailed && jobs.length ? (
        <p className="small-note" data-testid="operator-jobs-refresh-failed">
          Couldn't refresh discovery jobs. Showing the last loaded list.{' '}
          <button className="text-btn" type="button" onClick={onRefresh}>
            Retry
          </button>
        </p>
      ) : null}
      <div className="job-list">
        {loading && !jobs.length ? (
          <Loading text="Loading discovery jobs…" />
        ) : jobs.length ? (
          <>
            {!liveReady && !statusLoading && jobs.some((item) => item.status === 'queued') ? (
              <p className="small-note" data-testid="operator-claim-idle-not-ready">
                Queued jobs stay idle until live discovery is ready — claim returns 204 not_ready (worker waits; no
                Tavily spend).
              </p>
            ) : null}
            {jobs.map((j) => (
              <article className="job-row" key={j.id}>
                <div>
                  <strong>{j.query}</strong>
                  <small>
                    Up to {j.max_results ?? 5} pages · {j.result?.sources?.length ?? 0} sources ·{' '}
                    {j.result?.candidate_count ?? 0} candidates
                    {j.result?.usage?.tavily_credits != null
                      ? ` · ${j.result.usage.tavily_credits} reported Tavily credits`
                      : ''}
                    {j.result?.usage?.model_tokens != null
                      ? ` · ${j.result.usage.model_tokens} reported model tokens`
                      : ''}{' '}
                    {j.result?.warnings?.map((w, i) => (
                      <span className="job-warning" key={i}>
                        {w}
                      </span>
                    ))}
                  </small>
                  {j.result?.sources?.length ? (
                    <ul className="source-list">
                      {j.result.sources.map((source, index) => {
                        const href = publicWebUrl(source.url);
                        return (
                          <li key={(source.url || source.title || 'source') + '-' + index}>
                            {href ? (
                              <a href={href} target="_blank" rel="noreferrer">
                                {source.title || source.url}
                              </a>
                            ) : (
                              <span>{source.title || 'Source URL is not available'}</span>
                            )}
                            {source.extraction_status ? <span> · {source.extraction_status}</span> : null}
                            {source.retrieved_at ? (
                              <span> · retrieved {source.retrieved_at}</span>
                            ) : (
                              <span> · retrieval time unavailable</span>
                            )}
                            {source.snippet ? <span> — {source.snippet}</span> : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </div>
                <div className="button-row">
                  <span className={'status ' + j.status}>{j.status}</span>
                  {j.status === 'interrupted' && (
                    <button
                      className="secondary"
                      disabled={saving || paidBlocked}
                      onClick={() => {
                        if (paidBlocked) return;
                        onRetry(j.id);
                      }}
                    >
                      Retry job
                    </button>
                  )}
                </div>
              </article>
            ))}
            {onJobPage && (jobTotal ?? 0) > 20 && (
              <div className="pagination">
                <button
                  className="secondary"
                  type="button"
                  disabled={jobPage <= 1 || saving || loading}
                  onClick={() => onJobPage(jobPage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {jobPage} of {Math.max(1, Math.ceil((jobTotal || 0) / 20))}
                </span>
                <button
                  className="secondary"
                  type="button"
                  disabled={jobPage * 20 >= (jobTotal || 0) || saving || loading}
                  onClick={() => onJobPage(jobPage + 1)}
                >
                  Next
                </button>
              </div>
            )}
          </>
        ) : (
          <Empty
            title={
              jobsFailed
                ? "Couldn't load discovery jobs"
                : jobStatus
                  ? 'No jobs match this status filter'
                  : 'No discovery jobs yet'
            }
            text={
              jobsFailed
                ? 'Check your connection, then try again.'
                : jobStatus
                  ? 'Try another status, or clear the filter to see all jobs.'
                  : 'Start a search above to populate the review queue.'
            }
            action={onRefresh}
            actionLabel="Retry"
          />
        )}
      </div>
      <div className="section-heading">
        <h2>Review candidates</h2>
        <span>
          {loading && !candidates.length
            ? 'Loading…'
            : candidatesFailed
              ? "Couldn't load…"
              : `${candidateTotal ?? candidates.length} ${countLabel}`}
        </span>
      </div>
      {(onCandidateStatus || onCandidateJobId) && (
        <div className="filter-row" data-testid="operator-candidate-filters">
          {onCandidateStatus ? (
            <label>
              Status
              <select
                aria-label="Candidate status filter"
                value={candidateStatus}
                onChange={(e) => onCandidateStatus(e.target.value)}
                disabled={saving}
              >
                <option value="awaiting">Awaiting review (pending + held)</option>
                <option value="pending">Pending</option>
                <option value="held">Held</option>
                <option value="rejected">Rejected</option>
                <option value="pending,held,rejected">All reviewable</option>
              </select>
            </label>
          ) : null}
          {onCandidateJobId ? (
            <label>
              Job
              <select
                aria-label="Candidate job filter"
                value={candidateJobId}
                onChange={(e) => onCandidateJobId(e.target.value)}
                disabled={saving}
              >
                <option value="">All jobs</option>
                {candidateJobChoices.map((job) => (
                  <option key={job.id} value={job.id}>
                    {(job.query || job.id).slice(0, 48)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      )}
      {candidatesFailed && candidates.length ? (
        <p className="small-note" data-testid="operator-candidates-refresh-failed">
          Couldn't refresh review candidates. Showing the last loaded list.{' '}
          <button className="text-btn" type="button" onClick={onRefresh}>
            Retry
          </button>
        </p>
      ) : null}
      {loading && !candidates.length ? (
        <Loading text="Loading review candidates…" />
      ) : candidates.length ? (
        <>
          {candidates.map((c) => (
            <CandidateCard
              key={c.id + '-' + c.version}
              candidate={c}
              saving={saving}
              onReview={onReview}
            />
          ))}
          {onCandidatePage && (candidateTotal ?? 0) > 20 && (
            <div className="pagination">
              <button
                className="secondary"
                type="button"
                disabled={candidatePage <= 1 || saving || loading}
                onClick={() => onCandidatePage(candidatePage - 1)}
              >
                Previous
              </button>
              <span>
                Page {candidatePage} of {Math.max(1, Math.ceil((candidateTotal || 0) / 20))}
              </span>
              <button
                className="secondary"
                type="button"
                disabled={candidatePage * 20 >= (candidateTotal || 0) || saving || loading}
                onClick={() => onCandidatePage(candidatePage + 1)}
              >
                Next
              </button>
            </div>
          )}
        </>
      ) : (
        <Empty
          title={
            candidatesFailed
              ? "Couldn't load review candidates"
              : awaitingFilter && !candidateJobId
                ? 'No candidates awaiting review'
                : 'No candidates match these filters'
          }
          text={
            candidatesFailed
              ? 'Check your connection, then try again.'
              : awaitingFilter && !candidateJobId
                ? 'Queued jobs will appear here after the scraper finishes.'
                : 'Try another status or job, or clear filters to see the full queue.'
          }
          action={onRefresh}
          actionLabel="Retry"
        />
      )}
      <div className="section-heading">
        <h2>Operator audit</h2>
        <span>
          {loading
            ? 'Loading…'
            : auditFailed && !audits.length
              ? "Couldn't load…"
              : `${audits.length} recent`}
        </span>
      </div>
      {loading ? (
        <p className="small-note" role="status" aria-busy="true">
          Loading operator activity…
        </p>
      ) : (
        <>
          {auditFailed && audits.length ? (
            <p className="small-note" data-testid="operator-audit-stale">
              Couldn&apos;t refresh operator activity. Showing the last loaded list.{' '}
              <button className="text-btn" type="button" onClick={onRefresh}>
                Retry
              </button>
            </p>
          ) : null}
          {audits.length ? (
            <ul className="source-list">
              {audits.map((item) => (
                <li key={item.id}>
                  {item.action} · {item.entity_id}
                  {item.at ? ` · ${new Date(item.at * 1000).toLocaleString('en-MY')}` : ''}
                </li>
              ))}
            </ul>
          ) : (
            <p className="small-note">
              {auditFailed
                ? "Couldn't load operator activity. Check your connection, then try again."
                : 'Review and profile actions appear here. Personal notes are never stored on this list.'}
              {auditFailed ? (
                <>
                  {' '}
                  <button className="text-btn" type="button" onClick={onRefresh}>
                    Retry
                  </button>
                </>
              ) : null}
            </p>
          )}
        </>
      )}
    </>
  );
}
