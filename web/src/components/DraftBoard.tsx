// web/src/components/DraftBoard.tsx
import type { Team } from '../types';

interface Props {
  teams: Team[];
  takenBy: Record<string, string>; // code -> player name
  myName: string;
  canPick: boolean;
  onPick: (code: string) => void;
}

export default function DraftBoard({ teams, takenBy, myName, canPick, onPick }: Props) {
  const divisions = Array.from(new Set(teams.map((t) => t.division)));
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="dboard">
      {divisions.map((div) => (
        <div key={div} className="dboard-div">
          <h4>{div}</h4>
          {teams
            .filter((t) => t.division === div)
            .sort((a, b) => a.code.localeCompare(b.code))
            .map((t) => {
              const owner = takenBy[t.code];
              const taken = owner !== undefined;
              const cls = ['tile', taken ? 'taken' : canPick ? 'open' : '', owner === myName ? 'mine' : ''].join(' ');
              return (
                <button key={t.code} className={cls} disabled={taken || !canPick} onClick={() => onPick(t.code)} title={t.name}>
                  {t.code}
                  <span className="owner">{taken ? short(owner) : ' '}</span>
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}
