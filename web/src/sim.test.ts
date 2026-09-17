// web/src/sim.test.ts
//
// The Simulations tab now slices the cloud, splits win% by rating world, and
// reads an opened season for lead week and team luck. Those are all arithmetic
// on the roll; this file pins that arithmetic before the UI wires it up.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  expectedTeamWins,
  gameHome,
  gameSwing,
  leadOf,
  leadPhrase,
  packThisWeek,
  pinMatches,
  playedHistory,
  playerBanked,
  pwinBySource,
  pwinOf,
  rangeLabel,
  remainingWeeks,
  rollAll,
  rollSeason,
  seasonMatches,
  sparkArea,
  sparkDomain,
  thisWeekIndexes,
  toggleGamePin,
  togglePin,
  type Pin,
  type SimModel,
} from './sim.ts';

function toy(over: Partial<SimModel> = {}): SimModel {
  return {
    week: 1,
    computed_at: 0,
    ratings_fetched_at: null,
    hfa: 0,
    scale: 13.5,
    players: ['Nate', 'Evan'],
    rosters: { Nate: ['BUF'], Evan: ['NYJ'] },
    teams: ['BUF', 'NYJ'],
    sources: ['kalshi', 'epa'],
    weights: [0.5, 0.5],
    strength: [[7, -7], [-7, 7]],
    sigma: [0, 0],
    banked: [0, 0],
    weeks: [1],
    games: [[1, 'BUF', 'NYJ', 0.8]],
    played: [],
    ...over,
  };
}

test('thisWeekIndexes is the remaining games that carry a price', () => {
  const m = toy({
    weeks: [1, 2],
    games: [
      [1, 'BUF', 'NYJ', 0.8],
      [2, 'NYJ', 'BUF', null],
    ],
  });
  assert.deepEqual(thisWeekIndexes(m), [0]);
});

test('packThisWeek sets bit i when this-week game i is a home win', () => {
  const idx = [0, 2];
  assert.equal(packThisWeek(Uint8Array.of(1, 1, 0), idx), 0b01);
  assert.equal(packThisWeek(Uint8Array.of(1, 0, 1), idx), 0b11);
});

test('rollAll this-week bits match a replay of the same season', () => {
  const m = toy({
    weeks: [1, 2],
    games: [
      [1, 'BUF', 'NYJ', 0.8],
      [1, 'NYJ', 'BUF', 0.4],
      [2, 'BUF', 'NYJ', null],
    ],
  });
  const rolled = rollAll(m, 40, 7);
  const idx = thisWeekIndexes(m);
  const detail = new Uint8Array(m.games.length);
  for (let s = 0; s < rolled.nSims; s++) {
    rollSeason(m, 7, s, detail);
    assert.equal(rolled.thisWeek[s], packThisWeek(detail, idx));
  }
});

test('seasonMatches is true for every season when nothing is pinned', () => {
  assert.equal(seasonMatches(0b10, 0, 0), true);
  assert.equal(seasonMatches(0b11, 0b01, 0b01), true);
  assert.equal(seasonMatches(0b10, 0b01, 0b01), false);
});

test('togglePin cycles a game through home, away, and clear', () => {
  let mask = 0, want = 0;
  [mask, want] = togglePin(mask, want, 0, true);
  assert.deepEqual([mask, want], [0b01, 0b01]);
  [mask, want] = togglePin(mask, want, 0, true);
  assert.deepEqual([mask, want], [0, 0]);
  [mask, want] = togglePin(mask, want, 0, false);
  assert.deepEqual([mask, want], [0b01, 0]);
  [mask, want] = togglePin(mask, want, 0, true);
  assert.deepEqual([mask, want], [0b01, 0b01]);
});

test('pwinOf counts only seasons that match the pin', () => {
  const winner = Uint8Array.of(1, 0, 1, 1); // player 0 wins 0,2,3
  const bits = new Uint8Array([1, 0, 1, 2]);
  const all = pwinOf(winner, 0, bits, 1, []);
  assert.deepEqual(all, { wins: 3, n: 4 });
  const pinned = pwinOf(winner, 0, bits, 1, [{ g: 0, homeWin: true }]);
  assert.deepEqual(pinned, { wins: 2, n: 2 });
});

test('pwinBySource splits the same count per rating world', () => {
  const rows = pwinBySource(
    Uint8Array.of(0, 0, 1, 1),
    Uint8Array.of(1, 0, 1, 1),
    ['kalshi', 'epa'],
    0,
    new Uint8Array([0, 0, 0, 0]),
    1,
    [],
  );
  assert.deepEqual(rows, [
    { source: 'kalshi', wins: 1, n: 2 },
    { source: 'epa', wins: 2, n: 2 },
  ]);
});

test('playerBanked sums each roster from the team banked vector', () => {
  const m = toy({ banked: [1.5, 0] });
  assert.deepEqual(playerBanked(m), [1.5, 0]);
});

