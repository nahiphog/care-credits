'use client';

import Link from 'next/link';
import { FormEvent, useState } from 'react';
import { ArrowRight, BookOpen, Compass, GraduationCap, ShieldCheck } from 'lucide-react';
import { Brand } from '@/components/Brand';
import { api, User } from '@/lib/portal';

export function LoginForm({
  demo,
  signup,
  oauth,
  recovery,
  onLogin,
}: {
  demo: boolean;
  signup: boolean;
  oauth?: boolean;
  recovery?: boolean;
  onLogin: (u: User) => void;
}) {
  const [email, setEmail] = useState(demo ? 'demo@carecredits.local' : '');
  const [password, setPassword] = useState(demo ? 'CareCredits-demo-2026' : '');
  const [name, setName] = useState('');
  const [register, setRegister] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const body = { email, password, name: name || 'Doctor' };
      if (register) {
        await api('/auth/register', { method: 'POST', body: JSON.stringify(body) });
      }
      onLogin(await api('/auth/login', { method: 'POST', body: JSON.stringify(body) }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <Brand />
        <div>
          <span className="pill">FOR GENERAL PRACTITIONERS IN MALAYSIA</span>
          <h1>
            More learning.
            <br />
            Less searching.
          </h1>
          <p>
            Find your next training. Keep your CPDs together.
            <br />
            Make time for what matters.
          </p>
          <div className="login-values">
            <span>
              <Compass />
              Discover nearby courses
            </span>
            <span>
              <BookOpen />
              Keep a personal learning record
            </span>
            <span>
              <ShieldCheck />
              Share only what you choose
            </span>
          </div>
        </div>
        <small>A little learning can make a lasting difference.</small>
      </section>
      <section className="login-form" id="main-content">
        <div>
          <span className="round-icon">
            <GraduationCap />
          </span>
          <h2>{register ? 'Create your workspace' : 'Welcome to your workspace.'}</h2>
          <p className="muted">
            {register ? 'Start your personal CPD record.' : 'Sign in to pick up where you left off.'}
          </p>
          {demo && <p className="demo-banner">Demo account prefilled. Courses are fictional.</p>}
          <form onSubmit={submit}>
            {register && (
              <label>
                Your name
                <input required value={name} onChange={(e) => setName(e.target.value)} />
              </label>
            )}
            <label>
              Email address
              <input
                required
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <label>
              Password
              <input
                required
                type="password"
                minLength={12}
                maxLength={128}
                autoComplete={register ? 'new-password' : 'current-password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            {error && (
              <p role="alert" className="alert error">
                {error}
              </p>
            )}
            <button className="primary full" disabled={busy} aria-busy={busy}>
              {busy ? 'Please wait…' : register ? 'Create account' : 'Sign in'} <ArrowRight size={17} />
            </button>
            {oauth && (
              // OAuth needs full-document navigation; prefetching can change handshake state.
              // eslint-disable-next-line @next/next/no-html-link-for-pages
              <a className="secondary full" href="/api/v1/auth/oauth/google">
                Continue with Google
              </a>
            )}
          </form>
          {recovery && <Link href="/reset-password">Forgot your password?</Link>}
          {signup && (
            <button
              className="text-btn login-toggle"
              onClick={() => {
                setRegister(!register);
                setError('');
              }}
            >
              {register ? 'Already have an account? Sign in' : 'New here? Create an account'}
            </button>
          )}
          <p className="small-note">
            Your learning records are private by default. Contact the operator if you need account recovery.
          </p>
        </div>
      </section>
    </div>
  );
}
