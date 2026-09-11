// web/src/components/VoiceCharts.tsx
//
// Three hand-rolled SVG charts for the Admin tab, all sharing one legend and
// one colour assignment. The tables next to them stay: the palette's CVD
// check passes only with a labelled or tabular fallback available.
//
// The rule the whole file is built around: a voice that did not record a
// value is ABSENT, never zero and never interpolated. Zero pwin is a real
// answer, and the store genuinely holds a week where only two of the five
// sources reported.
import { useEffect, useRef, useState } from 'react';
import type { AdminHistory, AdminModel } from '../league';

// Five categorical slots live in live.css under `.viz`; here they are only
// referenced. Slots are handed out by sorted voice name, so a voice keeps its
// colour in every chart and in weeks where its neighbours are missing.
const SLOTS = ['var(--viz-1)', 'var(--viz-2)', 'var(--viz-3)', 'var(--viz-4)', 'var(--viz-5)'];
const OVERFLOW_COLOR = 'var(--viz-extra)';

function assignColors(voices: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  [...voices].sort().forEach((v, i) => { out[v] = SLOTS[i] ?? OVERFLOW_COLOR; });
  return out;
}

/** Chart geometry is in real pixels, not a scaled viewBox: a dot plot that
 *  stretches with its container stops being countable. */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

const DOT_R = 5;
const RING_R = 8;
const ROW_H = 26;
const AXIS_H = 20;
const MR = 20;

interface DotRow {
  key: string;
  label: string;
  /** Only the voices that actually have a value for this row. */
  values: Record<string, number>;
  ref: number | null;
}

interface DotPlotProps {
  rows: DotRow[];
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
}

interface DotHover { x: number; y: number; title: string; text: string; color: string }

