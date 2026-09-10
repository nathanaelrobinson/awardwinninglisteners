// web/src/components/Simulations.tsx
//
// The season, rolled a hundred thousand times, drawn as a hundred thousand
// lines. The server ships the ensemble; every roll happens here (see sim.ts).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getSimModel } from '../league';
import type { Rolled, SimModel } from '../sim';
import { rollAll, rollSeason, sourceLabel } from '../sim';
import type { RollRequest, RollResponse } from '../sim.worker';

type View = 'all' | 'margin';

const PAD = { l: 40, r: 12, t: 12, b: 24 };
const DRAW_N = 5000;           // lines actually painted; every count uses them all
const COUNTS = [20000, 50000, 100000, 250000];

const WIN = '#1b48e0';         // this player wins
const LOSE = '#d50a0a';        // ...and the seasons they don't
const CLOUD = '#a6a6a6';       // someone else wins (neutral, so blue reads as blue)
const RULE = '#d6d9de';
const DIM = '#626c80';

export default function Simulations({ myName }: { myName: string }) {
  const [model, setModel] = useState<SimModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rolled, setRolled] = useState<Rolled | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(0);

  const [view, setView] = useState<View>('all');
  const [nSims, setNSims] = useState(100000);
  const [seed, setSeed] = useState(12345);
  const [meIdx, setMeIdx] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);

  const wrapRef = useRef<HTMLDivElement>(null);
  const cloudCache = useRef(new Map<string, HTMLCanvasElement>());
  const tipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    getSimModel()
      .then((m) => { if (alive) { setModel(m); setMeIdx(Math.max(0, m.players.indexOf(myName))); } })
      .catch(() => { if (alive) setError('The projection is not ready yet.'); });
    return () => { alive = false; };
  }, [myName]);

  // Rolling blocks for a moment even in a worker, so paint the busy state first
  // and keep each cohort by size and seed rather than re-rolling on every toggle.
  const cohorts = useRef(new Map<string, Rolled>());
  const worker = useRef<Worker | null>(null);
  const reqId = useRef(0);

  useEffect(() => {
    try {
      worker.current = new Worker(new URL('../sim.worker.ts', import.meta.url), { type: 'module' });
    } catch {
      worker.current = null;          // fall back to rolling on this thread
    }
    return () => { worker.current?.terminate(); worker.current = null; };
  }, []);

  useEffect(() => {
    if (!model) return;
    const key = `${nSims}|${seed}`;
    const hit = cohorts.current.get(key);
    if (hit) { setRolled(hit); return; }

    const id = ++reqId.current;
    const accept = (r: Rolled) => {
      if (id !== reqId.current) return;   // a newer request has already started
      cohorts.current.set(key, r);
      cloudCache.current.clear();
      setRolled(r); setPicked(null); setHover(null); setBusy(false);
    };
    setBusy(true); setDone(0);

    const w = worker.current;
    if (!w) {
      const t = window.setTimeout(() => accept(rollAll(model, nSims, seed)), 16);
      return () => window.clearTimeout(t);
    }
    const onMsg = (e: MessageEvent<RollResponse>) => {
      if (e.data.id !== id) return;
      if (e.data.type === 'progress') setDone(e.data.done);
      else if (e.data.type === 'done') accept(e.data.rolled);
      else { setBusy(false); setError('The simulation could not run: ' + e.data.message); }
    };
    w.addEventListener('message', onMsg);
    const req: RollRequest = { id, model, nSims, seed };
    w.postMessage(req);
    return () => w.removeEventListener('message', onMsg);
  }, [model, nSims, seed]);

  useEffect(() => { cohorts.current.clear(); }, [model]);

  const act = useMemo(() => (rolled ? { paths: rolled.paths, winner: rolled.winner } : null), [rolled]);

  const margins = useMemo(() => {
    if (!rolled || !act || view !== 'margin') return null;
    const { nSims: nS, nWeeks: nW, nPlayers: nP } = rolled;
    const out = new Int16Array(nS * nW);
    for (let s = 0; s < nS; s++)
      for (let w = 0; w < nW; w++) {
        let best = -32768;
        for (let p = 0; p < nP; p++)
          if (p !== meIdx) { const v = act.paths[p][s * nW + w]; if (v > best) best = v; }
        out[s * nW + w] = act.paths[meIdx][s * nW + w] - best;
      }
    return out;
  }, [rolled, act, view, meIdx]);

  // 100k lines need an alpha so low each one is invisible. Paint an evenly
  // spaced sample and let every count use the whole set.
  const sample = useMemo(() => {
    if (!rolled) return [] as number[];
    const n = Math.min(DRAW_N, rolled.nSims), stride = rolled.nSims / n;
    const out = new Array<number>(n);
    for (let i = 0; i < n; i++) out[i] = (i * stride) | 0;
    return out;
  }, [rolled]);

  const seriesFor = useCallback((pi: number) =>
    (view === 'margin' ? margins! : act!.paths[pi]), [view, margins, act]);

  const drawPanel = useCallback((c: CanvasRenderingContext2D, w: number, h: number, pi: number) => {
    if (!rolled || !act) return null;
    const nW = rolled.nWeeks, arr = seriesFor(pi);
    let lo = Infinity, hi = -Infinity;
    for (const s of sample)
      for (let k = 0; k < nW; k++) { const v = arr[s * nW + k]; if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = Math.max(1, (hi - lo) * 0.04); lo -= pad; hi += pad;
    const X = (i: number) => PAD.l + (w - PAD.l - PAD.r) * (nW === 1 ? 0.5 : i / (nW - 1));
    const Y = (v: number) => PAD.t + (h - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo || 1));

    const key = `${pi}|${view}|${w}|${h}|${seed}|${nSims}`;
    let off = cloudCache.current.get(key);
    if (!off) {
      cloudCache.current.clear();
      const dpr = window.devicePixelRatio || 1;
      off = document.createElement('canvas');
      off.width = w * dpr; off.height = h * dpr;
      const oc = off.getContext('2d')!;
      oc.setTransform(dpr, 0, 0, dpr, 0, 0);
      // Translucent lines composite, so whichever class is drawn last wins the
      // overlap. Painted in two passes, a 24%-of-seasons colour covered 60% of
      // the ink. So interleave: same alpha, and alternate the two classes in
      // slices, which leaves neither systematically on top.
      const a = Math.max(0.03, Math.min(0.16, 420 / Math.max(sample.length, 1)));
      const SLICES = 12, per = Math.ceil(sample.length / SLICES);
      oc.lineWidth = 1;
      oc.globalAlpha = a;
      for (let slice = 0; slice < SLICES; slice++) {
        const from = slice * per, to = Math.min(sample.length, from + per);
        for (const [wins, col] of [[false, CLOUD], [true, WIN]] as [boolean, string][]) {
          oc.strokeStyle = col;
          oc.beginPath();
          for (let i = from; i < to; i++) {
            const s = sample[i];
            if ((act.winner[s] === pi + 1) !== wins) continue;
            oc.moveTo(X(0), Y(arr[s * nW]));
            for (let k = 1; k < nW; k++) oc.lineTo(X(k), Y(arr[s * nW + k]));
          }
          oc.stroke();
        }
      }
      cloudCache.current.set(key, off);
    }

    c.clearRect(0, 0, w, h);
    c.save(); c.setTransform(1, 0, 0, 1, 0, 0);
    c.drawImage(off, 0, 0);                       // 1:1; resampling this costs seconds
    c.restore();

    c.strokeStyle = RULE; c.lineWidth = 1;
    c.beginPath(); c.moveTo(PAD.l, PAD.t); c.lineTo(PAD.l, h - PAD.b);
    c.lineTo(w - PAD.r, h - PAD.b); c.stroke();
    if (view === 'margin' && lo < 0 && hi > 0) {
      c.save(); c.setLineDash([4, 4]); c.strokeStyle = DIM;
      c.beginPath(); c.moveTo(PAD.l, Y(0)); c.lineTo(w - PAD.r, Y(0)); c.stroke(); c.restore();
    }
    for (const sim of [picked, hover]) {
      if (sim == null) continue;
      c.save();
      c.strokeStyle = act.winner[sim] === pi + 1 ? WIN : LOSE;
      c.lineWidth = 2.25; c.lineJoin = 'round';
      c.beginPath(); c.moveTo(X(0), Y(arr[sim * nW]));
      for (let k = 1; k < nW; k++) c.lineTo(X(k), Y(arr[sim * nW + k]));
      c.stroke(); c.restore();
    }
    c.fillStyle = DIM; c.font = '10px system-ui, sans-serif';
    c.textAlign = 'right'; c.textBaseline = 'middle';
    const step = Math.max(1, Math.round((hi - lo) / 4));
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) c.fillText(String(v), PAD.l - 5, Y(v));
    c.textAlign = 'center'; c.textBaseline = 'top';
    c.fillText(`W${rolled.weeks[0]}`, X(0), h - PAD.b + 5);
    c.fillText(`W${rolled.weeks[nW - 1]}`, X(nW - 1), h - PAD.b + 5);
    return { X, Y, lo, hi };
  }, [rolled, act, sample, seriesFor, view, seed, nSims, picked, hover]);

  const panelsRef = useRef<(HTMLCanvasElement | null)[]>([]);
  const soloRef = useRef<HTMLCanvasElement>(null);
  const scalesRef = useRef<{ pi: number; X: (i: number) => number; Y: (v: number) => number; w: number; el: HTMLCanvasElement }[]>([]);

  const redraw = useCallback(() => {
    if (!rolled || !act) return;
    const dpr = window.devicePixelRatio || 1;
    scalesRef.current = [];
    const paint = (el: HTMLCanvasElement, pi: number, h: number) => {
      const w = el.clientWidth;
      if (!w) return;
      el.width = w * dpr; el.height = h * dpr; el.style.height = `${h}px`;
      const c = el.getContext('2d')!;
      c.setTransform(dpr, 0, 0, dpr, 0, 0);
      const sc = drawPanel(c, w, h, pi);
      if (sc) scalesRef.current.push({ pi, X: sc.X, Y: sc.Y, w, el });
    };
    if (view === 'all') model?.players.forEach((_, i) => {
      const el = panelsRef.current[i]; if (el) paint(el, i, 300);
    });
    else if (soloRef.current) paint(soloRef.current, meIdx, 430);
  }, [rolled, act, drawPanel, view, model, meIdx]);

  useEffect(() => { redraw(); }, [redraw]);
  useEffect(() => {
    const on = () => { cloudCache.current.clear(); redraw(); };
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, [redraw]);

  function onMove(e: React.MouseEvent) {
    if (!rolled || !act) return;
    let found: number | null = null;
    for (const p of scalesRef.current) {
      const r = p.el.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) continue;
      const mx = e.clientX - r.left, my = e.clientY - r.top;
      const arr = seriesFor(p.pi), nW = rolled.nWeeks;
      const t = (mx - PAD.l) / (p.w - PAD.l - PAD.r);
      const k = Math.max(0, Math.min(nW - 1, Math.round(t * (nW - 1))));
      let bd = 14;
      for (const s of sample) {
        const d = Math.abs(p.Y(arr[s * nW + k]) - my);
        if (d < bd) { bd = d; found = s; }
      }
    }
    setHover(found);
    const tip = tipRef.current, wrap = wrapRef.current;
    if (!tip || !wrap) return;
    if (found == null) { tip.style.opacity = '0'; return; }
    const r = wrap.getBoundingClientRect();
    const fin = model!.players
      .map((p, pi) => [p, act.paths[pi][found! * rolled.nWeeks + rolled.nWeeks - 1]] as [string, number])
      .sort((a, b) => b[1] - a[1]);
    tip.innerHTML =
      `<strong>Simulation #${found + 1}</strong> · ${sourceLabel(model!.sources[rolled.source[found]])}` +
      '<br>' + fin.map(([p, v], i) => `${i === 0 ? '🏆 ' : ''}${p} — ${v}`).join('<br>');
    tip.style.opacity = '1';
    tip.style.left = `${Math.min(e.clientX - r.left + 14, wrap.clientWidth - 220)}px`;
    tip.style.top = `${e.clientY - r.top + 14}px`;
  }

  if (error) return <div className="panel sim-empty">{error}</div>;
  if (!model) return <div className="panel sim-empty">Loading…</div>;

  const pct = (pi: number) => {
    if (!rolled || !act) return '—';
    let c = 0;
    for (let s = 0; s < rolled.nSims; s++) if (act.winner[s] === pi + 1) c++;
    return `${((c / rolled.nSims) * 100).toFixed(0)}%`;
  };

  return (
    <div className="sim">
      <div className="sim-controls">
        <div className="sim-seg">
          <button className={view === 'all' ? 'on' : ''} onClick={() => setView('all')}>All teams</button>
          <button className={view === 'margin' ? 'on' : ''} onClick={() => setView('margin')}>Single margin</button>
        </div>
        {view === 'margin' && (
          <select value={meIdx} onChange={(e) => setMeIdx(+e.target.value)}>
            {model.players.map((p, i) => <option key={p} value={i}>{p}</option>)}
          </select>
        )}
        <select value={nSims} onChange={(e) => setNSims(+e.target.value)}>
          {COUNTS.map((n) => <option key={n} value={n}>{n.toLocaleString()} sims</option>)}
        </select>
        {busy && <span className="sim-bar"><i style={{ width: `${(done / nSims) * 100}%` }} /></span>}
        <button className="btn" onClick={() => setSeed(Math.floor(Math.random() * 1e9))}>
          Resimulate
        </button>
      </div>

      {model.played.length > 0 && (
        <p className="sim-note">
          {model.played.length} game{model.played.length === 1 ? '' : 's'} played.
          Every simulation starts from the real results.
        </p>
      )}
      <div className="panel">
        <div className="sim-legend">
          <span><i style={{ background: WIN }} />
            {view === 'margin' ? `${model.players[meIdx].split(' ')[0]} wins` : 'this player wins'}</span>
          <span><i style={{ background: CLOUD }} />someone else wins</span>
          <span className="sim-hint">
            {busy
              ? `rolling ${(done || 0).toLocaleString()} of ${nSims.toLocaleString()}…`
              : 'hover a line to read it, click to open it'}
          </span>
        </div>

        <div className="sim-wrap" ref={wrapRef} onMouseMove={onMove}
             onMouseLeave={() => { setHover(null); if (tipRef.current) tipRef.current.style.opacity = '0'; }}
             onClick={() => { if (hover != null) setPicked(hover); }}>
          {view === 'all' ? (
            <div className="sim-panels">
              {model.players.map((p, i) => (
                <div key={p} className="sim-p">
                  <h3>{p}</h3>
                  <div className="sim-pct">{pct(i)} win</div>
                  <canvas ref={(el) => { panelsRef.current[i] = el; }} />
                </div>
              ))}
            </div>
          ) : <canvas ref={soloRef} />}
          <div className="sim-tip" ref={tipRef} />
        </div>
      </div>

      {picked != null && rolled && act
        ? <SeasonDetail model={model} sim={picked} seed={seed} />
        : <div className="panel sim-empty">Click any line to open that simulation.</div>}
    </div>
  );
}

