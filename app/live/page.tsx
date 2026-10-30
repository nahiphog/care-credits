'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { FormEvent, useEffect, useEffectEvent, useRef, useState } from 'react';
import {
  BookOpen,
  CalendarDays,
  ChevronRight,
  Compass,
  FileText,
  LayoutDashboard,
  Loader2,
  LogOut,
  Menu,
  Search,
  Settings,
  ShieldCheck,
  X,
} from 'lucide-react';
import { TrainingDetail } from '@/components/TrainingDetail';
import { PasswordSettings } from '@/components/PasswordSettings';
import { LiveIngestion } from '@/components/LiveIngestion';
import { CertificatePanel } from '@/components/CertificatePanel';
import { DateChip } from '@/components/CourseList';
import { dashboardPageFromPath, dashboardPaths, dashboardReturnPath, loginPath, loginPathFor, type DashboardPage } from '@/lib/dashboard-navigation';
import { api, ApiError, activityLabel, AuditItem, calendarYearLocal, Course, distanceLabel, emptyRecord, formatDate, locationLabel, normalizeRecordEdit, Progress, RecordData, RecordHistoryItem, User } from '@/lib/portal';

const PAGE_SIZE = 12;

function excludedCopy(progress: Progress | null) {
  if (!progress?.excluded) return '';
  const reasons = progress.excluded_reasons?.length
    ? ': ' +
      progress.excluded_reasons
        .map((item) => (item.reason === 'unknown_points' ? 'unknown points' : item.credit_label || 'other credit type'))
        .join(', ')
    : ' (unknown or other credit types)';
  return `${progress.excluded} attended record(s) excluded${reasons}.`;
}

const nav = [
  [LayoutDashboard, 'Overview'],
  [BookOpen, 'My Credits'],
  [Compass, 'Discover'],
  [CalendarDays, 'Events'],
  [FileText, 'Certificates'],
  [ShieldCheck, 'About credits'],
  [Settings, 'Settings'],
] as const;

function Mark() {
  return (
    <span className="care-mark">
      <i />
      <b />
    </span>
  );
}

function initials(name: string) {
  return name
    .replace(/^Dr\.?\s+/i, '')
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('');
}

