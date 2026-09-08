// web/src/components/MovementChart.tsx — P(win pool) by NFL week, one line per player.
import { useEffect, useRef, useState } from 'react';
import { playerColor } from '../colors';
import type { WeekPoint } from '../league';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;
const H = 200, ML = 34, MR = 72, MT = 10, MB = 24;

export default function MovementChart({ weeks, me }: { weeks: WeekPoint[]; me: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(380);
  const shown = weeks.length >= 3;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(240, el.clientWidth)));
    ro.observe(el);
    setW(Math.max(240, el.clientWidth));
    return () => ro.disconnect();
  }, [shown]);
  if (!shown) return null;

  const players = weeks[weeks.length - 1].rows.map((r) => r.player);
  const series = players.map((p) => ({
    player: p,
    pts: weeks.map((w) => ({ week: w.week, p: w.rows.find((r) => r.player === p)?.pwin ?? 0 })),
  }));
  const x0 = weeks[0].week, x1 = weeks[weeks.length - 1].week;
  const maxP = Math.max(0.2, ...series.flatMap((s) => s.pts.map((q) => q.p)));
  const pw = W - ML - MR, ph = H - MT - MB;
  const xPx = (w: number) => ML + ((w - x0) / Math.max(1, x1 - x0)) * pw;
  const yPx = (p: number) => MT + ph - (p / maxP) * ph;
  const path = (pts: { week: number; p: number }[]) =>
    pts.map((q, i) => `${i ? 'L' : 'M'}${xPx(q.week).toFixed(1)},${yPx(q.p).toFixed(1)}`).join('');
  const yTicks = [0, 0.25, 0.5, 0.75, 1].filter((t) => t <= maxP + 1e-9);

  return (
    <div className="card">
      <span className="eyebrow">Win probability by week</span>
      <div ref={box} className="move-chart">
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="Each player's probability of winning the pool by NFL week">
          {yTicks.map((t) => (
            <g key={t}>
              <line x1={ML} y1={yPx(t)} x2={ML + pw} y2={yPx(t)} stroke="var(--border)" />
              <text x={ML - 6} y={yPx(t) + 3} fill="var(--text-dim)" fontSize={10} textAnchor="end">{Math.round(t * 100)}%</text>
            </g>
          ))}
          {weeks.map((w) => (
            <text key={w.week} x={xPx(w.week)} y={H - 6} fill="var(--text-dim)" fontSize={10} textAnchor="middle">{w.week}</text>
          ))}
          {series.map((s) => {
            const c = playerColor(s.player).bg;
            const last = s.pts[s.pts.length - 1];
            const overflow = xPx(last.week) + 6 + 70 > W;
            const labelX = overflow ? ML + pw - 4 : xPx(last.week) + 6;
            return (
              <g key={s.player}>
                <path d={path(s.pts)} fill="none" stroke={c} strokeWidth={s.player === me ? 3 : 2} />
                <text x={labelX} y={yPx(last.p) + 3} fill={c} fontSize={11} fontWeight={700}
                      textAnchor={overflow ? 'end' : 'start'}>
                  {first(s.player)} {Math.round(last.p * 100)}%
                </text>
              </g>
            );
          })}
        </svg>
        <div className="move-axes"><span>Week</span><span>Win %</span></div>
      </div>
    </div>
  );
}