test('leadOf finds the first and last week a player was in first', () => {
  // start Evan 3-2; after W1 still; after W2 tied; after W3 Nate.
  const nate = Int16Array.of(2, 5, 8);
  const evan = Int16Array.of(4, 5, 7);
  const nateLead = leadOf([2, 3], [nate, evan], [1, 2, 3], 0, 0);
  assert.deepEqual(nateLead, { firstWeek: 2, lastWeek: 3 });
  const evanLead = leadOf([2, 3], [nate, evan], [1, 2, 3], 0, 1);
  assert.deepEqual(evanLead, { firstWeek: 'start', lastWeek: 2 });
});

test('leadPhrase names the week they took the lead, or that they never did', () => {
  assert.equal(leadPhrase({ firstWeek: 'start', lastWeek: 3 }, true), 'Led from the start.');
  assert.equal(leadPhrase({ firstWeek: 11, lastWeek: 18 }, true), 'Took the lead in week 11.');
  assert.equal(leadPhrase({ firstWeek: null, lastWeek: null }, false), 'Never led.');
  assert.equal(leadPhrase({ firstWeek: 'start', lastWeek: 9 }, false), 'Last led in week 9.');
});

test('expectedTeamWins uses this-week prices, not the sampled world, for tonight', () => {
  const m = toy({
    banked: [1, 0],
    strength: [[20, -20], [20, -20]],
    games: [[1, 'BUF', 'NYJ', 0.25]],
  });
  const ew = expectedTeamWins(m, 0);
  assert.equal(ew[0], 1.25);
  assert.equal(ew[1], 0.75);
});

test('expectedTeamWins uses the source strength for later weeks', () => {
  const m = toy({
    hfa: 0,
    scale: 13.5,
    banked: [0, 0],
    weeks: [2],
    games: [[2, 'BUF', 'NYJ', null]],
    strength: [[13.5, 0], [0, 0]],
  });
  const ew = expectedTeamWins(m, 0);
  // Phi(1) ~ 0.8413
  assert.ok(Math.abs(ew[0] - 0.841344746) < 1e-3, String(ew[0]));
  assert.ok(Math.abs(ew[1] - (1 - ew[0])) < 1e-12);
});

test('thisWeekIndexes throws when a week has more than 32 remaining games', () => {
  const games: SimModel['games'] = [];
  for (let i = 0; i < 33; i++) games.push([1, 'BUF', 'NYJ', 0.5]);
  assert.throws(() => thisWeekIndexes(toy({ games })), /32/);
});

test('playedHistory is empty when nothing has been played', () => {
  const h = playedHistory(toy());
  assert.deepEqual(h.weeks, []);
  assert.deepEqual(h.totals, [[], []]);
});

test('playedHistory prepends W1 from played games when remaining starts at W2', () => {
  const h = playedHistory(toy({
    weeks: [2],
    games: [[2, 'NYJ', 'BUF', 0.5]],
    played: [[1, 'BUF', 'NYJ', 1, 21, 10]],
  }));
  assert.deepEqual(h.weeks, [1]);
  assert.deepEqual(h.totals, [[1], [0]]);
});

test('playedHistory accumulates each fully-played week before the remaining schedule', () => {
  const h = playedHistory(toy({
    weeks: [3],
    games: [[3, 'BUF', 'NYJ', null]],
    played: [
      [1, 'BUF', 'NYJ', 1, 21, 10],
      [2, 'NYJ', 'BUF', 1, 17, 14],
    ],
  }));
  assert.deepEqual(h.weeks, [1, 2]);
  assert.deepEqual(h.totals, [[1, 1], [0, 1]]);
});

test('playedHistory counts a tie as zero wins for each side', () => {
  const h = playedHistory(toy({
    weeks: [2],
    games: [[2, 'BUF', 'NYJ', null]],
    played: [[1, 'BUF', 'NYJ', -1, 17, 17]],
  }));
  assert.deepEqual(h.totals, [[0], [0]]);
});

test('playedHistory ignores current-week finals already in the remaining path', () => {
  const h = playedHistory(toy({
    weeks: [2],
    games: [[2, 'NYJ', 'BUF', 0.4]],
    played: [
      [1, 'BUF', 'NYJ', 1, 21, 10],
      [2, 'NYJ', 'BUF', 1, 24, 7],
    ],
  }));
  assert.deepEqual(h.weeks, [1]);
  assert.deepEqual(h.totals, [[1], [0]]);
});

test('playedHistory covers W1 through the last played week when nothing remains', () => {
  const h = playedHistory(toy({
    weeks: [],
    games: [],
    played: [
      [1, 'BUF', 'NYJ', 1, 21, 10],
      [2, 'NYJ', 'BUF', 1, 17, 14],
    ],
  }));
  assert.deepEqual(h.weeks, [1, 2]);
  assert.deepEqual(h.totals, [[1, 1], [0, 1]]);
});

test('playedHistory throws when games have been played but week 1 is missing', () => {
  assert.throws(() => playedHistory(toy({
    weeks: [2],
    games: [[2, 'BUF', 'NYJ', null]],
    played: [[2, 'BUF', 'NYJ', 1, 21, 10]],
  })), /week 1/);
});

