"""Printable CareCredits affiliation certificates (CERT-01 / DEC-10)."""
from __future__ import annotations

import hashlib
import html
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from digest import progress_snapshot
from portal_models import Account, AffiliationCertificate


TZ = ZoneInfo('Asia/Kuala_Lumpur')
DISCLAIMER_VERSION = 'CERT-01-v1'
DISCLAIMER = (
    'This document confirms CareCredits affiliation and summarises self-reported CPD activity '
    'recorded in CareCredits. It is not an MMC, MOH, or APC compliance certificate and does not '
    'replace regulator-issued evidence.'
)


def issue_certificate(db: Session, account: Account, year: int) -> AffiliationCertificate:
    if not 1900 <= year <= 2200:
        raise ValueError('Invalid year.')
    progress = progress_snapshot(db, account.id, year)
    issued_at = time.time()
    material = '|'.join([
        account.id,
        str(year),
        str(progress['points']),
        DISCLAIMER_VERSION,
        f'{issued_at:.6f}',
    ])
    document_hash = hashlib.sha256(material.encode()).hexdigest()
    row = AffiliationCertificate(
        account_id=account.id,
        year=year,
        recorded_points_snapshot=float(progress['points']),
        issued_at=issued_at,
        document_hash=document_hash,
        disclaimer_version=DISCLAIMER_VERSION,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def certificate_json(row: AffiliationCertificate) -> dict:
    return {
        'id': row.id,
        'year': row.year,
        'recorded_points_snapshot': row.recorded_points_snapshot,
        'issued_at': row.issued_at,
        'document_hash': row.document_hash,
        'disclaimer_version': row.disclaimer_version,
        'download_path': f'/api/v1/me/certificates/{row.id}',
        # SDD §10 names this download_url; keep download_path for existing clients.
        'download_url': f'/api/v1/me/certificates/{row.id}',
    }


def _pdf_escape(value: str) -> str:
    """Fold Unicode to Helvetica-safe Latin-1 (core PDF fonts have no CJK/Malay diacritics).

    HTML certificates keep the original Unicode; PDF approximates accents then replaces
    remaining non-Latin-1 glyphs so names never crash rendering.
    """
    folded = unicodedata.normalize('NFKD', value or '')
    folded = ''.join(ch for ch in folded if not unicodedata.combining(ch))
    return (
        folded.encode('latin-1', 'replace')
        .decode('latin-1')
        .replace('\\', '\\\\')
        .replace('(', '\\(')
        .replace(')', '\\)')
    )


def _wrap(text: str, width: int = 86) -> list[str]:
    lines: list[str] = []
    current = ''
    for word in text.split():
        trial = (current + ' ' + word).strip()
        if len(trial) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_pdf(account: Account, row: AffiliationCertificate) -> bytes:
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
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
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
