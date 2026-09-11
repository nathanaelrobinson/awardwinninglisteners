// web/src/components/viz/RowChart.tsx
//
// One row per subject, one dot per voice, and a hollow ring for the blend or
// consensus. Two variants share this code because they are the same chart with
// different marks — keeping them as one component is what stops the pool view
// and the team view drifting apart.
//
//   'dots'   bare dots on a shared scale, for a handful of rows a reader can
//            take in at once.
//   'forest' the same dots bound by a min–max range line with the zero ruled
//            through every row, so disagreement is a LENGTH you scan down a
//            column instead of five loose dots you have to span by eye.
//
// The rule both variants obey: a voice with no value is ABSENT, never zero and
// never interpolated. Zero is a real answer here.
import { useState } from 'react';
import { useWidth } from './useWidth';

const DOT_R = 5;
const RING_R = 8;
const ROW_H = 26;
const AXIS_H = 20;
const MR = 20;
// A dot sitting on the low end of the scale is centred on the plot's left
// edge, so half a dot plus its halo hangs past it. Labels end this far short
// of the plot so the two never touch.
const LABEL_GAP = 14;

export interface RowDatum {
  key: string;
  label: string;
  /** Only the voices that actually have a value for this row. */
  values: Record<string, number>;
  ref: number | null;
}

interface RowChartProps {
  rows: RowDatum[];
  voices: string[];
  colors: Record<string, string>;
  lo: number;
  hi: number;
  ticks: number[];
  fmt: (v: number) => string;
  /** Name of the hollow-ring summary series: blend, or consensus. */
  refName: string;
  labelW: number;
  maxHeight?: number;
  label: string;
  variant?: 'dots' | 'forest';
}

interface Hover { id: string; x: number; y: number; title: string; text: string; color: string }

