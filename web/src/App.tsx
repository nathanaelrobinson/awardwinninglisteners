// web/src/App.tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import './App.css';
import type { LeagueView, Me } from './league';
import { getLeague, getMe, pickTeam } from './league';
import Login from './components/Login';
import Lobby from './components/Lobby';
import LiveDraft from './components/LiveDraft';
import Standings from './components/Standings';
import StatusBar from './components/StatusBar';
import OrderTicker from './components/OrderTicker';
import Practice from './components/Practice';
import Review from './components/Review';

type Tab = 'draft' | 'review' | 'standings' | 'practice';

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = checking, null = anonymous
  const [needLogin, setNeedLogin] = useState(false);
  const [view, setView] = useState<LeagueView | null>(null);
  const [tab, setTab] = useState<Tab>('draft');
  const [selected, setSelected] = useState<string | null>(null);
  const tabChosen = useRef(false);

  const refreshMe = useCallback(() => {
    getMe().then((m) => { setMe(m); setNeedLogin(false); }).catch(() => setMe(null));
  }, []);
  useEffect(refreshMe, [refreshMe]);

  // Poll league state: 2s while lobby/drafting, 10s when done. Anonymous
  // viewers get read-only access once the draft is done; before that the
  // server answers 401 and we show the login screen.
  useEffect(() => {
    if (me === undefined) return;
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const v = await getLeague();
        if (!alive) return;
        setView(v);
        if (!tabChosen.current) {
          tabChosen.current = true;
          setTab(v.status === 'done' || !me ? 'standings' : 'draft');
        }
        timer = window.setTimeout(tick, v.status === 'done' ? 10_000 : 2_000);
      } catch (e) {
        if ((e as Error).message === '401') {
          if (me) setMe(null); else setNeedLogin(true);
          return;
        }
        timer = window.setTimeout(tick, 5_000);
      }
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [me]);

  // Clear a selected-but-unconfirmed tile when it's no longer our turn, or once
  // the selected team shows up in picks (someone else took it, or ours landed).
  useEffect(() => {
    if (!view || !me) { setSelected(null); return; }
    const myTurn = view.status === 'drafting' && view.current_player === me.name;
    if (!myTurn) { setSelected(null); return; }
    if (selected && view.picks.some((p) => p.team === selected)) setSelected(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, me]);

  async function confirmPick() {
    if (!selected) return;
    const code = selected;
    setSelected(null);
    try { setView(await pickTeam(code)); } catch { getLeague().then(setView).catch(() => {}); }
  }

  if (me === undefined) return null;
  if (me === null && needLogin) return <Login onDone={refreshMe} />;
  if (!view) return null;

  const tabs: Tab[] = me ? ['draft'] : [];
  if (view.status === 'done') tabs.push('review');
  tabs.push('standings');
  if (me?.is_commissioner) tabs.push('practice');
  const LABEL: Record<Tab, string> = { draft: 'Draft', review: 'Draft Review', standings: 'Standings', practice: 'Practice' };

  return (
    <div className="app">
      <nav className="tab-bar">
        <div className="tab-bar-inner">
          {tabs.map((t) => (
            <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => { tabChosen.current = true; setTab(t); }}>
              {LABEL[t]}
            </button>
          ))}
          {me
            ? <span className="tab-me">{me.name}</span>
            : <button className="tab-btn tab-signin" onClick={() => setNeedLogin(true)}>Sign in</button>}
        </div>
      </nav>
      <StatusBar view={view} me={me} selected={selected} onConfirm={confirmPick} />
      <OrderTicker view={view} myName={me?.name ?? ''} />
      {tab !== 'practice' && (
        <main className="wrap">
          {tab === 'draft' && me && (view.status === 'lobby' ? <Lobby view={view} me={me} /> : <LiveDraft view={view} me={me} onChange={setView} selected={selected} onSelect={setSelected} />)}
          {tab === 'review' && <Review me={me} />}
          {tab === 'standings' && <Standings me={me} view={view} />}
        </main>
      )}
      {tab === 'practice' && <Practice />}
    </div>
  );
}
