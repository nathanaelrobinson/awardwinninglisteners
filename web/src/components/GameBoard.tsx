// web/src/components/GameBoard.tsx — the week's schedule, ordered by how much
// each game can move the pool. Ported from docs/mockups/this-week-v2.html
// (probCell, swing, gameRow, retroRow).
import { playerColor } from '../colors';
import type { WeekGame, WeekPlayer } from '../league';
import TeamLogo from './TeamLogo';

const first = (n: string) => n.trim().split(/\s+/)[0] ?? n;
const pct = (v: number | null | undefined) => (v == null ? '' : `${Math.round(v * 100)}%`);

function When({ g }: { g: WeekGame }) {
  if (g.state === 'final') return <div className="when">Final</div>;
  if (!g.kickoff) return <div className="when" />;
  const d = new Date(g.kickoff);
  if (Number.isNaN(d.getTime())) return <div className="when" />;
  return (
    <div className="when">
      {d.toLocaleDateString(undefined, { weekday: 'short' }).toUpperCase()}
      <br />
      {d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}
    </div>
  );
}

function Side({ code, fav, owner }: { code: string; fav: boolean; owner: string | undefined }) {
  return (
    <span className={`side ${fav ? 'fav' : 'dog'}`}>
      <span className="dot" style={{ background: owner ? playerColor(owner).bg : 'transparent' }} />
      <TeamLogo code={code} size={20} />
      <b>{code}</b>
    </span>
  );
}

function Matchup({ g, owner }: { g: WeekGame; owner: Record<string, string> }) {
  // A finished game marks the winner; an upcoming one marks the favourite.
  let homeUp: boolean;
  let awayUp: boolean;
  if (g.state === 'final' && g.home_score != null && g.away_score != null) {
    homeUp = g.home_score > g.away_score;
    awayUp = g.away_score > g.home_score;
  } else {
    homeUp = g.spread != null && g.spread < 0;
    awayUp = g.spread != null && g.spread > 0;
  }
  return (
    <div className="mu">
      <Side code={g.away} fav={awayUp} owner={owner[g.away]} />
      <span className="at">@</span>
      <Side code={g.home} fav={homeUp} owner={owner[g.home]} />
    </div>
  );
}

function ProbCell({ g }: { g: WeekGame }) {
  if (g.state === 'final') {
    const p = g.p_used ?? g.p_model;
    if (p == null || g.home_score == null || g.away_score == null) return <div />;
    const homeWon = g.home_score > g.away_score;
    const called = p >= 0.5 === homeWon;
    return (
      <div>
        <div className="pb">
          <span className="pbtrack">
            <i className={`pbrange ${called ? 'held' : 'upset'}`} style={{ left: 0, width: `${p * 100}%` }} />
            <i className="pbmean tick-final" style={{ left: `calc(${homeWon ? 100 : 0}% - 1px)` }} />
          </span>
          <span className="pbval">{pct(p)}</span>
        </div>
        <div className={`pbwho${called ? '' : ' split'}`}>{called ? '' : 'Upset'}</div>
      </div>
    );
  }
  const v = [g.p_model, g.p_book, g.p_kalshi].filter((x): x is number => x != null);
  if (!v.length) return <div />;
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const used = g.p_used ?? mean;
  const split = hi - lo > 0.08;
  return (
    <div>
      <div className="pb">
        <span className="pbtrack" title={`model ${pct(g.p_model)} · book ${pct(g.p_book)} · kalshi ${pct(g.p_kalshi)}`}>
          <i className={`pbrange${split ? ' split' : ''}`} style={{ left: `${lo * 100}%`, width: `${Math.max(1.2, (hi - lo) * 100)}%` }} />
          <i className="pbmean" style={{ left: `calc(${used * 100}% - 1px)` }} />
        </span>
        <span className="pbval">{pct(used)}</span>
      </div>
    </div>
  );
}

function Swing({ g, scale, pwin }: { g: WeekGame; scale: number; pwin: Record<string, number | null> }) {
  const ent = Object.entries(g.swing)
    .filter(([, v]) => Math.abs(v) >= 0.002)
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]));
  if (!ent.length) return <div className="swing" />;
  return (
    <div className="swing">
      <div className="sax">
        <span />
        <span className="l"><TeamLogo code={g.away} size={15} /></span>
        <span className="r"><TeamLogo code={g.home} size={15} /></span>
        <span />
      </div>
      {ent.map(([n, v]) => {
        // swing is signed for a HOME win: positive means that player needs the
        // home team, so the bar grows toward the home logo on the right.
        const needsHome = v > 0;
        const bar = <i style={{ width: `${(Math.abs(v) / scale) * 100}%`, background: playerColor(n).bg }} />;
        const base = pwin[n];
        let tip: string | undefined;
        if (base != null && g.p_used != null) {
          const ifHome = base + (1 - g.p_used) * v;
          const ifAway = ifHome - v;
          tip = `${first(n)} to win the pool — ${g.away} wins ${(ifAway * 100).toFixed(1)}%, ${g.home} wins ${(ifHome * 100).toFixed(1)}%`;
        }
        return (
          <div key={n} className="sw-row" title={tip}>
            <span className="who">{first(n)}</span>
            <span className="sw-l">{needsHome ? null : bar}</span>
            <span className="sw-r">{needsHome ? bar : null}</span>
            <span className="amt">{(Math.abs(v) * 100).toFixed(1)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function GameBoard({ week, games, players }: { week: number; games: WeekGame[]; players: WeekPlayer[] }) {
  const owner: Record<string, string> = {};
  for (const p of players) for (const t of p.teams) owner[t] = p.name;
  const pwin: Record<string, number | null> = {};
  for (const p of players) pwin[p.name] = p.pwin;

  // One scale for every bar on the board, so a 4.6 is visibly wider than a 3.5.
  // Normalising per row would make each game's biggest bar full width and
  // destroy the comparison the ordering exists to create.
  const scale = Math.max(0.01, ...games.flatMap((g) => Object.values(g.swing).map(Math.abs)));

  return (
    <div className="card">
      <span className="eyebrow">Week {week} Schedule</span>
      <div className="gh">
        <div>Kickoff</div><div>Matchup</div><div>Line</div><div>Home win</div><div>Pool swing · pts</div>
      </div>
      {games.map((g) => {
        const s = g.spread;
        const line = g.state === 'final' && g.home_score != null && g.away_score != null
          ? <span className="finalscore">{g.away_score}–{g.home_score}</span>
          : <>{s == null ? '' : s < 0 ? `${g.home} ${s}` : `${g.away} ${-s}`}
              {g.total != null && <span className="ou">o/u {g.total}</span>}</>;
        return (
          <div key={`${g.away}@${g.home}`} className="g">
            <When g={g} />
            <Matchup g={g} owner={owner} />
            <div className="line">{line}</div>
            <ProbCell g={g} />
            <Swing g={g} scale={scale} pwin={pwin} />
          </div>
        );
      })}
    </div>
  );
}
