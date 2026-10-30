"""Suggested upcoming catalogue sessions (PROG-02). Advisory only."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo




from models import Account
from repository import suggestion_repository as store
from repository.digest_repository import records_for_account, courses_by_ids


TZ = ZoneInfo('Asia/Kuala_Lumpur')
ADVISORY = (
    'Suggestions are advisory only. CareCredits does not decide MMC/MOH/APC compliance.'
)
VALID_MODES = frozenset({'in_person', 'online', 'hybrid'})


def _city_key(value: str | None) -> str | None:
    # Strip + casefold so padded / mixed-case extraction cities still rank (FIND-01 ilike parity).
    cleaned = (value or '').strip().casefold()
    return cleaned or None


def suggestions_for(db, account: Account, limit: int = 10) -> dict:
    today = datetime.now(TZ).date().isoformat()
    # Display keeps profile casing; match key is stripped + casefolded.
    display_city = (account.city or '').strip() or None
    city = _city_key(account.city)
    records = records_for_account(db, account.id)
    # Match progress/digest status fields so legacy bool drift cannot re-suggest attended/signed-up rows.
    attended_ids = {
        r.course_id
        for r in records
        if getattr(r, 'attendance_status', None) == 'attended' or r.attended
    }
    signed_ids = {
        r.course_id
        for r in records
        # Cancelled must not count as open sign-up even if legacy signed_up bool drifted.
        if getattr(r, 'signup_status', None) != 'cancelled'
        and (getattr(r, 'signup_status', None) == 'signed_up' or r.signed_up)
    }
    skip = attended_ids | signed_ids
    # PROG-02: most recent attended delivery mode (not majority vote); skip junk modes.
    preferred_mode = None
    if attended_ids:
        courses_by_id = {
            course.id: course
            for course in courses_by_ids(db, attended_ids)
        }
        attended_rows = [
            r for r in records
            if r.course_id in attended_ids
        ]
        # Latest attended_on first; missing dates sort last.
        attended_rows.sort(key=lambda r: (r.attended_on or ''), reverse=True)
        for row in attended_rows:
            mode = getattr(courses_by_id.get(row.course_id), 'mode', None)
            if mode in VALID_MODES:
                preferred_mode = mode
                break
    buckets = store.candidate_buckets(db, today, city, preferred_mode, skip, limit)
    seen = set()
    ordered = []
    for group in buckets:
        for course in group:
            if course.id in skip or course.id in seen:
                continue
            seen.add(course.id)
            ordered.append(course)
            if len(ordered) >= limit:
                break
        if len(ordered) >= limit:
            break
    items = []
    for course in ordered:
        city_match = bool(city and _city_key(course.city) == city)
        mode_match = bool(preferred_mode and course.mode == preferred_mode)
        if not course.start_date:
            reason = 'Online learning — date not listed; confirm availability with the provider'
        elif city_match and mode_match:
            reason = 'Matches your city and recent learning mode'
        elif city_match:
            reason = 'Matches your city'
        elif mode_match:
            reason = 'Matches a recent learning mode'
        else:
            reason = 'Upcoming catalogue listing'
        items.append({
            'id': course.id,
            'title': course.title,
            'provider': course.provider,
            'start_date': course.start_date,
            'city': course.city,
            'mode': course.mode,
            'fee': course.fee,
            'currency': course.currency,
            'points': course.points,
            'credit_label': course.credit_label,
            'reason': reason,
        })
    return {'items': items, 'advisory': ADVISORY, 'city': display_city, 'preferred_mode': preferred_mode}
