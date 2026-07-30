import { useMemo, useState } from 'react';
import { fetchAutosim } from '../api';
import type { AutosimResponse, MyStrategy, OppStrategy } from '../types';

interface Props {
  slot: number;
  nPlayers: number;
}

const MY_STRATEGIES: MyStrategy[] = ['optimal', 'power', 'market', 'random'];
const OPP_STRATEGIES: OppStrategy[] = ['market', 'power', 'random'];

export default function AutosimView({ slot, nPlayers }: Props) {
  const seats = useMemo(
    () => Array.from({ length: nPlayers }, (_, i) => i + 1),
    [nPlayers]
  );

  // Per-seat strategy: my slot defaults to "optimal", competitors to "market".
  const [strategies, setStrategies] = useState<Record<number, string>>(() => {
    const init: Record<number, string> = {};
    seats.forEach((p) => (init[p] = p === slot ? 'optimal' : 'market'));
    return init;
  });
  const [nSims, setNSims] = useState<number>(150);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AutosimResponse | null>(null);

  function setSeat(p: number, value: string) {
    setStrategies((prev) => ({ ...prev, [p]: value }));
  }

  function setAllOpponents(value: string) {
    setStrategies((prev) => {
      const next = { ...prev };
      seats.forEach((p) => {
        if (p !== slot) next[p] = value;
      });
      return next;
    });
  }

  function handleRun() {
    setLoading(true);
    setError(null);
    const payload: Record<string, string> = {};
    seats.forEach((p) => (payload[String(p)] = strategies[p] ?? (p === slot ? 'optimal' : 'market')));
    fetchAutosim({
      slot,
      my_strategy: (strategies[slot] as MyStrategy) ?? 'optimal',
      opp_strategy: 'market',
      strategies: payload,
      n_sims: nSims,
    })
      .then((data) => setResult(data))
      .catch((err) => setError(err.message ?? 'Auto-sim request failed'))
      .finally(() => setLoading(false));
  }

  return (
    <div className="autosim panel">
      <h3>Auto-sim</h3>
      <p className="autosim-explainer">
        Assign a draft strategy to every seat, then simulate the whole draft repeatedly to
        estimate your odds of winning the pool. Set your own seat and each competitor
        independently.
      </p>

      <div className="autosim-seatgrid">
        {seats.map((p) => {
          const mine = p === slot;
          const opts = mine ? MY_STRATEGIES : OPP_STRATEGIES;
          const val = strategies[p] ?? (mine ? 'optimal' : 'market');
          const safeVal = opts.includes(val as never) ? val : opts[0];
          return (
            <label key={p} className={`autosim-seat ${mine ? 'mine' : ''}`}>
              <span className="autosim-seat-label">
                {mine ? `You (P${p})` : `Player ${p}`}
              </span>
              <select value={safeVal} onChange={(e) => setSeat(p, e.target.value)}>
                {opts.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
          );
        })}
      </div>

      <div className="autosim-controls">
        <label className="autosim-field">
          <span className="label">Set all competitors</span>
          <select defaultValue="" onChange={(e) => e.target.value && setAllOpponents(e.target.value)}>
            <option value="">choose…</option>
            {OPP_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="autosim-field">
          <span className="label">Sims</span>
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
              : 'deterministic draft — exact (give a competitor the "random" strategy to see a spread)'}
          </div>
          <div className="autosim-meta">
            slot {result.slot} &middot; {result.n_sims} sims
          </div>
        </div>
      )}
    </div>
  );
}
