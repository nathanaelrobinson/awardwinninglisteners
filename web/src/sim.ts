// web/src/sim.ts
//
// Rolling seasons in the browser. The server ships the ensemble (see
// winspool/simmodel.py) and this plays it out: pick a rating source, nudge every
// team off it, then decide remaining games. Later weeks are a weighted coin
// from that world. This week's remaining games are independent coins at the
// price Standings uses (market quote, else the blend) so the cloud and the
// card answer the same question.
//
// Games that have been played are already in `banked` and absent from `games`,
// so a real result is locked into every season rolled here. Tied for first
// counts as a win for everyone tied, matching the prize rule.
//
// Each season gets its own RNG stream keyed by its index, so any single season
// can be replayed on demand. That is what lets the UI open one of a hundred
// thousand simulations without ever storing their games.

export interface SimModel {
  week: number;
  computed_at: number;
  ratings_fetched_at: string | null;
  hfa: number;
  scale: number;
  players: string[];
  rosters: Record<string, string[]>;
  teams: string[];
  sources: string[];
  weights: number[];
  strength: number[][];
  sigma: number[];
  banked: number[];
  weeks: number[];
  /** [week, home, away, p]; p is this week's home-win price, or null to roll from the sampled world */
  games: [number, string, string, number | null][];
  /** finals already banked: [week, home, away, 1 home won / 0 away won / -1 tie, home score, away score] */
  played: [number, string, string, number, number, number][];
}

export interface Rolled {
  nSims: number;
  nWeeks: number;
  nPlayers: number;
  nTeams: number;
  weeks: number[];
  /** per player: Int16Array(nSims * nWeeks) of running win totals */
  paths: Int16Array[];
  /** bit i set when player i is tied for first (co-champions count) */
  winner: Uint8Array;
  /** index into model.sources */
  source: Uint8Array;
}

interface Shape {
  gh: Uint8Array; ga: Uint8Array; gw: Uint8Array;
  gp: Float64Array;
  weekEnd: Int32Array; isEnd: Uint8Array;
  owner: Int8Array; banked0: Float64Array; pbanked0: Float64Array;
  nT: number; nG: number; nP: number; nW: number;
}

function shapeOf(m: SimModel): Shape {
  if (m.games.length > 0 && m.games[0].length < 4) {
    throw new Error('sim model is missing this-week prices');
  }
  const nT = m.teams.length, nG = m.games.length, nP = m.players.length;
  const nW = m.weeks.length;
  const ti = new Map(m.teams.map((c, i) => [c, i]));
  const gh = new Uint8Array(nG), ga = new Uint8Array(nG), gw = new Uint8Array(nG);
  const gp = new Float64Array(nG);
  m.games.forEach((g, i) => {
    gw[i] = g[0]; gh[i] = ti.get(g[1])!; ga[i] = ti.get(g[2])!;
    gp[i] = g[3] == null ? Number.NaN : g[3];
  });
  const wkIdx = new Map(m.weeks.map((w, i) => [w, i]));
  const weekEnd = new Int32Array(nW);
  for (let i = 0; i < nG; i++) weekEnd[wkIdx.get(gw[i])!] = i;
  const isEnd = new Uint8Array(nG);
  for (let k = 0; k < nW; k++) isEnd[weekEnd[k]] = 1;
  const owner = new Int8Array(nT).fill(-1);
  m.players.forEach((p, pi) => m.rosters[p].forEach((c) => { owner[ti.get(c)!] = pi; }));
  const banked0 = Float64Array.from(m.banked);
  const pbanked0 = new Float64Array(nP);
  for (let t = 0; t < nT; t++) if (owner[t] >= 0) pbanked0[owner[t]] += banked0[t];
  return { gh, ga, gw, gp, weekEnd, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW };
}

/** mulberry32 plus Box-Muller as plain locals, so the hot loop stays monomorphic */
function stream(seed: number, s: number) {
  let a = (seed + Math.imul(s, 0x9e3779b1)) >>> 0;
  let spare = 0, hasSpare = false;
  const rand = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const gauss = () => {
    if (hasSpare) { hasSpare = false; return spare; }
    let u = 0, v = 0, r = 0;
    do { u = rand() * 2 - 1; v = rand() * 2 - 1; r = u * u + v * v; } while (r === 0 || r >= 1);
    const f = Math.sqrt((-2 * Math.log(r)) / r);
    spare = v * f; hasSpare = true;
    return u * f;
  };
  return { rand, gauss };
}

