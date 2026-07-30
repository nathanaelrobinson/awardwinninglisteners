interface Props {
  rosters: Record<string, string[]>;
  mySlot: number;
  nPlayers: number;
  picksPerPlayer: number;
}

export default function Rosters({ rosters, mySlot, nPlayers, picksPerPlayer }: Props) {
  const players = Array.from({ length: nPlayers }, (_, i) => i + 1);

  return (
    <div className="rosters">
      {players.map((p) => {
        const codes = rosters[String(p)] ?? [];
        const mine = p === mySlot;
        return (
          <div key={p} className={`roster-col ${mine ? 'mine' : ''}`}>
            <div className="roster-header">
              Player {p} {mine && <span className="you-badge">YOU</span>}
              <span className="roster-count">
                {codes.length}/{picksPerPlayer}
              </span>
            </div>
            <ul className="roster-list">
              {codes.map((c) => (
                <li key={c}>{c}</li>
              ))}
              {codes.length === 0 && <li className="empty">—</li>}
            </ul>
          </div>
        );
      })}
    </div>
  );
}
