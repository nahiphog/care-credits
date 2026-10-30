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
import { LiveIngestion } from '@/components/LiveIngestion';
import { TrainingDetail } from '@/components/TrainingDetail';
import { PasswordSettings } from '@/components/PasswordSettings';
import {
  api,
  ApiError,
  AuditItem,
  calendarYearLocal,
  Course,
  emptyRecord,
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
  period: 'all',
  dateFrom: '',
  dateTo: '',
  includeUnknown: false,
  radius: '25',
  location: null,
  page: 1,
};

export default function Home() {
  const [user, setUser] = useState<User | null>(null);
  const [profileDraft, setProfileDraft] = useState<User | null>(null);
  const [bootstrapError, setBootstrapError] = useState('');
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [digestAvailable, setDigestAvailable] = useState(false);
  const [booting, setBooting] = useState(true);
  const [demo, setDemo] = useState(false);
  const [signup, setSignup] = useState(false);
  const [oauth, setOauth] = useState(false);
  const [history, setHistory] = useState<import('@/lib/portal').RecordHistoryItem[]>([]);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [tab, setTab] = useState<WorkspaceTab>('Overview');
  const [navOpen, setNavOpen] = useState(false);
  const [mobile, setMobile] = useState(false);
  const navRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const match = window.matchMedia('(max-width: 850px)');
    const update = () => setMobile(match.matches);
    update(); match.addEventListener('change', update);
    return () => match.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (!mobile || !navOpen) return;
    const previous = document.body.style.overflow; document.body.style.overflow = 'hidden';
    navRef.current?.querySelector<HTMLElement>('button')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setNavOpen(false); menuRef.current?.focus(); }
      if (event.key !== 'Tab') return;
      const nodes = Array.from(navRef.current?.querySelectorAll<HTMLElement>('button,a[href]') || []);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', key);
    return () => { document.body.style.overflow = previous; document.removeEventListener('keydown', key); };
  }, [mobile, navOpen]);
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
  const [filters, setFilters] = useState<DiscoverFilters>(initialFilters);
  // FIND-01: draft Discover filters for inputs; `filters` is last-successful (pager / Retry honesty).
  const [draftFilters, setDraftFilters] = useState<DiscoverFilters>(initialFilters);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Course | null>(null);
  const [opening, setOpening] = useState(false);
  const [edit, setEdit] = useState<RecordData>(emptyRecord);
  const [saving, setSaving] = useState(false);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [suggestionsCity, setSuggestionsCity] = useState<string | null>(null);
  const [digestOptIn, setDigestOptIn] = useState(false);
  const [digestBusy, setDigestBusy] = useState(false);
  const [year, setYear] = useState(() => calendarYearLocal());
  const [audits, setAudits] = useState<AuditItem[]>([]);
  const [learning, setLearning] = useState<LearningFilters>({ signupStatus: '', attended: '', page: 1 });
  // FIND-01: draft My learning filters; `learning` is last-successful (parity with /live loadLearning).
  const [draftLearning, setDraftLearning] = useState<LearningFilters>({
    signupStatus: '',
    attended: '',
    page: 1,
  });
  const [recordsTotal, setRecordsTotal] = useState(0);
  const retryRef = useRef<(() => void) | null>(null);
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
  useEffect(() => { userRef.current = user; }, [user]);

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
        setDemo(c.demo); setDigestAvailable(!!c.digest_available);
        setSignup(c.signup_enabled);
        setOauth(!!c.oauth_google);
      }),
      api('/me').then((account) => { setUser(account); setProfileDraft((draft) => draft?.id === account.id ? draft : account); }).catch((error) => { if (!(error instanceof ApiError && error.status === 401)) throw error; }),
    ]).catch((error) => setBootstrapError(error.message || 'CareCredits could not be reached.')).finally(() => setBooting(false));
  }, [bootstrapAttempt]);
  useEffect(() => {
    const expired = (event: Event) => {
      if (!userRef.current) return;
      userRef.current = null;
      ++catalogueRequest.current; ++learningRequest.current; ++progressRequest.current; ++detailRequest.current; ++operatorRequest.current; ++savingGen.current;
      setUser(null); setSelected(null); setCourses([]); setRecords([]); setProgress(null); setSuggestions([]); setAudits([]);
      setError((event as CustomEvent<string>).detail || 'Your session has expired. Please sign in again.');
    };
    window.addEventListener('carecredits:session-expired', expired);
    return () => window.removeEventListener('carecredits:session-expired', expired);
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
  }, [user?.id, draftLearning, year]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: draft filter changes reload records

  useEffect(() => {
    if (!user) return;
    const timer = setTimeout(() => {
      loadCourses().catch((e) => fail(e, () => loadCourses()));
    }, 250);
    return () => clearTimeout(timer);
  }, [user?.id, draftFilters]); // eslint-disable-line react-hooks/exhaustive-deps -- intentional: draft filter debounce

  useEffect(() => { if (!user?.id) return; document.getElementById('main-content')?.focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: 'instant' }); }, [tab, user?.id]);

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
    if (!user || !profileDraft) return;
    const owner = user.id;
    const gen = beginSaving();
    try {
      const saved = await api('/me', {
        method: 'PATCH',
        body: JSON.stringify({
          name: profileDraft.name,
          city: profileDraft.city,
          state: profileDraft.state || '',
          bio: profileDraft.bio,
          public_enabled: profileDraft.public_enabled,
          latitude: profileDraft.latitude ?? null,
          longitude: profileDraft.longitude ?? null,
        }),
      });
      if (userRef.current?.id !== owner) return;
      setUser(saved); setProfileDraft(saved);
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

  if (booting) {
    return (
      <div className="boot">
        <Brand /><button className="mobile-menu icon-btn" aria-label="Close navigation" onClick={() => { setNavOpen(false); menuRef.current?.focus(); }}><X /></button>
        <Loader2 className="spin" />
        <p id="main-content">Opening your workspace…</p>
      </div>
    );
  }
  if (bootstrapError) return <main className="public-page"><section role="alert"><h1>CareCredits is unavailable</h1><p>{bootstrapError}</p><button onClick={() => { setBooting(true); setBootstrapError(''); setBootstrapAttempt((value) => value + 1); }}>Try again</button></section></main>;
  if (!user) return <>{error && <p role="alert" className="alert error">{error}</p>}<LoginForm demo={demo} signup={signup} oauth={oauth} onLogin={(account) => { setError(''); setUser(account); setProfileDraft((draft) => draft?.id === account.id ? draft : account); }} /></>;

  const nav = [
    [LayoutDashboard, 'Overview'],
    [Compass, 'Discover training'],
    [BookOpen, 'My learning'],
    [Eye, 'Public profile'],
  ] as const;

  return (
    <div className="app-shell workspace-shell">
      {navOpen && <button className="nav-shade" aria-label="Close navigation" onClick={() => setNavOpen(false)} />}
      <aside ref={navRef} id="workspace-navigation" inert={mobile && !navOpen} className={'sidebar ' + (navOpen ? 'is-open' : '')}>
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
              try { await api('/auth/logout', { method: 'POST' }); } catch (error) { setError((error as Error).message); return; }
              userRef.current = null;
              ++catalogueRequest.current; ++learningRequest.current; ++progressRequest.current; ++detailRequest.current; ++operatorRequest.current; ++savingGen.current;
              setProfileDraft(null);
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
              setAudits([]);
              setHistory([]);
              setDigestOptIn(false);
              setEdit(emptyRecord);
              setFilters(initialFilters);
              setDraftFilters(initialFilters);
              setLearning({ signupStatus: '', attended: '', page: 1 });
              setDraftLearning({ signupStatus: '', attended: '', page: 1 });
              pendingDiscover.current = null;
              pendingLearning.current = null;
              setTotal(0);
              setRecordsTotal(0);
              setError('');
              setNotice('');
              setSuggestionsFailed(false);
              setAuditFailed(false);
              setDigestFailed(false);
              setRecordsFailed(false);
              setCoursesFailed(false);
              setHistoryFailed(false);
              setRecordsLoading(true);
              setCoursesLoading(true);
              // Drop any in-flight Retry so the next account cannot replay a prior cancel/review.
              retryRef.current = null;
              // Reset boot so the next operator session shows Loading… instead of a false empty queue.
            }}
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main className="main" inert={mobile && navOpen}>
        <header className="topbar">
          <button ref={menuRef} className="mobile-menu icon-btn" aria-controls="workspace-navigation" aria-expanded={navOpen} aria-label="Open navigation" onClick={() => setNavOpen(!navOpen)}>
            <Menu />
          </button>
          <div className="breadcrumbs">
            Workspace <ChevronRight size={14} /> <strong>{tab}</strong>
          </div>
          <span className="region">
            <MapPin size={14} /> Malaysia
          </span>
        </header>
        <div className="content" id="main-content" tabIndex={-1}>
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
              digestAvailable={digestAvailable}
              digestOptIn={digestOptIn}
              digestBusy={digestBusy}
              digestFailed={digestFailed}
              progressFailed={progressFailed}
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
            <> <ProfilePanel
              user={profileDraft || user}
              saving={saving}
              onUser={setProfileDraft}
              onSave={saveProfile}
              onLocateError={(message) => fail(new Error(message), locate)}
            /><PasswordSettings /></>
          )}
          {tab === 'Ingestion' && user.role === 'operator' && (
            <LiveIngestion onPublished={async () => { await Promise.all([loadCourses(), refreshRecords()]); }} />
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