export default function RowChart(
  { rows, voices, colors, lo, hi, ticks, fmt, refName, labelW, maxHeight, label, variant = 'dots' }: RowChartProps,
) {
  const [box, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<Hover | null>(null);

  const plotW = Math.max(40, w - labelW - MR);
  const span = hi - lo || 1;
  const xPx = (v: number) => labelW + ((v - lo) / span) * plotW;
  const bodyH = rows.length * ROW_H;
  const forest = variant === 'forest';

  return (
    <div className="viz-block">
      <div className="viz-sub">{label}</div>
      {/* The axis sits outside the scroller so 32 team rows can scroll under
          it. Its tick text is the only scale readout on the chart, so it is
          labelled rather than hidden from assistive tech. */}
      <div style={{ width: w || undefined }}>
        <svg width={w || '100%'} height={AXIS_H} className="viz-axis" role="img"
             aria-label={`Scale for ${label}: ${ticks.map(fmt).join(', ')}`}>
          <line x1={labelW} y1={AXIS_H - 1} x2={labelW + plotW} y2={AXIS_H - 1} stroke="var(--border-2)" strokeWidth={1} />
          {w > 0 && ticks.map((t) => (
            <text key={t} x={xPx(t)} y={AXIS_H - 6} textAnchor="middle" fontSize={10} fill="var(--text-dim)">
              {fmt(t)}
            </text>
          ))}
        </svg>
      </div>
      <div ref={box} className="viz-scroll" style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>
        <div style={{ position: 'relative' }}>
          <svg width={w || '100%'} height={bodyH} role="img" aria-label={label} onMouseLeave={() => setHover(null)}>
            {/* Strengths are mean-centred, so one rule down the whole plot makes
                above and below league average readable at a glance. */}
            {w > 0 && forest && lo < 0 && hi > 0 && (
              <line x1={xPx(0)} y1={0} x2={xPx(0)} y2={bodyH} stroke="var(--text)" strokeWidth={1} opacity={0.45} />
            )}
            {w > 0 && rows.map((r, i) => {
              const cy = i * ROW_H + ROW_H / 2;
              const present = voices.map((v) => r.values[v]).filter((v): v is number => v != null);
              const min = present.length ? Math.min(...present) : 0;
              const max = present.length ? Math.max(...present) : 0;
              return (
                <g key={r.key}>
                  <line x1={labelW} y1={cy} x2={labelW + plotW} y2={cy} stroke="var(--border)" strokeWidth={1} opacity={0.5} />
                  {ticks.map((t) => (
                    <line key={t} x1={xPx(t)} y1={cy - ROW_H / 2} x2={xPx(t)} y2={cy + ROW_H / 2}
                          stroke="var(--border)" strokeWidth={1} opacity={0.35} />
                  ))}
                  {/* One voice, or perfect agreement, has no spread to show. A
                      zero-length range would read as a tick that means
                      something, so it is left undrawn and the dot stands alone. */}
                  {forest && max > min && (
                    <line x1={xPx(min)} y1={cy} x2={xPx(max)} y2={cy}
                          stroke="var(--text)" strokeWidth={3} strokeLinecap="round" opacity={0.35} />
                  )}
                  <text x={labelW - LABEL_GAP} y={cy + 4} textAnchor="end" fontSize={12} fill="var(--text)" className="viz-rowlabel">
                    {r.label}
                  </text>
                  {r.ref != null && (
                    <circle cx={xPx(r.ref)} cy={cy} r={RING_R} fill="none" stroke="var(--text)" strokeWidth={2} />
                  )}
                  {voices.map((v) => {
                    const val = r.values[v];
                    // Absent voice: draw nothing at all. No zero, no placeholder.
                    if (val == null) return null;
                    return (
                      <circle key={v} cx={xPx(val)} cy={cy} r={DOT_R}
                              fill={colors[v]} stroke="var(--bg-panel)" strokeWidth={2} />
                    );
                  })}
                  {/* Hit targets last and oversized, so the smallest mark is still easy to hit.
                      Each clears the tooltip on its own mouseleave (not only the chart's), so
                      moving into empty plot space between dots drops the tooltip instead of
                      leaving it stuck on the last mark. Clearing is keyed by id rather than
                      unconditional, so leaving mark A while already hovering mark B (whichever
                      order the two events land in) can't clobber B's tooltip with a null. */}
                  {r.ref != null && (() => {
                    const id = `ref:${r.key}`;
                    return (
                      <circle cx={xPx(r.ref)} cy={cy} r={11} fill="transparent"
                              onMouseEnter={() => setHover({ id, x: xPx(r.ref as number), y: cy, title: r.label, text: `${refName}: ${fmt(r.ref as number)}`, color: 'var(--text)' })}
                              onMouseLeave={() => setHover((h) => (h?.id === id ? null : h))} />
                    );
                  })()}
                  {voices.map((v) => {
                    const val = r.values[v];
                    if (val == null) return null;
                    const id = `${v}:${r.key}`;
                    return (
                      <circle key={v} cx={xPx(val)} cy={cy} r={11} fill="transparent"
                              onMouseEnter={() => setHover({ id, x: xPx(val), y: cy, title: r.label, text: `${v}: ${fmt(val)}`, color: colors[v] })}
                              onMouseLeave={() => setHover((h) => (h?.id === id ? null : h))} />
                    );
                  })}
                </g>
              );
            })}
          </svg>
          {hover && (
            <div
              /* Near the top of a scrolling plot there is nothing above to
                 hang the tooltip in, so it flips below the mark instead. */
              className={`viz-tip${hover.y < 46 ? ' viz-tip-below' : ''}`}
              style={{ left: Math.min(Math.max(hover.x, 70), Math.max(w - 70, 70)), top: hover.y + (hover.y < 46 ? 14 : -12) }}
            >
              <div className="viz-tip-title">{hover.title}</div>
              <div><span className="viz-swatch" style={{ background: hover.color }} />{hover.text}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
