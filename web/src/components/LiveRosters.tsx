// web/src/components/LiveRosters.tsx
import type { LeagueView } from '../league';
import TeamLogo from './TeamLogo';

const ROWS = 6;

export default function LiveRosters({ view, myName }: { view: LeagueView; myName: string }) {
  const bySlot = [...view.players].sort((a, b) => (view.slots?.[a] ?? 0) - (view.slots?.[b] ?? 0));
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="card lrosters-card">
      <span className="eyebrow">Rosters</span>
      <div className="lrosters">
        {bySlot.map((p) => {
          const roster = view.rosters[p] ?? [];
          return (
            <div key={p} className={['lroster', p === myName ? 'me' : '', p === view.current_player ? 'turn' : ''].join(' ')}>
              <h4 title={p}>{short(p)}</h4>
              <ul>
                {Array.from({ length: ROWS }, (_, i) => {
                  const c = roster[i];
                  return c
                    ? <li key={c}><TeamLogo code={c} size={18} />{c}</li>
                    : <li key={`e${i}`} className="empty" />;
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
