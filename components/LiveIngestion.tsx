'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import './LiveIngestion.css';
import { CandidateCard } from '@/components/CandidateCard';
import { IntegrationStatus } from '@/components/IntegrationStatus';
import { api, Candidate, Job, publicWebUrl } from '@/lib/portal';

type Topic = { query: string; max_results: number };
type ScrapeResult = { enqueued: number; skipped: number; day: string; ceiling: number; topics: number };

const TERMINAL = new Set(['succeeded', 'partial', 'failed']);

function isFixtureJob(job: Job | null) {
  if (!job) return false;
  return (
    job.result?.extraction_status === 'fixture' ||
    (job.query || '').toLowerCase().includes('fictional fixtures') ||
    (job.result?.warnings || []).some((warning) => warning.toUpperCase().includes('FIXTURE'))
  );
}

export function LiveIngestion({ onPublished }: { onPublished?: () => void }) {
  const [query, setQuery] = useState('GP CPD courses Kuala Lumpur');
  const [maxResults, setMaxResults] = useState(1);
  const [sourceLimit, setSourceLimit] = useState(1);
  const [job, setJob] = useState<Job | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(true);
  const [candidatesFailed, setCandidatesFailed] = useState(false);
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [candidateStatus, setCandidateStatus] = useState('awaiting');
  const [candidateJobId, setCandidateJobId] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [liveReady, setLiveReady] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsFailed, setJobsFailed] = useState(false);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [topicsFailed, setTopicsFailed] = useState(false);
  const [jobPollFailed, setJobPollFailed] = useState(false);
  const [ceiling, setCeiling] = useState<number | null>(null);
  const [scrapeDay, setScrapeDay] = useState('');
  const [forceScrape, setForceScrape] = useState(false);
  const [scrapeBusy, setScrapeBusy] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<ScrapeResult | null>(null);
  const [digestBusy, setDigestBusy] = useState(false);
  const [digestResult, setDigestResult] = useState<{ sent: number; failed: number; day: string } | null>(null);
  const keyRef = useRef('');
  const jobsRequest = useRef(0);
  const candidatesRequest = useRef(0);
  const jobPollRequest = useRef(0);
  const CANDIDATE_PAGE = 20;

  async function loadCandidates(page = candidatePage, status = candidateStatus, jobId = candidateJobId) {
    const requestId = ++candidatesRequest.current;
    setCandidatesLoading(true);
    setError('');
    try {
      let current = page;
      while (true) {
        const params = new URLSearchParams({
          page: String(current),
          page_size: String(CANDIDATE_PAGE),
          status,
        });
        if (jobId) params.set('job_id', jobId);
        const data = await api('/admin/candidates?' + params);
        if (candidatesRequest.current !== requestId) return;
        const total = data.total || 0;
        const pageCount = Math.max(1, Math.ceil(total / CANDIDATE_PAGE));
        if (current > pageCount) {
          current = pageCount;
          continue;
        }
        setCandidates(data.items || []);
        setCandidateTotal(total);
        setCandidatePage(current);
        // Commit filters only after a successful load (parity with /live learning filter).
        setCandidateStatus(status);
        setCandidateJobId(jobId);
        setCandidatesFailed(false);
        break;
      }
    } catch (e) {
      if (candidatesRequest.current !== requestId) return;
      setCandidatesFailed(true);
      setError((e as Error).message);
    } finally {
      if (candidatesRequest.current === requestId) setCandidatesLoading(false);
    }
  }

  function applyCandidateStatus(next: string) {
    // Page resets only inside loadCandidates after a successful load (filter-commit honesty).
    loadCandidates(1, next, candidateJobId);
  }

  function applyCandidateJob(next: string) {
    // Page resets only inside loadCandidates after a successful load (filter-commit honesty).
    loadCandidates(1, candidateStatus, next);
  }

  async function loadJobs() {
    const requestId = ++jobsRequest.current;
    setJobsLoading(true);
    try {
      // Demo shell scans the newest page (max page_size) for the labelled fixture job.
      const jobList = await api('/admin/ingestion-jobs?page=1&page_size=50');
      if (jobsRequest.current !== requestId) return;
      const items: Job[] = jobList.items || [];
      setJobs(items);
      const fixture = items.find((item) => isFixtureJob(item));
      setJob((current) => current || fixture || items[0] || null);
      setJobsFailed(false);
    } catch (e) {
      if (jobsRequest.current !== requestId) return;
      setJobsFailed(true);
      setError((e as Error).message);
    } finally {
      if (jobsRequest.current === requestId) setJobsLoading(false);
    }
  }

  async function loadTopics() {
    try {
      const topicPayload = await api('/admin/scrape-topics');
      setTopics(topicPayload.topics || []);
      setCeiling(topicPayload.ceiling ?? null);
      setScrapeDay(topicPayload.day || '');
      setTopicsFailed(false);
    } catch {
      setTopicsFailed(true);
    }
  }

  useEffect(() => {
    api('/config').then((data) => setSourceLimit(data.discovery_max_results || 1)).catch(() => {});
    loadJobs();
    loadCandidates();
    loadTopics();
  }, []);

  async function refreshJobStatus(jobId = job?.id) {
    if (!jobId) return;
    const requestId = ++jobPollRequest.current;
    try {
      const current = await api('/admin/ingestion-jobs/' + jobId);
      if (jobPollRequest.current !== requestId) return;
      setJob(current);
      setJobPollFailed(false);
      if (TERMINAL.has(current.status)) loadCandidates();
    } catch {
      if (jobPollRequest.current === requestId) setJobPollFailed(true);
    }
  }

  useEffect(() => {
    if (!job?.id || TERMINAL.has(job.status) || job.status === 'interrupted') {
      if (job?.id && TERMINAL.has(job.status)) loadCandidates();
      return;
    }
    const trackedId = job.id;
    setJobPollFailed(false);
    const timer = window.setInterval(() => {
      refreshJobStatus(trackedId);
    }, 2000);
    return () => {
      window.clearInterval(timer);
      jobPollRequest.current += 1;
    };
  }, [job?.id, job?.status]);

  async function runDigests() {
    setDigestBusy(true);
    setError('');
    try {
      setDigestResult(await api('/admin/digests/run', { method: 'POST' }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDigestBusy(false);
    }
  }

  async function queueDaily() {
    if (!liveReady) {
      setError('Live discovery stays off until Tavily and the open-weight model are ready.');
      return;
    }
    setScrapeBusy(true);
    setError('');
    try {
      const result = await api('/admin/daily-scrape?force=' + String(forceScrape), { method: 'POST' });
      setScrapeResult(result);
      await loadJobs();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setScrapeBusy(false);
    }
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!liveReady) {
      setError('Live discovery stays off until Tavily and the open-weight model are ready.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (!keyRef.current) keyRef.current = crypto.randomUUID();
      const created = await api('/admin/ingestion-jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': keyRef.current },
        body: JSON.stringify({ query, max_results: maxResults }),
      });
      keyRef.current = '';
      setJob(created);
      if (created.execution_mode === 'request') {
        setJob(await api('/admin/ingestion-jobs/' + created.id + '/run', { method: 'POST' }));
      }
      await loadCandidates(1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function retry() {
    if (!job?.id) return;
    if (!liveReady) {
      setError('Live discovery stays off until Tavily and the open-weight model are ready.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const queued = await api('/admin/ingestion-jobs/' + job.id + '/retry', { method: 'POST' });
      setJob(queued);
      if (queued.execution_mode === 'request') {
        setJob(await api('/admin/ingestion-jobs/' + queued.id + '/run', { method: 'POST' }));
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function runQueued() {
    if (!job?.id) return;
    setBusy(true);
    setError('');
    try {
      setJob(await api('/admin/ingestion-jobs/' + job.id + '/run', { method: 'POST' }));
      await loadCandidates();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const sources = job?.result?.sources || [];
  const warnings = job?.result?.warnings || [];
  const fixtureJob = isFixtureJob(job);
  const fixtureCandidates = candidates.some(
    (item) => item.data._fixture || (item.data.source_url || '').includes('carecredits-demo-candidate'),
  );

  return (
    <section className="card ingestion-panel" aria-label="Training discovery workspace">
      <div className="card-heading">
        <div>
          <span className="heading-icon">▣</span>
          <h2>{fixtureJob || fixtureCandidates ? 'Fixture review queue' : 'Training discovery'}</h2>
        </div>
      </div>
      <p className="ingestion-intro">Find Malaysian CPD training, check the source, then publish it to your catalogue.</p>
      <div className="ingestion-readiness" role="status" data-ready={liveReady}>
        <span className="ingestion-dot" />
        <strong>{statusLoading ? 'Checking connections...' : liveReady ? 'Ready to discover' : 'Discovery unavailable'}</strong>
        <span>{candidateTotal} matching review candidates</span>
      </div>
      {(fixtureJob || fixtureCandidates) && (
        <p className="empty-copy" data-testid="fixture-review-banner">
          <span className="badge">FIXTURE</span> Pending candidates below are fictional demo fixtures for offline
          review. They are not a live Tavily Search/Extract or model run. Start a bounded discovery below only when
          live credentials are configured.
        </p>
      )}
      <h3 className="ingestion-section-title">1. Discover training</h3>
      <form className="ingestion-form" onSubmit={start}>
        <label>
          What training are you looking for?
          <input
            required
            minLength={3}
            maxLength={300}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              keyRef.current = '';
            }}
          />
        </label>
        <label>
          Source pages
          <select
            aria-label="Maximum source pages"
            value={maxResults}
            onChange={(e) => {
              setMaxResults(Number(e.target.value));
              keyRef.current = '';
            }}
          >
            {Array.from({ length: sourceLimit }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={busy || !liveReady || statusLoading}>
          {busy ? <Loader2 className="spin" size={16} /> : null}
          {busy ? 'Discovering…' : 'Discover training'}
        </button>
      </form>
      <p className="empty-copy">
        {liveReady
          ? `Searches up to ${sourceLimit} source page(s) using Tavily and your AI model. Each run uses API credits. Results await your review before publication.`
          : 'Discovery is unavailable until its connections are ready. You can still review existing candidates. Open Advanced tools for connection details.'}
      </p>
      <h3 className="ingestion-section-title">2. Run history</h3>
      {jobsFailed && jobs.length ? (
        <p className="empty-copy" data-testid="live-jobs-refresh-failed">
          Couldn't refresh discovery jobs. Showing the last loaded list.{' '}
          <button className="text-link" type="button" onClick={() => loadJobs()}>
            Retry
          </button>
        </p>
      ) : null}
      {jobsLoading && !jobs.length ? (
        <p className="empty-copy" role="status" aria-busy="true" data-testid="live-job-loading">
          Loading discovery jobs…
        </p>
      ) : jobs.length ? (
        <div className="empty-copy" data-testid="live-job-list">
          <p>Select a run to inspect its results and source evidence.</p>
          {!liveReady && !statusLoading && jobs.some((item) => item.status === 'queued') ? (
            <p data-testid="live-claim-idle-not-ready">
              Queued runs wait until the service is ready. No search credits are used while waiting.
            </p>
          ) : null}
          <ul>
            {jobs.slice(0, 8).map((item) => (
              <li key={item.id}>
                {item.status} · {item.query}
              </li>
            ))}
          </ul>
        </div>
      ) : jobsFailed ? (
        <p className="empty-copy" data-testid="live-job-empty">
          Couldn't load discovery jobs.{' '}
          <button className="text-link" type="button" onClick={() => loadJobs()}>
            Retry
          </button>
        </p>
      ) : null}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {job?.status === 'queued' && job.execution_mode === 'request' && (
        <button className="secondary" type="button" disabled={busy || !liveReady} onClick={runQueued}>
          Run queued discovery
        </button>
      )}
      {job && (
        <div className="empty-copy" data-testid="live-job-status">
          <p>
            {fixtureJob ? 'Fixture job' : 'Job'} {job.status}
            {job.result?.usage?.tavily_credits != null ? ` · ${job.result.usage.tavily_credits} reported Tavily credits` : ''}
            {job.result?.usage?.model_tokens != null ? ` · ${job.result.usage.model_tokens} reported model tokens` : ''}
          </p>
          {jobPollFailed ? (
            <p role="status">Showing the last recorded execution details.</p>
          ) : null}
          <details className="ingestion-details">
            <summary>AI extraction receipt</summary>
            {fixtureJob ? <p>Fictional fixture — no live model call.</p> : job.result?.extractions?.length ? (
              <ul>{job.result.extractions.map((run, index) => <li key={index}>
                <strong>Successful live extraction (reported by scraper)</strong><br />
                Model: {run.model_id} · Endpoint: {run.endpoint_host}<br />
                Completed: {run.completed_at} · Source-supported candidates: {run.candidate_count}
              </li>)}</ul>
            ) : <p>No successful live extraction recorded for this job.</p>}
            <p>Supporting sources and reviewable candidates appear below. This records the requested model, not independent provider attestation.</p>
          </details>
          {jobPollFailed ? (
            <p className="empty-copy" data-testid="live-job-poll-failed">
              Couldn't refresh job status. Last known status is shown above.{' '}
              <button className="text-link" type="button" onClick={() => refreshJobStatus()}>
                Retry
              </button>
            </p>
          ) : null}
          {sources.length ? (
            <ul>
              {sources.map((source, index) => {
                const href = publicWebUrl(source.url);
                return (
                  <li key={(source.url || 'source') + '-' + index}>
                    {source.extraction_status}: {href || 'URL omitted'}
                    {source.retrieved_at ? ` · retrieved ${source.retrieved_at}` : ' · retrieval time unavailable'}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p>{fixtureJob ? 'Fixture sources are labelled below. No Tavily URLs were fetched.' : 'No Tavily source URLs yet.'}</p>
          )}
          {warnings.map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
          {job.status === 'interrupted' && (
            <button className="secondary" type="button" disabled={busy || !liveReady || statusLoading} onClick={retry}>
              Retry interrupted job
            </button>
          )}
        </div>
      )}
      <div data-testid="live-review-queue">
        <h3 className="ingestion-section-title">3. Review &amp; publish</h3>
        <p className="ingestion-hint">Open a candidate to compare the extracted details with its source. Only publish after review.</p>
        <div className="filter-row" data-testid="live-candidate-filters">
          <label>
            Status
            <select
              aria-label="Candidate status filter"
              value={candidateStatus}
              onChange={(e) => applyCandidateStatus(e.target.value)}
              disabled={saving || candidatesLoading}
            >
              <option value="awaiting">Awaiting review (pending + held)</option>
              <option value="pending">Pending</option>
              <option value="held">Held</option>
              <option value="rejected">Rejected</option>
              <option value="pending,held,rejected">All reviewable</option>
            </select>
          </label>
          <label>
            Job
            <select
              aria-label="Candidate job filter"
              value={candidateJobId}
              onChange={(e) => applyCandidateJob(e.target.value)}
              disabled={saving || candidatesLoading}
            >
              <option value="">All jobs</option>
              {(candidateJobId && !jobs.some((item) => item.id === candidateJobId)
                ? [{ id: candidateJobId, query: candidateJobId } as Job, ...jobs]
                : jobs
              ).map((item) => (
                <option key={item.id} value={item.id}>
                  {(item.query || item.id).slice(0, 48)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {candidatesFailed && candidates.length ? (
          <p className="empty-copy" data-testid="live-candidates-refresh-failed">
            Couldn't refresh review candidates. Showing the last loaded list.{' '}
            <button className="text-link" type="button" onClick={() => loadCandidates(candidatePage)}>
              Retry
            </button>
          </p>
        ) : null}
        {candidatesLoading && !candidates.length ? (
          <p className="empty-copy" role="status" aria-busy="true" data-testid="live-review-loading">
            Loading review candidates…
          </p>
        ) : candidates.length ? (
          <>
            {candidates.map((item) => (
              <details className="ingestion-candidate" key={item.id + '-' + item.version}>
                <summary><span><strong>{item.data.title}</strong><small>{item.data.provider || 'Provider not listed'}</small></span><span className="ingestion-status">{item.status}</span></summary>
              <CandidateCard
                candidate={item}
                saving={saving}
                onReview={async (id, action, reason, version, corrections, evidence) => {
                  setSaving(true);
                  setError('');
                  try {
                    await api('/admin/candidates/' + id + '/review', {
                      method: 'POST',
                      body: JSON.stringify({ action, reason, version, corrections, evidence }),
                    });
                    await loadCandidates(candidatePage);
                    if (action === 'publish') onPublished?.();
                  } catch (e) {
                    const message = (e as Error).message || '';
                    // Stale version 409: reload cards so the operator sees current versions.
                    if (/changed|refresh|conflict/i.test(message)) {
                      await loadCandidates(candidatePage).catch(() => {});
                    }
                    setError(message);
                  } finally {
                    setSaving(false);
                  }
                }}
              />
              </details>
            ))}
            {candidateTotal > CANDIDATE_PAGE && (
              <div className="pager" data-testid="live-candidate-pager">
                <button
                  className="text-link"
                  type="button"
                  disabled={candidatePage <= 1 || saving || candidatesLoading}
                  onClick={() => loadCandidates(candidatePage - 1)}
                >
                  Previous
                </button>
                <span>
                  Page {candidatePage} of {Math.max(1, Math.ceil(candidateTotal / CANDIDATE_PAGE))}
                </span>
                <button
                  className="text-link"
                  type="button"
                  disabled={candidatePage * CANDIDATE_PAGE >= candidateTotal || saving || candidatesLoading}
                  onClick={() => loadCandidates(candidatePage + 1)}
                >
                  Next
                </button>
              </div>
            )}
          </>
        ) : (
          <p className="empty-copy" data-testid="live-review-empty">
            {candidatesFailed
              ? "Couldn't load review candidates. "
              : candidateStatus === 'awaiting' && !candidateJobId
                ? 'No candidates awaiting review. '
                : 'No candidates match these filters. '}
            <button className="text-link" type="button" onClick={() => loadCandidates(1)}>
              Retry
            </button>
          </p>
        )}
      </div>
      <details className="ingestion-advanced">
        <summary>Advanced tools &amp; connection details</summary>
        <p className="ingestion-hint">Service diagnostics and maintenance actions for operators.</p>
      <IntegrationStatus
        className="empty-copy"
        onLiveReady={(ready, loading) => {
          setLiveReady(ready);
          setStatusLoading(loading);
        }}
      />
        <details className="ingestion-details"><summary>Scheduled topics &amp; maintenance</summary>
        {sourceLimit === 1 && <p className="ingestion-hint">Scheduled batch discovery is disabled on this deployment. Use the single-source discovery form above.</p>}
      {topicsFailed && topics.length ? (
        <p className="empty-copy" data-testid="live-scrape-topics-stale">
          Couldn't refresh curated daily topics. Showing the last loaded list.{' '}
          <button className="text-link" type="button" onClick={() => loadTopics()}>
            Retry
          </button>
        </p>
      ) : null}
      {topicsFailed && !topics.length ? (
        <p className="empty-copy" data-testid="live-scrape-topics-failed">
          Couldn't load curated daily topics. Check your connection, then try again.{' '}
          <button className="text-link" type="button" onClick={() => loadTopics()}>
            Retry
          </button>
        </p>
      ) : topics.length ? (
        <div className="empty-copy" data-testid="live-scrape-topics">
          <p>
            Curated daily topics ({topics.length}
            {ceiling != null ? ` · ceiling ${ceiling}` : ''}
            {scrapeDay ? ` · ${scrapeDay}` : ''}). Edit config/scrape_topics.json to change the list.
          </p>
          <ul>
            {topics.map((topic) => (
              <li key={topic.query}>
                {topic.query} · up to {topic.max_results}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="empty-copy" data-testid="live-daily-scrape">
        <label>
          <input type="checkbox" checked={forceScrape} onChange={(e) => setForceScrape(e.target.checked)} />{' '}
          Re-queue idle interrupted/failed/partial jobs (force; never succeeded)
        </label>{' '}
        <button className="secondary" type="button" disabled={sourceLimit === 1 || scrapeBusy || !liveReady || statusLoading} onClick={queueDaily}>
          {scrapeBusy ? 'Queuing…' : 'Queue daily scrape'}
        </button>
        {scrapeResult ? (
          <p>
            Daily scrape {scrapeResult.day}: {scrapeResult.enqueued} queued, {scrapeResult.skipped} skipped, ceiling{' '}
            {scrapeResult.ceiling}, {scrapeResult.topics} topics.
          </p>
        ) : null}
      </div>
      <div className="empty-copy" data-testid="live-digest-run">
        <button className="secondary" type="button" disabled={digestBusy} onClick={runDigests}>
          {digestBusy ? 'Sending…' : 'Send due digests'}
        </button>
        {digestResult ? (
          <p>
            Digest {digestResult.day}: {digestResult.sent} sent, {digestResult.failed} failed. Catalogue and progress
            only — no Tavily call.
          </p>
        ) : null}
      </div>
        </details>
      </details>
    </section>
  );
}
