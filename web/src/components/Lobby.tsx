// web/src/components/Lobby.tsx
import type { LeagueView, Me } from '../league';
import { randomize } from '../league';
import PickStrip from './PickStrip';

const ONLINE_MS = 30_000;

const initials = (n: string) =>
  n.split(/[\s-]+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');

export default function Lobby({ view, me }: { view: LeagueView; me: Me }) {
  const ref = Math.max(...Object.values(view.logged_in), 0);
  return (
    <div className="lobby card">
      <div className="card-head">
        <span className="eyebrow">Draft lobby</span>
        {me.is_commissioner && (
          <button className="btn primary" onClick={() => randomize().catch(() => {})}>
            Start draft
          </button>
        )}
      </div>
      <ul className="lobby-list">
        {view.players.map((p) => {
          const seen = view.logged_in[p];
          const on = seen !== undefined && ref - seen < ONLINE_MS / 1000;
          return (
            <li key={p} className="lobby-player">
              <span className="avatar">{initials(p)}</span>
              <span className="lobby-name">{p}</span>
              <span className={`dot ${on ? 'on' : ''}`} />
            </li>
          );
        })}
      </ul>
      <PickStrip view={view} myName={me.name} preview />
    </div>
  );
}
