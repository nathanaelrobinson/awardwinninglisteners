// web/src/colors.ts
// Fixed player colors by slot order (index 0..4), matching the league's old sheet.
const PLAYER_COLORS = ['#d50a0a', '#1b48e0', '#e8842b', '#6b2fb3', '#0a8f5a'];

export function playerColor(index: number): string {
  return PLAYER_COLORS[index % PLAYER_COLORS.length];
}
