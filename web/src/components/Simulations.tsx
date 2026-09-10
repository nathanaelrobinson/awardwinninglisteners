// web/src/components/Simulations.tsx
//
// The season, rolled a hundred thousand times, drawn as a hundred thousand
// lines. The server ships the ensemble; every roll happens here (see sim.ts).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getSimModel } from '../league';
import type { Rolled, SimModel } from '../sim';
import { rollAll, rollSeason, scheduleOf, sourceLabel } from '../sim';

type View = 'all' | 'margin';
type Mode = 'possible' | 'resim';

const PAD = { l: 40, r: 12, t: 12, b: 24 };
const DRAW_N = 5000;           // lines actually painted; every count uses them all
const COUNTS = [20000, 50000, 100000, 250000];

const WIN = '#1b48e0';         // this player wins
const DEAD = '#d50a0a';        // ruled out
const CLOUD = '#9aa1ad';       // someone else wins
const INK = '#151515';
const RULE = '#d6d9de';
const DIM = '#626c80';

export default function Simulations({ myName }: { myName: string }) {
  const [model, setModel] = useState<SimModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rolled, setRolled] = useState<Rolled | null>(null);
  const [busy, setBusy] = useState(false);

  const [view, setView] = useState<View>('all');
  const [mode, setMode] = useState<Mode>('resim');
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

  // Two cohorts, rolled lazily and kept. "Resimulate" starts every season from
  // today's banked wins; "Still possible" replays the whole season from zero so
  // results have something to rule out. Rolling blocks for a moment, so paint
  // the busy state before starting.
  const cohorts = useRef(new Map<string, Rolled>());
  useEffect(() => {
    if (!model) return;
    const key = `${mode}|${nSims}|${seed}`;
    const hit = cohorts.current.get(key);
    if (hit) { setRolled(hit); return; }
    setBusy(true);
    const id = window.setTimeout(() => {
      const r = rollAll(model, nSims, seed, mode === 'possible');
      cohorts.current.set(key, r);
      setRolled(r);
      cloudCache.current.clear();
      setPicked(null); setHover(null); setBusy(false);
    }, 16);
    return () => window.clearTimeout(id);
  }, [model, nSims, seed, mode]);
  useEffect(() => { cohorts.current.clear(); }, [model]);

  const locked = rolled?.playedWeeks ?? 0;

  // Resimulate already starts from banked wins, so its lines need no re-anchoring.
  const act = useMemo(() => {
    if (!rolled) return null;
    return { paths: rolled.paths, winner: rolled.winner };
  }, [rolled]);

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

  const aliveAt = useCallback((s: number) => !rolled || !rolled.dead[s], [rolled]);
  // a ruled-out season stops at the boundary between results and everything after
  const liveEnd = useCallback((s: number) => {
    if (!rolled) return 0;
    return rolled.dead[s] ? Math.max(2, Math.min(rolled.nWeeks, locked)) : rolled.nWeeks;
  }, [rolled, locked]);

  // 100k lines need an alpha so low each is invisible, so paint a sample of
  // whatever is still possible and count with the whole set.
  const sample = useMemo(() => {
    if (!rolled) return { alive: [] as number[], dead: [] as number[] };
    const alive: number[] = [], dead: number[] = [];
    for (let s = 0; s < rolled.nSims; s++) (aliveAt(s) ? alive : dead).push(s);
    const pick = (arr: number[], n: number) => {
      if (arr.length <= n) return arr;
      const out = new Array<number>(n), stride = arr.length / n;
      for (let i = 0; i < n; i++) out[i] = arr[(i * stride) | 0];
      return out;
    };
    return { alive: pick(alive, DRAW_N), dead: pick(dead, DRAW_N >> 1) };
  }, [rolled, aliveAt]);

  const seriesFor = useCallback((pi: number) =>
    (view === 'margin' ? margins! : act!.paths[pi]), [view, margins, act]);

  const drawPanel = useCallback((c: CanvasRenderingContext2D, w: number, h: number, pi: number) => {
    if (!rolled || !act) return null;
    const nW = rolled.nWeeks, arr = seriesFor(pi);
    let lo = Infinity, hi = -Infinity;
    for (const s of [...sample.alive, ...sample.dead]) {
      const end = liveEnd(s);
      for (let k = 0; k < end; k++) { const v = arr[s * nW + k]; if (v < lo) lo = v; if (v > hi) hi = v; }
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = Math.max(1, (hi - lo) * 0.04); lo -= pad; hi += pad;
    const X = (i: number) => PAD.l + (w - PAD.l - PAD.r) * (nW === 1 ? 0.5 : i / (nW - 1));
    const Y = (v: number) => PAD.t + (h - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo || 1));

    const key = `${pi}|${view}|${mode}|${w}|${h}|${locked}|${seed}|${nSims}`;
    let off = cloudCache.current.get(key);
    if (!off) {
      cloudCache.current.clear();
      const dpr = window.devicePixelRatio || 1;
      off = document.createElement('canvas');
      off.width = w * dpr; off.height = h * dpr;
      const oc = off.getContext('2d')!;
      oc.setTransform(dpr, 0, 0, dpr, 0, 0);
      const a = Math.max(0.03, Math.min(0.16, 420 / Math.max(sample.alive.length, 1)));
      const passes: { list: number[]; keep: (s: number) => boolean; col: string; al: number; cut?: boolean }[] = [
        { list: sample.dead, keep: () => true, col: DEAD, al: a * 0.55, cut: true },
        { list: sample.alive, keep: (s) => act.winner[s] !== pi + 1, col: CLOUD, al: a * 0.8 },
        { list: sample.alive, keep: (s) => act.winner[s] === pi + 1, col: WIN, al: a * 1.3 },
      ];
      for (const p of passes) {
        oc.strokeStyle = p.col; oc.globalAlpha = Math.min(p.al, 0.5); oc.lineWidth = 1;
        oc.beginPath();
        for (const s of p.list) {
          if (!p.keep(s)) continue;
          const end = p.cut ? liveEnd(s) : nW;
          oc.moveTo(X(0), Y(arr[s * nW]));
          for (let k = 1; k < end; k++) oc.lineTo(X(k), Y(arr[s * nW + k]));
        }
        oc.stroke();
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
    if (locked > 0) {
      c.save(); c.strokeStyle = DIM; c.globalAlpha = 0.5;
      c.beginPath(); c.moveTo(X(locked - 1), PAD.t); c.lineTo(X(locked - 1), h - PAD.b);
      c.stroke(); c.restore();
      if (view !== 'margin') {
        c.save(); c.strokeStyle = INK; c.lineWidth = 2.5; c.lineJoin = 'round';
        c.beginPath(); c.moveTo(X(0), Y(rolled.realPath[pi][0]));
        for (let k = 1; k < locked; k++) c.lineTo(X(k), Y(rolled.realPath[pi][k]));
        c.stroke(); c.restore();
      }
    }
    for (const [sim, col] of [[picked, WIN], [hover, DEAD]] as [number | null, string][]) {
      if (sim == null) continue;
      const end = Math.max(liveEnd(sim), 2);
      c.save(); c.strokeStyle = col; c.lineWidth = 2.25; c.lineJoin = 'round';
      c.globalAlpha = aliveAt(sim) ? 1 : 0.55;
      c.beginPath(); c.moveTo(X(0), Y(arr[sim * nW]));
      for (let k = 1; k < end; k++) c.lineTo(X(k), Y(arr[sim * nW + k]));
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
  }, [rolled, act, sample, seriesFor, liveEnd, aliveAt, view, mode, locked, seed, nSims, picked, hover]);

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
      for (const s of [...sample.alive, ...sample.dead]) {
        if (liveEnd(s) <= k) continue;
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
      (aliveAt(found) ? '' : ` · <span style="color:${DEAD}">no longer possible</span>`) +
      '<br>' + fin.map(([p, v], i) => `${i === 0 ? '🏆 ' : ''}${p} — ${v}`).join('<br>');
    tip.style.opacity = '1';
    tip.style.left = `${Math.min(e.clientX - r.left + 14, wrap.clientWidth - 220)}px`;
    tip.style.top = `${e.clientY - r.top + 14}px`;
  }

  if (error) return <div className="panel sim-empty">{error}</div>;
  if (!model) return <div className="panel sim-empty">Loading…</div>;

  const pct = (pi: number) => {
    if (!rolled || !act) return '—';
    let n = 0, c = 0;
    for (let s = 0; s < rolled.nSims; s++) if (aliveAt(s)) { n++; if (act.winner[s] === pi + 1) c++; }
    return `${((c / Math.max(n, 1)) * 100).toFixed(0)}%`;
  };

  return (
    <div className="sim">
      <div className="sim-controls">
        <div className="sim-seg">
          <button className={view === 'all' ? 'on' : ''} onClick={() => setView('all')}>All five</button>
          <button className={view === 'margin' ? 'on' : ''} onClick={() => setView('margin')}>Margin</button>
        </div>
        <div className="sim-seg">
          <button className={mode === 'resim' ? 'on' : ''} onClick={() => setMode('resim')}>Resimulate</button>
          <button className={mode === 'possible' ? 'on' : ''} onClick={() => setMode('possible')}>Still possible</button>
        </div>
        {view === 'margin' && (
          <select value={meIdx} onChange={(e) => setMeIdx(+e.target.value)}>
            {model.players.map((p, i) => <option key={p} value={i}>{p}</option>)}
          </select>
        )}
        <select value={nSims} onChange={(e) => setNSims(+e.target.value)}>
          {COUNTS.map((n) => <option key={n} value={n}>{n.toLocaleString()} sims</option>)}
        </select>
        <span className="sim-alive">
          {mode === 'possible' && rolled && rolled.nAlive < nSims
            ? <><b>{rolled.nAlive.toLocaleString()}</b> of {nSims.toLocaleString()} still possible</>
            : <><b>{nSims.toLocaleString()}</b> futures</>}
        </span>
        <button className="btn" onClick={() => setSeed(Math.floor(Math.random() * 1e9))}>
          Reroll
        </button>
      </div>

      {model.played.length > 0 && (
        <p className="sim-note">
          {model.played.length} game{model.played.length === 1 ? ' is' : 's are'} final.{' '}
          {mode === 'resim'
            ? `Every one of these ${nSims.toLocaleString()} seasons starts from those results.`
            : `These ${nSims.toLocaleString()} seasons were rolled before any of them, so results can rule them out.`}
        </p>
      )}

      <div className="panel">
        <div className="sim-legend">
          <span><i style={{ background: WIN }} />
            {view === 'margin' ? `${model.players[meIdx].split(' ')[0]} wins` : 'this player wins'}</span>
          <span><i style={{ background: CLOUD }} />someone else wins</span>
          {mode === 'possible' && rolled && rolled.nAlive < nSims &&
            <span><i style={{ background: DEAD }} />ruled out — {(nSims - rolled.nAlive).toLocaleString()}</span>}
          {locked > 0 && view !== 'margin' && <span><i style={{ background: INK }} />what happened</span>}
          <span className="sim-hint">
            {busy ? 'rolling…' : 'hover a line to read it, click to open it'}
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
        ? <SeasonDetail model={model} rolled={rolled} sim={picked} seed={seed}
                        alive={aliveAt(picked)} />
        : <div className="panel sim-empty">Click any line to open that simulation.</div>}
    </div>
  );
}

function SeasonDetail({ model, rolled, sim, seed, alive }: {
  model: SimModel; rolled: Rolled; sim: number; seed: number; alive: boolean;
}) {
  const [lit, setLit] = useState<string | null>(null);
  const d = useMemo(() => {
    const pre = rolled.preseason;
    const sched = scheduleOf(model, pre);
    const detail = new Uint8Array(sched.length);
    const src = model.sources[rollSeason(model, seed, sim, detail, pre)];
    const ti = new Map(model.teams.map((c, i) => [c, i]));
    const str = model.strength[model.sources.indexOf(src)];

    // real results, so a preseason season can be checked against them
    const real = new Map(model.played.map(([w, h, a, hw]) => [`${w}|${h}|${a}`, hw]));

    type G = { w: string; l: string; upset: boolean; conflict: boolean; final?: boolean; tie?: boolean; h: string; a: string };
    const byWeek = new Map<number, G[]>();
    const push = (wk: number, g: G) => {
      if (!byWeek.has(wk)) byWeek.set(wk, []);
      byWeek.get(wk)!.push(g);
    };

    // a live cohort never plays the finals, so list them from the real results
    if (!pre) {
      for (const [wk, home, away, hw] of model.played) {
        push(wk, { w: hw === 0 ? away : home, l: hw === 0 ? home : away,
                   upset: false, conflict: false, final: true, tie: hw === -1, h: home, a: away });
      }
    }

    const tw = pre ? new Float64Array(model.teams.length) : Float64Array.from(model.banked);
    let upsets = 0, conflicts = 0;
    sched.forEach(([wk, home, away], i) => {
      const h = ti.get(home)!, a = ti.get(away)!;
      const hw = detail[i];
      tw[hw ? h : a]++;
      const upset = (str[h] - str[a] + model.hfa) * (hw ? 1 : -1) < 0;
      const realHW = real.get(`${wk}|${home}|${away}`);
      const conflict = realHW !== undefined && realHW !== -1 && realHW !== hw;
      if (upset) upsets++;
      if (conflict) conflicts++;
      push(wk, { w: hw ? home : away, l: hw ? away : home, upset, conflict,
                 final: realHW !== undefined && !conflict, h: home, a: away });
    });

    const owners = model.players.map((p) => {
      const codes = model.rosters[p].map((c) => ({ c, n: tw[ti.get(c)!] }))
        .sort((x, y) => y.n - x.n);
      return { p, codes, total: codes.reduce((t, x) => t + x.n, 0) };
    }).sort((a, b) => b.total - a.total);

    const weeks = [...byWeek].sort((a, b) => a[0] - b[0]);
    return { src, weeks, owners, upsets, conflicts, finals: model.played.length, pre };
  }, [model, rolled, sim, seed]);

  const best = d.owners[0].total;
  return (
    <div className="panel sim-detail">
      <h2>Simulation #{sim + 1} using {sourceLabel(d.src)} rankings</h2>
      <p className="sim-meta">
        {d.pre
          ? <>Rolled from week 1, before anything was played. </>
          : d.finals > 0 && <><b>{d.finals} already final</b>, banked in. </>}
        {d.upsets} {d.pre || d.finals === 0 ? 'games were' : 'of the rest were'} upsets.{' '}
        {alive
          ? 'This outcome is still possible.'
          : `No longer possible${d.conflicts ? `: ${d.conflicts} game${d.conflicts === 1 ? '' : 's'} went the other way.` : '.'}`}
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
      <div className={`sim-weeks${lit ? ' dim' : ''}`}>
        {d.weeks.map(([wk, games]) => (
          <div key={wk} className="sim-wk">
            <div className="sim-wk-lab">Wk {wk}</div>
            {games.map((g, i) => (
              <div key={i}
                   className={`sim-g${g.conflict ? ' conflict' : g.final ? ' final' : ''}${lit && (g.h === lit || g.a === lit) ? ' hit' : ''}`}>
                <span className={g.upset ? 'w up' : 'w'}>{g.tie ? '—' : g.w}</span>
                <span className="l">{g.tie ? `${g.h}/${g.a}` : g.l}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
