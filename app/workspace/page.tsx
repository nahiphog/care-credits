'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Compass,
  Eye,
  LayoutDashboard,
  Loader2,
  LogOut,
  MapPin,
  Menu,
  Settings2,
  ShieldCheck,
  X,
} from 'lucide-react';
import { Brand } from '@/components/Brand';
import { LoginForm } from '@/components/LoginForm';
import { OverviewPanel } from '@/components/OverviewPanel';
import { DiscoverPanel, DiscoverFilters, LearningFilters } from '@/components/DiscoverPanel';
import { ProfilePanel } from '@/components/ProfilePanel';
import { IngestionPanel } from '@/components/IngestionPanel';
import { TrainingDetail } from '@/components/TrainingDetail';
import {
  api,
  AuditItem,
  calendarYearLocal,
  Candidate,
  Course,
  emptyRecord,
  Job,
  normalizeRecordEdit,
  Progress,
  RecordData,
  Suggestion,
  User,
  WorkspaceTab,
} from '@/lib/portal';

const initialFilters: DiscoverFilters = {
  q: '',
  city: '',
  state: '',
  mode: '',
  difficulty: '',
  maxFee: '',
  minPoints: '',
  period: 'upcoming',
  dateFrom: '',
  dateTo: '',
  includeUnknown: false,
  radius: '25',
  location: null,
  page: 1,
};

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [demo, setDemo] = useState(false);
  const [signup, setSignup] = useState(false);
  const [oauth, setOauth] = useState(false);
  const [history, setHistory] = useState<import('@/lib/portal').RecordHistoryItem[]>([]);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [tab, setTab] = useState<WorkspaceTab>('Overview');
  const [navOpen, setNavOpen] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [courses, setCourses] = useState<Course[]>([]);
  const [records, setRecords] = useState<Course[]>([]);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [recordsLoading, setRecordsLoading] = useState(true);
  const [coursesLoading, setCoursesLoading] = useState(true);
  const [coursesFailed, setCoursesFailed] = useState(false);
  // GEO-02: distance labels follow the last successful Near-me result set (parity with /live resultsNearby),
  // not the draft location filter — avoids "distance unavailable" on non-nearby lists mid-search.
  const [resultsNearby, setResultsNearby] = useState(false);
  const [recordsFailed, setRecordsFailed] = useState(false);
  const [suggestionsFailed, setSuggestionsFailed] = useState(false);
  const [auditFailed, setAuditFailed] = useState(false);
  const [digestFailed, setDigestFailed] = useState(false);
  const [progressFailed, setProgressFailed] = useState(false);
  const [jobsFailed, setJobsFailed] = useState(false);
  const [candidatesFailed, setCandidatesFailed] = useState(false);
  const [operatorAuditFailed, setOperatorAuditFailed] = useState(false);
  const [topicsFailed, setTopicsFailed] = useState(false);
  const [operatorLoading, setOperatorLoading] = useState(true);
  const [filters, setFilters] = useState<DiscoverFilters>(initialFilters);
  // FIND-01: draft Discover filters for inputs; `filters` is last-successful (pager / Retry honesty).
  const [draftFilters, setDraftFilters] = useState<DiscoverFilters>(initialFilters);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Course | null>(null);
  const [opening, setOpening] = useState(false);
  const [edit, setEdit] = useState<RecordData>(emptyRecord);
  const [saving, setSaving] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [jobQuery, setJobQuery] = useState('GP CPD courses Kuala Lumpur');
  const [submitting, setSubmitting] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionsCity, setSuggestionsCity] = useState<string | null>(null);
  const [digestOptIn, setDigestOptIn] = useState(false);
  const [digestBusy, setDigestBusy] = useState(false);
  const [certBusy, setCertBusy] = useState(false);
  const [year, setYear] = useState(() => calendarYearLocal());
  const [jobMaxResults, setJobMaxResults] = useState(5);
  const [jobTotal, setJobTotal] = useState(0);
  const [jobPage, setJobPage] = useState(1);
  const [jobStatus, setJobStatus] = useState('');
  const [jobFilterOptions, setJobFilterOptions] = useState<Job[]>([]);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [candidatePage, setCandidatePage] = useState(1);
  const [candidateStatus, setCandidateStatus] = useState('awaiting');
  const [candidateJobId, setCandidateJobId] = useState('');
  const [audits, setAudits] = useState<AuditItem[]>([]);
  const [operatorAudits, setOperatorAudits] = useState<AuditItem[]>([]);
  const [topics, setTopics] = useState<{ query: string; max_results: number }[]>([]);
  const [scrapeCeiling, setScrapeCeiling] = useState<number | null>(null);
  const [scrapeDay, setScrapeDay] = useState('');
  const [forceScrape, setForceScrape] = useState(false);
  const [scrapeResult, setScrapeResult] = useState<{
    enqueued: number;
    skipped: number;
    day: string;
    ceiling: number;
    topics: number;
  } | null>(null);
  const [digestResult, setDigestResult] = useState<{ sent: number; failed: number; day: string } | null>(null);
  const [learning, setLearning] = useState<LearningFilters>({ signupStatus: '', attended: '', page: 1 });
  // FIND-01: draft My learning filters; `learning` is last-successful (parity with /live loadLearning).
  const [draftLearning, setDraftLearning] = useState<LearningFilters>({
    signupStatus: '',
    attended: '',
    page: 1,
  });
  const [recordsTotal, setRecordsTotal] = useState(0);
  const jobKey = useRef('');
  const retryRef = useRef<(() => void) | null>(null);
  const operatorBoot = useRef(true);
  const progressRequest = useRef(0);
  const learningRequest = useRef(0);
  const catalogueRequest = useRef(0);
  const operatorRequest = useRef(0);
  const detailRequest = useRef(0);
  // Pending Discover / My learning attempts so Retry re-issues the failed filter set (parity with /live pendingSearch).
  const pendingDiscover = useRef<DiscoverFilters | null>(null);
  const pendingLearning = useRef<LearningFilters | null>(null);
  // Shared saving flag (detail / profile / ingestion): generation so a stale finally cannot clear a newer busy state.
  const savingGen = useRef(0);
  const userRef = useRef(user);
  userRef.current = user;

  function beginSaving() {
    const gen = ++savingGen.current;
    setSaving(true);
    return gen;
  }

  function endSaving(gen: number) {
    if (savingGen.current === gen) setSaving(false);
  }

  function fail(err: unknown, retry: () => void) {
    // After logout, ignore in-flight workspace failures so they cannot paint on the sign-in gate.
    if (!userRef.current) {
      retryRef.current = null;
      return;
    }
    setError((err as Error).message);
    retryRef.current = retry;
  }

  useEffect(() => {
    Promise.all([
      api('/config').then((c) => {
        setDemo(c.demo);
        setSignup(c.signup_enabled);
        setOauth(!!c.oauth_google);
      }),
      api('/me').then(setUser).catch(() => {}),
    ]).finally(() => setBooting(false));
  }, []);

  const refreshRecords = useCallback(async (opts?: {
    page?: number;
    pageOnly?: boolean;
    filters?: LearningFilters;
  }) => {
    const learningId = ++learningRequest.current;
    const request = opts?.pageOnly
      ? { ...learning, page: opts.page ?? learning.page }
      : { ...(opts?.filters ?? draftLearning), page: opts?.page ?? (opts?.filters ?? draftLearning).page };
    pendingLearning.current = request;
    const page = request.page;
    const params = new URLSearchParams({
      page: String(page),
      page_size: '9',
    });
    if (request.signupStatus) params.set('signup_status', request.signupStatus);
    if (request.attended) params.set('attendance_status', request.attended);
    setRecordsLoading(true);
    try {
      try {
        const r = await api('/me/trainings?' + params);
        if (learningRequest.current === learningId) {
          setRecords(r.items);
          setRecordsTotal(r.total || 0);
          setRecordsFailed(false);
          // FIND-01: commit My learning filters/page only after a successful load (parity with /live).
          // Do not rewrite draftLearning here — a new object would re-trigger the draft effect.
          setLearning(request);
          pendingLearning.current = null;
        }
      } catch (e) {
        if (learningRequest.current === learningId) {
          setRecordsFailed(true);
          fail(e, () => {
            refreshRecords({ filters: request }).catch((err) =>
              fail(err, () => refreshRecords({ filters: request })),
            );
          });
        }
      }
      // Year / learning filter changes bump learningRequest; a stale refresh must not re-bump
      // progressRequest or it can apply an older year after a newer year change (stuck …).
      if (learningRequest.current !== learningId) return;
      const requestId = ++progressRequest.current;
      const requestedYear = year;
      try {
        const next = await api('/me/progress?year=' + requestedYear);
        // Discard out-of-order years even if request ids race (UI-01 / PROG-01 honesty).
        if (progressRequest.current === requestId && next?.year === requestedYear) {
          setProgress(next);
          setProgressFailed(false);
        }
      } catch {
        if (progressRequest.current === requestId) {
          setProgress(null);
          setProgressFailed(true);
        }
      }
      const [digestRes, suggestionsRes, auditRes] = await Promise.all([
        api('/me/digest')
          .then((d) => ({ ok: true as const, d }))
          .catch((e) => ({ ok: false as const, e })),
        api('/me/suggestions')
          .then((d) => ({ ok: true as const, d }))
          .catch((e) => ({ ok: false as const, e })),
        api('/me/audit?page=1&page_size=8')
          .then((d) => ({ ok: true as const, d }))
          .catch((e) => ({ ok: false as const, e })),
      ]);
      if (learningRequest.current !== learningId) return;
      if (digestRes.ok) {
        setDigestOptIn(!!digestRes.d.opted_in);
        setDigestFailed(false);
      } else {
        setDigestFailed(true);
      }
      if (suggestionsRes.ok) {
        setSuggestions(suggestionsRes.d.items || []);
        setSuggestionsCity(typeof suggestionsRes.d.city === 'string' ? suggestionsRes.d.city : null);
        setSuggestionsFailed(false);
      } else {
        setSuggestionsFailed(true);
      }
      if (auditRes.ok) {
        setAudits(auditRes.d.items || []);
        setAuditFailed(false);
      } else {
        setAuditFailed(true);
      }
    } finally {
      if (learningRequest.current === learningId) setRecordsLoading(false);
    }
  }, [year, learning, draftLearning]);

  const loadCourses = useCallback(async (opts?: {
    page?: number;
    pageOnly?: boolean;
    filters?: DiscoverFilters;
  }) => {
    const requestId = ++catalogueRequest.current;
    const request = opts?.pageOnly
      ? { ...filters, page: opts.page ?? filters.page }
      : { ...(opts?.filters ?? draftFilters), page: opts?.page ?? (opts?.filters ?? draftFilters).page };
    pendingDiscover.current = request;
    setCoursesLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        q: request.q,
        city: request.city,
        state: request.state,
        mode: request.mode,
        difficulty: request.difficulty,
        period: request.period,
        page: String(request.page),
        page_size: '9',
        include_unknown: String(request.includeUnknown),
      });
      if (request.maxFee) params.set('max_fee_myr', request.maxFee);
      if (request.minPoints) params.set('min_points', request.minPoints);
      if (request.dateFrom) params.set('date_from', request.dateFrom);
      if (request.dateTo) params.set('date_to', request.dateTo);
      if (request.location) {
        params.set('latitude', String(request.location.latitude));
        params.set('longitude', String(request.location.longitude));
        params.set('radius_km', request.radius);
      }
      const data = await api('/trainings?' + params);
      if (catalogueRequest.current !== requestId) return;
      setCourses(data.items);
      setTotal(data.total);
      setResultsNearby(!!request.location);
      setCoursesFailed(false);
      // FIND-01: commit Discover filters/page only after a successful load (parity with /live appliedSearch).
      // Do not rewrite draftFilters here — a new object would re-trigger the draft debounce effect.
      setFilters(request);
      pendingDiscover.current = null;
    } catch (e) {
      if (catalogueRequest.current !== requestId) return;
      setCoursesFailed(true);
      fail(e, () => {
        loadCourses({ filters: request });
      });
    } finally {
      if (catalogueRequest.current === requestId) setCoursesLoading(false);
    }
  }, [filters, draftFilters]);

  useEffect(() => {
    if (user) refreshRecords().catch((e) => fail(e, () => refreshRecords()));
  }, [user, draftLearning, year]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: draft filter changes reload records

  useEffect(() => {
    if (!user) return;
    const timer = setTimeout(() => {
      loadCourses().catch((e) => fail(e, () => loadCourses()));
    }, 250);
    return () => clearTimeout(timer);
  }, [user, draftFilters]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: draft filter debounce

  const refreshOperator = useCallback(async (overrides?: {
    candidateStatus?: string;
    candidateJobId?: string;
    candidatePage?: number;
    jobStatus?: string;
    jobPage?: number;
  }) => {
    const requestId = ++operatorRequest.current;
    if (operatorBoot.current) setOperatorLoading(true);
    const statusFilter = overrides?.candidateStatus ?? candidateStatus;
    const jobFilter = overrides?.candidateJobId ?? candidateJobId;
    const jobStatusFilter = overrides?.jobStatus ?? jobStatus;
    let firstError: Error | null = null;
    try {
      const jobsResult = await Promise.allSettled([
        (async () => {
          let currentJobPage = overrides?.jobPage ?? jobPage;
          while (true) {
            const jobParams = new URLSearchParams({
              page: String(currentJobPage),
              page_size: '20',
            });
            if (jobStatusFilter) jobParams.set('status', jobStatusFilter);
            const jobList = await api('/admin/ingestion-jobs?' + jobParams);
            if (operatorRequest.current !== requestId) return null;
            const totalJobs = jobList.total || 0;
            const jobPageCount = Math.max(1, Math.ceil(totalJobs / 20));
            if (currentJobPage > jobPageCount) {
              currentJobPage = jobPageCount;
              continue;
            }
            return { items: jobList.items || [], total: totalJobs, page: currentJobPage };
          }
        })(),
      ]).then((rows) => rows[0]);
      if (operatorRequest.current !== requestId) return;
      if (jobsResult.status === 'fulfilled' && jobsResult.value) {
        setJobs(jobsResult.value.items);
        setJobTotal(jobsResult.value.total);
        setJobPage(jobsResult.value.page);
        // Commit job status filter only after a successful jobs load (parity with candidates).
        if (overrides?.jobStatus !== undefined) setJobStatus(overrides.jobStatus);
        setJobsFailed(false);
      } else if (jobsResult.status === 'rejected') {
        setJobsFailed(true);
        firstError =
          jobsResult.reason instanceof Error ? jobsResult.reason : new Error(String(jobsResult.reason));
      }
      try {
        // Candidate job filter needs jobs beyond the paginated discovery-jobs page (and across status filters).
        const filterList = await api('/admin/ingestion-jobs?page=1&page_size=50');
        if (operatorRequest.current !== requestId) return;
        setJobFilterOptions(filterList.items || []);
      } catch {
        // Keep last filter options; discovery-jobs failure is already surfaced above.
      }
      try {
        let current = overrides?.candidatePage ?? candidatePage;
        while (true) {
          const params = new URLSearchParams({
            page: String(current),
            page_size: '20',
            status: statusFilter,
          });
          if (jobFilter) params.set('job_id', jobFilter);
          const c = await api('/admin/candidates?' + params);
          if (operatorRequest.current !== requestId) return;
          const total = c.total || 0;
          const pageCount = Math.max(1, Math.ceil(total / 20));
          if (current > pageCount) {
            current = pageCount;
            continue;
          }
          setCandidates(c.items || []);
          setCandidateTotal(total);
          setCandidatePage(current);
          // Commit status/job filters only after a successful candidate load.
          if (overrides?.candidateStatus !== undefined) setCandidateStatus(overrides.candidateStatus);
          if (overrides?.candidateJobId !== undefined) setCandidateJobId(overrides.candidateJobId);
          setCandidatesFailed(false);
          break;
        }
      } catch (reason) {
        setCandidatesFailed(true);
        if (!firstError) {
          firstError = reason instanceof Error ? reason : new Error(String(reason));
        }
      }
      try {
        const topicPayload = await api('/admin/scrape-topics');
        if (operatorRequest.current !== requestId) return;
        setTopics(topicPayload.topics || []);
        setScrapeCeiling(topicPayload.ceiling ?? null);
        setScrapeDay(topicPayload.day || '');
        setTopicsFailed(false);
      } catch {
        if (operatorRequest.current === requestId) setTopicsFailed(true);
      }
      try {
        const auditPayload = await api('/admin/audit?page=1&page_size=10');
        if (operatorRequest.current !== requestId) return;
        setOperatorAudits(auditPayload.items || []);
        setOperatorAuditFailed(false);
      } catch {
        if (operatorRequest.current === requestId) setOperatorAuditFailed(true);
      }
      if (firstError) throw firstError;
    } finally {
      if (operatorRequest.current === requestId) {
        operatorBoot.current = false;
        setOperatorLoading(false);
      }
    }
  }, [candidatePage, candidateStatus, candidateJobId, jobPage, jobStatus]);

  useEffect(() => {
    if (user?.role !== 'operator' || tab !== 'Ingestion') return;
    refreshOperator().catch((e) => fail(e, () => refreshOperator()));
    // Candidate/job status filters commit via explicit refreshOperator overrides (not these deps).
    // Per-list failed flags drive IngestionPanel stale banners; interval ignores soft refresh errors.
    const timer = setInterval(() => {
      refreshOperator().catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [user, tab, candidatePage, jobPage, refreshOperator]);

  function navigate(next: WorkspaceTab) {
    setTab(next);
    setNavOpen(false);
    setError('');
    setNotice('');
  }

  async function loadHistory(courseId: string, requestId?: number) {
    // Sequence against detailRequest so a slower prior history cannot paint on a newer course.
    const expected = requestId ?? detailRequest.current;
    try {
      const hist = await api('/me/trainings/' + courseId + '/history');
      if (detailRequest.current !== expected) return;
      setHistory(hist.items || []);
      setHistoryFailed(false);
    } catch {
      if (detailRequest.current !== expected) return;
      setHistory([]);
      setHistoryFailed(true);
    }
  }

  async function openCourse(course: Course) {
    const requestId = ++detailRequest.current;
    setOpening(true);
    setError('');
    // Drop prior course trail immediately so My learning cannot flash the wrong history.
    setHistory([]);
    setHistoryFailed(false);
    try {
      const current = await api('/trainings/' + course.id);
      if (detailRequest.current !== requestId) return;
      setSelected(current);
      setEdit(normalizeRecordEdit(current.record));
      await loadHistory(current.id, requestId);
    } catch (e) {
      if (detailRequest.current !== requestId) return;
      fail(e, () => openCourse(course));
    } finally {
      if (detailRequest.current === requestId) setOpening(false);
    }
  }

  async function saveRecord(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const courseId = selected.id;
    // Capture open generation so await yields cannot close/overwrite a newer detail modal.
    const requestId = detailRequest.current;
    const gen = beginSaving();
    setError('');
    try {
      await api('/me/trainings/' + courseId, { method: 'PUT', body: JSON.stringify(edit) });
      // Persist succeeded — refresh lists even if the modal closed or switched.
      await refreshRecords();
      await loadCourses();
      if (detailRequest.current !== requestId) return;
      setSelected(null);
      setNotice('Training record saved.');
    } catch (e) {
      if (detailRequest.current !== requestId) return;
      const message = (e as Error).message || '';
      // Stale version 409: reload the current record so Retry does not replay last-write losers.
      if (/changed|Reopen|Refresh/i.test(message)) {
        try {
          const current = await api('/trainings/' + courseId);
          if (detailRequest.current !== requestId) return;
          setSelected(current);
          setEdit(normalizeRecordEdit(current.record));
          // REG-01: keep correction history honest while the modal stays open (parity with /live).
          await loadHistory(courseId, requestId);
        } catch {
          /* keep showing the conflict message */
        }
        if (detailRequest.current !== requestId) return;
        fail(e, () => openCourse({ id: courseId } as Course));
      } else {
        fail(e, () => saveRecord({ preventDefault() {} } as FormEvent));
      }
    } finally {
      endSaving(gen);
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!user) return;
    const gen = beginSaving();
    try {
      const saved = await api('/me', {
        method: 'PATCH',
        body: JSON.stringify({
          name: user.name,
          city: user.city,
          state: user.state || '',
          bio: user.bio,
          public_enabled: user.public_enabled,
          latitude: user.latitude ?? null,
          longitude: user.longitude ?? null,
        }),
      });
      setUser(saved);
      setNotice('Profile settings saved.');
    } catch (e) {
      fail(e, () => saveProfile({ preventDefault() {} } as FormEvent));
    } finally {
      endSaving(gen);
    }
  }

  function locate() {
    if (!navigator.geolocation) {
      setError('Location is unavailable. Choose your city instead.');
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => {
        // Draft only — Near me commits after a successful catalogue load (FIND-01 honesty).
        setDraftFilters((f) => ({
          ...f,
          location: { latitude: p.coords.latitude, longitude: p.coords.longitude },
          page: 1,
        }));
      },
      () => setError('Location was not available. You can still search by city.'),
      { timeout: 10000 },
    );
  }

  async function newJob(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError('');
    try {
      if (!jobKey.current) jobKey.current = crypto.randomUUID();
      await api('/admin/ingestion-jobs', {
        method: 'POST',
        headers: { 'Idempotency-Key': jobKey.current },
        body: JSON.stringify({ query: jobQuery, max_results: jobMaxResults }),
      });
      jobKey.current = '';
      // Reset candidate page only after refresh succeeds (pass override; do not pre-commit).
      await refreshOperator({ candidatePage: 1 });
      setNotice('Job queued. The scraper will process it when running.');
    } catch (e) {
      fail(e, () => newJob({ preventDefault() {} } as FormEvent));
    } finally {
      setSubmitting(false);
    }
  }

  async function review(
    id: string,
    action: string,
    reason = '',
    version = 0,
    corrections: Record<string, string> = {},
    evidence: Record<string, string> = {},
  ) {
    const gen = beginSaving();
    try {
      await api('/admin/candidates/' + id + '/review', {
        method: 'POST',
        body: JSON.stringify({ action, reason, version, corrections, evidence }),
      });
      await refreshOperator();
      await loadCourses();
      setNotice(
        action === 'publish'
          ? 'Training published with source evidence.'
          : action === 'hold'
            ? 'Candidate held for later review.'
            : 'Candidate rejected.',
      );
    } catch (e) {
      // Version 409 / stale card: refresh the queue so Retry does not replay the same version.
      const message = (e as Error).message || '';
      if (/changed|refresh|conflict/i.test(message)) {
        await refreshOperator().catch(() => {});
        fail(e, () => refreshOperator());
      } else {
        fail(e, () => review(id, action, reason, version, corrections, evidence));
      }
    } finally {
      endSaving(gen);
    }
  }

  async function retryJob(id: string) {
    const gen = beginSaving();
    setError('');
    try {
      await api('/admin/ingestion-jobs/' + id + '/retry', { method: 'POST' });
      await refreshOperator();
      setNotice('Interrupted job queued again. Paid calls will not repeat until the scraper claims it.');
    } catch (e) {
      fail(e, () => retryJob(id));
    } finally {
      endSaving(gen);
    }
  }

  if (booting) {
    return (
      <div className="boot">
        <Brand />
        <Loader2 className="spin" />
        <p id="main-content">Opening your workspace…</p>
      </div>
    );
  }
  if (!user) return <LoginForm demo={demo} signup={signup} oauth={oauth} onLogin={setUser} />;

  const nav = [
    [LayoutDashboard, 'Overview'],
    [Compass, 'Discover training'],
    [BookOpen, 'My learning'],
    [Eye, 'Public profile'],
  ] as const;

  return (
    <div className="app-shell">
      {navOpen && <button className="nav-shade" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
      <aside className={'sidebar ' + (navOpen ? 'is-open' : '')}>
        <Brand />
        <p className="nav-label">YOUR WORKSPACE</p>
        <nav>
          {nav.map(([Icon, label]) => (
            <button
              key={label}
              className={'nav-item ' + (tab === label ? 'active' : '')}
              aria-current={tab === label ? 'page' : undefined}
              onClick={() => navigate(label)}
            >
              <Icon size={19} />
              {label}
            </button>
          ))}
        </nav>
        {user.role === 'operator' && (
          <>
            <p className="nav-label">MANAGE</p>
            <button
              className={'nav-item ' + (tab === 'Ingestion' ? 'active' : '')}
              aria-current={tab === 'Ingestion' ? 'page' : undefined}
              onClick={() => navigate('Ingestion')}
            >
              <Settings2 size={19} />
              Training sources
            </button>
          </>
        )}
        <div className="sidebar-note">
          <ShieldCheck size={23} />
          <strong>Your learning. Your choice.</strong>
          <p>Your records stay private until you choose to share them.</p>
        </div>
        <div className="account">
          <span className="avatar">{user.name.replace('Dr ', '').slice(0, 1)}</span>
          <div>
            <strong>{user.name}</strong>
            <small>{user.role === 'operator' ? 'Operator' : user.city || 'Malaysia'}</small>
          </div>
          <button
            className="icon-btn"
            aria-label="Sign out"
            onClick={async () => {
              await api('/auth/logout', { method: 'POST' });
              setUser(null);
              // Leave Training sources so the next doctor cannot inherit operator Ingestion chrome.
              setTab('Overview');
              setNavOpen(false);
              setYear(calendarYearLocal());
              setSelected(null);
              setCourses([]);
              setResultsNearby(false);
              setRecords([]);
              setProgress(null);
              setProgressFailed(false);
              setSuggestions([]);
              setSuggestionsCity(null);
              setCandidateStatus('awaiting');
              setCandidateJobId('');
              setJobStatus('');
              setAudits([]);
              setOperatorAudits([]);
              setJobs([]);
              setJobFilterOptions([]);
              setCandidates([]);
              setTopics([]);
              setHistory([]);
              setDigestOptIn(false);
              setEdit(emptyRecord);
              setFilters(initialFilters);
              setDraftFilters(initialFilters);
              setLearning({ signupStatus: '', attended: '', page: 1 });
              setDraftLearning({ signupStatus: '', attended: '', page: 1 });
              pendingDiscover.current = null;
              pendingLearning.current = null;
              setCandidatePage(1);
              setJobPage(1);
              setTotal(0);
              setRecordsTotal(0);
              setCandidateTotal(0);
              setJobTotal(0);
              setScrapeResult(null);
              setDigestResult(null);
              setScrapeCeiling(null);
              setScrapeDay('');
              setForceScrape(false);
              setJobQuery('GP CPD courses Kuala Lumpur');
              setJobMaxResults(5);
              setError('');
              setNotice('');
              setSuggestionsFailed(false);
              setAuditFailed(false);
              setDigestFailed(false);
              setRecordsFailed(false);
              setCoursesFailed(false);
              setJobsFailed(false);
              setCandidatesFailed(false);
              setOperatorAuditFailed(false);
              setTopicsFailed(false);
              setHistoryFailed(false);
              setRecordsLoading(true);
              setCoursesLoading(true);
              // Drop any in-flight Retry so the next account cannot replay a prior cancel/review.
              retryRef.current = null;
              // Reset boot so the next operator session shows Loading… instead of a false empty queue.
              operatorBoot.current = true;
              setOperatorLoading(true);
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button className="mobile-menu icon-btn" aria-label="Open navigation" onClick={() => setNavOpen(!navOpen)}>
            <Menu />
          </button>
          <div className="breadcrumbs">
            Workspace <ChevronRight size={14} /> <strong>{tab}</strong>
          </div>
          <span className="region">
            <MapPin size={14} /> Malaysia
          </span>
        </header>
        <div className="content" id="main-content">
          {demo && (
            <div className="demo-banner">
              <span className="badge">DEMO</span> Example courses are fictional. Live discovery needs configured Tavily
              and model credentials.
            </div>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button
                className="text-btn"
                type="button"
                onClick={() => {
                  const action = retryRef.current;
                  retryRef.current = null;
                  if (action) action();
                }}
              >
                Retry
              </button>
              <button className="icon-btn" aria-label="Dismiss error" onClick={() => setError('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              <CheckCircle2 size={18} />
              {notice}
              <button className="icon-btn" aria-label="Dismiss notification" onClick={() => setNotice('')}>
                <X size={16} />
              </button>
            </div>
          )}
          {opening && (
            <p className="alert" role="status" aria-busy="true">
              Opening training details…
            </p>
          )}
          {tab === 'Overview' && (
            <OverviewPanel
              progress={progress}
              year={year}
              courses={courses}
              suggestions={suggestions}
              suggestionsCity={suggestionsCity}
              digestOptIn={digestOptIn}
              digestBusy={digestBusy}
              digestFailed={digestFailed}
              progressFailed={progressFailed}
              certBusy={certBusy}
              loading={recordsLoading}
              coursesLoading={coursesLoading}
              coursesFailed={coursesFailed}
              suggestionsFailed={suggestionsFailed}
              auditFailed={auditFailed}
              audits={audits}
              onDiscover={() => navigate('Discover training')}
              onLearning={() => navigate('My learning')}
              onOpen={openCourse}
              onYear={(next) => {
                progressRequest.current += 1;
                setProgress(null);
                setProgressFailed(false);
                setYear(next);
              }}
              onRetrySuggestions={() => refreshRecords().catch((e) => fail(e, () => refreshRecords()))}
              onRetryAudit={() => refreshRecords().catch((e) => fail(e, () => refreshRecords()))}
              onRetryDigest={() => refreshRecords().catch((e) => fail(e, () => refreshRecords()))}
              onRetryProgress={() => refreshRecords().catch((e) => fail(e, () => refreshRecords()))}
              onRetryCourses={() => loadCourses().catch((e) => fail(e, () => loadCourses()))}
              onToggleDigest={async (next) => {
                setDigestBusy(true);
                setError('');
                try {
                  // Omit cadence_days so a stored NTF-01 preference (e.g. 30) is not wiped to 14.
                  const d = await api('/me/digest', {
                    method: 'PATCH',
                    body: JSON.stringify({ opted_in: next }),
                  });
                  setDigestOptIn(!!d.opted_in);
                  setNotice(d.opted_in ? 'Biweekly digest enabled.' : 'Digest emails turned off.');
                } catch (e) {
                  fail(e, () => refreshRecords());
                } finally {
                  setDigestBusy(false);
                }
              }}
              onIssueCertificate={async () => {
                setCertBusy(true);
                setError('');
                try {
                  const cert = await api('/me/certificates', {
                    method: 'POST',
                    body: JSON.stringify({ year }),
                  });
                  window.open('/api/v1/me/certificates/' + cert.id, '_blank', 'noopener');
                  setNotice('Affiliation certificate ready to print. It is not a regulator document.');
                } catch (e) {
                  fail(e, () => refreshRecords());
                } finally {
                  setCertBusy(false);
                }
              }}
            />
          )}
          {(tab === 'Discover training' || tab === 'My learning') && (
            <DiscoverPanel
              tab={tab}
              filters={{ ...draftFilters, page: filters.page }}
              courses={courses}
              records={records}
              total={total}
              loading={tab === 'My learning' ? recordsLoading : coursesLoading}
              failed={tab === 'My learning' ? recordsFailed : coursesFailed}
              resultsNearby={tab === 'Discover training' ? resultsNearby : false}
              learning={{ ...draftLearning, page: learning.page }}
              recordsTotal={recordsTotal}
              year={year}
              onFilters={(patch) => setDraftFilters((f) => ({ ...f, ...patch, page: 1 }))}
              onLocate={locate}
              onDiscover={() => navigate('Discover training')}
              onOpen={openCourse}
              onClearFilters={() => setDraftFilters(initialFilters)}
              onLearningFilters={(patch) => setDraftLearning((f) => ({ ...f, ...patch, page: 1 }))}
              onPage={(page) =>
                loadCourses({ page, pageOnly: true }).catch((e) =>
                  fail(e, () => loadCourses({ page, pageOnly: true })),
                )
              }
              onLearningPage={(page) =>
                refreshRecords({ page, pageOnly: true }).catch((e) =>
                  fail(e, () => refreshRecords({ page, pageOnly: true })),
                )
              }
              onRetry={() => {
                if (tab === 'My learning') {
                  const pending = pendingLearning.current;
                  const retry = pending
                    ? () => refreshRecords({ filters: pending })
                    : () => refreshRecords();
                  retry().catch((e) => fail(e, retry));
                } else {
                  const pending = pendingDiscover.current;
                  const retry = pending
                    ? () => loadCourses({ filters: pending })
                    : () => loadCourses();
                  retry().catch((e) => fail(e, retry));
                }
              }}
            />
          )}
          {tab === 'Public profile' && (
            <ProfilePanel
              user={user}
              saving={saving}
              onUser={setUser}
              onSave={saveProfile}
              onLocateError={(message) => fail(new Error(message), locate)}
            />
          )}
          {tab === 'Ingestion' && user.role === 'operator' && (
            <IngestionPanel
              jobQuery={jobQuery}
              jobMaxResults={jobMaxResults}
              jobs={jobs}
              jobPage={jobPage}
              jobTotal={jobTotal}
              jobStatus={jobStatus}
              jobFilterOptions={jobFilterOptions}
              candidates={candidates}
              candidatePage={candidatePage}
              candidateTotal={candidateTotal}
              candidateStatus={candidateStatus}
              candidateJobId={candidateJobId}
              submitting={submitting}
              saving={saving}
              jobKey={jobKey}
              onJobQuery={setJobQuery}
              onJobMaxResults={setJobMaxResults}
              onSubmit={newJob}
              onRefresh={() => refreshOperator().catch((e) => fail(e, () => refreshOperator()))}
              onRetry={retryJob}
              onReview={review}
              onJobPage={(page) => {
                // Commit job page only after a successful jobs load (parity with status filters / /live).
                refreshOperator({ jobPage: page }).catch((e) =>
                  fail(e, () => refreshOperator({ jobPage: page })),
                );
              }}
              onJobStatus={(value) => {
                refreshOperator({ jobStatus: value, jobPage: 1 }).catch((e) =>
                  fail(e, () => refreshOperator({ jobStatus: value, jobPage: 1 })),
                );
              }}
              onCandidatePage={(page) => {
                // Commit candidate page only after a successful load (parity with status filters / /live).
                refreshOperator({ candidatePage: page }).catch((e) =>
                  fail(e, () => refreshOperator({ candidatePage: page })),
                );
              }}
              onCandidateStatus={(value) => {
                refreshOperator({ candidateStatus: value, candidatePage: 1 }).catch((e) =>
                  fail(e, () => refreshOperator({ candidateStatus: value, candidatePage: 1 })),
                );
              }}
              onCandidateJobId={(value) => {
                refreshOperator({ candidateJobId: value, candidatePage: 1 }).catch((e) =>
                  fail(e, () => refreshOperator({ candidateJobId: value, candidatePage: 1 })),
                );
              }}
              loading={operatorLoading}
              jobsFailed={jobsFailed}
              candidatesFailed={candidatesFailed}
              auditFailed={operatorAuditFailed}
              topicsFailed={topicsFailed}
              topics={topics}
              ceiling={scrapeCeiling}
              scrapeDay={scrapeDay}
              forceScrape={forceScrape}
              onForceScrape={setForceScrape}
              scrapeResult={scrapeResult}
              digestResult={digestResult}
              audits={operatorAudits}
              onDailyScrape={async () => {
                const gen = beginSaving();
                setError('');
                try {
                  const result = await api('/admin/daily-scrape?force=' + String(forceScrape), { method: 'POST' });
                  setScrapeResult(result);
                  await refreshOperator();
                  setNotice(
                    `Daily scrape ${result.day}: ${result.enqueued} queued, ${result.skipped} skipped (ceiling ${result.ceiling}).`,
                  );
                } catch (e) {
                  fail(e, () => refreshOperator());
                } finally {
                  endSaving(gen);
                }
              }}
              onRunDigests={async () => {
                const gen = beginSaving();
                setError('');
                try {
                  const result = await api('/admin/digests/run', { method: 'POST' });
                  setDigestResult(result);
                  setNotice(
                    `Digest ${result.day}: ${result.sent} sent, ${result.failed} failed. No Tavily call.`,
                  );
                } catch (e) {
                  fail(e, () => refreshOperator());
                } finally {
                  endSaving(gen);
                }
              }}
            />
          )}
          <footer>
            CareCredits <span>Built around your professional growth.</span>
            <small>Training and points are not independently accredited by CareCredits.</small>
          </footer>
        </div>
      </main>
      {selected && (
        <TrainingDetail
          course={selected}
          edit={edit}
          error={error}
          saving={saving}
          history={history}
          historyFailed={historyFailed}
          onClose={() => {
            // Bump detailRequest so an in-flight history fetch cannot repaint after close.
            detailRequest.current += 1;
            setHistory([]);
            setHistoryFailed(false);
            setSelected(null);
          }}
          onEdit={setEdit}
          onSave={saveRecord}
          onRetryHistory={() => loadHistory(selected.id, detailRequest.current)}
          onRetryError={() => {
            const action = retryRef.current;
            retryRef.current = null;
            if (action) action();
            else void loadCourses().catch((e) => fail(e, () => loadCourses()));
          }}
          canCancel={user?.role === 'operator'}
          onCancel={async () => {
            const courseId = selected.id;
            const requestId = detailRequest.current;
            const runCancel = async () => {
              const gen = beginSaving();
              setError('');
              retryRef.current = null;
              try {
                await api('/admin/trainings/' + courseId + '/cancel', { method: 'POST' });
                // Cancel persisted — refresh catalogue even if the modal closed or switched.
                await loadCourses();
                if (detailRequest.current !== requestId) return;
                setSelected(null);
                setNotice('Session cancelled. Personal records were kept.');
              } catch (e) {
                if (detailRequest.current !== requestId) return;
                fail(e, () => {
                  void runCancel();
                });
              } finally {
                endSaving(gen);
              }
            };
            await runCancel();
          }}
        />
      )}
    </div>
  );
}
