"""Biweekly digest compose + send (NTF-01 / DEC-10). Never calls Tavily."""
from __future__ import annotations

import html
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from portal_models import Account, Course, DigestPreference, DigestSend, Record, uid, counts_toward_cpd, listed_filter
from security import digest as hash_digest


TZ = ZoneInfo('Asia/Kuala_Lumpur')
BACKOFF_SECONDS = (15 * 60, 60 * 60, 4 * 3600, 12 * 3600, 24 * 3600)
DISCLAIMER = (
    'CareCredits digests summarise catalogue listings and your self-reported progress. '
    'They are not MMC, MOH, or APC compliance statements.'
)


def local_now() -> datetime:
    return datetime.now(TZ)


def backoff_seconds(fail_count: int) -> int:
    if fail_count < 1:
        return BACKOFF_SECONDS[0]
    return BACKOFF_SECONDS[min(fail_count, len(BACKOFF_SECONDS)) - 1]


def progress_snapshot(db: Session, account_id: str, year: int | None = None) -> dict:
    # Callers validate year=0; do not falsy-coerce 0 into the current calendar year.
    year = local_now().year if year is None else year
    records = db.query(Record).filter_by(account_id=account_id).all()
    course_ids = [r.course_id for r in records]
    starts = {
        row.id: row.start_date
        for row in db.query(Course).filter(Course.id.in_(course_ids)).all()
    } if course_ids else {}
    attended = [r for r in records if (getattr(r, 'attendance_status', None) == 'attended' or r.attended) and r.attended_on and r.attended_on.startswith(str(year))]
    countable = [r for r in attended if counts_toward_cpd(r)]
    excluded_reasons = []
    for row in attended:
        if row.points is None:
            excluded_reasons.append({'reason': 'unknown_points', 'credit_label': row.credit_label})
        elif not counts_toward_cpd(row):
            excluded_reasons.append({'reason': 'unmapped_credit_label', 'credit_label': row.credit_label})
    signed_up = 0
    for row in records:
        # Prefer signup_status: cancelled must not count as open even if legacy signed_up bool drifted.
        signup_status = getattr(row, 'signup_status', None)
        if signup_status == 'cancelled':
            continue
        open_signup = (signup_status == 'signed_up' or row.signed_up) and not (
            getattr(row, 'attendance_status', None) == 'attended' or row.attended
        )
        if not open_signup:
            continue
        start = starts.get(row.course_id) or ''
        if start.startswith(str(year)):
            signed_up += 1
    return {
        'year': year,
        'signed_up': signed_up,
        'attended': len(attended),
        'points': round(sum(r.points for r in countable), 2),
        'excluded': len(excluded_reasons),
        'excluded_reasons': excluded_reasons,
    }


def upcoming_sessions(db: Session, city: str | None, limit: int = 8) -> list[dict]:
    from sqlalchemy import func

    today = local_now().date().isoformat()
    query = db.query(Course).filter(listed_filter(), Course.start_date != None, Course.start_date >= today)
    city_key = (city or '').strip().casefold() or None
    if city_key:
        # Trim + casefold so padded / mixed-case extraction cities still match (PROG-02 parity).
        same_city = query.filter(func.lower(func.trim(Course.city)) == city_key).order_by(Course.start_date).limit(limit).all()
        if same_city:
            rows = same_city
        else:
            rows = query.order_by(Course.start_date).limit(limit).all()
    else:
        rows = query.order_by(Course.start_date).limit(limit).all()
    items = []
    for course in rows:
        fee = course.fee
        # Whitespace-only currency is missing (same honesty as blank name/place).
        currency = (course.currency or '').strip() or None
        if fee is None:
            price_label = 'Price unknown'
        elif float(fee) == 0:
            price_label = 'Free'
        elif currency:
            amount = int(fee) if float(fee).is_integer() else fee
            price_label = f'{amount} {currency}'
        else:
            # Do not invent MYR when a fee lacks currency (SDD fee honesty).
            amount = int(fee) if float(fee).is_integer() else fee
            price_label = f'{amount} (currency unknown)'
        items.append({
            'id': course.id,
            'title': course.title,
            'provider': course.provider,
            'start_date': course.start_date,
            'city': course.city,
            'mode': course.mode,
            'fee': fee,
            'currency': currency,
            'price_label': price_label,
            'points': course.points,
            'credit_label': course.credit_label,
        })
    return items


