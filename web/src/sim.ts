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
  /** bit i set when this-week remaining game i was a home win */
  thisWeek: Uint32Array;
  /** packed home-win bits for every remaining game, nSims * stride bytes */
  homeBits: Uint8Array;
  stride: number;
  nGames: number;
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

/** Combined-wins percentile range shown next to projected totals. */
export function rangeLabel(p10: number, p90: number): string {
  return `${p10}-${p90}`;
}

/** Shared wins-axis and height so several densities can be compared. */
export type SparkScale = { lo: number; hi: number; maxP: number };

/** Union of bins where any density is positive, plus the tallest peak. */
export function sparkDomain(x: number[], dists: number[][]): SparkScale {
  if (!x.length) throw new Error('spark domain with empty x');
  let maxP = 0;
  let lo = Infinity;
  let hi = -Infinity;
  for (const dist of dists) {
    if (dist.length !== x.length) throw new Error('spark dist length');
    for (let i = 0; i < x.length; i++) {
      if (dist[i] > 0) {
        maxP = Math.max(maxP, dist[i]);
        lo = Math.min(lo, x[i]);
        hi = Math.max(hi, x[i]);
      }
    }
  }
  if (!(maxP > 0)) throw new Error('spark domain all zero');
  return { lo, hi, maxP };
}

/** SVG area path for a small combined-wins density. Null when there is nothing to draw. */
export function sparkArea(
  x: number[], dist: number[], w: number, h: number, scale?: SparkScale,
): string | null {
  if (!x.length || dist.length !== x.length) return null;
  const maxP = scale ? scale.maxP : Math.max(...dist);
  if (!(maxP > 0)) return null;
  const lo = scale ? scale.lo : x[0];
  const hi = scale ? scale.hi : x[x.length - 1];
  const span = Math.max(1, hi - lo);
  const xPx = (v: number) => ((v - lo) / span) * w;
  const yPx = (p: number) => h - (p / maxP) * h;
  const line = dist.map((p, i) => `${i ? 'L' : 'M'}${xPx(x[i]).toFixed(1)},${yPx(p).toFixed(1)}`).join('');
  return `${line}L${xPx(hi).toFixed(1)},${yPx(0).toFixed(1)}L${xPx(lo).toFixed(1)},${yPx(0).toFixed(1)}Z`;
}

export type Pin = { g: number; homeWin: boolean };

/** Unique remaining weeks, in schedule order. */
export function remainingWeeks(m: SimModel): number[] {
  const seen: number[] = [];
  for (const g of m.games) if (seen[seen.length - 1] !== g[0]) seen.push(g[0]);
  return seen;
}

export function bitStride(nGames: number): number {
  return Math.max(1, Math.ceil(nGames / 8));
}

/** Packed home-win bit for remaining game `g` in season `s`. */
export function gameHome(bits: Uint8Array, stride: number, s: number, g: number): boolean {
  return (bits[s * stride + (g >> 3)] & (1 << (g & 7))) !== 0;
}

function setGameHome(bits: Uint8Array, stride: number, s: number, g: number): void {
  bits[s * stride + (g >> 3)] |= 1 << (g & 7);
}

/** True when season `s` matches every pin. An empty pin list matches everyone. */
export function pinMatches(bits: Uint8Array, stride: number, s: number, pins: Pin[]): boolean {
  for (const p of pins) {
    if (gameHome(bits, stride, s, p.g) !== p.homeWin) return false;
  }
  return true;
}

/**
 * Pin remaining game `g` to a home win or an away win. Clicking the side
 * that is already pinned clears it; clicking the other side switches.
 */
export function toggleGamePin(pins: Pin[], g: number, homeWin: boolean): Pin[] {
  const i = pins.findIndex((p) => p.g === g);
  if (i < 0) return [...pins, { g, homeWin }];
  if (pins[i].homeWin === homeWin) return pins.filter((_, j) => j !== i);
  return pins.map((p, j) => (j === i ? { g, homeWin } : p));
}

/** P(player pi finishes first | home) minus P(... | away) for each remaining game. */
export function gameSwing(
  winner: Uint8Array, homeBits: Uint8Array, stride: number, nGames: number, pi: number,
): number[] {
  const homeW = new Float64Array(nGames), homeN = new Float64Array(nGames);
  const awayW = new Float64Array(nGames), awayN = new Float64Array(nGames);
  for (let s = 0; s < winner.length; s++) {
    const won = finishedFirst(winner, s, pi) ? 1 : 0;
    for (let g = 0; g < nGames; g++) {
      if (gameHome(homeBits, stride, s, g)) { homeN[g]++; homeW[g] += won; }
      else { awayN[g]++; awayW[g] += won; }
    }
  }
  const out = new Array<number>(nGames);
  for (let g = 0; g < nGames; g++) {
    const hp = homeN[g] ? homeW[g] / homeN[g] : 0;
    const ap = awayN[g] ? awayW[g] / awayN[g] : 0;
    out[g] = hp - ap;
  }
  return out;
}
export function thisWeekIndexes(m: SimModel): number[] {
  const idx: number[] = [];
  for (let i = 0; i < m.games.length; i++) if (m.games[i][3] != null) idx.push(i);
  if (idx.length > 32) throw new Error('this week has more than 32 remaining games');
  return idx;
}