export default function LiveSearch() {
  const [user, setUser] = useState<User | null>(null);
  const [profileDraft, setProfileDraft] = useState<User | null>(null);
  const [profileNotice, setProfileNotice] = useState('');
  const [bootstrapError, setBootstrapError] = useState('');
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0);
  const [mobile, setMobile] = useState(false);
  const [geoError, setGeoError] = useState('');
  const [locating, setLocating] = useState(false);
  const geoRequest = useRef(0);
  const [digestAvailable, setDigestAvailable] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [booting, setBooting] = useState(true);
  const [signup, setSignup] = useState(false);
  const [oauth, setOauth] = useState(false);
  const [recovery, setRecovery] = useState(false);
  const [demo, setDemo] = useState(false);
  const [history, setHistory] = useState<RecordHistoryItem[]>([]);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<'register' | 'signin'>('signin');
  const pathname = usePathname();
  const tab = dashboardPageFromPath(pathname);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [query, setQuery] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [deliveryMode, setDeliveryMode] = useState('');
  const [period, setPeriod] = useState('all');
  const [difficulty, setDifficulty] = useState('');
  const [maxFee, setMaxFee] = useState('');
  const [minPoints, setMinPoints] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [includeUnknown, setIncludeUnknown] = useState(false);
  const [radius, setRadius] = useState('25');
  const [page, setPage] = useState(1);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const filterDialogRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (!filtersOpen) return;
    const dialog = filterDialogRef.current;
    if (!dialog) return;
    dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { dialog.close(); document.body.style.overflow = previousOverflow; };
  }, [filtersOpen]);
  const [nearby, setNearby] = useState<{ latitude: number; longitude: number } | null>(null);
  const [year, setYear] = useState(() => calendarYearLocal());
  const [courses, setCourses] = useState<Course[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<Course | null>(null);
  const [edit, setEdit] = useState<RecordData>(emptyRecord);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [searchFailed, setSearchFailed] = useState(false);
  const [learningFailed, setLearningFailed] = useState(false);
  const [digestOptIn, setDigestOptIn] = useState(false);
  const [suggestions, setSuggestions] = useState<
    { id: string; title: string; provider?: string; start_date?: string | null; city?: string | null; mode?: string; reason?: string; points?: number | null }[]
  >([]);
  const [suggestionsCity, setSuggestionsCity] = useState<string | null>(null);
  const [suggestionsBusy, setSuggestionsBusy] = useState(true);
  const [suggestionsFailed, setSuggestionsFailed] = useState(false);
  const [digestBusy, setDigestBusy] = useState(false);
  const [digestFailed, setDigestFailed] = useState(false);
  const [digestPreferenceBusy, setDigestPreferenceBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [locationBusy, setLocationBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [records, setRecords] = useState<Course[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [learningFilter, setLearningFilter] = useState<'all' | 'signed_up' | 'attended'>('all');
  const [learningPage, setLearningPage] = useState(1);
  const [learningBusy, setLearningBusy] = useState(true);
  const [progressBusy, setProgressBusy] = useState(true);
  const [progressFailed, setProgressFailed] = useState(false);
  const [audits, setAudits] = useState<AuditItem[]>([]);
  const [auditBusy, setAuditBusy] = useState(true);
  const [auditFailed, setAuditFailed] = useState(false);
  const progressRequest = useRef(0);
  const learningRequest = useRef(0);
  const catalogueRequest = useRef(0);
  const workspaceRequest = useRef(0);
  const detailRequest = useRef(0);
  // Detail save/cancel busy flag: generation so a stale finally cannot clear a newer busy state.
  const savingGen = useRef(0);
  // When set, page/modal Retry runs this action (cancel). Otherwise Retry reloads the workspace.
  const retryRef = useRef<(() => void) | null>(null);
  const userRef = useRef(user);
  useEffect(() => { userRef.current = user; }, [user]);

  function navigateToTab(next: DashboardPage, replace = false) {
    const path = dashboardPaths[next];
    // Next.js syncs native history changes with usePathname. Keep the shared
    // dashboard mounted so search filters and unsaved profile drafts survive.
    if (window.location.pathname !== path) {
      window.history[replace ? 'replaceState' : 'pushState'](null, '', path);
    }
    setOpen(false);
  }

  function beginSaving() {
    const gen = ++savingGen.current;
    setSaving(true);
    return gen;
  }

  function endSaving(gen: number) {
    if (savingGen.current === gen) setSaving(false);
  }

  function fail(err: unknown, retry?: () => void) {
    // After logout, ignore in-flight workspace failures so they cannot paint on the sign-in gate.
    if (!userRef.current) {
      retryRef.current = null;
      return;
    }
    setError((err as Error).message);
    retryRef.current = retry || null;
  }
  // FIND-01: pager uses last successful Search filters; Retry re-issues a failed attempt via pendingSearch.
  const [applied, setApplied] = useState({
    query: '',
    city: '',
    state: '',
    mode: '',
    period: 'all',
    difficulty: '',
    maxFee: '',
    minPoints: '',
    dateFrom: '',
    dateTo: '',
    includeUnknown: false,
    radius: '25',
    nearby: null as { latitude: number; longitude: number } | null,
  });
  const appliedSearch = useRef(applied);
  // Last in-flight / failed Search (including page turns). Cleared on success so Retry matches the failed request
  // while the pager keeps paging the last successful list when a Search refresh fails.
  const pendingSearch = useRef<{
    query: string;
    city: string;
    state: string;
    mode: string;
    period: string;
    difficulty: string;
    maxFee: string;
    minPoints: string;
    dateFrom: string;
    dateTo: string;
    includeUnknown: boolean;
    radius: string;
    nearby: { latitude: number; longitude: number } | null;
    page: number;
  } | null>(null);
  // My learning: Retry re-issues a failed filter/page attempt (parity with pendingSearch / `/` pendingLearning).
  const pendingLearning = useRef<{
    filter: 'all' | 'signed_up' | 'attended';
    page: number;
  } | null>(null);
  const [resultsNearby, setResultsNearby] = useState(false);
  useEffect(() => {
    const match = window.matchMedia('(max-width: 830px)');
    const update = () => setMobile(match.matches);
    update(); match.addEventListener('change', update);
    return () => match.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    if (!open || !mobile) return;
    const before = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    sidebarRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); menuRef.current?.focus(); }
      if (event.key !== 'Tab') return;
      const nodes = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('button,a[href]') || []);
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', key);
    return () => { document.body.style.overflow = before; document.removeEventListener('keydown', key); };
  }, [open, mobile]);
  useEffect(() => {
    const expired = (event: Event) => {
      if (!userRef.current) return;
      userRef.current = null;
      ++workspaceRequest.current; ++catalogueRequest.current; ++learningRequest.current; ++progressRequest.current; ++detailRequest.current; ++savingGen.current;
      setUser(null); setMode('signin'); setSelected(null); setCourses([]); setRecords([]); setProgress(null); setSuggestions([]); setAudits([]); setOpen(false); setFiltersOpen(false);
      setError((event as CustomEvent<string>).detail || 'Your session has expired. Please sign in again.');
    };
    window.addEventListener('carecredits:session-expired', expired);
    return () => window.removeEventListener('carecredits:session-expired', expired);
  }, []);
  useEffect(() => {
    if (!user?.id) return;
    document.getElementById('page-heading')?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }, [tab, user?.id]);
  function cancelFilters() {
    ++geoRequest.current; setLocating(false);
    const saved = appliedSearch.current;
    setCity(saved.city); setState(saved.state); setDeliveryMode(saved.mode); setPeriod(saved.period);
    setDifficulty(saved.difficulty); setMaxFee(saved.maxFee); setMinPoints(saved.minPoints);
    setDateFrom(saved.dateFrom); setDateTo(saved.dateTo); setIncludeUnknown(saved.includeUnknown);
    setRadius(saved.radius); setNearby(saved.nearby); setGeoError(''); setFiltersOpen(false);
  }


  useEffect(() => {
    Promise.all([
      api('/config').then((c) => {
        setSignup(c.signup_enabled); setDigestAvailable(!!c.digest_available);
        setOauth(!!c.oauth_google);
        setRecovery(!!c.password_recovery_available);
        setDemo(!!c.demo);
        // Mirror LoginForm: only offer register when signup is enabled.
        setMode(c.signup_enabled && !c.demo ? 'register' : 'signin');
        if (c.demo) {
          setEmail((current) => current || 'demo@carecredits.local');
          setPassword((current) => current || 'CareCredits-demo-2026');
        }
      }),
      api('/me')
        .then((account) => { setUser(account); setProfileDraft((draft) => draft?.id === account.id ? draft : account); })
        .catch((error) => { if (!(error instanceof ApiError && error.status === 401)) throw error; }),
    ]).catch((error) => setBootstrapError(error.message || 'CareCredits could not be reached.')).finally(() => setBooting(false));
  }, [bootstrapAttempt]);

  useEffect(() => {
    if (booting || bootstrapError) return;
    // Read the current address so an explicit logout cannot reuse a stale page path.
    const currentPath = window.location.pathname;
    if (!user?.id && currentPath !== loginPath) {
      window.history.replaceState(null, '', loginPathFor(currentPath));
    } else if (user?.id && currentPath === loginPath) {
      const next = new URLSearchParams(window.location.search).get('next');
      window.history.replaceState(null, '', dashboardReturnPath(next));
    }
  }, [booting, bootstrapError, user?.id, pathname]);

  // AUTH-01: Google callback redirects here with oauth=denied|failed; surface the outcome.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const oauthStatus = params.get('oauth');
    const timer = window.setTimeout(() => {
    if (oauthStatus === 'denied') {
      setError('Google sign-in was cancelled or denied. Try again or use email.');
    } else if (oauthStatus === 'failed') {
      setError('Google sign-in failed. Try again or use email.');
    }
    if (oauthStatus === 'denied' || oauthStatus === 'failed') {
      params.delete('oauth');
      const next = params.toString();
      const path = window.location.pathname + (next ? '?' + next : '') + window.location.hash;
      window.history.replaceState({}, '', path);
    }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function search(overrides: {
    query?: string;
    city?: string;
    state?: string;
    mode?: string;
    period?: string;
    difficulty?: string;
    maxFee?: string;
    minPoints?: string;
    dateFrom?: string;
    dateTo?: string;
    includeUnknown?: boolean;
    radius?: string;
    page?: number;
    nearby?: { latitude: number; longitude: number } | null;
    /** Pager/Retry: keep the last committed catalogue filters; ignore draft top-bar edits. */
    pageOnly?: boolean;
  } = {}) {
    const base = overrides.pageOnly ? appliedSearch.current : null;
    const nextQuery = overrides.query ?? (base ? base.query : query);
    const nextCity = overrides.city ?? (base ? base.city : city);
    const nextState = overrides.state ?? (base ? base.state : state);
    const nextMode = overrides.mode ?? (base ? base.mode : deliveryMode);
    const nextPeriod = overrides.period ?? (base ? base.period : period);
    const nextDifficulty = overrides.difficulty ?? (base ? base.difficulty : difficulty);
    const nextMaxFee = overrides.maxFee ?? (base ? base.maxFee : maxFee);
    const nextMinPoints = overrides.minPoints ?? (base ? base.minPoints : minPoints);
    const nextDateFrom = overrides.dateFrom ?? (base ? base.dateFrom : dateFrom);
    const nextDateTo = overrides.dateTo ?? (base ? base.dateTo : dateTo);
    const nextIncludeUnknown = overrides.includeUnknown ?? (base ? base.includeUnknown : includeUnknown);
    const nextRadius = overrides.radius ?? (base ? base.radius : radius);
    const nextPage = overrides.page ?? page;
    const nextNearby =
      overrides.nearby !== undefined ? overrides.nearby : base ? base.nearby : nearby;
    const requestFilters = {
      query: nextQuery,
      city: nextCity,
      state: nextState,
      mode: nextMode,
      period: nextPeriod,
      difficulty: nextDifficulty,
      maxFee: nextMaxFee,
      minPoints: nextMinPoints,
      dateFrom: nextDateFrom,
      dateTo: nextDateTo,
      includeUnknown: nextIncludeUnknown,
      radius: nextRadius,
      nearby: nextNearby,
    };
    // Track the attempt for Retry. Commit appliedSearch only after success so a failed Search
    // cannot make the pager page a different filter set than the stale list on screen.
    pendingSearch.current = { ...requestFilters, page: nextPage };
    const requestId = ++catalogueRequest.current;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        q: nextQuery,
        city: nextCity,
        state: nextState,
        period: nextPeriod,
        page: String(nextPage),
        page_size: String(PAGE_SIZE),
        include_unknown: String(nextIncludeUnknown),
      });
      if (nextMode) params.set('mode', nextMode);
      if (nextDifficulty) params.set('difficulty', nextDifficulty);
      if (nextMaxFee) params.set('max_fee_myr', nextMaxFee);
      if (nextMinPoints) params.set('min_points', nextMinPoints);
      if (nextDateFrom) params.set('date_from', nextDateFrom);
      if (nextDateTo) params.set('date_to', nextDateTo);
      if (nextNearby) {
        params.set('latitude', String(nextNearby.latitude));
        params.set('longitude', String(nextNearby.longitude));
        params.set('radius_km', nextRadius);
      }
      const data = await api('/trainings?' + params);
      if (catalogueRequest.current !== requestId) return;
      setCourses(data.items);
      setTotal(data.total);
      setPage(nextPage);
      appliedSearch.current = requestFilters;
      setApplied(requestFilters);
      pendingSearch.current = null;
      setResultsNearby(!!nextNearby);
      setSearchFailed(false);
    } catch (e) {
      if (catalogueRequest.current !== requestId) return;
      setSearchFailed(true);
      setError((e as Error).message);
    } finally {
      if (catalogueRequest.current === requestId) setLoading(false);
    }
  }

  function retrySearch() {
    const pending = pendingSearch.current;
    if (pending) {
      void search({
        query: pending.query,
        city: pending.city,
        state: pending.state,
        mode: pending.mode,
        period: pending.period,
        difficulty: pending.difficulty,
        maxFee: pending.maxFee,
        minPoints: pending.minPoints,
        dateFrom: pending.dateFrom,
        dateTo: pending.dateTo,
        includeUnknown: pending.includeUnknown,
        radius: pending.radius,
        nearby: pending.nearby,
        page: pending.page,
      });
      return;
    }
    void search({ page, pageOnly: true });
  }
  /** Commit only the last Search filters (+ overrides). Draft top-bar edits stay unapplied. */
  function searchCommitted(
    overrides: {
      query?: string;
      city?: string;
      state?: string;
      mode?: string;
      period?: string;
      difficulty?: string;
      maxFee?: string;
      minPoints?: string;
      dateFrom?: string;
      dateTo?: string;
      includeUnknown?: boolean;
      radius?: string;
      page?: number;
      nearby?: { latitude: number; longitude: number } | null;
    } = {},
  ) {
    const base = appliedSearch.current;
    const next = {
      query: overrides.query ?? base.query,
      city: overrides.city ?? base.city,
      state: overrides.state ?? base.state,
      mode: overrides.mode ?? base.mode,
      period: overrides.period ?? base.period,
      difficulty: overrides.difficulty ?? base.difficulty,
      maxFee: overrides.maxFee ?? base.maxFee,
      minPoints: overrides.minPoints ?? base.minPoints,
      dateFrom: overrides.dateFrom ?? base.dateFrom,
      dateTo: overrides.dateTo ?? base.dateTo,
      includeUnknown: overrides.includeUnknown ?? base.includeUnknown,
      radius: overrides.radius ?? base.radius,
      nearby: overrides.nearby !== undefined ? overrides.nearby : base.nearby,
      page: overrides.page ?? 1,
    };
    // Keep draft controls aligned with what we are committing so pager/Retry stay honest.
    setQuery(next.query);
    setCity(next.city);
    setState(next.state);
    setDeliveryMode(next.mode);
    setPeriod(next.period);
    setDifficulty(next.difficulty);
    setMaxFee(next.maxFee);
    setMinPoints(next.minPoints);
    setDateFrom(next.dateFrom);
    setDateTo(next.dateTo);
    setIncludeUnknown(next.includeUnknown);
    setRadius(next.radius);
    setNearby(next.nearby);
    return search(next);
  }

  async function loadLearning(
    filter: 'all' | 'signed_up' | 'attended' = learningFilter,
    nextPage = filter === learningFilter ? learningPage : 1,
  ) {
    const requestId = ++learningRequest.current;
    // Track the attempt for Retry. Commit filter/page only after success (UI-01 honesty).
    pendingLearning.current = { filter, page: nextPage };
    setLearningBusy(true);
    try {
      const params = new URLSearchParams({ page: String(nextPage), page_size: '12' });
      if (filter === 'signed_up') params.set('signup_status', 'signed_up');
      if (filter === 'attended') params.set('attendance_status', 'attended');
      const data = await api('/me/trainings?' + params);
      if (learningRequest.current !== requestId) return;
      const total = data.total || 0;
      const pageCount = Math.max(1, Math.ceil(total / 12));
      if (nextPage > pageCount) {
        await loadLearning(filter, pageCount);
        return;
      }
      setRecords(data.items || []);
      setRecordsTotal(total);
      setLearningFilter(filter);
      setLearningPage(nextPage);
      setLearningFailed(false);
      pendingLearning.current = null;
    } catch (e) {
      if (learningRequest.current !== requestId) return;
      setLearningFailed(true);
      setError((e as Error).message);
    } finally {
      if (learningRequest.current === requestId) setLearningBusy(false);
    }
  }

  function retryLearning() {
    const pending = pendingLearning.current;
    if (pending) {
      void loadLearning(pending.filter, pending.page);
      return;
    }
    void loadLearning(learningFilter, learningPage);
  }

  async function loadWorkspace(nextCity = appliedSearch.current.city, nextState = appliedSearch.current.state) {
    const workspaceId = ++workspaceRequest.current;
    setLoading(true);
    setSuggestionsBusy(true);
    setLearningBusy(true);
    setProgressBusy(true);
    setAuditBusy(true);
    setDigestPreferenceBusy(true);
    const progressId = ++progressRequest.current;
    const progressYear = year;
    // FIND-01: workspace reload/Retry must reuse committed Search filters — draft top-bar
    // mode/period/etc. must not silently rewrite results (city/state overrides still apply).
    await searchCommitted({ city: nextCity, state: nextState, page: 1 });
    if (workspaceRequest.current !== workspaceId) return;
    setSuggestionsBusy(true);
    try {
      const [progressRes, digestRes, suggestionsRes, auditRes] = await Promise.all([
        api('/me/progress?year=' + progressYear)
          .then((d) => ({ ok: true as const, d }))
          .catch((e) => ({ ok: false as const, e })),
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
      if (workspaceRequest.current !== workspaceId) return;
      if (progressRequest.current === progressId) {
        if (progressRes.ok && progressRes.d?.year === progressYear) {
          setProgress(progressRes.d);
          setProgressFailed(false);
        } else if (progressRes.ok) {
          // Wrong-year payload must not stick Overview/Learning on endless … without Retry.
          setProgress(null);
          setProgressFailed(true);
        } else {
          setProgress(null);
          setProgressFailed(true);
          setError((progressRes.e as Error).message);
        }
      }
      if (digestRes.ok) {
        setDigestOptIn(!!digestRes.d.opted_in);
        setDigestFailed(false);
      } else {
        setDigestFailed(true);
      }
      if (suggestionsRes.ok) {
        setSuggestions(suggestionsRes.d.items || []);
        setSuggestionsCity(
          typeof suggestionsRes.d.city === 'string' && suggestionsRes.d.city.trim()
            ? suggestionsRes.d.city.trim()
            : null,
        );
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
      await loadLearning(learningFilter);
    } catch (e) {
      if (workspaceRequest.current !== workspaceId) return;
      setError((e as Error).message);
    } finally {
      if (workspaceRequest.current !== workspaceId) return;
      if (progressRequest.current === progressId) setProgressBusy(false);
      setSuggestionsBusy(false);
      setAuditBusy(false);
      setDigestPreferenceBusy(false);
    }
  }

  const filterChips: { key: string; label: string; overrides: Parameters<typeof searchCommitted>[0] }[] = [];
  const addChip = (key: string, label: string, overrides: Parameters<typeof searchCommitted>[0]) => filterChips.push({ key, label, overrides });
  if (applied.query) addChip('query', `Search: ${applied.query}`, { query: '' });
  if (applied.city) addChip('city', applied.city, { city: '' });
  if (applied.state) addChip('state', applied.state, { state: '' });
  if (applied.mode) addChip('mode', applied.mode.replace('_', ' '), { mode: '' });
  if (applied.period !== 'all') addChip('period', applied.period, { period: 'all' });
  if (applied.difficulty) addChip('difficulty', applied.difficulty, { difficulty: '' });
  if (applied.maxFee) addChip('fee', `Up to MYR ${applied.maxFee}`, { maxFee: '' });
  if (applied.minPoints) addChip('points', `${applied.minPoints}+ points`, { minPoints: '' });
  if (applied.dateFrom) addChip('from', `From ${applied.dateFrom}`, { dateFrom: '' });
  if (applied.dateTo) addChip('to', `Until ${applied.dateTo}`, { dateTo: '' });
  if (applied.includeUnknown) addChip('unknown', 'Include unconfirmed details', { includeUnknown: false });
  if (applied.nearby) addChip('nearby', `Within ${applied.radius} km`, { nearby: null });
  const activeFilterCount = filterChips.filter((chip) => chip.key !== 'query').length;

  function clearFilters() {
    const nextCity = '';
    const nextState = '';
    setQuery('');
    setCity(nextCity);
    setState(nextState);
    setDeliveryMode('');
    setPeriod('all');
    setDifficulty('');
    setMaxFee('');
    setMinPoints('');
    setDateFrom('');
    setDateTo('');
    setIncludeUnknown(false);
    setRadius('25');
    setNearby(null);
    // Page commits inside search() only after a successful load (FIND-01 pager honesty).
    search({
      query: '',
      city: nextCity,
      state: nextState,
      mode: '',
      period: 'all',
      difficulty: '',
      maxFee: '',
      minPoints: '',
      dateFrom: '',
      dateTo: '',
      includeUnknown: false,
      radius: '25',
      page: 1,
      nearby: null,
    });
  }

  function locateNearby() {
    const request = ++geoRequest.current;
    if (!navigator.geolocation) {
      setGeoError('Location is unavailable. Choose your city instead.');
      return;
    }
    setLocating(true); setGeoError('');
    navigator.geolocation.getCurrentPosition(
      (position) => {
        if (geoRequest.current !== request) return;
        const next = { latitude: position.coords.latitude, longitude: position.coords.longitude };
        setNearby(next); setLocating(false);
        // Page commits inside search() only after a successful load.
        // Location is a draft filter until Apply filters is pressed.
      },
      () => { if (geoRequest.current !== request) return; setLocating(false); setGeoError('Location was not available. You can still search by city or state.'); },
      { timeout: 10000 },
    );
  }

  async function saveLocation(event: FormEvent) {
    event.preventDefault();
    if (!user || !profileDraft) return;
    const owner = user.id;
    setLocationBusy(true);
    setError('');
    try {
      const saved = await api('/me', {
        method: 'PATCH',
        body: JSON.stringify({
          name: profileDraft.name,
          city: profileDraft.city || '',
          state: profileDraft.state || '',
          bio: profileDraft.bio || '',
          public_enabled: profileDraft.public_enabled,
          latitude: user.latitude ?? null,
          longitude: user.longitude ?? null,
        }),
      });
      if (userRef.current?.id !== owner) return;
      setUser(saved); setProfileDraft(saved);
      setProfileNotice('Profile saved. Catalogue filters have not changed.');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLocationBusy(false);
    }
  }

  const loadSignedInWorkspace = useEffectEvent(() => {
    // Profile location must not silently restrict the catalogue on login/reload.
    const nextCity = appliedSearch.current.city;
    const nextState = appliedSearch.current.state;
    setSuggestionsBusy(true);
    setLoading(true);
    loadWorkspace(nextCity, nextState).catch((e) => {
      setError((e as Error).message || 'Workspace could not be loaded.');
    });
  });
  useEffect(() => {
    if (!user?.id) return;
    const timer = window.setTimeout(() => loadSignedInWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [user?.id]);

  async function toggleDigest(next: boolean) {
    setError('');
    setDigestBusy(true);
    try {
      // Omit cadence_days so a stored NTF-01 preference (e.g. 30) is not wiped to 14.
      const d = await api('/me/digest', {
        method: 'PATCH',
        body: JSON.stringify({ opted_in: next }),
      });
      setDigestOptIn(!!d.opted_in);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDigestBusy(false);
    }
  }

  async function submitAccount(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const body = { email, password, name: name || 'Doctor' };
      if (mode === 'register') {
        if (!signup) throw new Error('Registration is disabled on this server.');
        await api('/auth/register', { method: 'POST', body: JSON.stringify(body) });
      }
      const account = await api('/auth/login', { method: 'POST', body: JSON.stringify(body) });
      setUser(account); setProfileDraft((draft) => draft?.id === account.id ? draft : account);
      setLoading(true);
      setSuggestionsBusy(true);
      setLearningBusy(true);
      setAuditBusy(true);
      // The auth route effect restores the requested page, or opens Overview.
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function saveRecord(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    const courseId = selected.id;
    // Capture open generation so await yields cannot overwrite a newer detail modal.
    const requestId = detailRequest.current;
    const gen = beginSaving();
    setError('');
    retryRef.current = null;
    try {
      await api('/me/trainings/' + courseId, { method: 'PUT', body: JSON.stringify(edit) });
      // Persist succeeded — refresh workspace (incl. sequenced progress) even if the modal closed or switched.
      // Do not naked-setProgress here: an unsequenced year fetch can overwrite a newer year change and stick `…`.
      await loadWorkspace();
      if (detailRequest.current !== requestId) return;
      const current = await api('/trainings/' + courseId);
      if (detailRequest.current !== requestId) return;
      setSelected(current);
      setEdit(normalizeRecordEdit(current.record));
      // REG-01: keep the correction trail honest while the detail modal stays open.
      await loadHistory(courseId, requestId);
    } catch (e) {
      if (detailRequest.current !== requestId) return;
      const message = (e as Error).message || '';
      // Stale version 409: reload so Retry does not replay a last-write loser.
      if (/changed|Reopen|Refresh/i.test(message)) {
        try {
          const current = await api('/trainings/' + courseId);
          if (detailRequest.current !== requestId) return;
          setSelected(current);
          setEdit(normalizeRecordEdit(current.record));
          await loadHistory(courseId, requestId);
        } catch {
          /* keep conflict message */
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
    setError('');
    setOpening(true);
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
      setError((e as Error).message);
    } finally {
      if (detailRequest.current === requestId) setOpening(false);
    }
  }

  const authRoutePending = !bootstrapError && (user ? pathname === loginPath : pathname !== loginPath);
  if (booting || authRoutePending) {
    return (
      <div className="dash">
        <div className="gate" id="main-content">
          <Loader2 className="spin" />
          <p>Opening CareCredits…</p>
        </div>
      </div>
    );
  }

  if (bootstrapError) return <main className="dash gate"><section className="gate-card" role="alert"><h1>CareCredits is unavailable</h1><p>{bootstrapError}</p><button onClick={() => { setBooting(true); setBootstrapError(''); setBootstrapAttempt((value) => value + 1); }}>Try again</button></section></main>;
  if (!user) {
    return (
      <div className="dash">
        <div className="gate">
          <form id="main-content" className="gate-card" onSubmit={submitAccount} aria-busy={busy}>
            <div className="brand">
              <Mark />
              <div>
                <strong>Care Credits</strong>
                <small>Log points. Find training. Focus on patients.</small>
              </div>
            </div>
            <h1>{mode === 'register' ? 'Create your workspace' : 'Sign in to search'}</h1>
            <p>
              {demo
                ? 'Demo mode: sign in as demo@carecredits.local to review fixtures and personal tracking. Live Tavily/model discovery needs configured credentials.'
                : signup
                  ? 'Register, then search Malaysian CPD courses from the original dashboard.'
                  : 'Sign in to search Malaysian CPD courses from the original dashboard.'}
            </p>
            {demo && (
              <p className="demo-banner">
                <span className="badge">DEMO</span> Example courses and review candidates are fictional. Use doctor@carecredits.local for a pure doctor login.
              </p>
            )}
            {mode === 'register' && (
              <label>
                Your name
                <input required minLength={2} value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            )}
            <label>
              Email address
              <input required type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Password
              <input
                required
                type="password"
                autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
                minLength={12}
                maxLength={128}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="alert">
                {error}
              </p>
            )}
            <button className="primary" disabled={busy}>
              {busy ? 'Please wait…' : mode === 'register' ? 'Create account and search' : 'Sign in and search'}
              <ChevronRight />
            </button>
            {oauth && (
              // OAuth must navigate the document to the backend; never prefetch this state-changing handshake.
              // eslint-disable-next-line @next/next/no-html-link-for-pages
              <a className="secondary" href="/api/v1/auth/oauth/google">
                Continue with Google
              </a>
            )}
            {recovery && <Link href="/reset-password">Forgot your password?</Link>}
            {signup && (
              <button
                type="button"
                className="text-link"
                onClick={() => {
                  setMode(mode === 'register' ? 'signin' : 'register');
                  setError('');
                }}
              >
                {mode === 'register' ? 'Already have an account? Sign in' : 'New here? Create an account'}
              </button>
            )}
          </form>
        </div>
      </div>
    );
  }

  // Failed progress must not look like an endless load (`…` forever).
  const progressReady = !progressBusy && !progressFailed && !!progress && progress.year === year;
  const points = progressReady ? progress.points ?? 0 : '…';
  const attended = progressReady ? progress.attended ?? 0 : '…';
  const signed = progressReady ? progress.signed_up ?? 0 : '…';

  return (
    <div className="dash">
      <div className="app-shell">
        <aside ref={sidebarRef} id="dashboard-navigation" inert={mobile && !open} className={open ? 'sidebar sidebar-open' : 'sidebar'}>
          <div className="brand">
            <Mark />
            <div>
              <strong>Care Credits</strong>
              <small>Log points. Find training. Focus on patients.</small>
            </div>
            <button className="close-nav" aria-label="Close navigation" onClick={() => { setOpen(false); menuRef.current?.focus(); }}>
              <X />
            </button>
          </div>
          <nav>
            {nav.map(([Icon, item]) => (
              <Link
                key={item}
                href={dashboardPaths[item]}
                prefetch={false}
                className={item === tab ? 'nav-item active' : 'nav-item'}
                aria-current={item === tab ? 'page' : undefined}
                onNavigate={(event) => {
                  event.preventDefault();
                  navigateToTab(item);
                  if (item === 'Events' || item === 'Discover') {
                    // Navigation preserves the filters explicitly applied by the user.
                    void searchCommitted({ page: 1 });
                  }
                }}
              >
                <Icon />
                <span>{item}</span>
              </Link>
            ))}
          </nav>
          <div className="profile">
            <span className="avatar">{initials(user.name)}</span>
            <div>
              <strong>{user.name}</strong>
              <small>{user.role === 'operator' ? 'Operator' : user.city || 'Malaysia'}</small>
            </div>
            <button
              className="text-link"
              aria-label="Sign out"
              onClick={async () => {
                try { await api('/auth/logout', { method: 'POST' }); } catch (error) { setError((error as Error).message); return; }
                userRef.current = null;
                ++catalogueRequest.current; ++learningRequest.current; ++progressRequest.current; ++detailRequest.current; ++savingGen.current;
                setProfileDraft(null);
                setUser(null);
                // Explicit sign-out starts the next session at Overview, without a return destination.
                window.history.replaceState(null, '', loginPath);
                setMode('signin');
                setOpen(false);
                setCourses([]);
                setSelected(null);
                setRecords([]);
                setProgress(null);
                setProgressFailed(false);
                setSuggestions([]);
                setSuggestionsCity(null);
                setAudits([]);
                setHistory([]);
                setDigestOptIn(false);
                setEdit(emptyRecord);
                setTotal(0);
                setRecordsTotal(0);
                setNearby(null);
                setResultsNearby(false);
                pendingSearch.current = null;
                pendingLearning.current = null;
                appliedSearch.current = {
                  query: '',
                  city: '',
                  state: '',
                  mode: '',
                  period: 'all',
                  difficulty: '',
                  maxFee: '',
                  minPoints: '',
                  dateFrom: '',
                  dateTo: '',
                  includeUnknown: false,
                  radius: '25',
                  nearby: null,
                };
                setApplied(appliedSearch.current);
                setQuery('');
                setCity('');
                setState('');
                setDeliveryMode('');
                setPeriod('all');
                setDifficulty('');
                setMaxFee('');
                setMinPoints('');
                setDateFrom('');
                setDateTo('');
                setIncludeUnknown(false);
                setRadius('25');
                setPage(1);
                setLearningFilter('all');
                setLearningPage(1);
                setYear(calendarYearLocal());
                setError('');
                setSuggestionsFailed(false);
                setAuditFailed(false);
                setDigestFailed(false);
                setSearchFailed(false);
                setLearningFailed(false);
                setHistoryFailed(false);
                setLoading(true);
                setSuggestionsBusy(true);
                setLearningBusy(true);
                setProgressBusy(true);
                setAuditBusy(true);
                setDigestPreferenceBusy(true);
                // Drop any in-flight Retry so the next account cannot replay a prior cancel/review.
                retryRef.current = null;
              }}
            >
              <LogOut />
            </button>
          </div>
        </aside>
        {open && <button className="veil" onClick={() => setOpen(false)} aria-label="Close navigation" />}
        <main className="main" id="main-content" inert={mobile && open}>
          <header className="topbar">
            <button ref={menuRef} className="menu-button" aria-expanded={open} aria-controls="dashboard-navigation" onClick={() => setOpen(true)} aria-label="Open navigation">
              <Menu />
            </button>
            <form className="catalogue-search" role="search" aria-label="Search catalogue" onSubmit={(event) => {
              event.preventDefault(); navigateToTab('Discover'); searchCommitted({ query, page: 1 });
            }}>
              <label className="search">
                <Search aria-hidden="true" />
                <input aria-label="Search training" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the training catalogue" />
              </label>
                    <button type="button" className="filter-toggle" aria-expanded={filtersOpen} aria-haspopup="dialog" aria-controls="catalogue-filter-dialog" onClick={() => setFiltersOpen(!filtersOpen)}>
                      Filters{activeFilterCount ? ` (${activeFilterCount})` : ''}
                    </button>
              <button className="search-btn" disabled={loading}>{loading ? 'Searching...' : 'Search'}</button>
            </form>
            <div className="top-actions">
              <span className="avatar" title={user.name} aria-label={user.name}>
                {initials(user.name)}
              </span>
            </div>
          </header>
          <div className="content"><h1 id="page-heading" tabIndex={-1} className="page-heading">{tab}</h1>
            {demo && (
              <p className="demo-banner">
                <span className="badge">DEMO</span> Example courses and review candidates are fictional. Live discovery
                needs configured Tavily and model credentials.
              </p>
            )}
            {error && (
              <p role="alert" className="alert">
                {error}{' '}
                <button
                  className="text-link"
                  type="button"
                  onClick={() => {
                    const action = retryRef.current;
                    retryRef.current = null;
                    if (action) action();
                    else void loadWorkspace();
                  }}
                >
                  Retry
                </button>
              </p>
            )}
            {opening && (
              <p className="alert" role="status" aria-busy="true">
                Opening training details…
              </p>
            )}
            {tab === 'Overview' && (
              <>
                <section className="hero">
                  <div className="hero-copy">
                    <span className="eyebrow">MALAYSIA CPD</span>
                    <h1>Your learning, in one place</h1>
                    <p>Search the owned Malaysia CPD catalogue, keep a personal record, and open the provider page when you are ready.</p>
                  </div>
                  <div className="progress-panel">
                    <div className="progress-copy">
                      {progressFailed && !progressBusy ? (
                        <p className="empty-copy" data-testid="live-progress-failed">
                          Couldn&apos;t load progress for {year}. Check your connection, then try again.{' '}
                          <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                            Retry
                          </button>
                        </p>
                      ) : (
                        <>
                          <h2>
                            {points} <span>self-reported CPD points</span>
                          </h2>
                          <p>
                            <CalendarDays /> {year} record
                            <br />
                            <strong>
                              {attended} attended · {signed} signed up
                            </strong>
                          </p>
                        </>
                      )}
                      <b className="warning">Self-reported totals are not a regulator credit.</b>
                    </div>
                    <button
                      className="primary"
                      onClick={() => {
                        navigateToTab('Discover');
                        searchCommitted({ page: 1 });
                      }}
                    >
                      Find catalogue events <ChevronRight />
                    </button>
                  </div>
                </section>
                <section className="metrics">
                  <article className="metric">
                    <span className="metric-icon green">★</span>
                    <div>
                      <p>Points recorded</p>
                      <strong className="metric-green">{points}</strong>
                    </div>
                  </article>
                  <article className="metric">
                    <span className="metric-icon orange">◎</span>
                    <div>
                      <p>Courses attended</p>
                      <strong>{attended}</strong>
                    </div>
                  </article>
                  <article className="metric">
                    <span className="metric-icon blue">♢</span>
                    <div>
                      <p>Signed up</p>
                      <strong>{signed}</strong>
                      {progressReady && !!progress.excluded && <small>{excludedCopy(progress)}</small>}
                    </div>
                  </article>
                </section>
                <section className="card" id="live-audit">
                  <div className="card-heading">
                    <div>
                      <span className="heading-icon">▤</span>
                      <h2>Your activity</h2>
                    </div>
                  </div>
                  <p className="empty-copy">Your own audit trail. Personal notes and secrets are never shown here.</p>
                  {auditBusy ? (
                    <p className="empty-copy" role="status" aria-busy="true" data-testid="live-audit-loading">
                      Loading your activity…
                    </p>
                  ) : (
                    <>
                      {auditFailed && audits.length ? (
                        <p className="empty-copy" data-testid="live-audit-stale">
                          Couldn&apos;t refresh your activity. Showing the last loaded list.{' '}
                          <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                            Retry
                          </button>
                        </p>
                      ) : null}
                      {audits.length ? (
                        <ul className="source-list">
                          {audits.slice(0, 8).map((item) => (
                            <li key={item.id}>
                              {activityLabel(item.action)}
                              {item.at ? ` · ${new Date(item.at * 1000).toLocaleString('en-MY')}` : ''}
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="empty-copy" data-testid="live-audit-empty">
                          {auditFailed
                            ? "Couldn't load your activity. Check your connection, then try again. "
                            : 'Sign-up, attendance, and profile saves will appear here.'}
                          {auditFailed ? (
                            <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                              Retry
                            </button>
                          ) : null}
                        </p>
                      )}
                    </>
                  )}
                </section>
              </>
            )}
            <div className={'dashboard-grid ' + (!['Overview', 'Discover', 'Events'].includes(tab) ? 'single-feature' : '')}>
              {(tab === 'Discover' || tab === 'Events' || tab === 'Overview') && (
              <div className="left-column">
                <section className="card">
                  <div className="card-heading">
                    <div>
                      <span className="heading-icon">▣</span>
                      <h2>
                        {tab === 'Discover'
                          ? 'Search results'
                          : tab === 'Events'
                            ? (applied.period === 'upcoming' ? 'Upcoming training' : 'Training events')
                            : 'Listed training'}
                      </h2>
                    </div>
                    <p>
                      {loading
                        ? 'Searching…'
                        : searchFailed
                          ? "Couldn't load…"
                          : `${total} event${total === 1 ? '' : 's'}`}
                    </p>
                  </div>
                  <div className="catalogue-tools">
                    <p>Search published training. AI discovery and candidate review are separate below.</p>

                  </div>
                  <div className="filter-chips" aria-label="Applied filters">
                    {filterChips.map((chip) => <button key={chip.key} type="button" disabled={loading} onClick={() => searchCommitted(chip.overrides)} aria-label={`Remove ${chip.label} filter`}>{chip.label}<X size={14} aria-hidden="true" /></button>)}
                    {filterChips.length > 0 && <button type="button" className="clear-filters" disabled={loading} onClick={clearFilters}>Clear all</button>}
                  </div>

                  {loading ? (
                    <p className="empty-copy" role="status" aria-busy="true" data-testid="live-search-loading">
                      Finding your training…
                    </p>
                  ) : courses.length ? (
                    <>
                      {searchFailed ? (
                        <p className="empty-copy" data-testid="live-search-stale">
                          Couldn&apos;t refresh training. Showing the last loaded list.{' '}
                          <button
                            className="text-link"
                            type="button"
                            onClick={() => retrySearch()}
                          >
                            Retry
                          </button>
                        </p>
                      ) : null}
                      {courses.map((course) => (
                        <button key={course.id} className="event" onClick={() => openCourse(course)}>
                          <DateChip value={course.start_date} />
                          <span className="event-name">
                            <strong>
                              {course.title}
                              {course.demo ? ' · Demo course' : ''}
                            </strong>
                            <small>
                              {formatDate(course.start_date)} · {locationLabel(course)}
                              {distanceLabel(course, resultsNearby)}
                            </small>
                          </span>
                          <span className="event-points">
                            {course.points != null ? `${course.points} ${course.credit_label || 'CPD'} points` : 'Points not listed'}
                          </span>
                          <ChevronRight />
                        </button>
                      ))}
                      {total > PAGE_SIZE && (
                        <div className="pager">
                          <button
                            className="text-link"
                            type="button"
                            disabled={page <= 1 || loading}
                            onClick={() => search({ page: page - 1, pageOnly: true })}
                          >
                            Previous
                          </button>
                          <span>
                            Page {page} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
                          </span>
                          <button
                            className="text-link"
                            type="button"
                            disabled={page * PAGE_SIZE >= total || loading}
                            onClick={() => search({ page: page + 1, pageOnly: true })}
                          >
                            Next
                          </button>
                        </div>
                      )}
                      {resultsNearby && (
                        <p className="empty-copy">
                          Approximate straight-line distance when venue coordinates exist; otherwise distance unavailable.
                          Online sessions still appear for Online, Hybrid, or Any mode.
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="empty-copy" data-testid="live-search-empty">
                      {searchFailed
                        ? "Couldn't load training. Check your connection, then try again. "
                        : 'No matching training. Try a broader topic or clear filters.'}
                      {searchFailed ? (
                        <button
                          className="text-link"
                          type="button"
                          onClick={() => retrySearch()}
                        >
                          Retry
                        </button>
                      ) : null}
                    </p>
                  )}
                </section>
              </div>
              )}
              <div className="right-column">
                {user.role === 'operator' && (tab === 'Overview' || tab === 'Discover') && (
                  <LiveIngestion
                    onPublished={async () => {
                      await loadWorkspace();
                    }}
                  />
                )}
                {tab === 'Settings' && <section className="card" id="live-location">
                  <div className="card-heading">
                    <div>
                      <span className="heading-icon">⌖</span>
                      <h2>Profile settings</h2>
                    </div>
                  </div>
                  <p className="empty-copy">
                    Save your location, biography and public-sharing preference. These settings do not change catalogue filters.
                  </p>
                  <form onSubmit={saveLocation}>
                    <label>
                      City
                      <input
                        aria-label="Profile city"
                        value={profileDraft?.city || ''}
                        onChange={(e) => setProfileDraft({ ...(profileDraft || user), city: e.target.value })}
                        placeholder="Kuala Lumpur"
                      />
                    </label>
                    <label>
                      State
                      <input
                        aria-label="Profile state"
                        value={profileDraft?.state || ''}
                        onChange={(e) => setProfileDraft({ ...(profileDraft || user), state: e.target.value })}
                        placeholder="Optional, e.g. Selangor"
                      />
                    </label>
                    <label>
                      Public profile bio
                      <textarea
                        aria-label="Public profile bio"
                        value={profileDraft?.bio || ''}
                        onChange={(e) => setProfileDraft({ ...(profileDraft || user), bio: e.target.value })}
                        rows={2}
                      />
                    </label>
                    <label className="empty-copy">
                      <input
                        type="checkbox"
                        checked={!!profileDraft?.public_enabled}
                        onChange={(e) => setProfileDraft({ ...(profileDraft || user), public_enabled: e.target.checked })}
                      />{' '}
                      Show selected attended learning on a public profile
                    </label>
                    {user.public_slug ? (
                      <p className="empty-copy">
                        <a href={'/p/' + user.public_slug} target="_blank" rel="noreferrer">
                          Open public profile
                        </a>
                        {user.public_enabled ? '' : ' (private until you enable sharing)'}
                      </p>
                    ) : null}
                    <button className="secondary" disabled={locationBusy}>
                      {locationBusy ? 'Saving…' : 'Save profile'}
                    </button>
                  </form>
                  {profileNotice && <p role="status">{profileNotice}</p>}
                </section>}
                {(tab === 'Overview' || tab === 'Discover' || tab === 'Events') && <section className="card" id="live-suggestions" data-testid="live-suggestions">
                  <div className="card-heading">
                    <div>
                      <span className="heading-icon">✦</span>
                      <h2>Consider next</h2>
                    </div>
                  </div>
                  <p className="empty-copy">
                    Advisory catalogue matches by city and recent learning mode. CareCredits does not decide MMC, MOH, or APC compliance.
                  </p>
                  {suggestionsBusy ? (
                    <p className="empty-copy" role="status" aria-busy="true" data-testid="live-suggestions-loading">
                      Loading suggestions…
                    </p>
                  ) : (
                    <>
                      {suggestionsFailed && suggestions.length ? (
                        <p className="empty-copy" data-testid="live-suggestions-stale">
                          Couldn&apos;t refresh suggestions. Showing the last loaded list.{' '}
                          <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                            Retry
                          </button>
                        </p>
                      ) : null}
                      {suggestions.length ? (
                        suggestions.slice(0, 5).map((item) => (
                          <button
                            key={item.id}
                            className="recommendation"
                            type="button"
                            onClick={() => openCourse({ id: item.id } as Course)}
                          >
                            <DateChip value={item.start_date} />
                            <div>
                              <h3>{item.title}</h3>
                              <p>{item.provider || 'Catalogue listing'}</p>
                              <small>
                                {formatDate(item.start_date || null)} ·{' '}
                                {locationLabel({
                                  mode: item.mode || 'online',
                                  city: item.city || null,
                                })}
                                {item.reason ? ` — ${item.reason}` : ''}
                                {item.points != null ? ` · ${item.points} points` : ''}
                              </small>
                            </div>
                            <ChevronRight />
                          </button>
                        ))
                      ) : (
                        <p className="empty-copy" data-testid="live-suggestions-empty">
                          {suggestionsFailed
                            ? "Couldn't load suggestions. Check your connection, then try again. "
                            : suggestionsCity
                              ? 'No catalogue suggestions match your city and recent learning mode yet. Browse Discover for all training.'
                              : 'No catalogue suggestions yet. Save a city in Settings or browse Discover.'}
                          {suggestionsFailed ? (
                            <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                              Retry
                            </button>
                          ) : null}
                        </p>
                      )}
                    </>
                  )}
                </section>}
                {(tab === 'Overview') && <section className="card">
                  <div className="card-heading">
                    <div>
                      <span className="heading-icon">♧</span>
                      <h2>Learning record</h2>
                    </div>
                  </div>
                  {progressFailed && !progressBusy ? (
                    <p className="empty-copy" data-testid="live-learning-progress-failed">
                      Couldn&apos;t load progress for {year}. Check your connection, then try again.{' '}
                      <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                        Retry
                      </button>
                    </p>
                  ) : (
                    <p className="empty-copy">
                      {points} self-reported CPD points for {year}. This is the recorded total, not a fill toward a legal
                      annual target.
                    </p>
                  )}
                  <label>
                    Year{' '}
                    <select
                      aria-label="Progress year"
                      value={year}
                      onChange={async (e) => {
                        const next = Number(e.target.value);
                        const requestId = ++progressRequest.current;
                        setYear(next);
                        setProgress(null);
                        setProgressFailed(false);
                        setProgressBusy(true);
                        try {
                          const payload = await api('/me/progress?year=' + next);
                          // Discard stale out-of-order years (parity with Overview progressReady).
                          if (progressRequest.current === requestId && payload?.year === next) {
                            setProgress(payload);
                            setProgressFailed(false);
                          }
                        } catch (err) {
                          if (progressRequest.current === requestId) {
                            setProgress(null);
                            setProgressFailed(true);
                            setError((err as Error).message);
                          }
                        } finally {
                          if (progressRequest.current === requestId) setProgressBusy(false);
                        }
                      }}
                    >
                      {[0, 1, 2, 3, 4].map((offset) => {
                        const value = calendarYearLocal() - offset;
                        return (
                          <option key={value} value={value}>
                            {value}
                          </option>
                        );
                      })}
                    </select>
                  </label>
                  <p className="empty-copy">
                    {progressReady && progress.excluded
                      ? excludedCopy(progress)
                      : 'Opening a source does not register you with the provider.'}
                  </p>
                </section>}
                {tab === 'Settings' && <PasswordSettings />}
                {tab === 'About credits' && (
                  <section className="card">
                    <div className="card-heading">
                      <div>
                        <span className="heading-icon">▣</span>
                        <h2>About recorded credits</h2>
                      </div>
                    </div>
                    <p className="empty-copy">
                      CareCredits does not decide APC, MMC, or licence renewal. Points you record here are
                      self-reported and are not independently accredited.
                    </p>
                  </section>
                )}
                {tab === 'Certificates' && <CertificatePanel year={year} />}
                {tab === 'My Credits' && (
                  <section className="card" id="live-learning" data-testid="live-learning">
                    <div className="card-heading">
                      <div>
                        <span className="heading-icon">▣</span>
                        <h2>My learning</h2>
                      </div>
                      <p>
                        {learningBusy
                          ? 'Loading your records…'
                          : learningFailed
                            ? "Couldn't load…"
                            : `${recordsTotal} saved record${recordsTotal === 1 ? '' : 's'}`}
                      </p>
                    </div>
                    <p className="empty-copy">
                      Signed-up and attended lists from your personal record. Opening a provider link does not create a
                      sign-up.
                    </p>
                    <div className="button-row">
                      {(
                        [
                          ['all', 'All'],
                          ['signed_up', 'Signed up'],
                          ['attended', 'Attended'],
                        ] as const
                      ).map(([value, label]) => (
                        <button
                          key={value}
                          className={learningFilter === value ? 'secondary chosen' : 'secondary'}
                          type="button"
                          aria-pressed={learningFilter === value}
                          onClick={() => loadLearning(value)}
                        >
                          {label}
                        </button>
                      ))}
                      {learningFailed ? (
                        <button className="text-link" type="button" onClick={retryLearning}>
                          Retry
                        </button>
                      ) : null}
                      <a className="text-link" href={`/api/v1/me/export/csv?year=${year}`}>
                        Export CSV · {year}
                      </a>
                      <a className="text-link" href={`/api/v1/me/export/eml?year=${year}`}>
                        Email draft · {year}
                      </a>
                    </div>
                    {learningBusy ? (
                      <p className="empty-copy" role="status" aria-busy="true">
                        Loading your learning record…
                      </p>
                    ) : records.length ? (
                      <>
                        {learningFailed ? (
                          <p className="small-note" data-testid="live-learning-stale">
                            Couldn&apos;t refresh your records. Showing the last loaded list.{' '}
                            <button className="text-link" type="button" onClick={retryLearning}>
                              Retry
                            </button>
                          </p>
                        ) : null}
                        {records.map((course) => (
                          <button key={course.id} className="event" type="button" onClick={() => openCourse(course)}>
                            <DateChip value={course.start_date} />
                            <span className="event-name">
                              <strong>{course.title}</strong>
                              <small>
                                {formatDate(course.start_date)} ·{' '}
                                {course.record?.attendance_status === 'attended' || course.record?.attended
                                  ? 'Attended'
                                  : course.record?.signup_status === 'cancelled'
                                    ? 'Sign-up cancelled'
                                    : course.record?.signup_status === 'signed_up' || course.record?.signed_up
                                      ? 'Signed up'
                                      : 'Saved'}
                              </small>
                            </span>
                            <ChevronRight />
                          </button>
                        ))}
                        {recordsTotal > 12 && (
                          <div className="pager" data-testid="live-learning-pager">
                            <button
                              className="text-link"
                              type="button"
                              disabled={learningPage <= 1 || learningBusy}
                              onClick={() => loadLearning(learningFilter, learningPage - 1)}
                            >
                              Previous
                            </button>
                            <span>
                              Page {learningPage} of {Math.max(1, Math.ceil(recordsTotal / 12))}
                            </span>
                            <button
                              className="text-link"
                              type="button"
                              disabled={learningPage * 12 >= recordsTotal || learningBusy}
                              onClick={() => loadLearning(learningFilter, learningPage + 1)}
                            >
                              Next
                            </button>
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="empty-copy" data-testid="live-learning-empty">
                        {learningFailed
                          ? "Couldn't load your records. Check your connection, then try again. "
                          : 'Your learning story starts here. Open a catalogue course to record sign-up or attendance.'}
                        {learningFailed ? (
                          <button className="text-link" type="button" onClick={retryLearning}>
                            Retry
                          </button>
                        ) : null}
                      </p>
                    )}
                  </section>
                )}
                {tab === 'My Credits' && (
                  <section className="card">
                    <div className="card-heading">
                      <div>
                        <span className="heading-icon">✉</span>
                        <h2>Biweekly digest</h2>
                      </div>
                    </div>
                    <p className="empty-copy">
                      {digestAvailable ? 'Opt in for a 14-day email with catalogue events and your recorded CPD total.' : 'Automatic digest emails are unavailable on this deployment. Browse Discover for current training.'}
                    </p>
                    {!digestAvailable ? null : digestFailed ? (
                      <p className="empty-copy" data-testid="live-digest-failed">
                        Couldn&apos;t load digest preference. Check your connection, then try again.{' '}
                        <button className="text-link" type="button" onClick={() => loadWorkspace()}>
                          Retry
                        </button>
                      </p>
                    ) : digestPreferenceBusy ? (
                      <p className="empty-copy" role="status" aria-busy="true" data-testid="live-digest-loading">
                        Loading digest preference…
                      </p>
                    ) : (
                      <label className="empty-copy">
                        <input
                          type="checkbox"
                          checked={digestOptIn}
                          disabled={digestBusy}
                          onChange={(e) => toggleDigest(e.target.checked)}
                        />{' '}
                        Email me the biweekly digest
                      </label>
                    )}
                  </section>
                )}
              </div>
            </div>
          </div>
        </main>
      </div>
      {filtersOpen && <dialog ref={filterDialogRef} id="catalogue-filter-dialog" className="filter-dialog" aria-labelledby="filter-dialog-title" onCancel={cancelFilters}>
        <div className="filter-dialog-heading"><h2 id="filter-dialog-title">Filter training</h2><button type="button" className="filter-toggle" aria-label="Close filters" onClick={cancelFilters}><X size={20} /></button></div>
                  <form id="catalogue-filter-panel" className="catalogue-filter-panel" onSubmit={(event) => { event.preventDefault(); navigateToTab('Discover'); search({ page: 1 }); setFiltersOpen(false); }}>
                    <p className="filter-help">Adjust your filters, then apply them to update the results.</p>
                    <fieldset><legend>Location</legend><div className="filter-fields">
                      <label>City<input value={city} onChange={(e) => setCity(e.target.value)} placeholder="Any city" /></label>
                      <label>State<input value={state} onChange={(e) => setState(e.target.value)} placeholder="Any state" /></label>
                    </div>
                    <div className="nearby-controls"><button type="button" className="filter-toggle" onClick={locateNearby}>Use my location</button>
                    {nearby && <><label>Search radius<select value={radius} onChange={(e) => setRadius(e.target.value)}>{[10,25,50,100].map((km) => <option key={km} value={km}>{km} km</option>)}</select></label><span>Location ready. Apply filters to search nearby.</span><button type="button" className="text-link" onClick={() => setNearby(null)}>Remove location</button></>}
                    </div></fieldset>
                    <fieldset><legend>Format &amp; dates</legend><div className="filter-fields">
                      <label>Delivery mode<select value={deliveryMode} onChange={(e) => setDeliveryMode(e.target.value)}><option value="">Any mode</option><option value="online">Online</option><option value="in_person">In person</option><option value="hybrid">Hybrid</option></select></label>
                      <label>Period<select value={period} onChange={(e) => setPeriod(e.target.value)}><option value="upcoming">Upcoming</option><option value="all">All dates</option><option value="past">Past</option></select></label>
                      <label>From date<input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></label>
                      <label>To date<input type="date" min={dateFrom || undefined} value={dateTo} onChange={(e) => setDateTo(e.target.value)} /></label>
                      <label>Difficulty<select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}><option value="">Any level</option><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
                    </div></fieldset>
                    <fieldset><legend>Cost &amp; credits</legend><div className="filter-fields">
                      <label>Maximum fee (MYR)<input type="number" min="0" step="1" value={maxFee} onChange={(e) => setMaxFee(e.target.value)} placeholder="No maximum" /></label>
                      <label>Minimum advertised points<input type="number" min="0" step="0.1" value={minPoints} onChange={(e) => setMinPoints(e.target.value)} placeholder="No minimum" /></label>
                    </div><label className="filter-check"><input type="checkbox" checked={includeUnknown} onChange={(e) => setIncludeUnknown(e.target.checked)} />Include courses with unconfirmed dates, fees or points</label></fieldset>
                    <div aria-live="polite">{locating && <p>Finding your location…</p>}{geoError && <p role="alert">{geoError}</p>}</div><div className="filter-actions"><button className="search-btn" disabled={loading}>{loading ? 'Applying...' : 'Apply filters'}</button><button type="button" className="filter-toggle" onClick={cancelFilters}>Cancel</button></div>
                  </form>
      </dialog>}
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
            else void loadWorkspace();
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
                await search({ page: 1, pageOnly: true });
                if (detailRequest.current !== requestId) return;
                setSelected(null);
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
