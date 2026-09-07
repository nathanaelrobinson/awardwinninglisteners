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
