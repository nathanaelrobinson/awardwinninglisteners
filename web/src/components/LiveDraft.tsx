// web/src/components/LiveDraft.tsx
import { useEffect, useMemo, useState } from 'react';
import { fetchTeams } from '../api';
import type { Team } from '../types';
import type { LeagueView, Me } from '../league';
import { getLeague, restartDraft, undoPick } from '../league';
import PickStrip from './PickStrip';
import DraftBoard from './DraftBoard';
import LiveRosters from './LiveRosters';
import Feed from './Feed';
import Recommendations from './Recommendations';
import Forecast from './Forecast';
import Results from './Results';
import { fetchRecommend } from '../api';
import type { RecommendResponse } from '../types';

interface Props {
  view: LeagueView;
  me: Me;
  onChange: (v: LeagueView) => void;
  selected: string | null;
  onSelect: (code: string | null) => void;
}

export default function LiveDraft({ view, me, onChange, selected, onSelect }: Props) {
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

  const takenBy = useMemo(() => Object.fromEntries(view.picks.map((p) => [p.team, { name: p.by, n: p.n }])), [view.picks]);
  const myTurn = view.status === 'drafting' && view.current_player === me.name;
  // Stable identity across polls (the panels below key their fetches on it).
  const takenKey = view.picks.map((p) => p.team).join(',');
  const taken = useMemo(() => (takenKey ? takenKey.split(',') : []), [takenKey]);
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
  }, [me.is_commissioner, mySlot, view.status, taken]);

  const teamNames = useMemo(() => Object.fromEntries(teams.map((t) => [t.code, t.name])), [teams]);

  // Commissioner "what if": inspect a team (board tile or rec row) or default to
  // the top recommendation; the standings view below shows the field if I take it.
  const [inspect, setInspect] = useState<string | null>(null);
  const topRec = rec?.recommendations[0]?.code ?? null;
  const takenSet = useMemo(() => new Set(taken), [taken]);
  const whatIf = inspect && !takenSet.has(inspect) ? inspect : selected ?? topRec;

  async function act(fn: () => Promise<LeagueView>) {
    try { onChange(await fn()); } catch { getLeague().then(onChange).catch(() => {}); }
  }

  return (
    <div className="draft">
      <div className="card strip-card">
        <PickStrip view={view} myName={me.name} />
        {me.is_commissioner && (
          <div className="strip-actions">
            <button className="btn" disabled={view.picks.length === 0} onClick={() => act(undoPick)}>Undo</button>
            <button
              className="btn"
              onClick={() => { if (window.confirm('Restart draft?')) act(restartDraft); }}
            >
              Restart draft
            </button>
          </div>
        )}
      </div>
      <div className="live">
        <div className="live-col">
          <DraftBoard
            teams={teams}
            takenBy={takenBy}
            myName={me.name}
            canPick={myTurn}
            selected={selected}
            onPick={(c) => { onSelect(selected === c ? null : c); setInspect(c); }}
          />
          {me.is_commissioner && view.status === 'drafting' && (
            <>
              <Recommendations
                recommend={rec}
                loading={recLoading}
                teamNames={teamNames}
                selected={whatIf}
                onSelect={(c) => setInspect(c)}
              />
              <Forecast forecast={rec?.forecast ?? []} done={false} />
              {mySlot != null && rec && (
                <Results slot={mySlot} taken={taken} withTeam={whatIf} />
              )}
            </>
          )}
        </div>
        <div className="live-col live-side">
          <LiveRosters view={view} myName={me.name} />
          <Feed view={view} myName={me.name} />
        </div>
      </div>
    </div>
  );
}
