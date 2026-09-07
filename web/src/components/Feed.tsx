// web/src/components/Feed.tsx
import { useEffect, useRef, useState } from 'react';
import type { LeagueView, Message } from '../league';
import { getMessages, postMessage } from '../league';

type Item =
  | { ts: number; kind: 'pick'; n: number; by: string; team: string }
  | { ts: number; kind: 'msg'; by: string; text: string; id: string };

const merge = (prev: Message[], incoming: Message[]) => {
  const seen = new Set(prev.map((m) => m.id));
  return [...prev, ...incoming.filter((m) => !seen.has(m.id))];
};

export default function Feed({ view, myName }: { view: LeagueView; myName: string }) {
  const [msgs, setMsgs] = useState<Message[]>([]);
  const [text, setText] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const lastTs = useRef<number | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const m = await getMessages(lastTs.current);
        if (!alive) return;
        if (m.length) {
          lastTs.current = m[m.length - 1].ts;
          setMsgs((prev) => merge(prev, m));
        }
      } catch { /* retry next tick */ }
      timer = window.setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  const items: Item[] = [
    ...view.picks.map((p) => ({ ts: p.ts, kind: 'pick' as const, n: p.n, by: p.by, team: p.team })),
    ...msgs.map((m) => ({ ts: m.ts, kind: 'msg' as const, by: m.by, text: m.text, id: m.id })),
  ].sort((a, b) => a.ts - b.ts);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [items.length]);

  async function send() {
    const t = text.trim();
    if (!t) return;
    setText('');
    try {
      const m = await postMessage(t);
      lastTs.current = Math.max(lastTs.current ?? 0, m.ts);
      setMsgs((prev) => merge(prev, [m]));
    } catch { setText(t); }
  }

  return (
    <div className="feed card">
      <span className="eyebrow">Feed</span>
      <div className="feed-list" ref={listRef}>
        {items.map((it) =>
          it.kind === 'pick' ? (
            <div key={`p${it.n}`} className="feed-pick">{it.by} — <b>{it.team}</b></div>
          ) : (
            <div key={it.id} className="feed-msg"><span className="by">{it.by}</span>{it.text}</div>
          )
        )}
      </div>
      <input
        className="feed-input"
        placeholder={myName}
        value={text}
        maxLength={500}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && send()}
      />
    </div>
  );
}
