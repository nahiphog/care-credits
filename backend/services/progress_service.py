"""Self-reported CPD aggregation rules shared by records, digests and certificates."""
from domain.config import today
from repository import digest_repository as store
from repository.model_helpers import counts_toward_cpd


def progress_snapshot(db, account_id: str, year: int | None = None) -> dict:
    # Callers validate year=0; do not falsy-coerce 0 into the current calendar year.
    year = today().year if year is None else year
    records = store.records_for_account(db, account_id)
    course_ids = [r.course_id for r in records]
    starts = {
        row.id: row.start_date
        for row in store.courses_by_ids(db, course_ids)
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


