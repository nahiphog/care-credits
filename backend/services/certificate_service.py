"""Printable CareCredits affiliation certificates (CERT-01 / DEC-10)."""
from __future__ import annotations

import hashlib
import html
import json
import time
import textwrap
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

from repository import certificate_repository as store

from services.progress_service import progress_snapshot
from models import Account, AffiliationCertificate


TZ = ZoneInfo('Asia/Kuala_Lumpur')
DISCLAIMER_VERSION = 'CERT-01-v2'
DISCLAIMER = (
    'This document confirms CareCredits affiliation and summarises self-reported CPD activity '
    'recorded in CareCredits. It is not an MMC, MOH, or APC compliance certificate and does not '
    'replace regulator-issued evidence.'
)


def _snapshot_hash(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_certificate_snapshot(db, row):
    event = store.snapshot_event(db, row)
    snapshot = (event.changed or {}).get('certificate_snapshot') if event else None
    if (not snapshot and row.disclaimer_version == DISCLAIMER_VERSION) or (snapshot and _snapshot_hash(snapshot) != row.document_hash):
        raise ValueError('Certificate snapshot could not be verified. Please issue a new certificate.')
    row._identity_snapshot = snapshot
    return row


def _identity(row):
    snapshot = getattr(row, '_identity_snapshot', None)
    if snapshot:
        return SimpleNamespace(**{key: (snapshot.get(key) or '') for key in ('name', 'email', 'city')})
    # Never silently regenerate an old certificate with today's mutable profile.
    return SimpleNamespace(name='Legacy record (identity not recorded)', email='', city='')


def pdf_available(row):
    identity = _identity(row)
    try:
        (identity.name + identity.email + identity.city).encode('latin-1')
        return True
    except UnicodeEncodeError:
        return False


def issue_certificate(db, account: Account, year: int) -> AffiliationCertificate:
    if not 1900 <= year <= 2200:
        raise ValueError('Invalid year.')
    progress = progress_snapshot(db, account.id, year)
    issued_at = time.time()
    row = store.create(db,
        account_id=account.id,
        year=year,
        recorded_points_snapshot=float(progress['points']),
        issued_at=issued_at,
        document_hash='',
        disclaimer_version=DISCLAIMER_VERSION,
    )
    snapshot = {
        'version': 1, 'certificate_id': row.id, 'account_id': account.id,
        'name': account.name, 'email': account.email, 'city': account.city,
        'year': year, 'recorded_points': float(progress['points']),
        'issued_at': issued_at, 'disclaimer_version': DISCLAIMER_VERSION,
    }
    row.document_hash = _snapshot_hash(snapshot)
    row._identity_snapshot = snapshot
    # Existing append-only audit JSON stores the immutable document identity;
    # no schema migration or production backfill invents historical identity.
    store.save_snapshot(db, row, snapshot)
    return row


def certificate_json(row: AffiliationCertificate) -> dict:
    return {
        'id': row.id,
        'year': row.year,
        'recorded_points_snapshot': row.recorded_points_snapshot,
        'issued_at': row.issued_at,
        'document_hash': row.document_hash,
        'disclaimer_version': row.disclaimer_version,
        'download_path': f'/api/v1/me/certificates/{row.id}?format=html',
        # SDD §10 names this download_url; keep download_path for existing clients.
        'download_url': f'/api/v1/me/certificates/{row.id}?format=html',
        'print_url': f'/api/v1/me/certificates/{row.id}?format=html',
        'pdf_download_url': f'/api/v1/me/certificates/{row.id}?format=pdf',
        'pdf_available': pdf_available(row),
        'identity_snapshot_available': bool(getattr(row, '_identity_snapshot', None)),
    }


def _pdf_escape(value: str) -> str:
    """Escape the legacy Latin-1 PDF. Unicode identities use browser print instead."""
    folded = value or ''
    return (
        folded.encode('latin-1', 'replace')
        .decode('latin-1')
        .replace('\\', '\\\\')
        .replace('(', '\\(')
        .replace(')', '\\)')
    )


def _wrap(text: str, width: int = 86) -> list[str]:
    return textwrap.wrap(text, width=width, break_long_words=True, break_on_hyphens=False)


def render_pdf(account: Account, row: AffiliationCertificate) -> bytes:
    if not pdf_available(row):
        raise ValueError('This name needs Unicode printing. Open the printable HTML certificate and use Print / Save as PDF.')
    account = _identity(row)
    issued = datetime.fromtimestamp(row.issued_at, TZ).strftime('%d %B %Y, %H:%M %Z')
    display_name = (account.name or '').strip() or 'Doctor'
    city = (account.city or '').strip()
    place = f' · {city}' if city else ''
    lines = [
        ('/F1 22 Tf', 'CareCredits'),
        ('/F1 11 Tf', 'Malaysia GP CPD tracking · affiliation record'),
        ('/F1 16 Tf', 'Affiliation certificate'),
        (
            '/F1 11 Tf',
            f'This certifies that {display_name} ({account.email}) is affiliated with CareCredits '
            f'for the calendar year {row.year}{place}.',
        ),
        ('/F1 10 Tf', 'Self-reported CPD points recorded in CareCredits'),
        ('/F1 28 Tf', f'{row.recorded_points_snapshot:g}'),
        ('/F1 11 Tf', f'Issued {issued}'),
        ('/F1 9 Tf', DISCLAIMER),
        ('/F1 8 Tf', f'Document hash: {row.document_hash} · {row.disclaimer_version}'),
    ]
    commands = ['BT', '50 790 Td']
    first = True
    for font, text in lines:
        gap = '0 -18 Td' if first else '0 -20 Td'
        first = False
        commands.append(gap)
        commands.append(font)
        wrapped = _wrap(text)
        for index, part in enumerate(wrapped):
            if index:
                commands.append('0 -12 Td')
            commands.append(f'({_pdf_escape(part)}) Tj')
    commands.append('ET')
    content = '\n'.join(commands).encode('latin-1', 'replace')
    title = _pdf_escape(f'CareCredits affiliation certificate {row.year}')
    author = _pdf_escape(display_name)
    subject = _pdf_escape('CareCredits affiliation record — not a regulator certificate')
    info = (
        f'<< /Title ({title}) /Author ({author}) /Subject ({subject}) '
        f'/Creator (CareCredits) /Producer (CareCredits CERT-01) >>'
    ).encode('latin-1', 'replace')
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
        info,
    ]
    parts = [b'%PDF-1.4\n']
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(sum(len(part) for part in parts))
        parts.append(f'{index} 0 obj\n'.encode() + body + b'\nendobj\n')
    xref_at = sum(len(part) for part in parts)
    xref = [b'xref\n0 %d\n' % (len(objects) + 1), b'0000000000 65535 f \n']
    for offset in offsets[1:]:
        xref.append(f'{offset:010d} 00000 n \n'.encode())
    trailer = (
        b'trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n'
        % (len(objects) + 1, xref_at)
    )
    return b''.join(parts + xref + [trailer])


