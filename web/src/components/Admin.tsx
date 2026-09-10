// web/src/components/Admin.tsx
//
// Commissioner-only operator view: are the rating sources current, and are
// the background jobs still running? This tab is exempt from the game
// board's terse-copy rule — it's read by one person trying to work out
// whether something is broken, so it spells things out.
import { useEffect, useState } from 'react';
import type { AdminHealth } from '../league';
import { getAdminHealth } from '../league';

function formatAgo(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(s / 3600);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(s / 86400);
  return `${d}d ago`;
}

function formatLimit(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(s / 3600);
  if (h < 24) return `${h}h`;
  const d = Math.floor(s / 86400);
  return `${d}d`;
}

export default function Admin() {
  const [data, setData] = useState<AdminHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const d = await getAdminHealth();
        if (alive) { setData(d); setError(null); }
      } catch {
        if (alive) setError('Could not load admin health.');
      }
      if (alive) timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  if (error) return <div className="card"><span className="eyebrow">Admin</span><p>{error}</p></div>;
  if (!data) return null;

  return (
    <div className="admin">
      <div className="card admin-card">
        <span className="eyebrow">Rating sources</span>
        <div className="admin-sources">
          {data.sources.map((s) => (
            <div key={s.name} className={`admin-row${s.stale ? ' admin-stale' : ''}`}>
              <div className="admin-row-main">
                <span className="admin-name">{s.name}</span>
                <span className="admin-status">
                  {s.last_ok == null
                    ? 'Never succeeded'
                    : `Last successful fetch: ${formatAgo(s.age_s ?? 0)}`}
                  {' '}(limit {formatLimit(s.max_age_s)})
                </span>
              </div>
              {s.last_error && (
                <div className="admin-error">
                  Last error{s.last_error_at == null
                    ? ''
                    : ` (${formatAgo((Date.now() / 1000) - s.last_error_at)})`}: {s.last_error}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="card admin-card">
        <span className="eyebrow">Background jobs</span>
        <div className="admin-jobs">
          {data.jobs.map((j) => (
            <div key={j.name} className="admin-row">
              <div className="admin-row-main">
                <span className="admin-name">{j.name}</span>
                <span className="admin-status">
                  {j.at == null ? 'Never run' : `Last run: ${formatAgo((Date.now() / 1000) - j.at)}`}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
