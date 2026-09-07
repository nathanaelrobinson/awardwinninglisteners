// web/src/components/Lobby.tsx
import type { LeagueView, Me } from '../league';
import { randomize } from '../league';

const ONLINE_MS = 30_000;

export default function Lobby({ view, me }: { view: LeagueView; me: Me }) {
  const now = Date.now() / 1000;
  return (
    <div className="lobby">
      <ul className="lobby-list">
        {view.players.map((p) => {
          const seen = view.logged_in[p];
          const on = seen !== undefined && now - seen < ONLINE_MS / 1000;
          return (
            <li key={p}>
              <span className={`dot ${on ? 'on' : ''}`} />
              {p}
            </li>
          );
        })}
      </ul>
      {me.is_commissioner && (
        <button className="btn primary" onClick={() => randomize().catch(() => {})}>
          Randomize order
        </button>
      )}
    </div>
  );
}
