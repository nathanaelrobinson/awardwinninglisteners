// web/src/components/Standings.tsx
import { useEffect, useState } from 'react';
import { fetchTeams } from '../api';
import { playerColor } from '../colors';
import type { LeagueView, LiveProjection, Me, StandingsResponse, WeekPoint } from '../league';
import { getLive, getStandings, getWeeks, setOverride } from '../league';
import Feed from './Feed';
import TeamLogo from './TeamLogo';

const ROWS = 6;

export default function Standings({ me, view }: { me: Me | null; view: LeagueView }) {
  const [data, setData] = useState<StandingsResponse | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try { const d = await getStandings(); if (alive) setData(d); } catch { /* keep last */ }
      timer = window.setTimeout(tick, 60_000);
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

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const [l, w] = await Promise.all([getLive(), getWeeks()]);
        if (alive) { setLive(l); setWeeks(w); }
      } catch { /* 404 until the first refresh; keep last */ }
      timer = window.setTimeout(tick, 5 * 60_000);
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

  const pwinBy: Record<string, number> = {};
  const mktBy: Record<string, number | null> = {};
  for (const r of live?.rows ?? []) { pwinBy[r.player] = r.pwin; mktBy[r.player] = r.market_pwin; }
  const deltaBy: Record<string, number> = {};
  if (weeks.length >= 2) {
    const prev = Object.fromEntries(weeks[weeks.length - 2].rows.map((r) => [r.player, r.pwin]));
    for (const r of weeks[weeks.length - 1].rows) deltaBy[r.player] = r.pwin - (prev[r.player] ?? r.pwin);
  }
  const mover = Object.entries(deltaBy).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0]?.[0];
  const ratingsStale = !!live?.ratings_fetched_at
    && Date.now() - new Date(live.ratings_fetched_at).getTime() > 8 * 24 * 3600_000;

  return (
    <div className="standings">
      <div className="card standings-card">
        <span className="eyebrow">Standings</span>
        <div className="standings-grid">
          {data.rows.map((r) => {
            const color = playerColor(r.player);
            const isMe = r.player === me?.name;
            const first = r.player.trim().split(/\s+/)[0] ?? r.player;
            return (
              <div key={r.player} className={`standings-player${isMe ? ' me' : ''}${r.player === mover ? ' mover' : ''}`}>
                <div className="standings-head" style={{ background: color.bg, color: color.fg }}>{first}</div>
                <div className="standings-body">
                  {Array.from({ length: ROWS }, (_, i) => {
                    const t = r.teams[i];
                    if (!t) return <div key={i} className="standings-row empty" />;
                    const cellProps = me?.is_commissioner
                      ? { onClick: () => edit(t.code, t.wins) }
                      : {};
                    return (
                      <div
                        key={t.code}
                        className={`standings-row${me?.is_commissioner ? ' ov' : ''}`}
                        {...cellProps}
                      >
                        <span className="standings-team">
                          <TeamLogo code={t.code} size={20} />
                          <span className="standings-nick">{names[t.code] ?? t.code}</span>
                        </span>
                        <b className="standings-wins">{t.wins}</b>
                      </div>
                    );
                  })}
                </div>
                <div className="standings-foot">
                  <span>Total</span>
                  <b>{r.total}</b>
                </div>
                {pwinBy[r.player] !== undefined && (
                  <div className="standings-foot standings-win">
                    <span>Win</span>
                    <b>
                      {Math.round(pwinBy[r.player] * 100)}%
                      {mktBy[r.player] != null && Math.abs(mktBy[r.player]! - pwinBy[r.player]) > 0.05 && (
                        <span className="mkt">mkt {Math.round(mktBy[r.player]! * 100)}%</span>
                      )}
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
      <Feed view={view} myName={me?.name ?? null} />
    </div>
  );
}
