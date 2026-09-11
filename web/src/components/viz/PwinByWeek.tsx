// web/src/components/viz/PwinByWeek.tsx
//
// One player's chance of winning the pool, week by week, with a line per
// rating voice and the blend as a hollow ring.
//
// A voice that did not report in a week is ABSENT: its line breaks into runs
// rather than bridging the gap, its dot is simply missing, and the tooltip
// says so in words. Zero pwin is a real answer and must never stand in.
import { useLayoutEffect, useRef, useState } from 'react';
import type { AdminHistory } from '../../league';
import { useWidth } from './useWidth';

const DOT_R = 5;
const RING_R = 8;
const LINE_H = 210;
const LINE_ML = 42;
const LINE_MT = 12;
const LINE_MB = 26;
// How far the tooltip stands off the crosshair. Small enough to read as
// attached to the pointer, wide enough to leave the week's marks uncovered.
const TIP_GAP = 16;

interface LineProps {
  history: AdminHistory;
  voices: string[];
  colors: Record<string, string>;
  myName: string;
}

interface Cursor { i: number; x: number; y: number }

export default function PwinByWeek({ history, voices, colors, myName }: LineProps) {
  const [box, w] = useWidth<HTMLDivElement>();
  const [cur, setCur] = useState<Cursor | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  // The tooltip is placed from its own measured size so it can flip sides
  // rather than overflow. The seed is only used for the first frame of the
  // first hover; after that the measurement carries over between weeks.
  const [tipBox, setTipBox] = useState({ w: 170, h: 96 });

  useLayoutEffect(() => {
    const el = tipRef.current;
    if (!el) return;
    const next = { w: el.offsetWidth, h: el.offsetHeight };
    setTipBox((prev) => (prev.w === next.w && prev.h === next.h ? prev : next));
    // Re-measured per hovered week, since the digits in it change its width.
  }, [cur?.i]);

  const weeks = history.weeks;
  if (!weeks.length) return null;

  const valueAt = (wk: number, voice: string) => weeks[wk].views[voice]?.[myName];
  const all = weeks.flatMap((wk) => [
    wk.blend[myName],
    ...voices.map((v) => wk.views[v]?.[myName]),
  ]).filter((v): v is number => v != null);
  const yMax = Math.max(0.2, Math.ceil((Math.max(...all, 0) * 1.12) * 20) / 20);

  const plotW = Math.max(40, w - LINE_ML - 14);
  const plotH = LINE_H - LINE_MT - LINE_MB;
  const n = weeks.length;
  const xPx = (i: number) => (n === 1 ? LINE_ML + plotW / 2 : LINE_ML + (i / (n - 1)) * plotW);
  const yPx = (p: number) => LINE_MT + plotH - (p / yMax) * plotH;

  const step = [0.05, 0.1, 0.2, 0.25, 0.5].find((s) => yMax / s <= 5) ?? 1;
  const yTicks: number[] = [];
  for (let t = 0; t <= yMax + 1e-9; t += step) yTicks.push(Number(t.toFixed(4)));

  /** Runs of consecutive weeks in which this voice reported. A gap ends a run,
   *  so the line breaks rather than bridging a week the voice never saw. */
  const runs = (pick: (i: number) => number | undefined) => {
    const out: { i: number; v: number }[][] = [];
    let open: { i: number; v: number }[] = [];
    weeks.forEach((_, i) => {
      const v = pick(i);
      if (v == null) { if (open.length) out.push(open); open = []; return; }
      open.push({ i, v });
    });
    if (open.length) out.push(open);
    return out;
  };

  function onMove(e: React.MouseEvent) {
    const rect = box.current?.getBoundingClientRect();
    if (!rect || n === 0) return;
    const x = e.clientX - rect.left;
    const i = n === 1 ? 0 : Math.round(((x - LINE_ML) / plotW) * (n - 1));
    setCur({ i: Math.min(n - 1, Math.max(0, i)), x, y: e.clientY - rect.top });
  }

  return (
    <div className="viz-block">
      <div className="viz-sub">Chance of winning the pool by week — {myName || 'you'}</div>
      <div ref={box} style={{ position: 'relative' }}>
        <svg width={w || '100%'} height={LINE_H} role="img"
             aria-label={`Chance of winning the pool by week and rating source for ${myName}`}
             onMouseMove={onMove} onMouseLeave={() => setCur(null)}>
          {w > 0 && (
            <>
              {yTicks.map((t) => (
                <g key={t}>
                  <line x1={LINE_ML} y1={yPx(t)} x2={LINE_ML + plotW} y2={yPx(t)}
                        stroke="var(--border)" strokeWidth={1} opacity={t === 0 ? 1 : 0.45} />
                  <text x={LINE_ML - 8} y={yPx(t) + 4} textAnchor="end" fontSize={10} fill="var(--text-dim)">
                    {`${Math.round(t * 100)}%`}
                  </text>
                </g>
              ))}
              {weeks.map((wk, i) => (
                <text key={wk.week} x={xPx(i)} y={LINE_H - 8} textAnchor="middle" fontSize={10} fill="var(--text-dim)">
                  {`Wk ${wk.week}`}
                </text>
              ))}
              {cur != null && (
                <line x1={xPx(cur.i)} y1={LINE_MT} x2={xPx(cur.i)} y2={LINE_MT + plotH}
                      stroke="var(--text)" strokeWidth={1} opacity={0.25} />
              )}
              {voices.map((v) => (
                <g key={v}>
                  {runs((i) => valueAt(i, v)).map((run, k) => (
                    run.length > 1 && (
                      <path key={k} fill="none" stroke={colors[v]} strokeWidth={2} strokeLinejoin="round"
                            d={run.map((p, j) => `${j === 0 ? 'M' : 'L'}${xPx(p.i).toFixed(1)},${yPx(p.v).toFixed(1)}`).join('')} />
                    )
                  ))}
                  {weeks.map((_, i) => {
                    const val = valueAt(i, v);
                    if (val == null) return null;
                    return <circle key={i} cx={xPx(i)} cy={yPx(val)} r={DOT_R}
                                   fill={colors[v]} stroke="var(--bg-panel)" strokeWidth={2} />;
                  })}
                </g>
              ))}
              {runs((i) => weeks[i].blend[myName]).map((run, k) => (
                run.length > 1 && (
                  <path key={k} fill="none" stroke="var(--text)" strokeWidth={1.5} strokeLinejoin="round"
                        d={run.map((p, j) => `${j === 0 ? 'M' : 'L'}${xPx(p.i).toFixed(1)},${yPx(p.v).toFixed(1)}`).join('')} />
                )
              ))}
              {weeks.map((wk, i) => {
                const val = wk.blend[myName];
                if (val == null) return null;
                return <circle key={wk.week} cx={xPx(i)} cy={yPx(val)} r={RING_R}
                               fill="none" stroke="var(--text)" strokeWidth={2} />;
              })}
            </>
          )}
        </svg>
        {cur != null && w > 0 && (() => {
          // The box follows the pointer instead of parking in a corner. It is
          // offset from the crosshair, never across it, so the week's own marks
          // — which all sit on that crosshair — stay visible; and it takes the
          // side that has room, so it cannot run off the container.
          const cx = xPx(cur.i);
          const roomRight = w - cx - TIP_GAP;
          const side = roomRight >= tipBox.w || roomRight >= cx - TIP_GAP
            ? cx + TIP_GAP
            : cx - TIP_GAP - tipBox.w;
          // Narrower than the box on both sides: keep it inside the container.
          const left = Math.min(Math.max(side, 2), Math.max(w - tipBox.w - 2, 2));
          const top = Math.min(Math.max(cur.y - tipBox.h / 2, 2), Math.max(LINE_H - tipBox.h - 2, 2));
          return (
            <div ref={tipRef} className="viz-tip viz-tip-free" style={{ left, top }}>
              <div className="viz-tip-title">Week {weeks[cur.i].week}</div>
              {weeks[cur.i].blend[myName] != null && (
                <div><span className="viz-swatch viz-swatch-ring" />Blend: {(weeks[cur.i].blend[myName] * 100).toFixed(1)}%</div>
              )}
              {voices.map((v) => {
                const val = valueAt(cur.i, v);
                return (
                  <div key={v} className={val == null ? 'viz-tip-absent' : undefined}>
                    <span className="viz-swatch" style={{ background: colors[v] }} />
                    {v}: {val == null ? 'no value recorded' : `${(val * 100).toFixed(1)}%`}
                  </div>
                );
              })}
            </div>
          );
        })()}
      </div>
    </div>
  );
}
