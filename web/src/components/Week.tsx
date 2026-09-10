// web/src/components/Week.tsx — the Week tab: a week picker over the player
// strip and the game board. Ported from docs/mockups/this-week-v2.html.
import { useEffect, useState } from 'react';
import type { WeekResponse } from '../league';
import { getWeek, getWeeks } from '../league';
import GameBoard from './GameBoard';
import WeekStrip from './WeekStrip';

export default function Week({ myName }: { myName: string }) {
  const [data, setData] = useState<WeekResponse | null>(null);
  const [sel, setSel] = useState<number | null>(null); // null = the current week
  const [recorded, setRecorded] = useState<number[]>([]);

  // The picker's options are the weeks we have recorded, plus whichever week
  // the payload came back as. No endpoint of its own.
  useEffect(() => {
    let alive = true;
    getWeeks()
      .then((ws) => { if (alive) setRecorded(ws.map((w) => w.week)); })
      .catch(() => { /* the current week alone is enough */ });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      let live = false;
      try {
        const d = await getWeek(sel ?? undefined);
        if (!alive) return;
        setData(d);
        live = d.state === 'live';
      } catch { /* keep last */ }
      if (alive && live) timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [sel]);

  if (!data) return null;

  const weeks = [...new Set([...recorded, data.week])].sort((a, b) => a - b);

  return (
    <>
      <div className="card">
        <div className="wkbar">
          <select
            className="wksel"
            value={sel ?? data.week}
            onChange={(e) => setSel(Number(e.target.value))}
          >
            {weeks.map((w) => <option key={w} value={w}>Week {w}</option>)}
          </select>
        </div>
        <WeekStrip players={data.players} games={data.games} myName={myName} />
      </div>
      <GameBoard week={data.week} games={data.games} players={data.players} />
    </>
  );
}
