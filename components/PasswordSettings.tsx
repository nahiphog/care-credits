'use client';

import { FormEvent, useState } from 'react';
import { api } from '@/lib/portal';

export function PasswordSettings() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function save(event: FormEvent) {
    event.preventDefault();
    if (next !== confirm) { setError('The new passwords do not match.'); return; }
    setBusy(true); setError('');
    try {
      await api('/auth/password', { method: 'POST', body: JSON.stringify({ current_password: current, new_password: next }) });
      setCurrent(''); setNext(''); setConfirm('');
      window.dispatchEvent(new CustomEvent('carecredits:session-expired', { detail: 'Password changed. Sign in with your new password.' }));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="card panel password-settings">
    <h2>Change password</h2>
    <p>Use at least 12 characters. Changing your password signs out all active sessions.</p>
    <form onSubmit={save} aria-busy={busy}>
      <label>Current password<input type="password" autoComplete="current-password" required value={current} onChange={(event) => setCurrent(event.target.value)} /></label>
      <label>New password<input type="password" autoComplete="new-password" minLength={12} required value={next} onChange={(event) => setNext(event.target.value)} /></label>
      <label>Confirm new password<input type="password" autoComplete="new-password" minLength={12} required value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
      {error && <p role="alert">{error}</p>}
      <button className="secondary" disabled={busy}>{busy ? 'Changing password…' : 'Change password'}</button>
    </form>
    <p className="small-note">Forgotten-password email recovery is not available yet. This form requires your current password.</p>
  </section>;
}
