// web/src/components/viz/palette.ts
//
// The categorical palette for the Admin charts and the one rule that governs
// it: a colour belongs to a voice, not to a row.
//
// The five hexes themselves live in live.css under `.viz`; they were checked
// for colour-vision separation and are referenced here, never redefined.
import type { AdminHistory, AdminModel } from '../../league';

const SLOTS = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)', 'var(--viz-5)'];
export const OVERFLOW_COLOR = 'var(--viz-extra)';

/** Slots are handed out by sorted voice name rather than by position in the
 *  payload. The store genuinely holds a week where only two of five sources
 *  reported; assigning by index would repaint those two and make the chart
 *  lie about which voice it is showing. */
export function assignColors(voices: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  [...voices].sort().forEach((v, i) => { out[v] = SLOTS[i] ?? OVERFLOW_COLOR; });
  return out;
}

/** Every voice the tab knows about, current or historical, so a voice that
 *  only appears in an old week still matches itself in today's charts. */
export function allVoices(m: AdminModel | null, h: AdminHistory | null): string[] {
  return Array.from(new Set([
    ...(m?.sources ?? []).map((s) => s.name),
    ...(h?.weeks ?? []).flatMap((wk) => Object.keys(wk.views)),
  ])).sort();
}