function DotPlot({ rows, voices, colors, lo, hi, ticks, fmt, refName, labelW, maxHeight, label }: DotPlotProps) {
  const [box, w] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<DotHover | null>(null);

  const plotW = Math.max(40, w - labelW - MR);
  const span = hi - lo || 1;
  const xPx = (v: number) => labelW + ((v - lo) / span) * plotW;
  const bodyH = rows.length * ROW_H;

  return (
    <div className="viz-block">
      <div className="viz-sub">{label}</div>
      {/* The axis sits outside the scroller so 32 team rows can scroll under it. */}
      <div style={{ width: w || undefined }}>
        <svg width={w || '100%'} height={AXIS_H} role="presentation" className="viz-axis">
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
            {w > 0 && rows.map((r, i) => {
              const cy = i * ROW_H + ROW_H / 2;
              return (
                <g key={r.key}>
                  <line x1={labelW} y1={cy} x2={labelW + plotW} y2={cy} stroke="var(--border)" strokeWidth={1} opacity={0.5} />
                  {ticks.map((t) => (
                    <line key={t} x1={xPx(t)} y1={cy - ROW_H / 2} x2={xPx(t)} y2={cy + ROW_H / 2}
                          stroke="var(--border)" strokeWidth={1} opacity={0.35} />
                  ))}
                  <text x={labelW - 8} y={cy + 4} textAnchor="end" fontSize={12} fill="var(--text)" className="viz-rowlabel">
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
                  {/* Hit targets last and oversized, so the smallest mark is still easy to hit. */}
                  {r.ref != null && (
                    <circle cx={xPx(r.ref)} cy={cy} r={11} fill="transparent"
                            onMouseEnter={() => setHover({ x: xPx(r.ref as number), y: cy, title: r.label, text: `${refName}: ${fmt(r.ref as number)}`, color: 'var(--text)' })} />
                  )}
                  {voices.map((v) => {
                    const val = r.values[v];
                    if (val == null) return null;
                    return (
                      <circle key={v} cx={xPx(val)} cy={cy} r={11} fill="transparent"
                              onMouseEnter={() => setHover({ x: xPx(val), y: cy, title: r.label, text: `${v}: ${fmt(val)}`, color: colors[v] })} />
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

const LINE_H = 210;
const LINE_ML = 42;
const LINE_MT = 12;
const LINE_MB = 26;

interface LineProps {
  history: AdminHistory;
  voices: string[];
  colors: Record<string, string>;
  myName: string;
}

function PwinByWeek({ history, voices, colors, myName }: LineProps) {
  const [box, w] = useWidth<HTMLDivElement>();
  const [hi, setHi] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

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
    let cur: { i: number; v: number }[] = [];
    weeks.forEach((_, i) => {
      const v = pick(i);
      if (v == null) { if (cur.length) out.push(cur); cur = []; return; }
      cur.push({ i, v });
    });
    if (cur.length) out.push(cur);
    return out;
  };

  function onMove(e: React.MouseEvent) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || n === 0) return;
    const x = e.clientX - rect.left;
    const i = n === 1 ? 0 : Math.round(((x - LINE_ML) / plotW) * (n - 1));
    setHi(Math.min(n - 1, Math.max(0, i)));
  }

  return (
    <div className="viz-block">
      <div className="viz-sub">Chance of winning the pool by week — {myName || 'you'}</div>
      <div ref={box} style={{ position: 'relative' }}>
        <svg ref={svgRef} width={w || '100%'} height={LINE_H} role="img"
             aria-label={`Chance of winning the pool by week and rating source for ${myName}`}
             onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
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
              {hi != null && (
                <line x1={xPx(hi)} y1={LINE_MT} x2={xPx(hi)} y2={LINE_MT + plotH}
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
        {hi != null && w > 0 && (
          <div className="viz-tip viz-tip-below" style={{ left: Math.min(Math.max(xPx(hi), 80), Math.max(w - 80, 80)), top: LINE_MT }}>
            <div className="viz-tip-title">Week {weeks[hi].week}</div>
            {weeks[hi].blend[myName] != null && (
              <div><span className="viz-swatch viz-swatch-ring" />Blend: {(weeks[hi].blend[myName] * 100).toFixed(1)}%</div>
            )}
            {voices.map((v) => {
              const val = valueAt(hi, v);
              return (
                <div key={v} className={val == null ? 'viz-tip-absent' : undefined}>
                  <span className="viz-swatch" style={{ background: colors[v] }} />
                  {v}: {val == null ? 'no value recorded' : `${(val * 100).toFixed(1)}%`}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/** Where the five rating voices agree and where they pull apart — the view
 *  that makes a single wild source obvious without reading a grid of numbers. */
export default function VoiceCharts({ m, h, myName }: { m: AdminModel; h: AdminHistory | null; myName: string }) {
  // One colour map for all three charts, built from every voice the tab knows
  // about, so a voice that only appears in history still matches itself.
  const voices = Array.from(new Set([
    ...m.sources.map((s) => s.name),
    ...(h?.weeks ?? []).flatMap((wk) => Object.keys(wk.views)),
  ])).sort();
  const colors = assignColors(voices);

  const players = Object.keys(m.blend_pwin).sort((a, b) => m.blend_pwin[b] - m.blend_pwin[a]);
  const playerRows: DotRow[] = players.map((p) => ({
    key: p,
    label: p,
    values: Object.fromEntries(
      m.sources.filter((s) => s.pwin[p] != null).map((s) => [s.name, s.pwin[p]]),
    ),
    ref: m.blend_pwin[p] ?? null,
  }));

  const teams = [...m.teams].sort((a, b) => b.consensus - a.consensus);
  const teamRows: DotRow[] = teams.map((t) => ({
    key: t.code,
    label: t.code,
    values: t.strength,
    ref: t.consensus,
  }));
  // Strengths are mean-centred, so the axis is centred on zero: a symmetric
  // domain keeps "left of centre" meaning "below average" in both charts.
  const reach = Math.max(
    1,
    ...teams.flatMap((t) => [Math.abs(t.consensus), ...Object.values(t.strength).map(Math.abs)]),
  );
  const tReach = Math.ceil(reach / 2) * 2;

  return (
    <div className="card admin-card viz">
      <span className="eyebrow">Where the rating sources disagree</span>
      <div className="viz-legend">
        {voices.map((v) => (
          <span key={v} className="viz-leg">
            <span className="viz-swatch" style={{ background: colors[v] }} />
            {v}{colors[v] === OVERFLOW_COLOR ? ' (no colour slot left)' : ''}
          </span>
        ))}
        <span className="viz-leg">
          <span className="viz-swatch viz-swatch-ring" />
          Blend / consensus
        </span>
      </div>

      <DotPlot
        label="Chance of winning the pool, one dot per rating source"
        rows={playerRows}
        voices={voices}
        colors={colors}
        lo={0}
        hi={1}
        ticks={[0, 0.25, 0.5, 0.75, 1]}
        fmt={(v) => `${Math.round(v * 100)}%`}
        refName="Blend"
        labelW={150}
      />

      <DotPlot
        label="Team strength on the common scale, one dot per rating source"
        rows={teamRows}
        voices={voices}
        colors={colors}
        lo={-tReach}
        hi={tReach}
        ticks={[-tReach, -tReach / 2, 0, tReach / 2, tReach]}
        fmt={(v) => v.toFixed(0)}
        refName="Consensus"
        labelW={48}
        maxHeight={420}
      />

      {h && <PwinByWeek history={h} voices={voices} colors={colors} myName={myName} />}
    </div>
  );
}