/** Pack this-week home-win bits from a `rollSeason` detail array. */
export function packThisWeek(detail: Uint8Array, indexes: number[]): number {
  if (indexes.length > 32) throw new Error('this week has more than 32 remaining games');
  let bits = 0;
  for (let i = 0; i < indexes.length; i++) if (detail[indexes[i]]) bits |= 1 << i;
  return bits;
}

/** True when the season's this-week bits satisfy a pin. Mask 0 matches everyone. */
export function seasonMatches(bits: number, mask: number, want: number): boolean {
  return (bits & mask) === want;
}

/**
 * Pin this-week game `bit` to a home win or an away win. Clicking the side
 * that is already pinned clears it; clicking the other side switches.
 */
export function togglePin(mask: number, want: number, bit: number, homeWin: boolean): [number, number] {
  const m = 1 << bit;
  if (mask & m) {
    const currentlyHome = (want & m) !== 0;
    if (currentlyHome === homeWin) return [mask & ~m, want & ~m];
    return [mask, homeWin ? want | m : want & ~m];
  }
  return [mask | m, homeWin ? want | m : want];
}

/** Wins and season count for player `pi` among seasons matching the pins. */
export function pwinOf(
  winner: Uint8Array, pi: number, homeBits: Uint8Array, stride: number, pins: Pin[],
): { wins: number; n: number } {
  let wins = 0, n = 0;
  for (let s = 0; s < winner.length; s++) {
    if (!pinMatches(homeBits, stride, s, pins)) continue;
    n++;
    if (finishedFirst(winner, s, pi)) wins++;
  }
  return { wins, n };
}

/** Same count as `pwinOf`, split by which rating world the season sampled. */
export function pwinBySource(
  source: Uint8Array, winner: Uint8Array, sources: string[], pi: number,
  homeBits: Uint8Array, stride: number, pins: Pin[],
): { source: string; wins: number; n: number }[] {
  const wins = new Int32Array(sources.length), n = new Int32Array(sources.length);
  for (let s = 0; s < winner.length; s++) {
    if (!pinMatches(homeBits, stride, s, pins)) continue;
    const src = source[s];
    n[src]++;
    if (finishedFirst(winner, s, pi)) wins[src]++;
  }
  return sources.map((name, i) => ({ source: name, wins: wins[i], n: n[i] }));
}

/** Each player's combined banked wins at the start of the remaining schedule. */
export function playerBanked(m: SimModel): number[] {
  const ti = new Map(m.teams.map((c, i) => [c, i]));
  return m.players.map((p) => {
    let s = 0;
    for (const c of m.rosters[p]) {
      const i = ti.get(c);
      if (i === undefined) throw new Error(`unknown team ${c}`);
      s += m.banked[i];
    }
    return s;
  });
}

/**
 * Shared prefix of the cloud: cumulative roster wins after each week that is
 * already fully behind the remaining schedule. Derived from `played` only.
 * Current-week finals stay out — they are already inside the first remaining
 * path point via `banked`. Throws if games have been played but week 1 is not
 * among them, so the left edge cannot be a real W1.
 */
export function playedHistory(m: SimModel): { weeks: number[]; totals: number[][] } {
  const empty = { weeks: [] as number[], totals: m.players.map(() => [] as number[]) };
  if (m.played.length === 0) return empty;
  if (!m.played.some((g) => g[0] === 1)) {
    throw new Error('played games exist but week 1 is missing');
  }
  const lastHist = m.weeks.length > 0 ? m.weeks[0] - 1 : Math.max(...m.played.map((g) => g[0]));
  if (lastHist < 1) return empty;

  const weeks: number[] = [];
  for (let w = 1; w <= lastHist; w++) weeks.push(w);

  const owner = new Map<string, number>();
  m.players.forEach((p, pi) => {
    for (const c of m.rosters[p]) owner.set(c, pi);
  });
  const known = new Set(m.teams);
  const inc = weeks.map(() => new Float64Array(m.players.length));
  for (const [wk, home, away, hw] of m.played) {
    if (wk > lastHist) continue;
    if (!known.has(home) || !known.has(away)) throw new Error(`unknown team ${home}/${away}`);
    const i = wk - 1;
    const add = (code: string, n: number) => {
      const pi = owner.get(code);
      if (pi !== undefined) inc[i][pi] += n;
    };
    if (hw === 1) add(home, 1);
    else if (hw === 0) add(away, 1);
    else if (hw === -1) { /* NFL tie: 0 wins */ }
    else throw new Error(`bad played result ${hw}`);
  }

  const totals = m.players.map(() => new Array<number>(weeks.length));
  const run = new Float64Array(m.players.length);
  for (let w = 0; w < weeks.length; w++) {
    for (let p = 0; p < m.players.length; p++) {
      run[p] += inc[w][p];
      totals[p][w] = run[p];
    }
  }
  return { weeks, totals };
}

