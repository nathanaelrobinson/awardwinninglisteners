// web/src/components/PickStrip.tsx
import type { LeagueView } from '../league';

export default function PickStrip({ view, myName }: { view: LeagueView; myName: string }) {
  const nameOf = (slot: number) => Object.entries(view.slots ?? {}).find(([, s]) => s === slot)?.[0] ?? '';
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="strip">
      {view.pick_order.map((slot, i) => {
        const p = view.picks[i];
        const who = nameOf(slot);
        const cls = ['strip-cell', i === view.picks.length && view.status === 'drafting' ? 'now' : '', who === myName ? 'me' : ''].join(' ');
        return (
          <div key={i} className={cls}>
            <div className="who">{i + 1}. {short(who)}</div>
            <div className="team">{p?.team ?? ''}</div>
          </div>
        );
      })}
    </div>
  );
}
