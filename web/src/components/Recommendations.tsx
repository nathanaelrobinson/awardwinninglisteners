import type { RecommendResponse } from '../types';

interface Props {
  recommend: RecommendResponse | null;
  loading: boolean;
  teamNames: Record<string, string>;
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export default function Recommendations({ recommend, loading, teamNames }: Props) {
  if (!recommend) {
    return (
      <div className="recommendations panel">
        <h3>Recommendations</h3>
        <p>Loading…</p>
      </div>
    );
  }

  if (recommend.done) {
    return (
      <div className="recommendations panel">
        <h3>Recommendations</h3>
        <p>Draft complete.</p>
      </div>
    );
  }

  const title = recommend.my_turn
    ? '★ ON THE CLOCK — your pick'
    : `Targets — your next pick in ${recommend.my_next_in}`;

  const top = recommend.recommendations[0];

  return (
    <div className={`recommendations panel ${recommend.my_turn ? 'on-the-clock' : ''}`}>
      <h3>
        {title} {loading && <span className="loading-tag">updating…</span>}
      </h3>

      {top && (
        <div className="top-pick">
          <div className="top-pick-code">{top.code}</div>
          <div className="top-pick-name">{teamNames[top.code] ?? ''}</div>
          <div className="top-pick-stats">
            {recommend.my_turn && <span>P(win) {pct(top.pwin)}</span>}
            <span>&Delta; wins {top.delta_wins.toFixed(1)}</span>
            {top.survival !== undefined && <span>Survival {pct(top.survival)}</span>}
          </div>
        </div>
      )}

      <table className="rec-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Team</th>
            {recommend.my_turn && <th>P(win)</th>}
            <th>&Delta; wins</th>
            <th>Survival</th>
          </tr>
        </thead>
        <tbody>
          {recommend.recommendations.map((r, i) => (
            <tr key={r.code} className={i === 0 ? 'top-row' : ''}>
              <td>{i + 1}</td>
              <td className="rec-code">{r.code}</td>
              {recommend.my_turn && <td>{pct(r.pwin)}</td>}
              <td>{r.delta_wins.toFixed(1)}</td>
              <td>{r.survival !== undefined ? pct(r.survival) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
