'use client';
import { useState } from 'react';
import { api, publicWebUrl } from '@/lib/portal';

type Maintenance = { overdue: boolean; digests_needing_review: number; last_success: { finished_at: number } | null; items: { id: string; status: string; error_type?: string }[] };
type Quality = { total: number; page: number; page_size: number; items: { id: string; title: string; missing: string[]; last_reviewed_at: number | null; review_due: boolean; source_url: string | null }[] };

export function OperationsStatus() {
  const [maintenance, setMaintenance] = useState<Maintenance | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function load(page = 1) {
    setBusy(true); setError('');
    try {
      const [m, q] = await Promise.all([api('/admin/maintenance'), api('/admin/catalogue-quality?page=' + page)]);
      setMaintenance(m); setQuality(q);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <details className="card" style={{ marginTop: 24 }}>
    <summary>Maintenance and catalogue quality</summary>
    <p>Check housekeeping and listings that need source evidence. Missing information stays unknown until reviewed.</p>
    <button type="button" disabled={busy} onClick={() => void load()}>{busy ? 'Checking…' : 'Refresh checks'}</button>
    {error && <p role="alert">{error}</p>}
    {maintenance && <p role="status">{maintenance.overdue ? 'Maintenance needs attention.' : 'Maintenance is current.'} Last successful run: {maintenance.last_success ? new Date(maintenance.last_success.finished_at * 1000).toLocaleString() : 'Not yet recorded'}.</p>}
    {maintenance?.items[0]?.status === 'failed' && <p role="alert">Latest run failed ({maintenance.items[0].error_type}). Review the server logs.</p>}
    {maintenance?.items[0]?.status === 'interrupted' && <p role="alert">The latest maintenance run did not finish. Review its logs before retrying.</p>}
    {!!maintenance?.digests_needing_review && <p role="alert">{maintenance.digests_needing_review} digest deliveries need review. Automatic resending is paused to avoid duplicates.</p>}
    {quality && <>
      <h3>{quality.total} listings need review</h3>
      <ul>{quality.items.map(item => <li key={item.id} style={{ marginBlock: 16, overflowWrap: 'anywhere' }}>
        <strong>{item.title}</strong><br />
        {item.missing.length > 0 && <span>Missing: {item.missing.join(', ')}. </span>}
        <span>Last reviewed: {item.last_reviewed_at ? new Date(item.last_reviewed_at * 1000).toLocaleDateString() : 'Not recorded'}. {item.review_due && 'Source review due.'}</span>{' '}
        {publicWebUrl(item.source_url) && <a href={publicWebUrl(item.source_url)!} target="_blank" rel="noreferrer">Provider source</a>}
      </li>)}</ul>
      <button type="button" disabled={busy || quality.page <= 1} onClick={() => void load(quality.page - 1)}>Previous</button>{' '}
      <span>Page {quality.page} of {Math.max(1, Math.ceil(quality.total / quality.page_size))}</span>{' '}
      <button type="button" disabled={busy || quality.page * quality.page_size >= quality.total} onClick={() => void load(quality.page + 1)}>Next</button>
    </>}
  </details>;
}
