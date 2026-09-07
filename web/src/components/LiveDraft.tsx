// web/src/components/LiveDraft.tsx
import { useEffect, useMemo, useState } from 'react';
import { fetchTeams } from '../api';
import type { Team } from '../types';
import type { LeagueView, Me } from '../league';
import { getLeague, pickTeam, resetDraft, undoPick } from '../league';
import PickStrip from './PickStrip';
import DraftBoard from './DraftBoard';
import LiveRosters from './LiveRosters';
import Feed from './Feed';
import Recommendations from './Recommendations';
import Forecast from './Forecast';
import { fetchRecommend } from '../api';
import type { RecommendResponse } from '../types';

interface Props { view: LeagueView; me: Me; onChange: (v: LeagueView) => void }

export default function LiveDraft({ view, me, onChange }: Props) {
  const [teams, setTeams] = useState<Team[]>([]);
  useEffect(() => {
    let alive = true;
    let timer: number;
    const load = () => {
      fetchTeams()
        .then((t) => { if (alive) setTeams(t.teams); })
        .catch(() => { if (alive) timer = window.setTimeout(load, 3000); });
    };
    load();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  const takenBy = useMemo(() => Object.fromEntries(view.picks.map((p) => [p.team, p.by])), [view.picks]);
  const myTurn = view.status === 'drafting' && view.current_player === me.name;
  const taken = view.picks.map((p) => p.team);
  const mySlot = view.slots?.[me.name] ?? null;

  // Commissioner-only optimizer panel, driven by the live board.
  const [rec, setRec] = useState<RecommendResponse | null>(null);
  const [recLoading, setRecLoading] = useState(false);
  useEffect(() => {
    if (!me.is_commissioner || mySlot == null || view.status !== 'drafting') return;
    let cancelled = false;
    setRecLoading(true);
    fetchRecommend(mySlot, taken).then((r) => { if (!cancelled) setRec(r); }).catch(() => {}).finally(() => { if (!cancelled) setRecLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [me.is_commissioner, mySlot, view.status, taken.join(',')]);

  const teamNames = useMemo(() => Object.fromEntries(teams.map((t) => [t.code, t.name])), [teams]);

  async function act(fn: () => Promise<LeagueView>) {
    try { onChange(await fn()); } catch { getLeague().then(onChange).catch(() => {}); }
  }

  return (
    <>
      <PickStrip view={view} myName={me.name} />
      {me.is_commissioner && (
        <div className="strip-actions">
          <button className="btn" disabled={view.picks.length === 0} onClick={() => act(undoPick)}>Undo</button>
          {view.picks.length === 0 && <button className="btn" onClick={() => act(resetDraft)}>Re-randomize</button>}
        </div>
      )}
      <div className="live">
        <div>
          <DraftBoard teams={teams} takenBy={takenBy} myName={me.name} canPick={myTurn} onPick={(c) => act(() => pickTeam(c))} />
          {me.is_commissioner && view.status === 'drafting' && (
            <>
              <Recommendations recommend={rec} loading={recLoading} teamNames={teamNames} />
              <Forecast forecast={rec?.forecast ?? []} done={false} />
            </>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <LiveRosters view={view} myName={me.name} />
          <Feed view={view} myName={me.name} />
        </div>
      </div>
    </>
  );
}
