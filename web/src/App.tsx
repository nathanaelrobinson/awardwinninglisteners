// web/src/App.tsx
import { useCallback, useEffect, useRef, useState } from 'react';
import './App.css';
import type { LeagueView, Me } from './league';
import { getLeague, getMe } from './league';
import Login from './components/Login';
import Lobby from './components/Lobby';
import LiveDraft from './components/LiveDraft';
import Standings from './components/Standings';
import StatusBar from './components/StatusBar';
import Practice from './components/Practice';

type Tab = 'draft' | 'standings' | 'practice';

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = checking
  const [view, setView] = useState<LeagueView | null>(null);
  const [tab, setTab] = useState<Tab>('draft');
  const tabChosen = useRef(false);

  const refreshMe = useCallback(() => {
    getMe().then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(refreshMe, [refreshMe]);

  // Poll league state: 2s while lobby/drafting, 60s when done.
  useEffect(() => {
    if (!me) return;
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const v = await getLeague();
        if (!alive) return;
        setView(v);
        if (!tabChosen.current) {
          tabChosen.current = true;
          setTab(v.status === 'done' ? 'standings' : 'draft');
        }
        timer = window.setTimeout(tick, v.status === 'done' ? 10_000 : 2_000);
      } catch (e) {
        if ((e as Error).message === '401') { setMe(null); return; }
        timer = window.setTimeout(tick, 5_000);
      }
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, [me]);

  if (me === undefined) return null;
  if (me === null) return <Login onDone={refreshMe} />;
  if (!view) return null;

  const tabs: Tab[] = me.is_commissioner ? ['draft', 'standings', 'practice'] : ['draft', 'standings'];

  return (
    <div className="app">
      <nav className="tab-bar">
        <div className="tab-bar-inner">
          {tabs.map((t) => (
            <button key={t} className={`tab-btn ${tab === t ? 'active' : ''}`} onClick={() => { tabChosen.current = true; setTab(t); }}>
              {t === 'draft' ? 'Draft' : t === 'standings' ? 'Standings' : 'Practice'}
            </button>
          ))}
          <span className="tab-me">{me.name}</span>
        </div>
      </nav>
      <StatusBar view={view} me={me} />
      {tab !== 'practice' && (
        <main className="wrap">
          {tab === 'draft' && (view.status === 'lobby' ? <Lobby view={view} me={me} /> : <LiveDraft view={view} me={me} onChange={setView} />)}
          {tab === 'standings' && <Standings me={me} view={view} />}
        </main>
      )}
      {tab === 'practice' && <Practice />}
    </div>
  );
}
