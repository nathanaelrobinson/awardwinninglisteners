// web/src/sim.ts
//
// Rolling seasons in the browser. The server ships the ensemble (see
// winspool/simmodel.py) and this plays it out: pick a rating source, nudge every
// team off it, then decide every remaining game with a weighted coin flip.
//
// Games that have been played are already in `banked` and absent from `games`,
// so a real result is locked into every season rolled here.
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
  games: [number, string, string][];
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
  /** 1-based player index that won, 0 for a tie at the top */
  winner: Uint8Array;
  /** index into model.sources */
  source: Uint8Array;
}

interface Shape {
  gh: Uint8Array; ga: Uint8Array; gw: Uint8Array;
  weekEnd: Int32Array; isEnd: Uint8Array;
  owner: Int8Array; banked0: Float64Array; pbanked0: Float64Array;
  nT: number; nG: number; nP: number; nW: number;
}

function shapeOf(m: SimModel): Shape {
  const nT = m.teams.length, nG = m.games.length, nP = m.players.length;
  const nW = m.weeks.length;
  const ti = new Map(m.teams.map((c, i) => [c, i]));
  const gh = new Uint8Array(nG), ga = new Uint8Array(nG), gw = new Uint8Array(nG);
  m.games.forEach((g, i) => { gw[i] = g[0]; gh[i] = ti.get(g[1])!; ga[i] = ti.get(g[2])!; });
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
  return { gh, ga, gw, weekEnd, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW };
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
    const h = sh.gh[g], b = sh.ga[g];
    detail[g] = (st[h] - st[b] + m.hfa) > m.scale * gauss() ? 1 : 0;
  }
  return src;
}

export function rollAll(m: SimModel, nSims: number, seed: number,
                        onProgress?: (done: number) => void): Rolled {
  const { gh, ga, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW } = shapeOf(m);

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
      const wt = (st[h] - st[b] + hfa) > scale * gauss() ? h : b;
      acc[wt]++;
      const o = owner[wt];
      if (o >= 0) ptot[o]++;
      if (isEnd[g]) {
        const base = s * nW + w;
        for (let p = 0; p < nP; p++) paths[p][base] = ptot[p];
        w++;
      }
    }
    let best = -1, bi = -1, tie = false;
    for (let p = 0; p < nP; p++) {
      if (ptot[p] > best) { best = ptot[p]; bi = p; tie = false; }
      else if (ptot[p] === best) tie = true;
    }
    winner[s] = tie ? 0 : bi + 1;
  }

  return { nSims, nWeeks: nW, nPlayers: nP, nTeams: nT, weeks: m.weeks, paths, winner, source };
}

export const SOURCE_LABEL: Record<string, string> = {
  vegas: 'Vegas', kalshi: 'Kalshi', espn_fpi: 'ESPN FPI',
  nfelo: 'nfelo', clay: 'Clay', pff: 'PFF', epa: 'EPA',
};
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;

export interface Conditionals {
  /** each player's mean final wins across every simulation */
  mean: Float64Array;
  /** cond[i][j] = player j's mean final wins across the simulations player i won */
  cond: Float64Array[];
  /** simulations won outright by each player -- the sample behind each row */
  counts: Int32Array;
  /** simulations that tied at the top; counted in `mean`, excluded from `cond` */
  ties: number;
}

/**
 * Who does well when who else wins.
 *
 * A pool this shape is close to zero-sum -- a season hands out a fixed 272 wins
 * and the rosters hold 30 of the 32 teams -- so every pair of players is
 * negatively correlated whether or not they are really rivals, and a plain
 * correlation matrix mostly measures that arithmetic. Conditioning on the
 * winner instead keeps the answer in wins: when player i wins, how far from
 * their own average does everyone else land?
 */
export function winnerConditionals(r: Rolled): Conditionals {
  const { nSims, nWeeks, nPlayers, paths, winner } = r;
  const last = nWeeks - 1;
  const mean = new Float64Array(nPlayers);
  const cond = Array.from({ length: nPlayers }, () => new Float64Array(nPlayers));
  const counts = new Int32Array(nPlayers);
  let ties = 0;
  for (let s = 0; s < nSims; s++) {
    const w = winner[s];
    if (w === 0) ties++; else counts[w - 1]++;
    const base = s * nWeeks + last;
    for (let p = 0; p < nPlayers; p++) {
      const v = paths[p][base];
      mean[p] += v;
      if (w !== 0) cond[w - 1][p] += v;
    }
  }
  for (let p = 0; p < nPlayers; p++) mean[p] /= nSims || 1;
  for (let i = 0; i < nPlayers; i++) {
    const c = counts[i] || 1;
    for (let p = 0; p < nPlayers; p++) cond[i][p] /= c;
  }
  return { mean, cond, counts, ties };
}
