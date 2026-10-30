"""Owner export formatting and scope rules; independent of HTTP transport."""
import csv
import io
from email.message import EmailMessage
from domain.errors import DomainError
from shared.contracts import public_web_url
from repository.learning_repository import record_course_pairs

def export_records(db, user, kind, year=None):
    if year is not None and not 1900 <= year <= 2200:
        raise DomainError(422, 'Invalid year.')
    rows = record_course_pairs(db, user.id)
    if year is not None:
        year_key = str(year)
        scoped = []
        for r, c in rows:
            attended = getattr(r, 'attendance_status', None) == 'attended' or bool(r.attended)
            # Match PROG-01: attended rows use attended_on year; open/other rows use course start_date year.
            if attended:
                if r.attended_on and str(r.attended_on).startswith(year_key):
                    scoped.append((r, c))
            elif (c.start_date or '').startswith(year_key):
                scoped.append((r, c))
        rows = scoped
    def cell(value):
        value = str(value or '')
        # Strip BOM / zero-width / Unicode spaces / line-breaks before formula detection (CSV/Excel injection).
        visible = value.lstrip(
            ' \t\r\n\x0b\x0c\ufeff\u200b\u200c\u200d\u2060'
            '\u00a0\u1680\u180e\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
            '\u2028\u2029\u202f\u205f\u3000'
            # Bidi marks / embeddings / overrides / isolates can hide =+@- from Excel.
            '\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069'
            # Soft hyphen / CGJ / Arabic letter mark also hide formula starters in some Excel builds.
            '\u00ad\u034f\u061c'
        )
        # ASCII formula starters plus fullwidth / Unicode minus forms Excel may still treat as formulas.
        starters = (
            '=', '+', '-', '@',
            '\uff1d', '\uff0b', '\uff0d', '\uff20',
            '\u2212',  # MINUS SIGN
            '\ufe63',  # SMALL HYPHEN-MINUS
        )
        return "'" + value if visible[:1] in starters else value
    suffix = f'-{year}' if year is not None else ''
    if kind == 'csv':
        stream = io.StringIO()
        writer = csv.writer(stream)
        # Owner export is complete for tracking fields; private notes stay out of CSV and the public profile.
        writer.writerow([
            'Training', 'Provider', 'Session date', 'Signed up', 'Signup status', 'Attended',
            'Attendance status', 'Completed on', 'Recorded points', 'Credit label', 'Source', 'Evidence status',
        ])
        for r, c in rows:
            signup_status = getattr(r, 'signup_status', None) or ('signed_up' if r.signed_up else 'not_recorded')
            attendance_status = getattr(r, 'attendance_status', None) or ('attended' if r.attended else 'not_recorded')
            attended = attendance_status == 'attended' or bool(r.attended)
            # Match progress_snapshot / PROG-02: cancelled must not look open if signed_up bool drifted.
            signed_up = signup_status != 'cancelled' and (signup_status == 'signed_up' or bool(r.signed_up))
            writer.writerow([
                cell(c.title),
                cell(c.provider),
                cell(c.start_date or ''),
                signed_up,
                cell(signup_status),
                attended,
                cell(attendance_status),
                cell(r.attended_on or ''),
                r.points if r.points is not None else '',
                cell(r.credit_label),
                cell(public_web_url((c.data or {}).get('source_url')) or ''),
                'Self-reported',
            ])
        content, mime = stream.getvalue(), 'text/csv; charset=utf-8'
    else:
        message = EmailMessage()
        subject_year = f' ({year})' if year is not None else ''
        message['Subject'] = f'My CPD training record{subject_year}'
        message['X-Unsent'] = '1'
        lines = ['My personal training record (self-reported, not independently verified):', '']
        if year is not None:
            lines.append(f'Year filter: {year} (attended_on for attended rows; session start_date otherwise).')
            lines.append('')
        attended_lines = []
        for r, c in rows:
            if getattr(r, 'attendance_status', None) == 'attended' or r.attended:
                attended_lines.append(
                    f"{c.title} | {r.attended_on} | {r.points if r.points is not None else 'Not recorded'} {r.credit_label}"
                )
        if attended_lines:
            lines.extend(attended_lines)
        else:
            # Honest empty body: header-only CSV already discloses emptiness; EML must say so explicitly.
            if year is not None:
                lines.append(f'No attended records for {year}.')
            else:
                lines.append('No attended records yet.')
        message.set_content('\n'.join(lines))
        content, mime = message.as_bytes(), 'message/rfc822'
    return content, mime, f'carecredits-record{suffix}.{kind}'