def render_html(account: Account, row: AffiliationCertificate) -> str:
    account = _identity(row)
    legacy = '' if getattr(row, '_identity_snapshot', None) else '<p class="legacy">Legacy certificate: identity was not snapshotted at issue time. Issue a new certificate to include your current name.</p>'
    issued = datetime.fromtimestamp(row.issued_at, TZ).strftime('%d %B %Y, %H:%M %Z')
    name = html.escape((account.name or '').strip() or 'Doctor')
    email = html.escape(account.email)
    city = html.escape((account.city or '').strip())
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>CareCredits affiliation certificate — {row.year}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{
    font-family: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
    color: #10233f;
    background: linear-gradient(180deg, #f3f7fc 0%, #ffffff 40%);
    margin: 0;
    padding: 32px;
    overflow-wrap: anywhere;
  }}
  .sheet {{
    max-width: 720px;
    margin: 0 auto;
    border: 1px solid #c5d4e8;
    padding: 48px 40px;
    background: #fff;
  }}
  .brand {{
    font-size: 28px;
    letter-spacing: 0.04em;
    font-weight: 700;
    color: #0b4f9c;
  }}
  h1 {{
    font-size: 22px;
    margin: 28px 0 8px;
    font-weight: 600;
  }}
  .meta {{ margin: 0 0 24px; color: #4a607a; font-size: 14px; }}
  .points {{
    font-size: 42px;
    font-weight: 700;
    color: #0b4f9c;
    margin: 8px 0;
  }}
  .label {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: #6b7f96; }}
  .disclaimer {{
    margin-top: 36px;
    padding-top: 16px;
    border-top: 1px solid #d7e2ef;
    font-size: 12px;
    line-height: 1.5;
    color: #5a6f86;
  }}
  .hash {{ font-family: ui-monospace, Menlo, monospace; font-size: 11px; word-break: break-all; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .sheet {{ border: none; }}
    .noprint {{ display: none; }}
  }}
</style>
</head>
<body>
  <div class="sheet">
    <div class="brand">CareCredits</div>
    <p class="meta">Malaysia GP CPD tracking · affiliation record</p>
    <h1>Affiliation certificate</h1>
    {legacy}
    <p>This certifies that <strong>{name}</strong> ({email}) is affiliated with CareCredits
       for the calendar year <strong>{row.year}</strong>{f' · {city}' if city else ''}.</p>
    <p class="label">Self-reported CPD points recorded in CareCredits</p>
    <p class="points">{row.recorded_points_snapshot:g}</p>
    <p class="meta">Issued {issued}</p>
    <p class="disclaimer">{html.escape(DISCLAIMER)}</p>
    <p class="disclaimer hash">Document hash: {html.escape(row.document_hash)} · {html.escape(row.disclaimer_version)}</p>
    <p class="noprint meta"><button onclick="window.print()">Print / Save as PDF</button></p>
  </div>
</body>
</html>
"""


def create_certificate(db, user, year=None):
    from domain.config import today
    from domain.errors import DomainError
    year = today().year if year is None else year
    try:
        return certificate_json(issue_certificate(db, user, year))
    except ValueError as exc:
        raise DomainError(422, str(exc)) from exc


def certificate_history(db, user, year=None, page=1, page_size=10):
    from domain.errors import DomainError
    if page < 1 or not 1 <= page_size <= 50 or (year is not None and not 1900 <= year <= 2200):
        raise DomainError(422, 'Invalid year or pagination.')
    rows, total = store.page_for(db, user.id, year, page, page_size)
    try:
        items = [certificate_json(load_certificate_snapshot(db, row)) for row in rows]
    except ValueError as exc:
        raise DomainError(409, str(exc)) from exc
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


def download_certificate(db, user, certificate_id, format='html'):
    from domain.errors import DomainError
    row = store.get(db, certificate_id)
    if not row or row.account_id != user.id:
        raise DomainError(404, 'Certificate not found.')
    try:
        load_certificate_snapshot(db, row)
    except ValueError as exc:
        raise DomainError(409, str(exc)) from exc
    kind = (format or 'html').strip().lower()
    if kind not in ('pdf', 'html'):
        raise DomainError(422, 'Certificate format must be pdf or html.')
    filename = f'carecredits-{row.year}-{row.id[:8]}.{kind}'
    if kind == 'html':
        return render_html(user, row), 'text/html; charset=utf-8', f'inline; filename="{filename}"'
    try:
        return render_pdf(user, row), 'application/pdf', f'attachment; filename="{filename}"'
    except ValueError as exc:
        raise DomainError(422, str(exc)) from exc
