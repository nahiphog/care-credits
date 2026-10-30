'use client';

import { FormEvent } from 'react';
import { ExternalLink, Eye, EyeOff } from 'lucide-react';
import { User } from '@/lib/portal';

export function ProfilePanel({
  user,
  saving,
  onUser,
  onSave,
  onLocateError,
}: {
  user: User;
  saving: boolean;
  onUser: (next: User) => void;
  onSave: (event: FormEvent) => void;
  onLocateError?: (message: string) => void;
}) {
  return (
    <>
      <div className="page-title">
        <div>
          <p className="eyebrow">SHARE ON YOUR TERMS</p>
          <h1>A record you can be proud of.</h1>
          <p>Show selected learning on a public page you can link from your website.</p>
        </div>
      </div>
      <div className="profile-grid">
        <form className="panel" onSubmit={onSave}>
          <h2>Profile details</h2>
          <label>
            Display name
            <input required value={user.name} onChange={(e) => onUser({ ...user, name: e.target.value })} />
          </label>
          <label>
            City
            <input value={user.city} onChange={(e) => onUser({ ...user, city: e.target.value })} />
          </label>
          <label>
            State
            <input
              value={user.state || ''}
              placeholder="Optional, e.g. Selangor"
              onChange={(e) => onUser({ ...user, state: e.target.value })}
            />
          </label>
          <p className="small-note">
            City and state are enough for nearby search. Exact coordinates stay optional and are stored only after you
            consent.
          </p>
          <div className="button-row">
            <button
              className="secondary"
              type="button"
              onClick={() => {
                if (!navigator.geolocation) {
                  onLocateError?.('Location is unavailable. Choose your city instead.');
                  return;
                }
                navigator.geolocation.getCurrentPosition(
                  (position) =>
                    onUser({
                      ...user,
                      latitude: position.coords.latitude,
                      longitude: position.coords.longitude,
                    }),
                  () => onLocateError?.('Location was not available. You can still search by city.'),
                  { timeout: 10000 },
                );
              }}
            >
              Use my location
            </button>
            {(user.latitude != null || user.longitude != null) && (
              <button
                className="text-btn"
                type="button"
                onClick={() => onUser({ ...user, latitude: null, longitude: null })}
              >
                Clear coordinates
              </button>
            )}
          </div>
          {user.latitude != null && user.longitude != null && (
            <p className="small-note">
              Approximate coordinates saved with consent. They are not sent to Tavily or shown on your public page.
            </p>
          )}
          <label>
            Short introduction
            <textarea
              value={user.bio}
              maxLength={1000}
              onChange={(e) => onUser({ ...user, bio: e.target.value })}
            />
          </label>
          <label className="check-row">
            <input
              type="checkbox"
              checked={user.public_enabled}
              onChange={(e) => onUser({ ...user, public_enabled: e.target.checked })}
            />
            <span>
              <strong>Make my profile public</strong>
              <small>Only attended courses you individually select will appear.</small>
            </span>
          </label>
          <button className="primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save profile settings'}
          </button>
        </form>
        <section className="panel sharing-preview">
          <span className="round-icon">{user.public_enabled ? <Eye /> : <EyeOff />}</span>
          <h2>{user.public_enabled ? 'Choose what you share.' : 'Private is the starting point.'}</h2>
          <p>
            In My learning, open an attended course and select “Show on my public profile.” Your personal notes, email
            address and sign-ups are never displayed.
          </p>
          <a className="secondary" href={'/p/' + user.public_slug} target="_blank" rel="noreferrer">
            Preview public page <ExternalLink size={15} />
          </a>
          <p className="small-note">
            Save changes first. A private profile returns an unavailable page. Turning sharing off revokes the live
            page; previously downloaded copies cannot be recalled.
          </p>
        </section>
      </div>
    </>
  );
}
