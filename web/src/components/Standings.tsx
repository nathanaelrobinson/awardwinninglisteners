// web/src/components/Standings.tsx
import { useEffect, useState } from 'react';
import { fetchTeams } from '../api';
import { playerColor } from '../colors';
import type { LeagueView, LiveProjection, LiveViewRow, Me, StandingsResponse, WeekPoint } from '../league';
import { getLive, getStandings, getWeeks, setOverride } from '../league';
import Feed from './Feed';
import MovementChart from './MovementChart';
import TeamLogo from './TeamLogo';

const ROWS = 6;

// Score lens: which numbers the cards show. 'actual' = real wins; anything else
// is a key of live.views (the blend or one rating source at 100%).
const LENS_LABEL: Record<string, string> = {
  actual: 'Actual', blend: 'Blend', espn_fpi: 'FPI', nfelo: 'nfelo', clay: 'Clay',
  pff: 'PFF', epa: 'EPA', kalshi: 'Kalshi', vegas: 'Vegas',
};
const LENS_KEY = 'wp:lens';
const loadLens = () => { try { return localStorage.getItem(LENS_KEY) ?? 'actual'; } catch { return 'actual'; } };
const saveLens = (v: string) => { try { localStorage.setItem(LENS_KEY, v); } catch { /* ignore */ } };

export default function Standings({ me, view }: { me: Me | null; view: LeagueView }) {
  const [data, setData] = useState<StandingsResponse | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try { const d = await getStandings(); if (alive) setData(d); } catch { /* keep last */ }
      if (alive) timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    let alive = true;
    fetchTeams().then((r) => {
      if (!alive) return;
      const map: Record<string, string> = {};
      for (const t of r.teams) map[t.code] = t.name.trim().split(/\s+/).pop() ?? t.name;
      setNames(map);
    }).catch(() => { /* fall back to codes */ });
    return () => { alive = false; };
  }, []);

  const [live, setLive] = useState<LiveProjection | null>(null);
  const [weeks, setWeeks] = useState<WeekPoint[]>([]);
  const [lens, setLensState] = useState<string>(loadLens);
  const setLens = (v: string) => { setLensState(v); saveLens(v); };

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const [l, w] = await Promise.all([getLive(), getWeeks()]);
        if (alive) { setLive(l); setWeeks(w); }
      } catch { /* 404 until the first refresh; keep last */ }
      if (alive) timer = window.setTimeout(tick, 5 * 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  async function edit(code: string, current: number) {
    const v = window.prompt(code, String(current));
    if (v === null) return;
    const n = v.trim() === '' ? null : Number(v);
    if (n !== null && !Number.isInteger(n)) return;
    await setOverride(code, n).catch(() => {});
    setData(await getStandings());
  }

  if (!data) return null;

  const lenses = ['actual', ...Object.keys(live?.views ?? {})];
  const active = lenses.includes(lens) ? lens : 'actual';
  const viewKey = active === 'actual' ? 'blend' : active;
  const viewRows = live?.views?.[viewKey] ?? live?.rows ?? [];
  const projBy: Record<string, LiveViewRow> = {};
  const pwinBy: Record<string, number> = {};
  for (const r of viewRows) { projBy[r.player] = r; pwinBy[r.player] = r.pwin; }
  const deltaBy: Record<string, number> = {};
  if (weeks.length >= 2) {
    const pick = (w: WeekPoint) => w.views?.[viewKey] ?? w.rows;
    const prev = Object.fromEntries(pick(weeks[weeks.length - 2]).map((r) => [r.player, r.pwin]));
    for (const r of pick(weeks[weeks.length - 1])) deltaBy[r.player] = r.pwin - (prev[r.player] ?? r.pwin);
  }
  const mover = Object.entries(deltaBy)
    .filter(([, d]) => Math.round(Math.abs(d) * 100) > 0)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]?.[0];
  const ratingsStale = !!live?.ratings_fetched_at
    && Date.now() - new Date(live.ratings_fetched_at).getTime() > 8 * 24 * 3600_000;

  return (
    <div className="standings">
      <div className="card standings-card">
        <div className="card-head">
          <span className="eyebrow">Standings</span>
          {lenses.length > 1 && (
            <select className="lens" value={active} onChange={(e) => setLens(e.target.value)} aria-label="Score lens">
              {lenses.map((k) => <option key={k} value={k}>{LENS_LABEL[k] ?? k}</option>)}
            </select>
          )}
        </div>
        <div className="standings-grid">
          {data.rows.map((r) => {
            const color = playerColor(r.player);
            const isMe = r.player === me?.name;
            const first = r.player.trim().split(/\s+/)[0] ?? r.player;
            const proj = active === 'actual' ? null : projBy[r.player];
            const projWins = proj ? Object.fromEntries(proj.teams.map((t) => [t.code, t.exp_wins])) : null;
            return (
              <div key={r.player} className={`standings-player${isMe ? ' me' : ''}${r.player === mover ? ' mover' : ''}`}>
                <div className="standings-head" style={{ background: color.bg, color: color.fg }}>{first}</div>
                <div className="standings-body">
                  {Array.from({ length: ROWS }, (_, i) => {
                    const t = r.teams[i];
                    if (!t) return <div key={i} className="standings-row empty" />;
                    const editable = !!me?.is_commissioner && !proj;
                    const cellProps = editable ? { onClick: () => edit(t.code, t.wins) } : {};
                    return (
                      <div
                        key={t.code}
                        className={`standings-row${editable ? ' ov' : ''}`}
                        {...cellProps}
                      >
                        <span className="standings-team">
                          <TeamLogo code={t.code} size={20} />
                          <span className="standings-nick">{names[t.code] ?? t.code}</span>
                        </span>
                        <b className="standings-wins">{projWins ? (projWins[t.code] ?? t.wins).toFixed(1) : t.wins}</b>
                      </div>
                    );
                  })}
                </div>
                <div className="standings-foot">
                  <span>{proj ? 'Proj' : 'Total'}</span>
                  <b>{proj ? proj.exp_wins.toFixed(1) : r.total}</b>
                </div>
                {pwinBy[r.player] !== undefined && (
                  <div className="standings-foot standings-win">
                    <span>Win</span>
                    <b>
                      {Math.round(pwinBy[r.player] * 100)}%
                      {deltaBy[r.player] !== undefined && Math.round(Math.abs(deltaBy[r.player]) * 100) > 0 && (
                        <span className={`delta ${deltaBy[r.player] > 0 ? 'up' : 'down'}`}>
                          {deltaBy[r.player] > 0 ? '▲' : '▼'} {Math.round(Math.abs(deltaBy[r.player]) * 100)}
                        </span>
                      )}
                    </b>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="stale">
          Updated {new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {(data.stale || ratingsStale) && ' · stale'}
        </div>
      </div>
      <MovementChart weeks={weeks} me={me?.name ?? ''} />
      <Feed view={view} myName={me?.name ?? null} />
    </div>
  );
}
