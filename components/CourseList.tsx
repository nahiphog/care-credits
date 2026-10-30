'use client';

import { ArrowRight, BookOpen, CalendarDays, Check, GraduationCap, Loader2, MapPin } from 'lucide-react';
import { Course, distanceLabel, feeLabel, formatDate, locationLabel, modeName } from '@/lib/portal';

export function DateChip({ value, className = 'event-date' }: { value?: string | null; className?: string }) {
  if (!value) {
    return (
      <span className={className}>
        <strong>—</strong>
        <small>TBC</small>
      </span>
    );
  }
  const date = new Date(value + 'T00:00:00+08:00');
  return (
    <span className={className}>
      <strong>
        {date.toLocaleDateString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', day: 'numeric' })}
      </strong>
      <small>
        {date.toLocaleDateString('en-MY', { timeZone: 'Asia/Kuala_Lumpur', month: 'short' })}
      </small>
    </span>
  );
}

export function CourseCard({
  course: c,
  onOpen,
  nearby = false,
}: {
  course: Course;
  onOpen: () => void;
  nearby?: boolean;
}) {
  return (
    <article className="course-card">
      <div className={'course-cover ' + (c.mode === 'online' ? 'peach' : c.difficulty === 'beginner' ? 'blue' : 'green')}>
        <span className="cover-label">
          <GraduationCap size={15} />
          {modeName(c.mode)}
        </span>
        <DateChip value={c.start_date} className="course-date" />
        <span className="point-badge">
          {c.points !== null ? `${c.points} ${c.credit_label || 'credits'}` : 'Points not listed'}
        </span>
      </div>
      <div className="course-body">
        <div className="course-tags">
          {c.demo && <span className="tag">Demo</span>}
          <span>{c.difficulty || 'Level not listed'}</span>
          {c.record?.attendance_status === 'attended' || c.record?.attended ? (
            <span className="record-status">
              <Check size={13} /> Attended
            </span>
          ) : c.record?.signup_status === 'cancelled' ? (
            <span className="record-status">Sign-up cancelled</span>
          ) : (
            (c.record?.signup_status === 'signed_up' || c.record?.signed_up) && (
              <span className="record-status">Signed up</span>
            )
          )}
        </div>
        <h3>
          <button onClick={onOpen}>{c.title}</button>
        </h3>
        <p className="provider">{c.provider}</p>
        <div className="course-meta">
          <span>
            <CalendarDays size={15} />
            {formatDate(c.start_date)}
          </span>
          <span>
            <MapPin size={15} />
            {locationLabel(c)}
            {distanceLabel(c, nearby)}
          </span>
        </div>
        <div className="card-bottom">
          <strong>{feeLabel(c)}</strong>
          <button aria-label={'View ' + c.title} className="text-btn" onClick={onOpen}>
            View details <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </article>
  );
}

export function Empty({
  title,
  text,
  action,
  actionLabel = 'Explore training',
}: {
  title: string;
  text: string;
  action?: () => void;
  actionLabel?: string;
}) {
  return (
    <div className="empty-state">
      <BookOpen size={30} aria-hidden="true" />
      <h3>{title}</h3>
      <p>{text}</p>
      {action && (
        <button className="secondary" onClick={action}>
          {actionLabel} <ArrowRight size={16} />
        </button>
      )}
    </div>
  );
}

export function Loading({ text = 'Finding your training…' }: { text?: string }) {
  return (
    <div className="empty-state" role="status">
      <Loader2 className="spin" />
      <p>{text}</p>
    </div>
  );
}
