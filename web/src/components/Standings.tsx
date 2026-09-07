// web/src/components/Standings.tsx
import { useEffect, useState } from 'react';
import type { LeagueView, Me, StandingsResponse } from '../league';
import { getStandings, setOverride } from '../league';
import Feed from './Feed';
import TeamLogo from './TeamLogo';

export default function Standings({ me, view }: { me: Me; view: LeagueView }) {
  const [data, setData] = useState<StandingsResponse | null>(null);

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

  async function edit(code: string, current: number) {
    const v = window.prompt(code, String(current));
    if (v === null) return;
    const n = v.trim() === '' ? null : Number(v);
    if (n !== null && !Number.isInteger(n)) return;
    await setOverride(code, n).catch(() => {});
    setData(await getStandings());
  }

  if (!data) return null;
  const width = 6;
  return (
    <div className="standings">
      <div className="card standings-card">
        <span className="eyebrow">Standings</span>
        <table>
        <thead>
          <tr>
            <th></th>
            {Array.from({ length: width }, (_, i) => <th key={i} className="num" />)}
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {data.rows.map((r) => (
            <tr key={r.player}>
              <td>{r.player}</td>
              {Array.from({ length: width }, (_, i) => {
                const t = r.teams[i];
                if (!t) return <td key={i} />;
                return (
                  <td key={t.code} className={`num ${me.is_commissioner ? 'ov' : ''}`} onClick={() => me.is_commissioner && edit(t.code, t.wins)}>
                    <span className="st-cell"><TeamLogo code={t.code} size={18} /><span className="st-code">{t.code}</span><b>{t.wins}</b></span>
                  </td>
                );
              })}
              <td className="total">{r.total}</td>
            </tr>
          ))}
        </tbody>
        </table>
        <div className="stale">
          Updated {new Date(data.fetched_at * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
          {data.stale && ' · stale'}
        </div>
      </div>
      <Feed view={view} myName={me.name} />
    </div>
  );
}