test('rangeLabel is the p10-p90 combined-wins interval', () => {
  assert.equal(rangeLabel(48, 61), '48-61');
});

test('sparkArea is null when dist is empty or all zero', () => {
  assert.equal(sparkArea([], [], 40, 16), null);
  assert.equal(sparkArea([1, 2], [0, 0], 40, 16), null);
});

test('sparkArea traces the density and closes on the baseline', () => {
  const d = sparkArea([10, 11, 12], [0, 1, 0], 40, 16);
  assert.ok(d && d.startsWith('M'));
  assert.ok(d.endsWith('Z'));
});

test('sparkDomain is the union of where any density has mass', () => {
  const x = [10, 11, 12, 13];
  assert.deepEqual(
    sparkDomain(x, [[0, 1, 0, 0], [0, 0, 0.5, 0.2]]),
    { lo: 11, hi: 13, maxP: 1 },
  );
});

test('sparkArea on a shared scale puts left mass on the left of the plot', () => {
  const x = [10, 11, 12];
  const scale = { lo: 10, hi: 12, maxP: 1 };
  const left = sparkArea(x, [1, 0, 0], 40, 16, scale);
  const right = sparkArea(x, [0, 0, 1], 40, 16, scale);
  assert.ok(left && left.startsWith('M0.0,0.0'));
  assert.ok(right && right.includes('40.0,0.0'));
});

test('sparkArea on a shared maxP draws a half-mass peak at half height', () => {
  const d = sparkArea([0, 1, 2], [0, 0.5, 0], 40, 16, { lo: 0, hi: 2, maxP: 1 });
  assert.ok(d && d.includes('20.0,8.0'));
});

test('remainingWeeks lists unique remaining weeks in order', () => {
  const m = toy({
    weeks: [2, 3],
    games: [
      [2, 'BUF', 'NYJ', 0.6],
      [3, 'NYJ', 'BUF', null],
      [3, 'BUF', 'NYJ', null],
    ],
  });
  assert.deepEqual(remainingWeeks(m), [2, 3]);
});

test('toggleGamePin cycles a remaining game through home, away, and clear', () => {
  let pins: Pin[] = [];
  pins = toggleGamePin(pins, 4, true);
  assert.deepEqual(pins, [{ g: 4, homeWin: true }]);
  pins = toggleGamePin(pins, 4, true);
  assert.deepEqual(pins, []);
  pins = toggleGamePin(pins, 4, false);
  assert.deepEqual(pins, [{ g: 4, homeWin: false }]);
  pins = toggleGamePin(pins, 4, true);
  assert.deepEqual(pins, [{ g: 4, homeWin: true }]);
});

test('rollAll packs every remaining game so a later-week pin can filter', () => {
  const m = toy({
    weeks: [1, 2],
    games: [
      [1, 'BUF', 'NYJ', 0.8],
      [2, 'NYJ', 'BUF', null],
    ],
  });
  const rolled = rollAll(m, 20, 3);
  assert.ok(rolled.homeBits);
  assert.equal(rolled.nGames, 2);
  for (let s = 0; s < rolled.nSims; s++) {
    const detail = new Uint8Array(m.games.length);
    rollSeason(m, 3, s, detail);
    assert.equal(gameHome(rolled.homeBits, rolled.stride, s, 0), detail[0] === 1);
    assert.equal(gameHome(rolled.homeBits, rolled.stride, s, 1), detail[1] === 1);
  }
});

test('pinMatches keeps only seasons whose packed bits match every pin', () => {
  const bits = new Uint8Array(4); // 2 seasons, stride 2
  // season 0: game 0 home, game 1 away
  bits[0] = 0b01;
  // season 1: both home
  bits[2] = 0b11;
  assert.equal(pinMatches(bits, 2, 0, [{ g: 0, homeWin: true }]), true);
  assert.equal(pinMatches(bits, 2, 0, [{ g: 1, homeWin: true }]), false);
  assert.equal(pinMatches(bits, 2, 1, [{ g: 0, homeWin: true }, { g: 1, homeWin: true }]), true);
  assert.equal(pinMatches(bits, 2, 0, []), true);
});

test('pwinOf counts seasons matching remaining-game pins', () => {
  const winner = Uint8Array.of(1, 0, 1, 1);
  const bits = new Uint8Array([1, 0, 1, 2]);
  const pinned = pwinOf(winner, 0, bits, 1, [{ g: 0, homeWin: true }]);
  assert.deepEqual(pinned, { wins: 2, n: 2 });
  const away = pwinOf(winner, 0, bits, 1, [{ g: 0, homeWin: false }]);
  assert.deepEqual(away, { wins: 1, n: 2 });
});

test('gameSwing is P(win|home) minus P(win|away) for each remaining game', () => {
  const winner = Uint8Array.of(1, 1, 0, 0); // player 0 wins first two
  const bits = new Uint8Array([1, 1, 0, 0]);
  const swing = gameSwing(winner, bits, 1, 1, 0);
  assert.equal(swing.length, 1);
  assert.equal(swing[0], 1);
});
