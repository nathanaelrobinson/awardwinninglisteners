// web/src/components/StatusBar.tsx
import type { LeagueView, Me } from '../league';

const first = (n: string) => n.split(' ')[0];

export default function StatusBar({ view, me }: { view: LeagueView; me: Me }) {
  if (view.status === 'lobby') return null;
  if (view.status === 'done') {
    return (
      <div className="status status-done">
        <div className="status-inner">
          <span className="status-label">Draft complete</span>
        </div>
      </div>
    );
  }

  const nameOf = (slot: number | undefined) =>
    slot === undefined ? '' : Object.entries(view.slots ?? {}).find(([, s]) => s === slot)?.[0] ?? '';

  const i = view.picks.length;
  const total = view.pick_order.length;
  const onClock = view.current_player ?? nameOf(view.pick_order[i]);
  const upNext = nameOf(view.pick_order[i + 1]);

  const mine = onClock === me.name;
  const nextIsMine = !mine && upNext === me.name;
  const variant = mine ? 'status-mine' : nextIsMine ? 'status-next' : 'status-idle';

  return (
    <div className={`status ${variant}`}>
      <div className="status-inner">
        <span className="status-pick">Pick {i + 1} of {total}</span>
        <span className="status-clock">
          <b>{onClock}</b>
          <span className="status-badge">On the clock</span>
        </span>
        <span className="status-next-name">
          {upNext && upNext !== onClock && <><span className="status-label">Up next</span> {first(upNext)}</>}
        </span>
      </div>
    </div>
  );
}
