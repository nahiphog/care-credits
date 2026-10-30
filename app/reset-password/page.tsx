'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { api } from '@/lib/portal';

export default function PasswordRecovery() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [token, setToken] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const suppliedToken = useRef<string | null>(null);
  useEffect(() => {
    suppliedToken.current ??= new URLSearchParams(window.location.hash.slice(1)).get('token') || '';
    const supplied = suppliedToken.current;
    if (supplied) window.history.replaceState(null, '', '/reset-password');
    api('/config').then(c => { setToken(supplied); setEnabled(!!c.password_recovery_available); })
      .catch(() => { setEnabled(false); setError('Could not check account recovery. Please try again later.'); });
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(''); setMessage('');
    if (token && password !== confirm) { setError('Passwords do not match.'); return; }
    setBusy(true);
    try {
      const result = await api(token ? '/auth/password-reset' : '/auth/password-recovery', {
        method: 'POST', body: JSON.stringify(token ? { token, new_password: password } : { email }),
      });
      setMessage(result.message); setDone(true); setPassword(''); setConfirm(''); setToken('');
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }
  return <main style={{ maxWidth: 460, margin: '8vh auto', padding: 24 }}>
    <h1>{token ? 'Choose a new password' : 'Recover your account'}</h1>
    {enabled === null && <p role="status">Checking availability…</p>}
    {enabled === false && <p>Email recovery is not available. Contact the application operator for help.</p>}
    {enabled && !done && <form onSubmit={submit} style={{ display: 'grid', gap: 16 }}>
      {token ? <>
        <label>New password<input style={{ width: '100%' }} type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <label>Confirm password<input style={{ width: '100%' }} type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirm} onChange={e => setConfirm(e.target.value)} /></label>
      </> : <label>Email address<input style={{ width: '100%' }} type="email" autoComplete="email" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>}
      <button disabled={busy}>{busy ? 'Please wait…' : token ? 'Reset password' : 'Request reset email'}</button>
    </form>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <p><Link href="/">Back to sign in</Link></p>
  </main>;
}
