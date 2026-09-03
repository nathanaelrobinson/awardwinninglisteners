import { useRef, useState } from 'react';
import type { StandingRow } from '../api';

// Okabe–Ito categorical palette (colorblind-safe by construction), assigned by
// player number (identity), never by rank.
const COLORS: Record<number, string> = {
  1: '#0072B2',
  2: '#E69F00',
  3: '#009E73',
  4: '#D55E00',
  5: '#CC79A7',
};

interface Props {
  standings: StandingRow[];
  x: number[];
}

const W = 380;
const H = 210;
const ML = 30;
const MR = 10;
const MT = 12;
const MB = 26;

export default function DistributionChart({ standings, x }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hi, setHi] = useState<number | null>(null);

  if (!x.length || !standings.length) return null;

  const lo = x[0];
  const top = x[x.length - 1];
  const span = Math.max(1, top - lo);
  const plotW = W - ML - MR;
  const plotH = H - MT - MB;
  const maxP = Math.max(...standings.flatMap((s) => s.dist), 1e-6);

  const xPx = (w: number) => ML + ((w - lo) / span) * plotW;
  const yPx = (p: number) => MT + plotH - (p / maxP) * plotH;

  const linePath = (dist: number[]) =>
    dist.map((p, i) => `${i === 0 ? 'M' : 'L'}${xPx(x[i]).toFixed(1)},${yPx(p).toFixed(1)}`).join('');
  const areaPath = (dist: number[]) =>
    `${linePath(dist)}L${xPx(top).toFixed(1)},${yPx(0).toFixed(1)}L${xPx(lo).toFixed(1)},${yPx(0).toFixed(1)}Z`;

  const me = standings.find((s) => s.is_me);
  const xTicks = x.filter((w) => w % 5 === 0);

  function onMove(e: React.MouseEvent) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const scale = rect.width / W;
    const svgx = (e.clientX - rect.left) / scale;
    const w = Math.round(lo + ((svgx - ML) / plotW) * span);
    const idx = Math.min(x.length - 1, Math.max(0, w - lo));
    setHi(idx);
  }

  return (
    <div className="dist-chart" style={{ position: 'relative' }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label="Distribution of combined wins per player across simulated seasons"
        onMouseMove={onMove}
        onMouseLeave={() => setHi(null)}
      >
        {/* axes (recessive) */}
        <line x1={ML} y1={MT + plotH} x2={ML + plotW} y2={MT + plotH} stroke="#3a4150" strokeWidth={1} />
        {xTicks.map((w) => (
          <g key={w}>
            <line x1={xPx(w)} y1={MT + plotH} x2={xPx(w)} y2={MT + plotH + 4} stroke="#3a4150" />
            <text x={xPx(w)} y={H - 8} fill="#9aa4b2" fontSize={10} textAnchor="middle">
              {w}
            </text>
          </g>
        ))}
        <text x={ML + plotW / 2} y={H} fill="#6b7482" fontSize={9} textAnchor="middle" style={{ display: 'none' }}>
          combined wins
        </text>

        {/* other players: thin lines */}
        {standings
          .filter((s) => !s.is_me)
          .map((s) => (
            <path
              key={s.player}
              d={linePath(s.dist)}
              fill="none"
              stroke={COLORS[s.player]}
              strokeWidth={2}
              opacity={0.9}
            />
          ))}

        {/* me: filled area + thicker line */}
        {me && (
          <>
            <path d={areaPath(me.dist)} fill={COLORS[me.player]} opacity={0.18} />
            <path d={linePath(me.dist)} fill="none" stroke={COLORS[me.player]} strokeWidth={2.5} />
          </>
        )}

        {/* hover crosshair */}
        {hi !== null && (
          <line
            x1={xPx(x[hi])}
            y1={MT}
            x2={xPx(x[hi])}
            y2={MT + plotH}
            stroke="#e6ebf2"
            strokeWidth={1}
            opacity={0.4}
          />
        )}
      </svg>

      {hi !== null && (
        <div className="dist-tooltip" style={{ left: `${(xPx(x[hi]) / W) * 100}%` }}>
          <div className="dist-tt-title">{x[hi]} wins</div>
          {[...standings]
            .sort((a, b) => b.dist[hi] - a.dist[hi])
            .map((s) => (
              <div key={s.player} className="dist-tt-row">
                <span className="dist-swatch" style={{ background: COLORS[s.player] }} />
                {s.is_me ? 'You' : `P${s.player}`}: {(s.dist[hi] * 100).toFixed(1)}%
              </div>
            ))}
        </div>
      )}

      <div className="dist-legend">
        {standings.map((s) => (
          <span key={s.player} className={`dist-leg-item ${s.is_me ? 'mine' : ''}`}>
            <span className="dist-swatch" style={{ background: COLORS[s.player] }} />
            {s.is_me ? `You (P${s.player})` : `Player ${s.player}`} · {(s.pwin * 100).toFixed(0)}%
          </span>
        ))}
      </div>
      <div className="dist-xlabel">combined wins →</div>
    </div>
  );
}