def compose_digest(db: Session, account: Account) -> dict:
    progress = progress_snapshot(db, account.id)
    sessions = upcoming_sessions(db, account.city)
    return {
        'to': account.email,
        'name': account.name,
        'city': account.city,
        'progress': progress,
        'sessions': sessions,
        'disclaimer': DISCLAIMER,
        'composed_at': local_now().isoformat(),
    }


def _digest_name(payload: dict) -> str:
    # Parity for HTML + plain: blank/whitespace names must not render as "Hi None," / "Hi ,".
    return str(payload.get('name') or '').strip() or 'Doctor'


def _digest_place(item: dict) -> str:
    place = str(item.get('city') or '').strip() or str(item.get('mode') or '').strip()
    return place or 'location unknown'


def render_text(payload: dict, unsubscribe_url: str) -> str:
    progress = payload['progress']
    lines = [
        f"Hi {_digest_name(payload)},",
        '',
        f"Your CareCredits digest for {progress['year']}:",
        f"- Recorded CPD points: {progress['points']}",
        f"- Attended this year: {progress['attended']}",
        f"- Signed up (not yet attended): {progress['signed_up']}",
        f"- Excluded from CPD total: {progress['excluded']}",
        '',
        'Upcoming catalogue sessions:',
    ]
    if not payload['sessions']:
        lines.append('- None listed yet. Check the portal after the next daily catalogue refresh.')
    for item in payload['sessions']:
        points = f"{item['points']} {item['credit_label'] or 'CPD'}" if item['points'] is not None else 'points unknown'
        lines.append(
            f"- {item['start_date']} | {item['title']} ({item['provider']}) | "
            f"{_digest_place(item)} | {item['price_label']} | {points}"
        )
    lines.extend(['', DISCLAIMER, '', f'Unsubscribe: {unsubscribe_url}', ''])
    return '\n'.join(lines)


