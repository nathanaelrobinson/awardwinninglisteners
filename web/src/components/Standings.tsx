// web/src/components/Standings.tsx
import { useEffect, useRef, useState } from 'react';
import { fetchTeams } from '../api';
import { playerColor } from '../colors';
import type { LeagueView, LiveProjection, LiveViewRow, Me, StandingsResponse, WeekPoint } from '../league';
import { getLive, getStandings, getWeeks, setOverride } from '../league';
import Feed from './Feed';
import MovementChart from './MovementChart';
import TeamLogo from './TeamLogo';
import { rangeLabel, sparkArea, sparkDomain } from '../sim';

const ROWS = 6;

// Score lens: which numbers the cards show. 'actual' = real wins; anything else
// is a key of live.views (the blend or one rating source at 100%).
const LENS_LABEL: Record<string, string> = {
  actual: 'Actual', blend: 'Blend', espn_fpi: 'FPI', nfelo: 'nfelo', clay: 'Clay',
  pff: 'PFF', epa: 'EPA', kalshi: 'Kalshi', vegas: 'Vegas',
  covers: 'Covers', epa_adj: 'EPA', market_strength: 'Market',
};
const LENS_KEY = 'wp:lens';
const loadLens = () => { try { return localStorage.getItem(LENS_KEY) ?? 'actual'; } catch { return 'actual'; } };
const saveLens = (v: string) => { try { localStorage.setItem(LENS_KEY, v); } catch { /* ignore */ } };

