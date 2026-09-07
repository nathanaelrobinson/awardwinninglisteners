// web/src/components/OrderTicker.tsx
import { useEffect, useRef } from 'react';
import type { LeagueView } from '../league';

interface Props { view: LeagueView; myName: string }

export default function OrderTicker({ view, myName }: Props) {
  const currentRef = useRef<HTMLSpanElement>(null);

  const nameOf = (slot: number) =>
    Object.entries(view.slots ?? {}).find(([, s]) => s === slot)?.[0] ?? '';
  const short = (n: string) => n.split(' ')[0];

  useEffect(() => {
    currentRef.current?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [view.picks.length]);

  if (view.status !== 'drafting') return null;

  return (
    <div className="order-ticker">
      {view.pick_order.map((slot, i) => {
        const who = nameOf(slot);
        const pick = view.picks[i];
        const isCurrent = i === view.picks.length;
        const cls = ['ticker-chip', isCurrent ? 'current' : '', who === myName ? 'mine' : ''].join(' ');
        return (
          <span key={i} className={cls} ref={isCurrent ? currentRef : undefined}>
            {i > 0 && <span className="ticker-sep">·</span>}
            <span className="ticker-n">{i + 1}</span> {pick ? <b>{pick.team}</b> : short(who)}
          </span>
        );
      })}
    </div>
  );
}
