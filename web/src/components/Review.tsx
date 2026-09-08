// web/src/components/Review.tsx — post-draft projections for the whole league.
import { useEffect, useRef, useState } from 'react';
import { fetchTeams } from '../api';
import { playerColor } from '../colors';
import type { Me, ProjRow, ProjectionsResponse, SeasonSample } from '../league';
import { getProjections, getSampleSeason } from '../league';
import TeamLogo from './TeamLogo';

const first = (name: string) => name.trim().split(/\s+/)[0] ?? name;

export default function Review({ me }: { me: Me | null }) {
  const [data, setData] = useState<ProjectionsResponse | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [season, setSeason] = useState<SeasonSample | null>(null);
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e6));
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    getProjections().then((d) => { if (alive) setData(d); }).catch(() => {});
    fetchTeams().then((r) => {
      if (!alive) return;
      const map: Record<string, string> = {};
      for (const t of r.teams) map[t.code] = t.name.trim().split(/\s+/).pop() ?? t.name;
      setNames(map);
    }).catch(() => {});
    return () => { alive = false; };
  }, []);

  function play() {
    const s = seed + 1;
    setSeed(s);
    setBusy(true);
    getSampleSeason(s).then(setSeason).catch(() => {}).finally(() => setBusy(false));
  }

  if (!data) return null;
  return (
    <div className="review">
      <div className="card">
        <span className="eyebrow">Projected wins</span>
        <ProjChart rows={data.rows} x={data.x} me={me?.name ?? ''} />
        <table className="proj-table">
          <thead>
            <tr><th></th><th>Proj</th><th>Win</th><th>Range</th></tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const c = playerColor(r.player);
              return (
                <tr key={r.player} className={r.player === me?.name ? 'me' : ''}>
                  <td><span className="proj-swatch" style={{ background: c.bg }} />{first(r.player)}</td>
                  <td>{r.exp_wins.toFixed(1)}</td>
                  <td>{(r.pwin * 100).toFixed(0)}%</td>
                  <td>{r.p10}–{r.p90}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="stale">{data.n_sims.toLocaleString()} simulated seasons</div>
      </div>

      <div className="card standings-card">
        <span className="eyebrow">Rosters</span>
        <div className="standings-grid">
          {data.rows.map((r) => {
            const color = playerColor(r.player);
            return (
              <div key={r.player} className={`standings-player${r.player === me?.name ? ' me' : ''}`}>
                <div className="standings-head" style={{ background: color.bg, color: color.fg }}>{first(r.player)}</div>
                <div className="standings-body">
                  {r.teams.map((t) => (
                    <div key={t.code} className="standings-row">
                      <span className="standings-team">
                        <TeamLogo code={t.code} size={20} />
                        <span className="standings-nick">{names[t.code] ?? t.code}</span>
                      </span>
                      <b className="standings-wins">{t.exp_wins.toFixed(1)}</b>
                    </div>
                  ))}
                </div>
                <div className="standings-foot"><span>Proj</span><b>{r.exp_wins.toFixed(1)}</b></div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <span className="eyebrow">One season</span>
          <button className="btn btn-primary" disabled={busy} onClick={play}>
            {season ? 'Re-roll' : 'Play a season'}
          </button>
        </div>
        {season && (
          <div className="season-grid">
            {season.standings.map((r) => {
              const c = playerColor(r.player);
              const won = season.winners.includes(r.player);
              return (
                <div key={r.player} className={`season-row${won ? ' won' : ''}`}>
                  <span className="season-name"><span className="proj-swatch" style={{ background: c.bg }} />{won && '🏆 '}{first(r.player)}</span>
                  <b className="season-total">{r.total_wins}</b>
                  <span className="season-teams">
                    {r.teams.map((t) => (
                      <span key={t.code} className="season-team"><TeamLogo code={t.code} size={16} />{t.wins}</span>
                    ))}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

const H = 220, ML = 8, MR = 8, MT = 10, MB = 22;

function ProjChart({ rows, x, me }: { rows: ProjRow[]; x: number[]; me: string }) {
  const ref = useRef<SVGSVGElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [hi, setHi] = useState<number | null>(null);
  const [W, setW] = useState(380);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(Math.max(200, el.clientWidth)));
    ro.observe(el);
    setW(Math.max(200, el.clientWidth));
    return () => ro.disconnect();
  }, []);
  if (!x.length) return null;
  const lo = x[0], top = x[x.length - 1], span = Math.max(1, top - lo);
  const pw = W - ML - MR, ph = H - MT - MB;
  const maxP = Math.max(...rows.flatMap((r) => r.dist), 1e-6);
  const xPx = (w: number) => ML + ((w - lo) / span) * pw;
  const yPx = (p: number) => MT + ph - (p / maxP) * ph;
  const line = (d: number[]) => d.map((p, i) => `${i ? 'L' : 'M'}${xPx(x[i]).toFixed(1)},${yPx(p).toFixed(1)}`).join('');
  const area = (d: number[]) => `${line(d)}L${xPx(top).toFixed(1)},${yPx(0).toFixed(1)}L${xPx(lo).toFixed(1)},${yPx(0).toFixed(1)}Z`;
  const ticks = x.filter((w) => w % 5 === 0);
  const mine = rows.find((r) => r.player === me);

  function onMove(e: React.MouseEvent) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const sx = e.clientX - rect.left;
    const w = Math.round(lo + ((sx - ML) / pw) * span);
    setHi(Math.min(x.length - 1, Math.max(0, w - lo)));
  }

  return (
    <div ref={box} className="dist-chart" style={{ position: 'relative' }}>
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
        aria-label="Distribution of each player's combined wins across simulated seasons"
        onMouseMove={onMove} onMouseLeave={() => setHi(null)}>
        <line x1={ML} y1={MT + ph} x2={ML + pw} y2={MT + ph} stroke="var(--border-2)" />
        {ticks.map((w) => (
          <text key={w} x={xPx(w)} y={H - 6} fill="var(--text-dim)" fontSize={10} textAnchor="middle">{w}</text>
        ))}
        {rows.filter((r) => r !== mine).map((r) => (
          <path key={r.player} d={line(r.dist)} fill="none" stroke={playerColor(r.player).bg} strokeWidth={2} />
        ))}
        {mine && (
          <>
            <path d={area(mine.dist)} fill={playerColor(mine.player).bg} opacity={0.15} />
            <path d={line(mine.dist)} fill="none" stroke={playerColor(mine.player).bg} strokeWidth={2.5} />
          </>
        )}
        {hi !== null && <line x1={xPx(x[hi])} y1={MT} x2={xPx(x[hi])} y2={MT + ph} stroke="var(--text)" opacity={0.3} />}
      </svg>
      {hi !== null && (
        <div className="dist-tooltip" style={{ left: `${(xPx(x[hi]) / W) * 100}%` }}>
          <div className="dist-tt-title">{x[hi]} wins</div>
          {[...rows].sort((a, b) => b.dist[hi] - a.dist[hi]).map((r) => (
            <div key={r.player} className="dist-tt-row">
              <span className="dist-swatch" style={{ background: playerColor(r.player).bg }} />
              {first(r.player)} {(r.dist[hi] * 100).toFixed(1)}%
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
