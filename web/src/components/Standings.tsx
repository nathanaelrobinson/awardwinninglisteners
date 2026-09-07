// web/src/components/Standings.tsx
import { useEffect, useState } from 'react';
import { fetchTeams } from '../api';
import { playerColor } from '../colors';
import type { LeagueView, Me, StandingsResponse } from '../league';
import { getStandings, setOverride } from '../league';
import Feed from './Feed';
import TeamLogo from './TeamLogo';

const ROWS = 6;

export default function Standings({ me, view }: { me: Me; view: LeagueView }) {
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

  async function edit(code: string, current: number) {
    const v = window.prompt(code, String(current));
    if (v === null) return;
    const n = v.trim() === '' ? null : Number(v);
    if (n !== null && !Number.isInteger(n)) return;
    await setOverride(code, n).catch(() => {});
    setData(await getStandings());
  }

  if (!data) return null;
  return (
    <div className="standings">
      <div className="card standings-card">
        <span className="eyebrow">Standings</span>
        <div className="standings-grid">
          {data.rows.map((r) => {
            const slot = view.players.indexOf(r.player);
            const color = playerColor(slot < 0 ? 0 : slot);
            const isMe = r.player === me.name;
            const first = r.player.trim().split(/\s+/)[0] ?? r.player;
            return (
              <div key={r.player} className={`standings-player${isMe ? ' me' : ''}`}>
                <div className="standings-head" style={{ background: color }}>{first}</div>
                <div className="standings-body">
                  {Array.from({ length: ROWS }, (_, i) => {
                    const t = r.teams[i];
                    if (!t) return <div key={i} className="standings-row empty" />;
                    const cellProps = me.is_commissioner
                      ? { onClick: () => edit(t.code, t.wins) }
                      : {};
                    return (
                      <div
                        key={t.code}
                        className={`standings-row${me.is_commissioner ? ' ov' : ''}`}
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
              </div>
            );
          })}
        </div>
        <div className="stale">
          Updated {new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {data.stale && ' · stale'}
        </div>
      </div>
      <Feed view={view} myName={me.name} />
    </div>
  );
}
