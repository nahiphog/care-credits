export type User = {
  id: string;
  name: string;
  email: string;
  city: string;
  state: string;
  latitude?: number | null;
  longitude?: number | null;
  location_consent_at?: number | null;
  created_at?: number;
  bio: string;
  role: string;
  public_enabled: boolean;
  public_slug: string;
};

export type Suggestion = {
  id: string;
  title: string;
  provider?: string;
  start_date?: string | null;
  city?: string | null;
  mode?: string;
  fee?: number | null;
  currency?: string | null;
  reason?: string;
};

export type SignupStatus = 'not_recorded' | 'signed_up' | 'cancelled';
export type AttendanceStatus = 'not_recorded' | 'attended';

export type RecordData = {
  signed_up: boolean;
  signup_status: SignupStatus;
  attended: boolean;
  attendance_status?: AttendanceStatus;
  attended_on: string | null;
  points: number | null;
  credit_label: string;
  notes: string;
  public: boolean;
  version: number;
  signed_up_at?: number | null;
  points_origin?: string;
};

export type RecordHistoryItem = {
  at: number;
  signup_status?: SignupStatus;
  attendance_status?: AttendanceStatus;
  attended?: boolean;
  attended_on?: string | null;
  points?: number | null;
  credit_label?: string;
};

export type Course = {
  id: string;
  title: string;
  provider: string;
  description: string;
  model_id?: string | null;
  start_date: string | null;
  end_date?: string | null;
  timezone?: string | null;
  venue?: string | null;
  city: string | null;
  state?: string | null;
  mode: string;
  fee: number | null;
  currency: string | null;
  points: number | null;
  credit_label: string | null;
  difficulty: string | null;
  prerequisites: string | null;
  registration_url: string | null;
  source_url: string;
  evidence: Record<string, string>;
  distance_km?: number | null;
  demo: boolean;
  verification_status?: string;
  reviewed_at?: number | null;
  publication_status?: string;
  cancellation_status?: string;
  field_evidence?: { field_name: string; excerpt: string; reviewed_at?: number | null }[];
  record: RecordData | null;
};

export type Progress = {
  year: number;
  signed_up: number;
  attended: number;
  points: number;
  excluded: number;
  excluded_reasons?: { reason: string; credit_label?: string }[];
};

export type TavilySource = {
  url: string | null;
  title: string;
  snippet: string;
  extraction_status: string;
  verification_status: string;
  retrieved_at?: string | null;
};

export type Job = {
  execution_mode?: 'request' | 'worker';
  id: string;
  query: string;
  status: string;
  max_results?: number;
  attempt?: number;
  result: {
    extractions?: { model_id: string; endpoint_host: string; completed_at: string; candidate_count: number }[];
    warnings?: string[];
    candidate_count?: number;
    extraction_status?: string;
    sources?: TavilySource[];
    usage?: { tavily_credits?: number | null; model_tokens?: number | null };
  } | null;
};

export type RefreshDiff = { field: string; published: unknown; proposed: unknown };

export type JevJudgment = {
  decision?: string;
  confidence?: number;
  probabilities?: { exists?: number; new?: number; uncertain?: number };
  warning?: string | null;
};

export type Candidate = {
  id: string;
  job_id?: string | null;
  data: Course & {
    source_text?: string;
    retrieved_at?: string | null;
    _refresh_diff?: RefreshDiff[];
    _matched_course_id?: string;
    _judgment?: JevJudgment;
    _fixture?: boolean;
  };
  status: string;
  reason?: string;
  version?: number;
  schema_version?: number;
  resulting_course_id?: string | null;
};

export type AuditItem = {
  id: string;
  action: string;
  entity_id: string;
  changed: Record<string, unknown>;
  at: number;
};

export type WorkspaceTab =
  | 'Overview'
  | 'Discover training'
  | 'My learning'
  | 'Public profile'
  | 'Ingestion';

export const emptyRecord: RecordData = {
  signed_up: false,
  signup_status: 'not_recorded',
  attended: false,
  attendance_status: 'not_recorded',
  attended_on: null,
  points: null,
  credit_label: 'CPD',
  notes: '',
  public: false,
  version: 0,
};

/** Heal status/bool drift so TrainingDetail selects and PUT payloads stay consistent. */
export function normalizeRecordEdit(record?: Partial<RecordData> | null): RecordData {
  const base = { ...emptyRecord, ...(record || {}) };
  const signup_status: SignupStatus =
    base.signup_status === 'cancelled'
      ? 'cancelled'
      : base.signup_status === 'signed_up' || base.signed_up
        ? 'signed_up'
        : 'not_recorded';
  const attended = base.attendance_status === 'attended' || base.attended;
  return {
    ...base,
    signup_status,
    signed_up: signup_status === 'signed_up',
    attendance_status: attended ? 'attended' : 'not_recorded',
    attended,
  };
}

export function publicWebUrl(value?: string | null) {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname || '';
    if (
      (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') ||
      !host.includes('.') ||
      parsed.username ||
      parsed.password ||
      (parsed.port && parsed.port !== '80' && parsed.port !== '443') ||
      host.endsWith('.local') ||
      host.endsWith('.localhost') ||
      host.endsWith('.internal')
    ) {
      return null;
    }
    // Match shared/contracts.public_web_url: reject literal IPv4/IPv6 hosts.
    if (/^\d{1,3}(?:\.\d{1,3}){3}$/.test(host) || host.includes(':')) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

export function formatDate(value: string | null) {
  return value
    ? new Date(value + 'T00:00:00+08:00').toLocaleDateString('en-MY', {
        timeZone: 'Asia/Kuala_Lumpur',
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      })
    : 'Date to be confirmed';
}

export function feeLabel(c: { fee?: number | null; currency?: string | null }) {
  if (c.fee == null) return 'Fee not listed';
  if (c.fee === 0) return 'Free';
  // Whitespace-only currency is missing — do not invent MYR (SDD fee honesty).
  const currency = (c.currency || '').trim();
  if (!currency) return `${c.fee.toLocaleString()} (currency unknown)`;
  return `${currency} ${c.fee.toLocaleString()}`;
}

export function modeName(value: string) {
  return ({ in_person: 'In person', online: 'Online', hybrid: 'Hybrid' }[value] || value);
}

export function locationLabel(course: { mode: string; city: string | null; state?: string | null; venue?: string | null }) {
  const place = course.city
    ? course.state
      ? `${course.city}, ${course.state}`
      : course.city
    : course.mode === 'online'
      ? 'Online'
      : 'Location not listed';
  return course.venue ? `${course.venue} · ${place}` : place;
}

export function distanceLabel(course: { distance_km?: number | null; mode: string }, nearby = false) {
  if (course.distance_km != null) return ` · ~${course.distance_km} km`;
  if (nearby && course.mode !== 'online') return ' · distance unavailable';
  return '';
}

export function todayLocal() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kuala_Lumpur' }).format(new Date());
}

/** PROG-01 / CERT-01 calendar year in Asia/Kuala_Lumpur (parity with backend `today().year`). */
export function calendarYearLocal() {
  return Number(todayLocal().slice(0, 4));
}

export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch('/api/v1' + path, {
    ...options,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'X-Care-Client': '1',
      ...options.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const message = data?.error?.message || (typeof data.detail === 'string' ? data.detail : '');
    throw new Error(message || 'Please check your entries and try again.');
  }
  return response.json();
}
