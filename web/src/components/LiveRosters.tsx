// web/src/components/LiveRosters.tsx
import type { LeagueView } from '../league';

export default function LiveRosters({ view, myName }: { view: LeagueView; myName: string }) {
  const bySlot = [...view.players].sort((a, b) => (view.slots?.[a] ?? 0) - (view.slots?.[b] ?? 0));
  return (
    <div className="lrosters">
      {bySlot.map((p) => (
        <div key={p} className={['lroster', p === myName ? 'me' : '', p === view.current_player ? 'turn' : ''].join(' ')}>
          <h4>{p}</h4>
          <ul>
            {(view.rosters[p] ?? []).map((c) => <li key={c}>{c}</li>)}
          </ul>
        </div>
      ))}
    </div>
  );
}
