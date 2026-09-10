// web/src/colors.ts
// Fixed player colors by name (the league's long-standing colors).
const PLAYER_COLORS: Record<string, { bg: string; fg: string }> = {
  'Nate Robinson': { bg: '#6b2fb3', fg: '#ffffff' },
  'Logan Borgelt': { bg: '#d50a0a', fg: '#ffffff' },
  'Eric Whitley': { bg: '#1b48e0', fg: '#ffffff' },
  'Mitch Fischer': { bg: '#e8842b', fg: '#ffffff' },
  'Evan Goguillon-Bader': { bg: '#f5d90a', fg: '#151515' },
};

const DEFAULT_COLOR = { bg: '#013369', fg: '#ffffff' };

export function playerColor(name: string): { bg: string; fg: string } {
  return PLAYER_COLORS[name] ?? DEFAULT_COLOR;
}

// Diverging scale for a signed delta, anchored at zero: red below, navy above,
// a neutral gray at nothing. Both arms step monotonically darker and every step
// carries >=4.5:1 contrast with the paired ink, checked rather than guessed.
const BELOW = ['#fbe7e7', '#f4bfbf', '#ec8e8e', '#e25454', '#d50a0a'];
const ABOVE = ['#e6ebf0', '#bdcad8', '#8aa1ba', '#4d7096', '#013369'];
const INK = '#151515';
const BELOW_FG = [INK, INK, INK, INK, '#ffffff'];
const ABOVE_FG = [INK, INK, INK, '#ffffff', '#ffffff'];
const NEUTRAL = { bg: '#f0efec', fg: INK };

/** `t` is the value over the largest magnitude on the chart, so -1..1. */
export function deltaColor(t: number): { bg: string; fg: string } {
  if (!Number.isFinite(t) || t === 0) return NEUTRAL;
  const m = Math.min(Math.abs(t), 1);
  const i = Math.min(4, Math.max(0, Math.ceil(m * 5) - 1));
  return t < 0 ? { bg: BELOW[i], fg: BELOW_FG[i] } : { bg: ABOVE[i], fg: ABOVE_FG[i] };
}
