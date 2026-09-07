// web/src/components/PickStrip.tsx
import type { LeagueView } from '../league';
import TeamLogo from './TeamLogo';

interface Props { view: LeagueView; myName: string; preview?: boolean }

export default function PickStrip({ view, myName, preview = false }: Props) {
  const nameOf = (slot: number) => Object.entries(view.slots ?? {}).find(([, s]) => s === slot)?.[0] ?? '';
  const short = (n: string) => n.split(' ')[0];
  return (
    <div className="strip">
      {view.pick_order.map((slot, i) => {
        if (preview) {
          return (
            <div key={i} className="strip-cell">
              <div className="who"><span className="n">{i + 1}</span><span className="nm">Slot {slot}</span></div>
            </div>
          );
        }
        const p = view.picks[i];
        const who = nameOf(slot);
        const cls = ['strip-cell', i === view.picks.length && view.status === 'drafting' ? 'now' : '', who === myName ? 'me' : ''].join(' ');
        return (
          <div key={i} className={cls}>
            <div className="who"><span className="n">{i + 1}</span><span className="nm">{short(who)}</span></div>
            <div className="team">{p ? <><TeamLogo code={p.team} size={16} />{p.team}</> : ''}</div>
          </div>
        );
      })}
    </div>
  );
}
