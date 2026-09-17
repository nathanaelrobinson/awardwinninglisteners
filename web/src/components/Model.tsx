// web/src/components/Model.tsx
//
// Public walk through the live engine: this week's coins, the BMA mix, and
// the 32-team posterior. Admin keeps the operator tables.
import { useEffect, useState } from 'react';
import type { AdminModel, AdminModelTeam, LiveCoin, LiveProjection } from '../league';
import { getLive, getModel } from '../league';
import { sourceLabel } from '../sim';
import { assignColors } from './viz/palette';
import VoiceLegend from './viz/VoiceLegend';
import RowChart, { type RowDatum } from './viz/RowChart';
import TeamLogo from './TeamLogo';

const pct = (p: number) => `${Math.round(p * 100)}%`;

/** Posted line as the Week tab writes it: favourite first, home-favoured-negative. */
function fmtSpread(home: string, away: string, spread: number): string {
  return spread < 0 ? `${home} ${spread}` : `${away} ${-spread}`;
}

/** American odds with the leading plus on underdogs. */
function fmtMl(n: number): string {
  const i = Math.round(n);
  return i > 0 ? `+${i}` : String(i);
}

/** Largest voice minus smallest; a team the sources treat as the same is 0. */
function spreadOf(t: AdminModelTeam): number {
  const xs = Object.values(t.strength);
  return Math.max(...xs) - Math.min(...xs);
}

/** Team the voices disagree about most; that is the default forest pin. */
function loudestCode(teams: AdminModelTeam[]): string {
  return teams.reduce((a, b) => (spreadOf(b) > spreadOf(a) ? b : a)).code;
}

function weightOf(row: Record<string, number>, v: string): number {
  if (!(v in row)) throw new Error(`missing weight for ${v}`);
  return row[v];
}

function pOf(row: Record<string, number>, v: string): number {
  if (!(v in row)) throw new Error(`missing p_home for ${v}`);
  return row[v];
}

/** Mean log-loss on completed games. n=0 is a bug: nothing to score. */
function logLoss(loglik: number, n: number): number {
  if (n === 0) throw new Error('log-loss with n=0');
  return -loglik / n;
}

/** Model minus book, in percentage points. */
function ptsGap(model: number, used: number): number {
  return Math.round(model * 100) - Math.round(used * 100);
}

/** Signed percentage-point gap, ASCII sign. */
function fmtDelta(n: number): string {
  return n > 0 ? `+${n}` : String(n);
}

/** Min and max home-win p across the voices on one game. */
function voiceRange(voices: string[], pVoices: Record<string, number>): { lo: number; hi: number } {
  const ps = voices.map((v) => pOf(pVoices, v));
  return { lo: Math.min(...ps), hi: Math.max(...ps) };
}