export default function Standings({ me, view }: { me: Me | null; view: LeagueView }) {
  const [data, setData] = useState<StandingsResponse | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try { const d = await getStandings(); if (alive) setData(d); } catch { /* keep last */ }
      if (alive) timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    let alive = true;
    fetchTeams().then((r) => {
      if (!alive) return;
      const map: Record<string, string> = {};
      for (const t of r.teams) map[t.code] = t.name.trim().split(/\s+/).pop() ?? t.name;
      setNames(map);
    }).catch(() => { /* fall back to codes */ });
    return () => { alive = false; };
  }, []);

  const [live, setLive] = useState<LiveProjection | null>(null);
  const [weeks, setWeeks] = useState<WeekPoint[]>([]);
  const [lens, setLensState] = useState<string>(loadLens);
  const setLens = (v: string) => { setLensState(v); saveLens(v); };

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const [l, w] = await Promise.all([getLive(), getWeeks()]);
        if (alive) { setLive(l); setWeeks(w); }
      } catch { /* 404 until the first refresh; keep last */ }
      if (alive) timer = window.setTimeout(tick, 5 * 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  async function edit(code: string, current: number) {
    const v = window.prompt(code, String(current));
    if (v === null) return;
    const n = v.trim() === '' ? null : Number(v);
    if (n !== null && !Number.isInteger(n)) return;
    await setOverride(code, n).catch(() => {});
    setData(await getStandings());
  }

  if (!data) return null;

  const lenses = ['actual', ...Object.keys(live?.views ?? {})];
  const active = lenses.includes(lens) ? lens : 'actual';
  const viewKey = active === 'actual' ? 'blend' : active;
  const viewRows = live?.views?.[viewKey] ?? live?.rows ?? [];
  const projBy: Record<string, LiveViewRow> = {};
  const pwinBy: Record<string, number> = {};
  for (const r of viewRows) { projBy[r.player] = r; pwinBy[r.player] = r.pwin; }
  const deltaBy: Record<string, number> = {};
  if (weeks.length >= 2) {
    const pick = (w: WeekPoint) => w.views?.[viewKey] ?? w.rows;
    const prev = Object.fromEntries(pick(weeks[weeks.length - 2]).map((r) => [r.player, r.pwin]));
    for (const r of pick(weeks[weeks.length - 1])) deltaBy[r.player] = r.pwin - (prev[r.player] ?? r.pwin);
  }
  const mover = Object.entries(deltaBy)
    .filter(([, d]) => Math.round(Math.abs(d) * 100) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]?.[0];
  const ratingsStale = !!live?.ratings_fetched_at
    && Date.now() - new Date(live.ratings_fetched_at).getTime() > 8 * 24 * 3600_000;
  const sparkScale = live ? sparkDomain(live.x, live.rows.map((row) => row.dist)) : null;

  return (
    <div className="standings">
      <div className="card standings-card">
        <div className="card-head">
          <span className="eyebrow">Standings</span>
          {lenses.length > 1 && (
            <select className="lens" value={active} onChange={(e) => setLens(e.target.value)} aria-label="Score lens">
              {lenses.map((k) => <option key={k} value={k}>{LENS_LABEL[k] ?? k}</option>)}
            </select>
          )}
        </div>
        <div className="standings-grid">
          {data.rows.map((r) => {
            const color = playerColor(r.player);
            const isMe = r.player === me?.name;
            const first = r.player.trim().split(/\s+/)[0] ?? r.player;
            const proj = active === 'actual' ? null : projBy[r.player];
            const projWins = proj ? Object.fromEntries(proj.teams.map((t) => [t.code, t.exp_wins])) : null;
            return (
              <div key={r.player} className={`standings-player${isMe ? ' me' : ''}${r.player === mover ? ' mover' : ''}`}>
                <div className="standings-head" style={{ background: color.bg, color: color.fg }}>{first}</div>
                <div className="standings-body">
                  {Array.from({ length: ROWS }, (_, i) => {
                    const t = r.teams[i];
                    if (!t) return <div key={i} className="standings-row empty" />;
                    const editable = !!me?.is_commissioner && !proj;
                    const cellProps = editable ? { onClick: () => edit(t.code, t.wins) } : {};
                    return (
                      <div
                        key={t.code}
                        className={`standings-row${editable ? ' ov' : ''}`}
                        {...cellProps}
                      >
                        <span className="standings-team">
                          <TeamLogo code={t.code} size={20} />
                          <span className="standings-nick">{names[t.code] ?? t.code}</span>
                        </span>
                        <b className="standings-wins">{projWins ? (projWins[t.code] ?? t.wins).toFixed(1) : t.wins}</b>
                      </div>
                    );
                  })}
                </div>
                <div className="standings-foot">
                  <span>{proj ? 'Proj' : 'Total'}</span>
                  <b>
                    {proj ? proj.exp_wins.toFixed(1) : r.total}
                    {proj && (
                      <span className="standings-range">{rangeLabel(proj.p10, proj.p90)}</span>
                    )}
                  </b>
                </div>
                {sparkScale && live && (
                  <svg className="standings-spark" viewBox="0 0 72 22" width="72" height="22"
                       role="img" aria-label={`${first} combined-wins density`}>
                    {live.rows
                      .slice()
                      .sort((a, b) => Number(a.player === r.player) - Number(b.player === r.player))
                      .map((row) => {
                      const d = sparkArea(live.x, row.dist, 72, 22, sparkScale);
                      if (!d) throw new Error(`missing density for ${row.player}`);
                      const mine = row.player === r.player;
                      return (
                        <path
                          key={row.player}
                          d={d}
                          fill={playerColor(row.player).bg}
                          opacity={mine ? 0.55 : 0.12}
                        />
                      );
                    })}
                  </svg>
                )}
                {pwinBy[r.player] !== undefined && (
                  <div className="standings-foot standings-win">
                    <span>Win</span>
                    <b>
                      {Math.round(pwinBy[r.player] * 100)}%
                      {deltaBy[r.player] !== undefined && Math.round(Math.abs(deltaBy[r.player]) * 100) > 0 && (
                        <span className={`delta ${deltaBy[r.player] > 0 ? 'up' : 'down'}`}>
                          {deltaBy[r.player] > 0 ? '▲' : '▼'} {Math.round(Math.abs(deltaBy[r.player]) * 100)}
                        </span>
                      )}
                    </b>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="stale">
          Updated {new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {(data.stale || ratingsStale) && ' · stale'}
        </div>
      </div>
      <MovementChart weeks={weeks} me={me?.name ?? ''} />
      <TickSpark ticks={live?.ticks ?? []} me={me?.name ?? ''} />
      <Feed view={view} myName={me?.name ?? null} />
    </div>
  );
}

/** Keep first and last; keep a middle tick only when it has `minPx` of air on both sides. */
function thinAxis(xs: number[], minPx: number): boolean[] {
  const n = xs.length;
  const keep = Array(n).fill(false);
  if (n === 0) return keep;
  keep[0] = true;
  keep[n - 1] = true;
  let last = xs[0];
  for (let i = 1; i < n - 1; i++) {
    if (xs[i] - last >= minPx && xs[n - 1] - xs[i] >= minPx) {
      keep[i] = true;
      last = xs[i];
    }
  }
  return keep;
}

/** Spread y positions so consecutive labels sit `gap` apart, inside [lo, hi]. */
function dodgeY(ys: number[], gap: number, lo: number, hi: number): number[] {
  if (ys.length === 0) return [];
  if (hi - lo < (ys.length - 1) * gap) throw new Error('label lane is too short');
  const order = ys.map((_, i) => i).sort((a, b) => ys[a] - ys[b] || a - b);
  const out = ys.slice();
  for (let k = 1; k < order.length; k++) {
    const i = order[k];
    const prev = order[k - 1];
    if (out[i] < out[prev] + gap) out[i] = out[prev] + gap;
  }
  const last = order[order.length - 1];
  if (out[last] > hi) {
    const shift = out[last] - hi;
    for (const i of order) out[i] -= shift;
  }
  if (out[order[0]] < lo) {
    const shift = lo - out[order[0]];
    for (const i of order) out[i] += shift;
  }
  return out;
}

/** Intra-week P(win) as games go final. Hidden until two ticks exist. */
function TickSpark({ ticks, me }: { ticks: NonNullable<LiveProjection['ticks']>; me: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(380);
  const shown = ticks.length >= 2;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(240, el.clientWidth)));
    ro.observe(el);
    setW(Math.max(240, el.clientWidth));
    return () => ro.disconnect();
  }, [shown]);
  if (!shown) return null;

  const players = ticks[ticks.length - 1].rows.map((r) => r.player);
  const H = 140, ML = 8, MR = 88, MT = 10, MB = 22;
  const t0 = ticks[0].at, t1 = ticks[ticks.length - 1].at, span = Math.max(1, t1 - t0);
  const series = players.map((p) => ticks.map((tk) => tk.rows.find((r) => r.player === p)?.pwin ?? 0));
  const maxP = Math.max(0.2, ...series.flat());
  const pw = W - ML - MR, ph = H - MT - MB;
  const xPx = (at: number) => ML + ((at - t0) / span) * pw;
  const yPx = (p: number) => MT + ph - (p / maxP) * ph;
  const xs = ticks.map((tk) => xPx(tk.at));
  const showTime = thinAxis(xs, 64);
  const lastYs = series.map((s) => yPx(s[s.length - 1]));
  const labelYs = dodgeY(lastYs, 18, MT + 4, MT + ph);
  return (
    <div className="card">
      <span className="eyebrow">Win probability today</span>
      <div ref={box} className="move-chart">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
             aria-label="Each player's probability of winning the pool as games finished today">
          {ticks.map((tk, i) => (
            <line key={`g${tk.at}`} x1={xs[i]} y1={MT} x2={xs[i]} y2={MT + ph}
                  stroke="var(--border)" strokeWidth={1} />
          ))}
          {ticks.map((tk, i) => showTime[i] && (
            <text key={tk.at} x={xs[i]} y={H - 6} fill="var(--text-dim)" fontSize={10}
                  textAnchor={i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle'}>
              {new Date(tk.at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
            </text>
          ))}
          {players.map((p, i) => {
            const c = playerColor(p).bg;
            const d = series[i].map((v, k) => `${k ? 'L' : 'M'}${xs[k].toFixed(1)},${yPx(v).toFixed(1)}`).join('');
            return (
              <g key={p}>
                <path d={d} fill="none" stroke={c} strokeWidth={p === me ? 3 : 2} />
                <text x={xs[xs.length - 1] + 8} y={labelYs[i] + 3} fill={c} fontSize={11} fontWeight={700}>
                  {p.trim().split(/\s+/)[0]} {Math.round(series[i][series[i].length - 1] * 100)}%
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
