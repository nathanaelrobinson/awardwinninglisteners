import { useEffect, useMemo, useState } from 'react';
import './App.css';
import { fetchRecommend, fetchTeams } from './api';
import type { Mode, RecommendResponse, TeamsResponse } from './types';
import Header from './components/Header';
import Board from './components/Board';
import Rosters from './components/Rosters';
import Recommendations from './components/Recommendations';
import AutosimView from './components/AutosimView';

const PICKS_PER_PLAYER = 6;

type Tab = 'draft' | 'autosim';

export default function App() {
  const [tab, setTab] = useState<Tab>('draft');
  const [slot, setSlot] = useState<number>(1);
  const [taken, setTaken] = useState<string[]>([]);
  const [mode, setMode] = useState<Mode>('rollout');

  const [teamsData, setTeamsData] = useState<TeamsResponse | null>(null);
  const [teamsError, setTeamsError] = useState<string | null>(null);

  const [recommend, setRecommend] = useState<RecommendResponse | null>(null);
  const [recommendError, setRecommendError] = useState<string | null>(null);
  const [recLoading, setRecLoading] = useState(false);

  // Load teams once.
  useEffect(() => {
    let cancelled = false;
    fetchTeams()
      .then((data) => {
        if (!cancelled) setTeamsData(data);
      })
      .catch((err) => {
        if (!cancelled) setTeamsError(err.message ?? 'Failed to load teams');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch recommendation whenever slot, taken, or mode changes.
  useEffect(() => {
    let cancelled = false;
    setRecLoading(true);
    fetchRecommend(slot, taken, mode)
      .then((data) => {
        if (!cancelled) {
          setRecommend(data);
          setRecommendError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setRecommendError(err.message ?? 'Failed to fetch recommendation');
      })
      .finally(() => {
        if (!cancelled) setRecLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slot, taken, mode]);

  const takenBy = useMemo(() => {
    const map: Record<string, number> = {};
    if (!teamsData) return map;
    taken.forEach((code, i) => {
      const player = teamsData.pick_order[i];
      if (player !== undefined) map[code] = player;
    });
    return map;
  }, [taken, teamsData]);

  const teamNames = useMemo(() => {
    const map: Record<string, string> = {};
    if (!teamsData) return map;
    teamsData.teams.forEach((t) => {
      map[t.code] = t.name;
    });
    return map;
  }, [teamsData]);

  function handleDraft(code: string) {
    if (takenBy[code] !== undefined) return;
    setTaken((prev) => [...prev, code]);
  }

  function handleReset() {
    setTaken([]);
  }

  function handleUndo() {
    setTaken((prev) => prev.slice(0, -1));
  }

  if (teamsError) {
    return (
      <div className="app-error">
        <h2>Backend not reachable</h2>
        <p>Could not load team data from /api/teams.</p>
        <p className="error-detail">{teamsError}</p>
        <p>Make sure the FastAPI backend is running, then reload the page.</p>
      </div>
    );
  }

  if (!teamsData) {
    return (
      <div className="app-loading">
        <p>Loading teams…</p>
      </div>
    );
  }

  return (
    <div className="app">
      <Header
        slot={slot}
        onSlotChange={setSlot}
        nPlayers={teamsData.n_players}
        recommend={recommend}
        mode={mode}
        onModeChange={setMode}
        onReset={handleReset}
        onUndo={handleUndo}
        canUndo={taken.length > 0}
      />

      {recommendError && (
        <div className="banner banner-error">
          Recommendation request failed: {recommendError}
        </div>
      )}

      <div className="tab-bar">
        <button
          className={`tab-btn ${tab === 'draft' ? 'active' : ''}`}
          onClick={() => setTab('draft')}
        >
          Draft
        </button>
        <button
          className={`tab-btn ${tab === 'autosim' ? 'active' : ''}`}
          onClick={() => setTab('autosim')}
        >
          Auto-sim
        </button>
      </div>

      {tab === 'draft' ? (
        <main className="main-layout">
          <div className="main-left">
            <Recommendations recommend={recommend} loading={recLoading} teamNames={teamNames} />
            <Rosters
              rosters={recommend?.rosters ?? {}}
              mySlot={slot}
              nPlayers={teamsData.n_players}
              picksPerPlayer={PICKS_PER_PLAYER}
            />
          </div>
          <div className="main-right">
            <Board
              teams={teamsData.teams}
              takenBy={takenBy}
              mySlot={slot}
              onDraft={handleDraft}
              disabled={false}
            />
          </div>
        </main>
      ) : (
        <main className="main-layout main-layout-single">
          <AutosimView slot={slot} nPlayers={teamsData.n_players} />
        </main>
      )}
    </div>
  );
}
