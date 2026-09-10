// web/src/sim.ts
//
// Rolling seasons in the browser. The server ships the ensemble (see
// winspool/simmodel.py) and this plays it out: pick a rating source, nudge every
// team off it, then decide every remaining game with a weighted coin flip.
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
  /** finals already banked: [week, home, away, 1 home won / 0 away won / -1 tie] */
  played: [number, string, string, number][];
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
  /** 1 once results have made this season impossible */
  dead: Uint8Array;
  /** how many of these seasons are still possible */
  nAlive: number;
  /** weeks that have at least one final; where the real line stops */
  playedWeeks: number;
  /** real player totals after each played week */
  realPath: number[][];
  /** rolled over the whole season from zero, rather than from today */
  preseason: boolean;
}

interface Shape {
  gh: Uint8Array; ga: Uint8Array; gw: Uint8Array;
  weekEnd: Int32Array; isEnd: Uint8Array;
  owner: Int8Array; banked0: Float64Array; pbanked0: Float64Array;
  nT: number; nG: number; nP: number; nW: number; weeksAll: number[];
}

/** The games a cohort plays: everything from week 1 for a preseason roll,
 *  only what is left for a live one. */
export function scheduleOf(m: SimModel, preseason: boolean): [number, string, string][] {
  if (!preseason) return m.games;
  const all: [number, string, string][] = [
    ...m.played.map(([w, h, a]) => [w, h, a] as [number, string, string]), ...m.games,
  ];
  return all.sort((x, y) => x[0] - y[0]);
}

function shapeOf(m: SimModel, preseason = false): Shape {
  const games = scheduleOf(m, preseason);
  const nT = m.teams.length, nG = games.length, nP = m.players.length;
  const weeksAll = [...new Set(games.map((g) => g[0]))].sort((a, b) => a - b);
  const nW = weeksAll.length;
  const ti = new Map(m.teams.map((c, i) => [c, i]));
  const gh = new Uint8Array(nG), ga = new Uint8Array(nG), gw = new Uint8Array(nG);
  games.forEach((g, i) => { gw[i] = g[0]; gh[i] = ti.get(g[1])!; ga[i] = ti.get(g[2])!; });
  const wkIdx = new Map(weeksAll.map((w, i) => [w, i]));
  const weekEnd = new Int32Array(nW);
  for (let i = 0; i < nG; i++) weekEnd[wkIdx.get(gw[i])!] = i;
  const isEnd = new Uint8Array(nG);
  for (let k = 0; k < nW; k++) isEnd[weekEnd[k]] = 1;
  const owner = new Int8Array(nT).fill(-1);
  m.players.forEach((p, pi) => m.rosters[p].forEach((c) => { owner[ti.get(c)!] = pi; }));
  // a preseason cohort starts from nothing; a live one starts from what is banked
  const banked0 = preseason ? new Float64Array(nT) : Float64Array.from(m.banked);
  const pbanked0 = new Float64Array(nP);
  for (let t = 0; t < nT; t++) if (owner[t] >= 0) pbanked0[owner[t]] += banked0[t];
  return { gh, ga, gw, weekEnd, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW, weeksAll };
}

/** mulberry32 plus Box-Muller, as plain locals so the hot loop stays monomorphic */
function streamFor(seed: number, s: number) {
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

/**
 * Replay one season exactly. Fills `detail` with each game's outcome (1 = home
 * won) and returns which rating source's world it was. Must stay in step with
 * the loop in `rollAll`, which is why both draw in the same order: source,
 * then one nudge per team, then one flip per game.
 */
export function rollSeason(m: SimModel, seed: number, s: number, detail: Uint8Array,
                           preseason = false): number {
  const sh = shapeOf(m, preseason);
  const { rand, gauss } = streamFor(seed, s);
  const u0 = rand();
  let src = m.weights.length - 1, cum = 0;
  for (let i = 0; i < m.weights.length; i++) { cum += m.weights[i]; if (u0 < cum) { src = i; break; } }
  const str = m.strength[src];
  const st = new Float64Array(sh.nT);
  for (let t = 0; t < sh.nT; t++) st[t] = str[t] + m.sigma[t] * gauss();
  for (let g = 0; g < sh.nG; g++) {
    const h = sh.gh[g], a = sh.ga[g];
    detail[g] = (st[h] - st[a] + m.hfa) > m.scale * gauss() ? 1 : 0;
  }
  return src;
}

/**
 * `preseason` replays the whole season from zero, including games that have
 * since been decided, so the cohort is what we believed in August and results
 * can rule members of it out. Otherwise every season starts from today's banked
 * wins, which is what a live projection shows and which can never be wrong.
 */
export function rollAll(m: SimModel, nSims: number, seed: number, preseason = false): Rolled {
  const sh = shapeOf(m, preseason);
  const { gh, ga, isEnd, owner, banked0, pbanked0, nT, nG, nP, nW } = sh;

  const paths = m.players.map(() => new Int16Array(nSims * nW));
  const winner = new Uint8Array(nSims);
  const source = new Uint8Array(nSims);
  const finals = new Int16Array(nSims * nP);
  const st = new Float64Array(nT), acc = new Float64Array(nT), ptot = new Float64Array(nP);
  const { hfa, scale, weights } = m;

  for (let s = 0; s < nSims; s++) {
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

    const u0 = rand();
    let src = weights.length - 1, cum = 0;
    for (let i = 0; i < weights.length; i++) { cum += weights[i]; if (u0 < cum) { src = i; break; } }
    source[s] = src;
    const str = m.strength[src];
    for (let t = 0; t < nT; t++) st[t] = str[t] + m.sigma[t] * gauss();
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
      finals[s * nP + p] = ptot[p];
      if (ptot[p] > best) { best = ptot[p]; bi = p; tie = false; }
      else if (ptot[p] === best) tie = true;
    }
    winner[s] = tie ? 0 : bi + 1;
  }

  const { dead, nAlive, realPath, playedWeeks } = eliminate(m, sh, finals, nSims, preseason);
  return { nSims, nWeeks: nW, nPlayers: nP, nTeams: nT, weeks: sh.weeksAll,
           paths, winner, source, dead, nAlive, playedWeeks, realPath, preseason };
}

