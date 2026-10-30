'use client';

import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { api } from '@/lib/portal';

type Certificate = {
  id: string;
  year: number;
  issued_at: number;
  recorded_points_snapshot: number;
  identity_snapshot_available: boolean;
  pdf_available: boolean;
};

/** Issuance never opens a popup after await: the saved document remains in history. */
export function CertificatePanel({ year }: { year: number }) {
  return <YearCertificates key={year} year={year} />;
}

function YearCertificates({ year }: { year: number }) {
  const [items, setItems] = useState<Certificate[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const request = useRef(0);
  const activeYear = useRef(year);


  async function load(nextPage = 1, targetYear = year) {
    const id = ++request.current;
    setLoading(true);
    setError('');
    try {
      const result = await api(`/me/certificates?year=${targetYear}&page=${nextPage}&page_size=10`);
      if (id !== request.current || targetYear !== activeYear.current) return;
      setItems(result.items || []);
      setTotal(result.total || 0);
      setPage(nextPage);
    } catch (e) {
      if (id === request.current) setError((e as Error).message || 'Certificate history could not be loaded.');
    } finally {
      if (id === request.current) setLoading(false);
    }
  }

  const loadInitialHistory = useEffectEvent(() => { void load(1, year); });
  useEffect(() => {
    const timer = window.setTimeout(() => loadInitialHistory(), 0);
    return () => { window.clearTimeout(timer); request.current += 1; };
  }, []);

  async function issue() {
    const issuedYear = year;
    setIssuing(true);
    setError('');
    setNotice('');
    try {
      await api('/me/certificates', { method: 'POST', body: JSON.stringify({ year: issuedYear }) });
      if (activeYear.current === issuedYear) {
        setNotice('Your affiliation record was saved. Open or download it below.');
        await load(1, issuedYear);
      }
    } catch (e) {
      setError((e as Error).message || 'Could not issue the affiliation record.');
    } finally {
      setIssuing(false);
    }
  }

  return <section aria-labelledby="certificate-history-title">
    <h2 id="certificate-history-title">Affiliation records</h2>
    <p className="small-note">A snapshot of your self-reported learning for {year}. This is not an MMC, MOH or APC certificate.</p>
    <button type="button" className="primary" disabled={issuing} onClick={issue}>
      {issuing ? 'Preparing…' : 'Issue affiliation record'}
    </button>
    {notice && <p role="status" className="small-note">{notice}</p>}
    {error && <p role="alert" className="alert error">{error}{' '}
      <button type="button" className="text-btn" disabled={loading} onClick={() => load(page)}>Retry history</button>
    </p>}
    {loading ? <p role="status" aria-busy="true">Loading saved records…</p> : items.length ? <ul className="certificate-history">
      {items.map((item) => <li key={item.id}>
        <p><strong>{item.year} affiliation record</strong> · {item.recorded_points_snapshot} self-reported points</p>
        <p className="small-note">Issued {new Date(item.issued_at * 1000).toLocaleString('en-MY', { timeZone: 'Asia/Kuala_Lumpur' })}</p>
        {!item.identity_snapshot_available && <p className="small-note">Legacy record: identity details were not captured at issuance. Issue a new record for an immutable identity snapshot.</p>}
        <div className="button-row">
          <a className="secondary" href={`/api/v1/me/certificates/${encodeURIComponent(item.id)}?format=html`} target="_blank" rel="noopener noreferrer">Open / print</a>
          {item.pdf_available && <a className="secondary" href={`/api/v1/me/certificates/${encodeURIComponent(item.id)}?format=pdf`} target="_blank" rel="noopener noreferrer">Download PDF</a>}
        </div>
        {!item.pdf_available && <p className="small-note">Use Open / print, then Save as PDF to preserve all characters in your name.</p>}
      </li>)}
    </ul> : !error && <p className="empty-state">No affiliation records issued for {year} yet.</p>}
    {total > 10 && <div className="pagination">
      <button type="button" disabled={loading || page === 1} onClick={() => load(page - 1)}>Previous</button>
      <span>Page {page} of {Math.ceil(total / 10)}</span>
      <button type="button" disabled={loading || page * 10 >= total} onClick={() => load(page + 1)}>Next</button>
    </div>}
  </section>;
}