/** Prior, log-loss, and Now. The bar is Prior to Now on one scale. */
function MixTable({ prior, weights, loglik, nPlayed, voices, colors }: {
  prior: Record<string, number>;
  weights: Record<string, number>;
  loglik: Record<string, number>;
  nPlayed: number;
  voices: string[];
  colors: Record<string, string>;
}) {
  const rows = [...voices].sort((a, b) => weightOf(weights, b) - weightOf(weights, a));
  const hi = Math.max(
    ...rows.flatMap((v) => [weightOf(prior, v), weightOf(weights, v)]),
  );
  if (hi === 0) throw new Error('BMA weights are all 0');
  return (
    <div className="card">
      <span className="eyebrow">What the blend is</span>
      <table className="model-bma">
        <thead>
          <tr>
            <th>Voice</th>
            <th className="num">n={nPlayed}</th>
            <th>Prior to Now</th>
            <th className="num">Now</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((v) => {
            const now = weightOf(weights, v);
            const pr = weightOf(prior, v);
            const a = Math.min(pr, now);
            const b = Math.max(pr, now);
            return (
              <tr key={v}>
                <td>
                  <span className="viz-swatch" style={{ background: colors[v] }} />
                  {sourceLabel(v)}
                </td>
                <td className="num">{logLoss(weightOf(loglik, v), nPlayed).toFixed(3)}</td>
                <td>
                  <span className="model-db">
                    <i className="model-db-line" style={{ left: `${(a / hi) * 100}%`, width: `${((b - a) / hi) * 100}%` }} />
                    <i className="model-db-prior" style={{ left: `${(pr / hi) * 100}%` }} />
                    <i className="model-db-now" style={{ left: `${(now / hi) * 100}%`, background: colors[v] }} />
                  </span>
                </td>
                <td className="num">{pct(now)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** One remaining game: matchup, book/model p, voices on a home-win trough. */
function CoinRow({ g, voices, colors, open, onToggle }: {
  g: LiveCoin; voices: string[]; colors: Record<string, string>;
  open: boolean; onToggle: () => void;
}) {
  const { lo, hi } = voiceRange(voices, g.p_voices);
  const used = g.p_used;
  const coinName = g.source === 'market' ? 'book' : 'model';
  const showModel = g.source === 'market' && Math.round(g.p_model * 100) !== Math.round(used * 100);
  const gap = g.p_market != null ? ptsGap(g.p_model, used) : null;
  return (
    <button type="button" className={`model-coin${open ? ' model-coin-open' : ''}`} onClick={onToggle}>
      <div className="model-coin-h">
        <span className="model-match">
          <TeamLogo code={g.away} size={18} />
          <b>{g.away}</b>
          <span className="model-at">@</span>
          <TeamLogo code={g.home} size={18} />
          <b>{g.home}</b>
        </span>
        <span className="model-used">
          <b>{pct(used)}</b>
          {coinName}
          {showModel && <span className="model-alt">{pct(g.p_model)} model</span>}
          {gap != null && gap !== 0 && <span className="model-alt">{fmtDelta(gap)}</span>}
        </span>
        <div className="model-track">
          <TeamLogo code={g.away} size={15} />
          <span className="model-trough" role="img" aria-label={`${g.away} at ${g.home} home-win ${pct(used)} ${coinName}`}>
            <i className="model-mid" />
            <i className="model-band" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
            {voices.map((v) => (
              <i
                key={v}
                className="model-voice"
                style={{ left: `${pOf(g.p_voices, v) * 100}%`, background: colors[v] }}
              />
            ))}
            <i className="model-mark-model" style={{ left: `${g.p_model * 100}%` }} />
            {g.p_market != null && (
              <i className="model-mark-book" style={{ left: `${g.p_market * 100}%` }} />
            )}
          </span>
          <TeamLogo code={g.home} size={15} />
        </div>
      </div>
      {open && (
        <div className="model-gap">
          {g.spread != null && <span>Line {fmtSpread(g.home, g.away, g.spread)}</span>}
          {g.ml_home != null && g.ml_away != null && (
            <span>{fmtMl(g.ml_home)} / {fmtMl(g.ml_away)}</span>
          )}
          <span>Prior {pct(g.p_prior)}</span>
          <span>Model {pct(g.p_model)}</span>
        </div>
      )}
    </button>
  );
}

/** Remaining games this week, one expandable row each. */
function WeekCoins({ games, voices, colors, openGame, setOpenGame }: {
  games: LiveCoin[]; voices: string[]; colors: Record<string, string>;
  openGame: string | null; setOpenGame: (k: string | null) => void;
}) {
  return (
    <div className="card">
      <span className="eyebrow">This week&apos;s coins</span>
      {games.map((g) => {
        const key = `${g.home}-${g.away}`;
        return (
          <CoinRow
            key={key}
            g={g}
            voices={voices}
            colors={colors}
            open={openGame === key}
            onToggle={() => setOpenGame(openGame === key ? null : key)}
          />
        );
      })}
    </div>
  );
}

/** Public Model tab. Throws if the live doc is missing fields this page needs. */
export default function ModelPage() {
  const [model, setModel] = useState<AdminModel | null | undefined>(undefined);
  const [live, setLive] = useState<LiveProjection | null | undefined>(undefined);
  const [picked, setPicked] = useState<string | null>(null);
  const [openGame, setOpenGame] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getModel(), getLive()]).then(([m, l]) => {
      if (alive) { setModel(m); setLive(l); }
    }).catch(() => { if (alive) { setModel(null); setLive(null); } });
    return () => { alive = false; };
  }, []);

  if (model === undefined || live === undefined) return null;
  if (!model || !live) {
    return (
      <div className="card">
        <span className="eyebrow">Model</span>
        <p>The projection is not ready yet.</p>
      </div>
    );
  }
  const games = live.games;
  const prior = live.prior;
  const weights = live.weights;
  const loglik = live.loglik;
  const nPlayed = live.n_played;
  if (!games) throw new Error('live doc missing games');
  if (!prior || !weights) throw new Error('live doc missing BMA weights');
  if (!loglik || nPlayed == null) throw new Error('live doc missing BMA loglik');
  for (const g of games) {
    if (!g.p_voices) throw new Error('live games missing p_voices');
    if (g.p_prior == null) throw new Error('live games missing p_prior');
  }

  const voices = Object.keys(weights);
  const colors = assignColors(voices);
  const selected = picked ?? loudestCode(model.teams);
  const teams = [...model.teams].sort((a, b) => b.consensus - a.consensus);
  const reach = Math.max(
    1,
    ...teams.flatMap((t) => [Math.abs(t.consensus), ...Object.values(t.strength).map(Math.abs)]),
  );
  const tReach = Math.ceil(reach / 2) * 2;
  const forestRows: RowDatum[] = teams.map((t) => ({
    key: t.code,
    label: t.code,
    values: t.strength,
    ref: t.consensus,
    interval: (t.lo80 != null && t.hi80 != null) ? { lo: t.lo80, hi: t.hi80 } : undefined,
  }));

  return (
    <div className="model viz">
      <VoiceLegend voices={voices} colors={colors} />
      <WeekCoins
        games={games} voices={voices} colors={colors}
        openGame={openGame} setOpenGame={setOpenGame}
      />
      <MixTable
        prior={prior} weights={weights} loglik={loglik} nPlayed={nPlayed}
        voices={voices} colors={colors}
      />
      <div className="card">
        <span className="eyebrow">Where the voices agree</span>
        <RowChart
          variant="forest"
          rows={forestRows}
          voices={voices}
          colors={colors}
          lo={-tReach}
          hi={tReach}
          ticks={[-tReach, -tReach / 2, 0, tReach / 2, tReach]}
          fmt={(v) => v.toFixed(0)}
          refName="Model"
          labelW={54}
          maxHeight={420}
          onRowClick={setPicked}
          selectedKey={selected}
        />
      </div>
    </div>
  );
}