def render_html(payload: dict, unsubscribe_url: str) -> str:
    """Multipart HTML alternative; escape every catalogue/account field."""
    progress = payload['progress']
    name = html.escape(_digest_name(payload))
    year = html.escape(str(progress.get('year') or ''))
    rows = []
    if not payload.get('sessions'):
        rows.append('<li>None listed yet. Check the portal after the next daily catalogue refresh.</li>')
    for item in payload.get('sessions') or []:
        points = (
            f"{html.escape(str(item['points']))} {html.escape(str(item.get('credit_label') or 'CPD'))}"
            if item.get('points') is not None
            else 'points unknown'
        )
        place = html.escape(_digest_place(item))
        rows.append(
            '<li>'
            f"{html.escape(str(item.get('start_date') or ''))} | "
            f"{html.escape(str(item.get('title') or ''))} "
            f"({html.escape(str(item.get('provider') or ''))}) | "
            f"{place} | {html.escape(str(item.get('price_label') or ''))} | {points}"
            '</li>'
        )
    unsub = html.escape(unsubscribe_url, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/><title>CareCredits digest</title></head>
<body style="font-family:Georgia,serif;color:#10233f;max-width:36rem;margin:0 auto;padding:1rem;">
  <p>Hi {name},</p>
  <p>Your CareCredits digest for {year}:</p>
  <ul>
    <li>Recorded CPD points: {html.escape(str(progress.get('points')))}</li>
    <li>Attended this year: {html.escape(str(progress.get('attended')))}</li>
    <li>Signed up (not yet attended): {html.escape(str(progress.get('signed_up')))}</li>
    <li>Excluded from CPD total: {html.escape(str(progress.get('excluded')))}</li>
  </ul>
  <p>Upcoming catalogue sessions:</p>
  <ul>
    {''.join(rows)}
  </ul>
  <p style="color:#3d536b;font-size:0.95rem;">{html.escape(DISCLAIMER)}</p>
  <p><a href="{unsub}">Unsubscribe</a></p>
</body>
</html>"""


def send_via_provider(to: str, subject: str, body: str, html_body: str | None = None) -> dict:
    provider = (os.getenv('MAIL_PROVIDER') or 'log').strip().lower()
    if provider == 'log':
        out = Path(os.getenv('DIGEST_LOG_DIR') or Path(__file__).resolve().parents[1] / '.data' / 'digests')
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
        stem = f'{stamp}-{hash_digest(to)[:12]}'
        path = out / f'{stem}.txt'
        path.write_text(f'To: {to}\nSubject: {subject}\n\n{body}', encoding='utf-8')
        if html_body:
            (out / f'{stem}.html').write_text(html_body, encoding='utf-8')
        return {'status': 'sent', 'provider_message_id': str(path), 'error': ''}
    if provider == 'smtp':
        import smtplib
        from email.message import EmailMessage

        host = os.getenv('SMTP_HOST') or ''
        port = int(os.getenv('SMTP_PORT') or '587')
        user = os.getenv('SMTP_USER') or ''
        password = os.getenv('SMTP_PASSWORD') or ''
        from_addr = os.getenv('SMTP_FROM') or user
        if not host or not from_addr:
            return {'status': 'failed', 'provider_message_id': None, 'error': 'SMTP is not configured.'}
        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = from_addr
        message['To'] = to
        # Plain first, then HTML alternative so clients that prefer HTML still keep a text part.
        message.set_content(body)
        if html_body:
            message.add_alternative(html_body, subtype='html')
        # Hint clients/list-unsub tooling at the one-click NTF-01 link embedded in the body.
        for line in body.splitlines():
            if line.startswith('Unsubscribe: '):
                message['List-Unsubscribe'] = f'<{line[len("Unsubscribe: "):].strip()}>'
                break
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.starttls()
            if user:
                client.login(user, password)
            client.send_message(message)
        return {'status': 'sent', 'provider_message_id': f'smtp:{to}', 'error': ''}
    return {'status': 'failed', 'provider_message_id': None, 'error': f'Unknown MAIL_PROVIDER={provider}'}


def ensure_preference(db: Session, account_id: str) -> DigestPreference:
    pref = db.get(DigestPreference, account_id)
    if pref:
        return pref
    pref = DigestPreference(account_id=account_id, unsubscribe_token=uid())
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def preference_json(pref: DigestPreference) -> dict:
    return {
        'opted_in': pref.opted_in,
        'cadence_days': pref.cadence_days,
        'last_sent_at': pref.last_sent_at,
        'unsubscribed_at': pref.unsubscribed_at,
    }


def due_preferences(db: Session, now: float | None = None) -> list[DigestPreference]:
    now = now if now is not None else time.time()
    rows = db.query(DigestPreference).filter_by(opted_in=True).all()
    due = []
    for pref in rows:
        retry_at = getattr(pref, 'next_retry_at', None)
        if retry_at is not None and now < retry_at:
            continue
        cadence = max(1, pref.cadence_days or 14) * 86400
        if pref.last_sent_at is None or (now - pref.last_sent_at) >= cadence:
            due.append(pref)
    return due


def send_digest(db: Session, account: Account, pref: DigestPreference, public_base: str, now: float | None = None) -> DigestSend:
    now = now if now is not None else time.time()
    payload = compose_digest(db, account)
    unsub = f"{public_base.rstrip('/')}/api/v1/digest/unsubscribe?token={pref.unsubscribe_token}"
    body = render_text(payload, unsub)
    html_body = render_html(payload, unsub)
    subject = f"CareCredits digest — {payload['progress']['year']} progress + upcoming CPD"
    result = send_via_provider(account.email, subject, body, html_body=html_body)
    row = DigestSend(
        account_id=account.id,
        status=result['status'],
        event_count=len(payload.get('sessions') or []),
        recorded_points_snapshot=float((payload.get('progress') or {}).get('points') or 0),
        provider_message_id=result.get('provider_message_id'),
        error=result.get('error') or '',
        payload=payload,
    )
    db.add(row)
    if result['status'] == 'sent':
        pref.last_sent_at = now
        pref.fail_count = 0
        pref.next_retry_at = None
    else:
        pref.fail_count = (pref.fail_count or 0) + 1
        pref.next_retry_at = now + backoff_seconds(pref.fail_count)
    db.commit()
    db.refresh(row)
    return row


def run_due_digests(db: Session, public_base: str | None = None, now: float | None = None) -> dict:
    # Prefer the public Next BFF host so email clients hit `/api/v1/...` through the portal
    # (same cookie/API surface as OAuth). Fall back to PUBLIC_API_BASE for API-direct demos.
    base = (
        public_base
        or (os.getenv('PUBLIC_FRONTEND_BASE') or '').strip()
        or (os.getenv('PUBLIC_API_BASE') or '').strip()
        or 'http://127.0.0.1:3000'
    )
    now = now if now is not None else time.time()
    sent = 0
    failed = 0
    for pref in due_preferences(db, now):
        account = db.get(Account, pref.account_id)
        if not account or account.role != 'doctor':
            continue
        row = send_digest(db, account, pref, base, now=now)
        if row.status == 'sent':
            sent += 1
        else:
            failed += 1
    return {'sent': sent, 'failed': failed, 'day': local_now().date().isoformat()}
