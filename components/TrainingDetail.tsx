'use client';

import { FormEvent, useEffect, useRef } from 'react';
import { Check, ExternalLink, X } from 'lucide-react';
import {
  Course,
  RecordData,
  RecordHistoryItem,
  feeLabel,
  formatDate,
  locationLabel,
  modeName,
  publicWebUrl,
  todayLocal,
} from '@/lib/portal';

export function TrainingDetail({
  course,
  edit,
  error,
  saving,
  history = [],
  historyFailed = false,
  onClose,
  onEdit,
  onSave,
  onRetryHistory,
  onRetryError,
  canCancel = false,
  onCancel,
}: {
  course: Course;
  edit: RecordData;
  error: string;
  saving: boolean;
  history?: RecordHistoryItem[];
  historyFailed?: boolean;
  onClose: () => void;
  onEdit: (next: RecordData) => void;
  onSave: (event: FormEvent) => void;
  onRetryHistory?: () => void;
  /** When set, modal errors expose Retry (e.g. re-run cancel / save). */
  onRetryError?: () => void;
  canCancel?: boolean;
  onCancel?: () => void;
}) {
  const attendable = !course.start_date || course.start_date <= todayLocal();
  // Prefer status, but honour legacy bool drift (same as CourseList / `/live` badges).
  // Do not use `status || fallback`: `not_recorded` is truthy and would hide a drifted attended/signed_up bool.
  const isAttended = edit.attendance_status === 'attended' || edit.attended;
  const signupValue: RecordData['signup_status'] =
    edit.signup_status === 'cancelled'
      ? 'cancelled'
      : edit.signup_status === 'signed_up' || edit.signed_up
        ? 'signed_up'
        : 'not_recorded';
  const attendanceValue: NonNullable<RecordData['attendance_status']> = isAttended
    ? 'attended'
    : 'not_recorded';
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const sourceHref = publicWebUrl(course.source_url);
  const registrationHref = publicWebUrl(course.registration_url);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const priorOverflow = document.body.style.overflow;
    const priorHtmlOverflow = document.documentElement.style.overflow;
    document.body.style.overflow = 'hidden';
    document.documentElement.style.overflow = 'hidden';
    document.body.classList.add('modal-open');
    // Focus close once on open. Keep onClose in a ref so parent re-renders (edit keystrokes)
    // do not tear down the Tab trap mid-dialog.
    closeRef.current?.focus();
    const focusables = () => {
      if (!dialogRef.current) return [] as HTMLElement[];
      return Array.from(
        dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]),a[href],input:not([disabled]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => !el.hasAttribute('disabled') && el.getAttribute('aria-hidden') !== 'true');
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialogRef.current) return;
      const items = focusables();
      if (!items.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      const inside = active ? dialogRef.current.contains(active) : false;
      if (!inside) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
        return;
      }
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = priorOverflow;
      document.documentElement.style.overflow = priorHtmlOverflow;
      document.body.classList.remove('modal-open');
      previous?.focus();
    };
  }, []);
  return (
    <div className="modal-shade" onClick={onClose}>
      <section
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="training-title"
        aria-describedby="training-disclaimer"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <button
          ref={closeRef}
          className="modal-close icon-btn"
          aria-label="Close training details"
          onClick={onClose}
        >
          <X />
        </button>
        <span className="pill">
          {modeName(course.mode)} {course.demo ? '· Demo course' : ''}
          {course.verification_status === 'source_reviewed' ? ' · Source reviewed' : ' · Unverified claims'}
        </span>
        <h2 id="training-title">{course.title}</h2>
        <p className="muted">{course.provider}</p>
        <p>{course.description}</p>
        <div className="detail-grid">
          <div>
            <small>Date</small>
            <strong>
              {formatDate(course.start_date)}
              {course.end_date ? ` – ${formatDate(course.end_date)}` : ''}
              {course.timezone ? ` · ${course.timezone}` : ''}
            </strong>
          </div>
          <div>
            <small>Location</small>
            <strong>{locationLabel(course)}</strong>
          </div>
          <div>
            <small>Fee</small>
            <strong>{feeLabel(course)}</strong>
          </div>
          <div>
            <small>Advertised credits</small>
            <strong>
              {course.points ?? 'Not listed'} {course.credit_label || ''}
            </strong>
          </div>
          <div>
            <small>Level</small>
            <strong>{course.difficulty || 'Not listed'}</strong>
          </div>
          <div>
            <small>Prerequisites</small>
            <strong>
              {course.prerequisites || 'Unknown — source does not establish prerequisites'}
            </strong>
          </div>
        </div>
        {(course.field_evidence?.length || Object.keys(course.evidence || {}).length) ? (
          <details className="source-evidence"><summary>Source evidence</summary><p className="small-note">Quoted supporting text for the published course details.</p><dl className="evidence">
            {(course.field_evidence?.length
              ? course.field_evidence.map((row) => [row.field_name, row.excerpt] as const)
              : Object.entries(course.evidence)
            ).map(([field, excerpt]) => (
              <div key={field}>
                <dt>{field.replaceAll('_', ' ')}</dt>
                <dd>{excerpt}</dd>
              </div>
            ))}
          </dl></details>
        ) : null}
        <div className="button-row">
          {registrationHref ? (
            <a className="secondary" href={registrationHref} target="_blank" rel="noreferrer">
              Provider registration <ExternalLink size={14} />
            </a>
          ) : null}
          {sourceHref ? (
            <a className="text-btn" href={sourceHref} target="_blank" rel="noreferrer">
              View original source <ExternalLink size={14} />
            </a>
          ) : (
            <span className="small-note">Original source URL is not available.</span>
          )}
          {canCancel && onCancel && course.publication_status !== 'cancelled' ? (
            <button type="button" className="text-btn" disabled={saving} onClick={onCancel}>
              Cancel published session
            </button>
          ) : null}
          {course.publication_status === 'cancelled' ? <span className="small-note">Session cancelled; personal records are kept.</span> : null}
        </div>
        <p className="small-note" id="training-disclaimer">
          Confirm details and CPD eligibility with the provider. Opening a link does not register you.
          Attendance you record here is self-reported and is not MMC, MOH, or APC proof.
        </p>
        <hr />
        <form onSubmit={onSave}>
          <h3>Your personal record</h3>
          {error && (
            <p className="alert error" role="alert">
              {error}
              {onRetryError ? (
                <>
                  {' '}
                  <button className="text-btn" type="button" disabled={saving} onClick={onRetryError}>
                    Retry
                  </button>
                </>
              ) : null}
            </p>
          )}
          <label>
            Provider sign-up
            <select
              aria-label="Provider sign-up status"
              value={signupValue}
              onChange={(e) =>
                onEdit({
                  ...edit,
                  signup_status: e.target.value as RecordData['signup_status'],
                  signed_up: e.target.value === 'signed_up',
                })
              }
            >
              <option value="not_recorded">Not recorded</option>
              <option value="signed_up">Signed up with the provider</option>
              {(signupValue === 'signed_up' || signupValue === 'cancelled') && (
                <option value="cancelled">Cancelled sign-up</option>
              )}
            </select>
          </label>
          <label>
            Attendance
            <select
              aria-label="Attendance status"
              value={attendanceValue}
              disabled={!attendable && !isAttended}
              onChange={(e) => {
                const attendance_status = e.target.value as RecordData['attendance_status'];
                const attended = attendance_status === 'attended';
                onEdit({
                  ...edit,
                  attendance_status,
                  attended,
                  attended_on: attended ? edit.attended_on || todayLocal() : null,
                  public: attended ? edit.public : false,
                });
              }}
            >
              <option value="not_recorded">Not recorded</option>
              <option value="attended">Attended</option>
            </select>
            {!attendable && !isAttended && (
              <small> Attendance can be recorded after the session date ({formatDate(course.start_date)}).</small>
            )}
          </label>
          {isAttended && (
            <>
              <div className="form-grid">
                <label>
                  Completion date
                  <input
                    required
                    type="date"
                    max={todayLocal()}
                    value={edit.attended_on || ''}
                    onChange={(e) => onEdit({ ...edit, attended_on: e.target.value })}
                  />
                </label>
                <label>
                  Points I recorded
                  <input
                    type="number"
                    min="0"
                    max="10000"
                    step="0.1"
                    placeholder="Unknown"
                    value={edit.points ?? ''}
                    onChange={(e) =>
                      onEdit({
                        ...edit,
                        points: e.target.value === '' ? null : Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  Original credit label
                  <input
                    required
                    maxLength={30}
                    value={edit.credit_label}
                    onChange={(e) => onEdit({ ...edit, credit_label: e.target.value })}
                  />
                </label>
              </div>
              <label className="check-row">
                <input
                  type="checkbox"
                  checked={edit.public}
                  onChange={(e) => onEdit({ ...edit, public: e.target.checked })}
                />
                <span>
                  Show on my public profile
                  <small>Visible only when your profile is also public. Labelled self-reported.</small>
                </span>
              </label>
            </>
          )}
          <label>
            Private learning notes
            <textarea
              placeholder="What did you learn? Where is your certificate stored?"
              value={edit.notes}
              maxLength={5000}
              onChange={(e) => onEdit({ ...edit, notes: e.target.value })}
            />
          </label>
          <button className="primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save my record'} <Check size={16} />
          </button>
          {historyFailed ? (
            <p className="small-note" data-testid="history-failed">
              Couldn&apos;t load correction history. Check your connection, then try again.
              {onRetryHistory ? (
                <>
                  {' '}
                  <button className="text-btn" type="button" onClick={onRetryHistory}>
                    Retry
                  </button>
                </>
              ) : null}
            </p>
          ) : history.length > 0 ? (
            <div className="small-note">
              <p>Correction history. Cancelling sign-up does not erase attendance.</p>
              <ol className="source-list">
                {history.map((item, index) => (
                  <li key={`${item.at}-${index}`}>
                    {item.at ? new Date(item.at * 1000).toLocaleString('en-MY') : 'Earlier'}
                    {item.signup_status ? ` · sign-up ${item.signup_status.replaceAll('_', ' ')}` : ''}
                    {item.attendance_status === 'attended' || item.attended
                      ? ' · attended'
                      : item.attendance_status != null || item.attended != null
                        ? ' · not attended'
                        : ''}
                    {item.attended_on ? ` · ${item.attended_on}` : ''}
                    {item.points != null ? ` · ${item.points} ${item.credit_label || ''}`.trim() : ''}
                  </li>
                ))}
              </ol>
            </div>
          ) : null}
        </form>
      </section>
    </div>
  );
}