function SeasonDetail({ model, sim, seed }: {
  model: SimModel; sim: number; seed: number;
}) {
  const [lit, setLit] = useState<string | null>(null);
  const d = useMemo(() => {
    const detail = new Uint8Array(model.games.length);
    const src = model.sources[rollSeason(model, seed, sim, detail)];
    const ti = new Map(model.teams.map((c, i) => [c, i]));
    const str = model.strength[model.sources.indexOf(src)];

    type G = { w: string; l: string; upset: boolean; played?: boolean; tie?: boolean; h: string; a: string };
    const byWeek = new Map<number, G[]>();
    const push = (wk: number, g: G) => {
      if (!byWeek.has(wk)) byWeek.set(wk, []);
      byWeek.get(wk)!.push(g);
    };

    // games with a real score are already in `banked`; show them as settled
    const tw = Float64Array.from(model.banked);
    for (const [wk, home, away, hw] of model.played) {
      push(wk, { w: hw === 0 ? away : home, l: hw === 0 ? home : away,
                 upset: false, played: true, tie: hw === -1, h: home, a: away });
    }

    let upsets = 0;
    model.games.forEach(([wk, home, away], i) => {
      const h = ti.get(home)!, a = ti.get(away)!;
      const hw = detail[i];
      tw[hw ? h : a]++;
      const upset = (str[h] - str[a] + model.hfa) * (hw ? 1 : -1) < 0;
      if (upset) upsets++;
      push(wk, { w: hw ? home : away, l: hw ? away : home, upset, h: home, a: away });
    });

    const owners = model.players.map((p) => {
      const codes = model.rosters[p].map((c) => ({ c, n: tw[ti.get(c)!] }))
        .sort((x, y) => y.n - x.n);
      return { p, codes, total: codes.reduce((t, x) => t + x.n, 0) };
    }).sort((a, b) => b.total - a.total);

    return { src, weeks: [...byWeek].sort((a, b) => a[0] - b[0]), owners,
             upsets, played: model.played.length };
  }, [model, sim, seed]);

  const best = d.owners[0].total;
  return (
    <div className="panel sim-detail">
      <h2>Simulation #{sim + 1} using {sourceLabel(d.src)} rankings</h2>
      <p className="sim-meta">
        {d.played > 0 && `${d.played} played game${d.played === 1 ? '' : 's'} locked in. `}
        {d.upsets} upsets.
      </p>
      <div className="sim-owners">
        {d.owners.map((o) => (
          <div key={o.p} className={`sim-own${o.total === best ? ' first' : ''}`}>
            <div className="sim-own-hd"><span>{o.p}</span><b>{o.total}</b></div>
            {o.codes.map((t) => (
              <div key={t.c} className="sim-tm"
                   onMouseEnter={() => setLit(t.c)} onMouseLeave={() => setLit(null)}>
                <span className="c">{t.c}</span>
                <span className="b" style={{ width: `${(t.n / 17) * 100}%` }} />
                <span className="n">{t.n}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <p className="sim-key">
        Winner on the left. <b>Dark</b> games have been played, light ones are simulated.{' '}
        <span className="mk">*</span> means the ratings had the other team ahead.
      </p>
      <div className={`sim-weeks${lit ? ' dim' : ''}`}>
        {d.weeks.map(([wk, games]) => (
          <div key={wk} className="sim-wk">
            <div className="sim-wk-lab">Wk {wk}</div>
            {games.map((g, i) => (
              <div key={i}
                   className={`sim-g${g.played ? ' played' : ''}${lit && (g.h === lit || g.a === lit) ? ' hit' : ''}`}>
                <span className="mk">{g.upset ? '*' : ''}</span>
                <span className="w">{g.tie ? 'tie' : g.w}</span>
                <span className="l">{g.tie ? `${g.h}/${g.a}` : g.l}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