/** Which rating source this season believes, then that source's ratings nudged. */
function world(m: SimModel, st: Float64Array, rand: () => number, gauss: () => number) {
  const u0 = rand();
  let src = m.weights.length - 1, cum = 0;
  for (let i = 0; i < m.weights.length; i++) { cum += m.weights[i]; if (u0 < cum) { src = i; break; } }
  const str = m.strength[src];
  for (let t = 0; t < st.length; t++) st[t] = str[t] + m.sigma[t] * gauss();
  return src;
}

/**
 * Replay one season exactly. Fills `detail` with each game's outcome (1 = home
 * won) and returns which rating source's world it was. It draws in the same
 * order as `rollAll` — source, a nudge per team, a flip per game — which is what
 * keeps a replayed season identical to the one that was drawn.
 */
export function rollSeason(m: SimModel, seed: number, s: number, detail: Uint8Array): number {
  const sh = shapeOf(m);
  const { rand, gauss } = stream(seed, s);
  const st = new Float64Array(sh.nT);
  const src = world(m, st, rand, gauss);
  for (let g = 0; g < sh.nG; g++) {
    const p = sh.gp[g];
    if (p === p) {                       // this-week priced coin; NaN is the mixture
      detail[g] = rand() < p ? 1 : 0;
      continue;
    }
    const h = sh.gh[g], b = sh.ga[g];
    detail[g] = (st[h] - st[b] + m.hfa) > m.scale * gauss() ? 1 : 0;
  }
  return src;
}

/** Whether player `pi` finished first (or tied for first) in season `s`. */
export function finishedFirst(winner: Uint8Array, s: number, pi: number): boolean {
  return (winner[s] & (1 << pi)) !== 0;
}

export function rollAll(m: SimModel, nSims: number, seed: number,
                        onProgress?: (done: number) => void): Rolled {
  const { gh, ga, gp, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW } = shapeOf(m);

  const paths = m.players.map(() => new Int16Array(nSims * nW));
  const winner = new Uint8Array(nSims);
  const source = new Uint8Array(nSims);
  const st = new Float64Array(nT), acc = new Float64Array(nT), ptot = new Float64Array(nP);
  const { hfa, scale } = m;

  const step = Math.max(1, Math.ceil(nSims / 20));
  for (let s = 0; s < nSims; s++) {
    if (onProgress && s > 0 && s % step === 0) onProgress(s);
    const { rand, gauss } = stream(seed, s);
    source[s] = world(m, st, rand, gauss);
    acc.set(banked0); ptot.set(pbanked0);
    let w = 0;
    for (let g = 0; g < nG; g++) {
      const h = gh[g], b = ga[g];
      const p = gp[g];
      const home = p === p ? rand() < p : (st[h] - st[b] + hfa) > scale * gauss();
      const wt = home ? h : b;
      acc[wt]++;
      const o = owner[wt];
      if (o >= 0) ptot[o]++;
      if (isEnd[g]) {
        const base = s * nW + w;
        for (let p = 0; p < nP; p++) paths[p][base] = ptot[p];
        w++;
      }
    }
    let best = -1;
    for (let p = 0; p < nP; p++) if (ptot[p] > best) best = ptot[p];
    let bits = 0;
    for (let p = 0; p < nP; p++) if (ptot[p] >= best) bits |= 1 << p;
    winner[s] = bits;
  }

  return { nSims, nWeeks: nW, nPlayers: nP, nTeams: nT, weeks: m.weeks, paths, winner, source };
}

export const SOURCE_LABEL: Record<string, string> = {
  vegas: 'Vegas', kalshi: 'Kalshi', espn_fpi: 'ESPN FPI',
  nfelo: 'nfelo', clay: 'Clay', pff: 'PFF', epa: 'EPA',
  covers: 'Covers', epa_adj: 'EPA', market_strength: 'Market',
};
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;