export type Lead = {
  firstWeek: number | 'start' | null;
  lastWeek: number | 'start' | null;
};

/** First and last checkpoint at which player `pi` was tied-for or sole first. */
export function leadOf(
  startTotals: number[], paths: Int16Array[], weeks: number[], s: number, pi: number,
): Lead {
  const nW = weeks.length;
  const isLead = (totals: number[]) => {
    let best = -Infinity;
    for (const v of totals) if (v > best) best = v;
    return totals[pi] >= best;
  };
  let first: Lead['firstWeek'] = null;
  let last: Lead['lastWeek'] = null;
  if (isLead(startTotals)) { first = 'start'; last = 'start'; }
  for (let w = 0; w < nW; w++) {
    const totals = paths.map((p) => p[s * nW + w]);
    if (isLead(totals)) {
      if (first === null) first = weeks[w];
      last = weeks[w];
    }
  }
  return { firstWeek: first, lastWeek: last };
}

/** One-line reading of `leadOf` for the opened season. */
export function leadPhrase(lead: Lead, won: boolean): string {
  if (lead.firstWeek === null) return 'Never led.';
  if (won) {
    if (lead.firstWeek === 'start') return 'Led from the start.';
    return `Took the lead in week ${lead.firstWeek}.`;
  }
  if (lead.lastWeek === 'start') return 'Led at the start.';
  return `Last led in week ${lead.lastWeek}.`;
}

/** Standard normal CDF. Home-win probability is Phi((s_h - s_a + hfa) / scale). */
export function normCdf(z: number): number {
  return 0.5 * (1 + erf(z / Math.SQRT2));
}

/** Abramowitz and Stegun 7.1.26. */
function erf(x: number): number {
  const sign = x < 0 ? -1 : 1;
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592)
    * t * Math.exp(-x * x);
  return sign * y;
}

/**
 * Banked wins plus remaining expected wins in source world `src`. This week's
 * games use the shipped price; later weeks use Phi of that world's strengths.
 */
export function expectedTeamWins(m: SimModel, src: number): Float64Array {
  if (m.scale === 0) throw new Error('scale is 0');
  const ti = new Map(m.teams.map((c, i) => [c, i]));
  const str = m.strength[src];
  const out = Float64Array.from(m.banked);
  for (const g of m.games) {
    const h = ti.get(g[1]), a = ti.get(g[2]);
    if (h === undefined || a === undefined) throw new Error(`unknown team ${g[1]}/${g[2]}`);
    const pHome = g[3] == null ? normCdf((str[h] - str[a] + m.hfa) / m.scale) : g[3];
    out[h] += pHome;
    out[a] += 1 - pHome;
  }
  return out;
}

export function rollAll(m: SimModel, nSims: number, seed: number,
                        onProgress?: (done: number) => void): Rolled {
  const { gh, ga, gp, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW } = shapeOf(m);

  const paths = m.players.map(() => new Int16Array(nSims * nW));
  const winner = new Uint8Array(nSims);
  const source = new Uint8Array(nSims);
  const thisWeek = new Uint32Array(nSims);
  const stride = bitStride(nG);
  const homeBits = new Uint8Array(nSims * stride);
  const st = new Float64Array(nT), acc = new Float64Array(nT), ptot = new Float64Array(nP);
  const { hfa, scale } = m;
  thisWeekIndexes(m);

  const step = Math.max(1, Math.ceil(nSims / 20));
  for (let s = 0; s < nSims; s++) {
    if (onProgress && s > 0 && s % step === 0) onProgress(s);
    const { rand, gauss } = stream(seed, s);
    source[s] = world(m, st, rand, gauss);
    acc.set(banked0); ptot.set(pbanked0);
    let w = 0, bits = 0, bit = 0;
    for (let g = 0; g < nG; g++) {
      const h = gh[g], b = ga[g];
      const p = gp[g];
      const home = p === p ? rand() < p : (st[h] - st[b] + hfa) > scale * gauss();
      if (home) setGameHome(homeBits, stride, s, g);
      if (p === p) { if (home) bits |= 1 << bit; bit++; }
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
    let wbits = 0;
    for (let p = 0; p < nP; p++) if (ptot[p] >= best) wbits |= 1 << p;
    winner[s] = wbits;
    thisWeek[s] = bits;
  }

  return { nSims, nWeeks: nW, nPlayers: nP, nTeams: nT, weeks: m.weeks, paths, winner, source, thisWeek,
           homeBits, stride, nGames: nG };
}

export const SOURCE_LABEL: Record<string, string> = {
  posterior: 'Posterior',
  vegas: 'Vegas', kalshi: 'Kalshi', espn_fpi: 'ESPN FPI',
  nfelo: 'nfelo', clay: 'Clay', pff: 'PFF', epa: 'EPA',
  covers: 'Covers', epa_adj: 'EPA', market_strength: 'Market',
};
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;
