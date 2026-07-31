import type { Team } from '../types';

interface Props {
  teams: Team[];
  takenBy: Record<string, number>; // code -> player number
  mySlot: number;
  onDraft: (code: string) => void;
  disabled: boolean;
  survival?: Record<string, number>; // code -> P(still available at my next pick)
}

function pct(x: number): string {
  return `${(x * 100).toFixed(0)}%`;
}

// green (likely yours) -> red (likely gone)
function survColor(s: number): string {
  return `hsl(${Math.round(s * 120)}, 65%, 60%)`;
}

export default function Board({ teams, takenBy, mySlot, onDraft, disabled, survival }: Props) {
  const divisions = Array.from(new Set(teams.map((t) => t.division)));

  return (
    <div className="board">
      {divisions.map((div) => (
        <div key={div} className="division-group">
          <h3 className="division-title">{div}</h3>
          <div className="division-grid">
            {teams
              .filter((t) => t.division === div)
              .sort((a, b) => b.mean - a.mean) // best -> worst, left to right
              .map((t) => {
                const player = takenBy[t.code];
                const taken = player !== undefined;
                const mine = taken && player === mySlot;
                return (
                  <button
                    key={t.code}
                    className={`team-card ${taken ? 'taken' : ''} ${mine ? 'mine' : ''}`}
                    onClick={() => !taken && !disabled && onDraft(t.code)}
                    disabled={taken || disabled}
                    title={t.name}
                  >
                    <div className="team-card-top">
                      <span className="team-code">{t.code}</span>
                      {taken ? (
                        <span className="team-owner">{mine ? 'YOU' : `P${player}`}</span>
                      ) : (
                        survival && survival[t.code] !== undefined && (
                          <span
                            className="surv-badge"
                            style={{ color: survColor(survival[t.code]) }}
                            title="chance still available at your next pick"
                          >
                            {pct(survival[t.code])}
                          </span>
                        )
                      )}
                    </div>
                    <div className="team-stat">O/U {t.win_total.toFixed(1)}</div>
                    <div className="team-stat">
                      {t.mean.toFixed(1)}&plusmn;{t.sd.toFixed(1)} wins
                    </div>
                    <div className="team-stat-row">
                      <span>ceil {pct(t.ceiling)}</span>
                      <span>floor {pct(t.floor)}</span>
                    </div>
                  </button>
                );
              })}
          </div>
        </div>
      ))}
    </div>
  );
}
