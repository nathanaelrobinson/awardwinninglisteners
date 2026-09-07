import { useEffect, useState } from 'react';
import { fetchResults, sampleSeason } from '../api';
import type { SeasonRow, StandingRow } from '../api';
import DistributionChart from './DistributionChart';

interface Props {
  slot: number;
  taken: string[];
  /** Hypothetical pick added to my roster ("if I take this team"). */
  withTeam?: string | null;
}

export default function Results({ slot, taken, withTeam = null }: Props) {
  const [standings, setStandings] = useState<StandingRow[] | null>(null);
  const [xWins, setXWins] = useState<number[]>([]);
  const [nSims, setNSims] = useState<number>(0);
  const [season, setSeason] = useState<{ standings: SeasonRow[]; winners: number[] } | null>(null);
  const [seed, setSeed] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchResults(slot, taken, withTeam).then((r) => {
      if (!cancelled) {
        setStandings(r.standings);
        setXWins(r.x);
        setNSims(r.n_sims);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [slot, taken, withTeam]);

  // A new hypothetical invalidates the sampled season.
  useEffect(() => {
    setSeason(null);
  }, [withTeam, taken]);

  function playSeason(nextSeed: number) {
    setBusy(true);
    sampleSeason(slot, taken, nextSeed, withTeam)
      .then(setSeason)
      .finally(() => setBusy(false));
  }

  return (
    <div className="results panel">
      <h3>{withTeam ? `If you take ${withTeam}` : 'Final standings'}</h3>
      {!withTeam && (
        <p className="results-sub">
          Distribution of each player's combined wins across {nSims.toLocaleString()} simulated
          seasons (teams play each other, so wins are correlated). % = chance to win the pool.
        </p>
      )}

      {standings && xWins.length > 0 && (
        <DistributionChart standings={standings} x={xWins} />
      )}

      {!standings && <p>Simulating…</p>}
      {standings && (
        <table className="rec-table results-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Proj wins</th>
              <th>P(win)</th>
              <th>Range</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((r, i) => (
              <tr key={r.player} className={r.is_me ? 'top-row' : ''}>
                <td>{i + 1}</td>
                <td>{r.is_me ? `You (P${r.player})` : `Player ${r.player}`}</td>
                <td>{r.exp_wins.toFixed(1)}</td>
                <td>{(r.pwin * 100).toFixed(1)}%</td>
                <td>
                  {r.p10}–{r.p90}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="results-actions">
        <button
          className="btn btn-primary"
          disabled={busy}
          onClick={() => {
            const s = seed + 1;
            setSeed(s);
            playSeason(s);
          }}
        >
          {busy ? 'Playing…' : season ? 'Re-roll season' : 'Play out a season →'}
        </button>
      </div>

      {season && (
        <div className="season-result">
          <div className="season-winner">
            {season.winners.length > 1
              ? `Co-champions: ${season.winners.map((p) => (p === slot ? 'You' : `P${p}`)).join(', ')}`
              : season.winners[0] === slot
                ? '🏆 You win this season!'
                : `🏆 Player ${season.winners[0]} wins this season`}
          </div>
          <table className="rec-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Player</th>
                <th>Wins</th>
                <th>Teams (wins)</th>
              </tr>
            </thead>
            <tbody>
              {season.standings.map((r, i) => (
                <tr key={r.player} className={r.is_me ? 'top-row' : ''}>
                  <td>{i + 1}</td>
                  <td>{r.is_me ? 'You' : `P${r.player}`}</td>
                  <td>
                    <strong>{r.total_wins}</strong>
                  </td>
                  <td className="season-teams">
                    {r.teams.map((t) => `${t.code} ${t.wins}`).join(' · ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