/**
 * A season rolled from zero is a whole-season prediction of where every player
 * lands. Results rule it out once a player has already banked more wins than it
 * allowed them, or can no longer reach the number it gave them.
 *
 * The pool only reads player totals, so that is where the test belongs. Testing
 * all 32 teams instead kills 99.8% of seasons by week 8 — true, and useless.
 *
 * A cohort rolled from today's banked wins is consistent with results by
 * construction, so nothing is ever ruled out there.
 */
function eliminate(m: SimModel, sh: Shape, finals: Int16Array, nSims: number,
                   preseason: boolean) {
  const { owner, nP, nT } = sh;
  const ti = new Map(m.teams.map((c, i) => [c, i]));

  // what the players have actually banked, and how much is still to come
  const realP = new Float64Array(nP);
  for (let t = 0; t < nT; t++) if (owner[t] >= 0) realP[owner[t]] += m.banked[t];
  const remP = new Int32Array(nP);
  for (const [, home, away] of m.games) {
    const oh = owner[ti.get(home)!], oa = owner[ti.get(away)!];
    if (oh >= 0) remP[oh]++;
    if (oa >= 0) remP[oa]++;
  }

  // real player totals after each week that has a final, for the "what happened" line
  const weeksWithFinals = [...new Set(m.played.map((g) => g[0]))].sort((a, b) => a - b);
  const running = new Float64Array(nP);
  const realPath: number[][] = m.players.map(() => []);
  for (const wk of weeksWithFinals) {
    for (const [w, home, away, hw] of m.played) {
      if (w !== wk) continue;
      if (hw === -1) {
        const oh = owner[ti.get(home)!], oa = owner[ti.get(away)!];
        if (oh >= 0) running[oh] += 0.5;
        if (oa >= 0) running[oa] += 0.5;
      } else {
        const o = owner[ti.get(hw === 1 ? home : away)!];
        if (o >= 0) running[o]++;
      }
    }
    for (let p = 0; p < nP; p++) realPath[p].push(running[p]);
  }

  const dead = new Uint8Array(nSims);
  let nAlive = nSims;
  if (preseason && m.played.length) {
    for (let s = 0; s < nSims; s++) {
      for (let p = 0; p < nP; p++) {
        const pred = finals[s * nP + p];
        if (pred < realP[p] || pred > realP[p] + remP[p]) { dead[s] = 1; nAlive--; break; }
      }
    }
  }
  return { dead, nAlive, realPath, playedWeeks: weeksWithFinals.length };
}

/**
 * Re-anchor every season on the results that are in and replay only what is
 * left. Team strengths are not re-fit to those results; the games after the
 * line are the same rolls the season already made.
 */
export function resimulate(r: Rolled, lockedWeeks: number) {
  if (lockedWeeks <= 0 || !r.realPath[0]?.length) return { paths: r.paths, winner: r.winner };
  const { nSims, nWeeks: nW, nPlayers: nP } = r, k = lockedWeeks;
  const paths = r.paths.map(() => new Int16Array(nSims * nW));
  const winner = new Uint8Array(nSims);
  for (let p = 0; p < nP; p++) {
    const src = r.paths[p], dst = paths[p], realK = r.realPath[p][k - 1];
    for (let s = 0; s < nSims; s++) {
      const base = s * nW, anchor = src[base + k - 1];
      for (let w = 0; w < k; w++) dst[base + w] = r.realPath[p][w];
      for (let w = k; w < nW; w++) dst[base + w] = realK + (src[base + w] - anchor);
    }
  }
  for (let s = 0; s < nSims; s++) {
    let best = -1, bi = -1, tie = false;
    for (let p = 0; p < nP; p++) {
      const v = paths[p][s * nW + nW - 1];
      if (v > best) { best = v; bi = p; tie = false; } else if (v === best) tie = true;
    }
    winner[s] = tie ? 0 : bi + 1;
  }
  return { paths, winner };
}

export const SOURCE_LABEL: Record<string, string> = {
  vegas: 'Vegas', kalshi: 'Kalshi', espn_fpi: 'ESPN FPI',
  nfelo: 'nfelo', clay: 'Clay', pff: 'PFF', epa: 'EPA',
};
export const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;
