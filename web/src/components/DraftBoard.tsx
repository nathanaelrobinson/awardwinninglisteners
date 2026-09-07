// web/src/components/DraftBoard.tsx
import type { Team } from '../types';
import TeamLogo from './TeamLogo';

const DIVISION_ORDER = [
  'AFC East', 'AFC North', 'AFC South', 'AFC West',
  'NFC East', 'NFC North', 'NFC South', 'NFC West',
];

interface Props {
  teams: Team[];
  takenBy: Record<string, string>; // code -> player name
  myName: string;
  canPick: boolean;
  selected?: string | null;
  onPick: (code: string) => void;
}

export default function DraftBoard({ teams, takenBy, myName, canPick, selected, onPick }: Props) {
  const present = new Set(teams.map((t) => t.division));
  const divisions = DIVISION_ORDER.filter((d) => present.has(d));
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="card dboard-card">
      <span className="eyebrow">Board</span>
      <div className="dboard">
        {divisions.map((div) => (
        <div key={div} className="dboard-div">
          <h4>{div}</h4>
          <div className="dboard-tiles">
            {teams
              .filter((t) => t.division === div)
              .sort((a, b) => a.code.localeCompare(b.code))
              .map((t) => {
                const owner = takenBy[t.code];
                const taken = owner !== undefined;
                const cls = [
                  'tile',
                  taken ? 'taken' : canPick ? 'open' : '',
                  owner === myName ? 'mine' : '',
                  !taken && canPick && t.code === selected ? 'selected' : '',
                ].join(' ');
                return (
                  <button key={t.code} className={cls} disabled={taken || !canPick} onClick={() => onPick(t.code)} title={t.name}>
                    <TeamLogo code={t.code} size={28} />
                    <span className="tile-text">
                      {t.code}
                      <span className="owner">{taken ? short(owner) : ' '}</span>
                    </span>
                  </button>
                );
              })}
          </div>
        </div>
        ))}
      </div>
    </div>
  );
}
