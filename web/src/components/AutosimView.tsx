import { useState } from 'react';
import { fetchAutosim } from '../api';
import type { AutosimResponse, MyStrategy, OppStrategy } from '../types';

interface Props {
  slot: number;
}

const MY_STRATEGIES: MyStrategy[] = ['optimal', 'power', 'market', 'random'];
const OPP_STRATEGIES: OppStrategy[] = ['market', 'power', 'random'];

export default function AutosimView({ slot }: Props) {
  const [myStrategy, setMyStrategy] = useState<MyStrategy>('optimal');
  const [oppStrategy, setOppStrategy] = useState<OppStrategy>('market');
  const [nSims, setNSims] = useState<number>(150);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AutosimResponse | null>(null);

  function handleRun() {
    setLoading(true);
    setError(null);
    fetchAutosim({ slot, my_strategy: myStrategy, opp_strategy: oppStrategy, n_sims: nSims })
      .then((data) => setResult(data))
      .catch((err) => setError(err.message ?? 'Auto-sim request failed'))
      .finally(() => setLoading(false));
  }

  return (
    <div className="autosim panel">
      <h3>Auto-sim</h3>
      <p className="autosim-explainer">
        Opponents all draft using the chosen opponents strategy; your slot drafts using your
        chosen strategy, simulated repeatedly to estimate your odds of winning the pool.
      </p>

      <div className="autosim-controls">
        <label className="autosim-field">
          <span className="label">My strategy</span>
          <select value={myStrategy} onChange={(e) => setMyStrategy(e.target.value as MyStrategy)}>
            {MY_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="autosim-field">
          <span className="label">Opponents strategy</span>
          <select value={oppStrategy} onChange={(e) => setOppStrategy(e.target.value as OppStrategy)}>
            {OPP_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="autosim-field">
          <span className="label">n_sims</span>
          <input
            type="number"
            min={1}
            max={5000}
            value={nSims}
            onChange={(e) => setNSims(Number(e.target.value))}
          />
        </label>

        <button className="btn btn-primary" onClick={handleRun} disabled={loading}>
          {loading ? 'Running…' : 'Run'}
        </button>
      </div>

      <p className="autosim-helper">
        market = always take the highest posted win total &middot; power = highest rating &middot;
        random = chaotic &middot; optimal = maximize P(win).
      </p>

      {error && <div className="banner banner-error">{error}</div>}

      {result && (
        <div className="autosim-result">
          <div className="autosim-win">You win {result.win_pct.toFixed(1)}%</div>
          <div className="autosim-fair">(fair share {result.fair_share.toFixed(1)}%)</div>
          <div className="autosim-range">
            {result.p90 > result.p10
              ? `range ${result.p10.toFixed(1)}%–${result.p90.toFixed(1)}% across simulated drafts`
              : 'deterministic draft — exact (pick a "random" strategy to see a spread)'}
          </div>
          <div className="autosim-meta">
            slot {result.slot} &middot; {result.n_sims} sims &middot; my: {result.my_strategy} vs opp:{' '}
            {result.opp_strategy}
          </div>
        </div>
      )}
    </div>
  );
}
