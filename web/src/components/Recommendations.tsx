import type { RecommendResponse } from '../types';

interface Props {
  recommend: RecommendResponse | null;
  loading: boolean;
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export default function Recommendations({ recommend, loading }: Props) {
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

  if (!recommend.my_turn) {
    return (
      <div className="recommendations panel">
        <h3>Recommendations</h3>
        <p>Waiting — player {recommend.current_player} is on the clock.</p>
      </div>
    );
  }

  const hasSurvival = recommend.recommendations.some((r) => r.survival !== undefined);

  return (
    <div className="recommendations panel">
      <h3>Recommendations {loading && <span className="loading-tag">updating…</span>}</h3>
      <table className="rec-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Team</th>
            <th>P(win)</th>
            <th>&Delta; wins</th>
            {hasSurvival && <th>Survival</th>}
          </tr>
        </thead>
        <tbody>
          {recommend.recommendations.map((r, i) => (
            <tr key={r.code} className={i === 0 ? 'top-row' : ''}>
              <td>{i + 1}</td>
              <td className="rec-code">{r.code}</td>
              <td>{pct(r.pwin)}</td>
              <td>{r.delta_wins.toFixed(1)}</td>
              {hasSurvival && <td>{r.survival !== undefined ? pct(r.survival) : '—'}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
