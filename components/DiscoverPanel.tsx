'use client';

import { ArrowDownToLine, ChevronLeft, ChevronRight, FileText, MapPin, Search } from 'lucide-react';
import { Course } from '@/lib/portal';
import { CourseCard, Empty, Loading } from '@/components/CourseList';

export type DiscoverFilters = {
  q: string;
  city: string;
  state: string;
  mode: string;
  difficulty: string;
  maxFee: string;
  minPoints: string;
  period: string;
  dateFrom: string;
  dateTo: string;
  includeUnknown: boolean;
  radius: string;
  location: { latitude: number; longitude: number } | null;
  page: number;
};

export type LearningFilters = {
  signupStatus: string;
  attended: string;
  page: number;
};

export function DiscoverPanel({
  tab,
  filters,
  courses,
  records,
  total,
  loading,
  failed = false,
  resultsNearby = false,
  learning,
  recordsTotal,
  year,
  onFilters,
  onLocate,
  onDiscover,
  onOpen,
  onClearFilters,
  onLearningFilters,
  onPage,
  onLearningPage,
  onRetry,
}: {
  tab: 'Discover training' | 'My learning';
  filters: DiscoverFilters;
  courses: Course[];
  records: Course[];
  total: number;
  loading: boolean;
  failed?: boolean;
  /** GEO-02: true only when the currently listed courses were fetched with Near me (not draft location). */
  resultsNearby?: boolean;
  learning?: LearningFilters;
  recordsTotal?: number;
  year?: number;
  onFilters: (patch: Partial<DiscoverFilters>) => void;
  onLocate: () => void;
  onDiscover: () => void;
  onOpen: (course: Course) => void;
  onClearFilters?: () => void;
  onLearningFilters?: (patch: Partial<LearningFilters>) => void;
  /** FIND-01: commit Discover page only after a successful catalogue load (parity with /live / Ingestion). */
  onPage?: (page: number) => void;
  /** FIND-01: commit My learning page only after a successful records load. */
  onLearningPage?: (page: number) => void;
  onRetry?: () => void;
}) {
  const list = tab === 'My learning' ? records : courses;
  const exportYear = typeof year === 'number' ? `?year=${year}` : '';
  const {
    q,
    city,
    state,
    mode,
    difficulty,
    maxFee,
    minPoints,
    period,
    dateFrom,
    dateTo,
    includeUnknown,
    radius,
    location,
    page,
  } = filters;

  return (
    <>
      <div className="page-title">
        <div>
          <p className="eyebrow">{tab === 'My learning' ? 'YOUR PERSONAL RECORD' : 'OPPORTUNITIES NEAR YOU'}</p>
          <h1>{tab === 'My learning' ? 'A little learning. Lasting impact.' : 'Find your next CPD training.'}</h1>
          <p>
            {tab === 'My learning'
              ? 'Keep sign-ups, attendance and notes together.'
              : 'Compare practical details before making time in your calendar.'}
          </p>
        </div>
        {tab === 'My learning' && (
          <div className="button-row">
            <a className="secondary" href={`/api/v1/me/export/csv${exportYear}`}>
              <ArrowDownToLine size={16} /> Spreadsheet{typeof year === 'number' ? ` · ${year}` : ''}
            </a>
            <a className="secondary" href={`/api/v1/me/export/eml${exportYear}`}>
              <FileText size={16} /> Email draft{typeof year === 'number' ? ` · ${year}` : ''}
            </a>
          </div>
        )}
      </div>
      {tab === 'My learning' && onLearningFilters && learning && (
        <section className="filter-panel">
          <div className="filters">
            <label>
              Sign-up status
              <select
                aria-label="Filter by sign-up status"
                value={learning.signupStatus}
                onChange={(e) => onLearningFilters({ signupStatus: e.target.value, page: 1 })}
              >
                <option value="">All sign-ups</option>
                <option value="signed_up">Signed up</option>
                <option value="cancelled">Cancelled</option>
                <option value="not_recorded">Not recorded</option>
              </select>
            </label>
            <label>
              Attendance
              <select
                aria-label="Filter by attendance"
                value={learning.attended}
                onChange={(e) => onLearningFilters({ attended: e.target.value, page: 1 })}
              >
                <option value="">All records</option>
                <option value="attended">Attended</option>
                <option value="not_recorded">Not recorded</option>
              </select>
            </label>
          </div>
        </section>
      )}
      {tab === 'Discover training' && (
        <section className="filter-panel">
          <div className="search-line">
            <label className="search-box">
              <Search size={19} />
              <input
                aria-label="Search training"
                placeholder="Search a topic, course or provider…"
                value={q}
                onChange={(e) => onFilters({ q: e.target.value, page: 1 })}
              />
            </label>
            <button className={'secondary ' + (location ? 'chosen' : '')} onClick={onLocate}>
              <MapPin size={16} />
              {location ? 'Location selected' : 'Near me'}
            </button>
            {location && (
              <button className="text-btn" type="button" onClick={() => onFilters({ location: null, page: 1 })}>
                Clear location
              </button>
            )}
            {onClearFilters && (
              <button className="text-btn" type="button" onClick={onClearFilters}>
                Clear all filters
              </button>
            )}
          </div>
          <div className="filters">
            <label>
              City
              <input
                placeholder="City, e.g. Kuala Lumpur"
                value={city}
                onChange={(e) => onFilters({ city: e.target.value, page: 1 })}
              />
            </label>
            <label>
              State
              <input
                placeholder="State, e.g. Selangor"
                value={state}
                onChange={(e) => onFilters({ state: e.target.value, page: 1 })}
              />
            </label>
            {location && (
              <label>
                Radius
                <select
                  aria-label="Search radius"
                  value={radius}
                  onChange={(e) => onFilters({ radius: e.target.value, page: 1 })}
                >
                  {[10, 25, 50, 100].map((n) => (
                    <option key={n} value={n}>
                      {n} km
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              Format
              <select value={mode} onChange={(e) => onFilters({ mode: e.target.value, page: 1 })}>
                <option value="">Any format</option>
                <option value="in_person">In person</option>
                <option value="online">Online</option>
                <option value="hybrid">Hybrid</option>
              </select>
            </label>
            <label>
              Level
              <select value={difficulty} onChange={(e) => onFilters({ difficulty: e.target.value, page: 1 })}>
                <option value="">Any level</option>
                {['beginner', 'intermediate', 'advanced'].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <label>
              Max fee (MYR)
              <input
                type="number"
                min="0"
                placeholder="Any price"
                value={maxFee}
                onChange={(e) => onFilters({ maxFee: e.target.value, page: 1 })}
              />
            </label>
            <label>
              Min points
              <input
                type="number"
                min="0"
                placeholder="Any points"
                value={minPoints}
                onChange={(e) => onFilters({ minPoints: e.target.value, page: 1 })}
              />
            </label>
            <label>
              When
              <select value={period} onChange={(e) => onFilters({ period: e.target.value, page: 1 })}>
                <option value="upcoming">Upcoming</option>
                <option value="past">Past courses</option>
                <option value="all">All dates</option>
              </select>
            </label>
            <label>
              From
              <input type="date" value={dateFrom} onChange={(e) => onFilters({ dateFrom: e.target.value, page: 1 })} />
            </label>
            <label>
              To
              <input type="date" value={dateTo} onChange={(e) => onFilters({ dateTo: e.target.value, page: 1 })} />
            </label>
          </div>
          <label className="check-row">
            <input
              type="checkbox"
              checked={includeUnknown}
              onChange={(e) => onFilters({ includeUnknown: e.target.checked, page: 1 })}
              aria-label="Include date not confirmed and unknown fees or points"
            />
            <span>Include date not confirmed and unknown fees or points</span>
          </label>
          {location && (
            <p className="filter-note">
              Approximate straight-line distance, not travel time. Courses without venue coordinates stay visible when
              they match city or state, with distance unavailable. Online courses appear when Online, Hybrid or Any
              format is selected.
            </p>
          )}
        </section>
      )}
      <div className="results-heading">
        <span>
          {loading
            ? tab === 'My learning'
              ? 'Loading your records…'
              : 'Searching…'
            : failed
              ? "Couldn't load…"
              : `${tab === 'My learning' ? recordsTotal ?? records.length : total} ${
                  tab === 'My learning' ? 'saved records' : 'training opportunities'
                }`}
        </span>
        <span>Source-linked · Details may change</span>
      </div>
      {failed && list.length ? (
        <p className="small-note" data-testid={tab === 'My learning' ? 'learning-stale' : 'discover-stale'}>
          {tab === 'My learning'
            ? "Couldn't refresh your records. Showing the last loaded list."
            : "Couldn't refresh training. Showing the last loaded list."}{' '}
          {onRetry ? (
            <button className="text-btn" type="button" onClick={onRetry}>
              Retry
            </button>
          ) : null}
        </p>
      ) : null}
      {loading ? (
        <Loading text={tab === 'My learning' ? 'Loading your records…' : 'Finding your training…'} />
      ) : list.length ? (
        <div className="course-grid">
          {list.map((c) => (
            <CourseCard
              key={c.id}
              course={c}
              // GEO-02: My learning never has distance_km; do not inherit Discover Near-me labels.
              nearby={tab !== 'My learning' && resultsNearby}
              onOpen={() => onOpen(c)}
            />
          ))}
        </div>
      ) : (
        <Empty
          title={
            failed
              ? tab === 'My learning'
                ? "Couldn't load your records"
                : "Couldn't load training"
              : tab === 'My learning'
                ? 'Your learning story starts here'
                : 'No matching training yet'
          }
          text={
            failed
              ? 'Check your connection, then try again.'
              : tab === 'My learning'
                ? 'Open a course to record your sign-up or attendance.'
                : 'Try another city or fewer filters. The catalogue may need more sources.'
          }
          action={failed ? onRetry : onDiscover}
          actionLabel={failed ? 'Retry' : 'Explore training'}
        />
      )}
      {tab === 'Discover training' && total > 9 && (
        <div className="pagination" data-testid="discover-pager">
          <button
            className="secondary"
            disabled={loading || page === 1}
            onClick={() => (onPage ? onPage(page - 1) : onFilters({ page: page - 1 }))}
          >
            <ChevronLeft size={16} /> Previous
          </button>
          <span>
            Page {page} of {Math.ceil(total / 9)}
          </span>
          <button
            className="secondary"
            disabled={loading || page * 9 >= total}
            onClick={() => (onPage ? onPage(page + 1) : onFilters({ page: page + 1 }))}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      )}
      {tab === 'My learning' && onLearningFilters && learning && (recordsTotal ?? 0) > 9 && (
        <div className="pagination" data-testid="learning-pager">
          <button
            className="secondary"
            disabled={loading || learning.page === 1}
            onClick={() =>
              onLearningPage
                ? onLearningPage(learning.page - 1)
                : onLearningFilters({ page: learning.page - 1 })
            }
          >
            <ChevronLeft size={16} /> Previous
          </button>
          <span>
            Page {learning.page} of {Math.ceil((recordsTotal || 0) / 9)}
          </span>
          <button
            className="secondary"
            disabled={loading || learning.page * 9 >= (recordsTotal || 0)}
            onClick={() =>
              onLearningPage
                ? onLearningPage(learning.page + 1)
                : onLearningFilters({ page: learning.page + 1 })
            }
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      )}
    </>
  );
}
