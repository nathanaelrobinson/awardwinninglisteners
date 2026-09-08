// web/src/components/ThisWeek.tsx — each player's games this week, ordered by
// how much the week can swing their pool odds.
import { playerColor } from '../colors';
import type { LiveProjection } from '../league';
import TeamLogo from './TeamLogo';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;

export default function ThisWeek({ live }: { live: LiveProjection }) {
  if (!live.this_week.some((r) => r.games.length)) return null;
  return (
    <div className="card">
      <span className="eyebrow">Week {live.week}</span>
      <div className="week-grid">
        {live.this_week.map((r) => {
          const c = playerColor(r.player);
          return (
            <div key={r.player} className="week-row">
              <span className="week-name"><span className="proj-swatch" style={{ background: c.bg }} />{first(r.player)}</span>
              <span className="week-games">
                {r.games.map((g) => (
                  <span key={g.team} className="week-game" title={`${g.team} ${g.home ? 'vs' : 'at'} ${g.opp}`}>
                    <TeamLogo code={g.team} size={18} />
                    <span className="week-vs">{g.home ? 'vs' : '@'}</span>
                    <TeamLogo code={g.opp} size={18} />
                    <b>{Math.round(g.p * 100)}%</b>
                  </span>
                ))}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
