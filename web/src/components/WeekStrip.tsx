// web/src/components/WeekStrip.tsx — one row per player: their games this
// week, their expected wins (the "chalk" projection), and the distribution
// over week wins. Ported from docs/mockups/this-week-v2.html (stripRow).
import { playerColor } from '../colors';
import type { WeekGame, WeekPlayer } from '../league';
import TeamLogo from './TeamLogo';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;

function Chips({ p, games }: { p: WeekPlayer; games: WeekGame[] }) {
  const mine = new Set(p.teams);
  return (
    <>
      {games.map((g) => {
        const h = mine.has(g.home);
        const a = mine.has(g.away);
        if (!h && !a) return null;
        const key = `${g.away}@${g.home}`;
        // Both sides ours: one win is already banked whatever happens.
        if (h && a) {
          return (
            <span key={key} className="pg lock" title={`${g.home} vs ${g.away}`}>
              <TeamLogo code={g.home} size={16} />
              <span className="vs">vs</span>
              <TeamLogo code={g.away} size={16} />
              <span className="sp">1</span>
            </span>
          );
        }
        const me = h ? g.home : g.away;
        const opp = h ? g.away : g.home;
        if (g.state === 'final' && g.home_score != null && g.away_score != null) {
          const ms = h ? g.home_score : g.away_score;
          const os = h ? g.away_score : g.home_score;
          return (
            <span key={key} className={`pg ${ms > os ? 'win' : 'loss'}`} title={`${me} ${h ? 'vs' : 'at'} ${opp}`}>
              <TeamLogo code={me} size={16} />
              <span className="vs">{h ? 'vs' : '@'}</span>
              <TeamLogo code={opp} size={16} />
              <span className="sp">{ms}–{os}</span>
            </span>
          );
        }
        const p_home = g.p_used ?? g.p_model;
        const pw = p_home == null ? null : (h ? p_home : 1 - p_home);
        return (
          <span key={key} className="pg" title={`${me} ${h ? 'vs' : 'at'} ${opp}`}>
            <TeamLogo code={me} size={16} />
            <span className="vs">{h ? 'vs' : '@'}</span>
            <TeamLogo code={opp} size={16} />
            {pw != null && <span className="sp">{Math.round(pw * 100)}%</span>}
          </span>
        );
      })}
    </>
  );
}

export default function WeekStrip({ players, games, myName }: { players: WeekPlayer[]; games: WeekGame[]; myName: string }) {
  const done = players.some((p) => p.actual != null);
  const rows = players.slice().sort((a, b) =>
    (done ? (b.actual ?? 0) - (a.actual ?? 0) : b.chalk - a.chalk));

  return (
    <>
      <div className="ph"><span /><span /><span>Expected Wins</span><span /></div>
      {rows.map((p) => {
        const bg = playerColor(p.name).bg;
        const off = p.locks + p.banked;
        const mx = Math.max(...p.dist, 1e-9);
        return (
          <div key={p.name} className={`pl${p.name === myName ? ' mine' : ''}`}>
            <div className="pname"><span className="sw" style={{ background: bg }} />{first(p.name)}</div>
            <div className="pgames"><Chips p={p} games={games} /></div>
            <div className="chalk">
              {p.actual == null
                ? <b>{p.chalk.toFixed(1)}</b>
                : <>
                    <b style={{ color: 'var(--text-dim)' }}>{p.chalk.toFixed(1)}</b>
                    <span className="arrow">→</span>
                    <span className="act">{p.actual}</span>
                  </>}
            </div>
            <div className="dist">
              {p.dist.map((d, i) => {
                const total = i + off;
                const hit = p.actual != null && total === p.actual;
                return (
                  <div key={total} className={`dcol${hit ? ' hit' : ''}`} title={`${(d * 100).toFixed(1)}% chance of ${total}`}>
                    <div className="dbar" style={{ height: Math.max(1, (d / mx) * 28), background: bg, opacity: 0.25 + 0.75 * (d / mx) }} />
                    <div className="dlab">{total}</div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </>
  );
}
