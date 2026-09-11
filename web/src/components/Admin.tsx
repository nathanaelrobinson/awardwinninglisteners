// web/src/components/Admin.tsx
//
// Commissioner-only operator view: are the rating sources current, and are
// the background jobs still running? This tab is exempt from the game
// board's terse-copy rule — it's read by one person trying to work out
// whether something is broken, so it spells things out.
import { useEffect, useState } from 'react';
import type { AdminHealth, AdminHistory, AdminModel } from '../league';
import { getAdminHealth, getAdminHistory, getAdminModel } from '../league';
import { allVoices, assignColors } from './viz/palette';
import VoiceLegend from './viz/VoiceLegend';
import RowChart, { type RowDatum } from './viz/RowChart';
import PwinByWeek from './viz/PwinByWeek';

function formatAgo(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(s / 3600);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(s / 86400);
  return `${d}d ago`;
}

function formatLimit(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(s / 3600);
  if (h < 24) return `${h}h`;
  const d = Math.floor(s / 86400);
  return `${d}d`;
}

const pct = (p: number) => `${(p * 100).toFixed(1)}%`;

/** What the ensemble computed before it threw the working out away: what each
 *  voice believes on its own, whether season variance was calibrated against
 *  the market, and every team's strength under every voice.
 *
 *  Each chart sits directly under the table it explains: the numbers are the
 *  fallback the palette's contrast check relies on, so they stay adjacent. */
function ModelSection(
  { m, chartVoices, colors }: { m: AdminModel; chartVoices: string[]; colors: Record<string, string> },
) {
  const voices = m.sources.map((s) => s.name);
  const players = Object.keys(m.blend_pwin)
    .sort((a, b) => m.blend_pwin[b] - m.blend_pwin[a]);
  const withMeta = m.sources.filter((s) => s.meta != null);

  const playerRows: RowDatum[] = players.map((p) => ({
    key: p,
    label: p,
    values: Object.fromEntries(
      m.sources.filter((s) => s.pwin[p] != null).map((s) => [s.name, s.pwin[p]]),
    ),
    ref: m.blend_pwin[p] ?? null,
  }));

  const teams = [...m.teams].sort((a, b) => b.consensus - a.consensus);
  const teamRows: RowDatum[] = teams.map((t) => ({
    key: t.code,
    label: t.code,
    values: t.strength,
    ref: t.consensus,
  }));
  // Strengths are mean-centred, so the axis is centred on zero: a symmetric
  // domain keeps "left of centre" meaning "below average" for every row.
  const reach = Math.max(
    1,
    ...teams.flatMap((t) => [Math.abs(t.consensus), ...Object.values(t.strength).map(Math.abs)]),
  );
  const tReach = Math.ceil(reach / 2) * 2;

  return (
    <>
      <div className="card admin-card viz">
        <span className="eyebrow">Chance of winning the pool, by rating source</span>
        <div className="admin-scroll">
          <table className="proj-table admin-table">
            <thead>
              <tr>
                <th>Player</th>
                <th>Blend</th>
                {voices.map((v) => <th key={v}>{v}</th>)}
              </tr>
            </thead>
            <tbody>
              {players.map((p) => (
                <tr key={p}>
                  <td>{p}</td>
                  <td className="admin-blend">{pct(m.blend_pwin[p])}</td>
                  {m.sources.map((s) => (
                    <td key={s.name}>{s.pwin[p] == null ? '—' : pct(s.pwin[p])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={`admin-sigma${m.sigma_calibrated ? '' : ' admin-sigma-bad'}`}>
          {m.sigma_calibrated
            ? 'Season variance: calibrated against Kalshi.'
            : `Season variance: NOT calibrated — falling back to base ${m.sigma_base}.`}
        </p>
        <VoiceLegend voices={chartVoices} colors={colors} refName="Blend" />
        <RowChart
          label="Chance of winning the pool, one dot per rating source"
          rows={playerRows}
          voices={chartVoices}
          colors={colors}
          lo={0}
          hi={1}
          ticks={[0, 0.25, 0.5, 0.75, 1]}
          fmt={(v) => `${Math.round(v * 100)}%`}
          refName="Blend"
          labelW={156}
        />
      </div>

      <div className="card admin-card viz">
        <span className="eyebrow">Team strength by rating source, on the common scale</span>
        <div className="admin-scroll">
          <table className="proj-table admin-table">
            <thead>
              <tr>
                <th>Team</th>
                {voices.map((v) => <th key={v}>{v}</th>)}
                <th>Consensus</th>
                <th>Sigma</th>
                <th>Market SD</th>
              </tr>
            </thead>
            <tbody>
              {m.teams.map((t) => (
                <tr key={t.code}>
                  <td>{t.code}</td>
                  {voices.map((v) => (
                    <td key={v}>{t.strength[v] == null ? '—' : t.strength[v].toFixed(2)}</td>
                  ))}
                  <td className="admin-blend">{t.consensus.toFixed(2)}</td>
                  <td>{t.sigma.toFixed(2)}</td>
                  <td>{t.target_sd == null ? '—' : t.target_sd.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <VoiceLegend voices={chartVoices} colors={colors} refName="Consensus" />
        {/* Sigma is in the table above but deliberately not on this chart: the
            range line is the spread between voices, and drawing season outcome
            variance the same way would conflate two unrelated facts. */}
        <RowChart
          variant="forest"
          label="Team strength on the common scale, range of the rating sources"
          rows={teamRows}
          voices={chartVoices}
          colors={colors}
          lo={-tReach}
          hi={tReach}
          ticks={[-tReach, -tReach / 2, 0, tReach / 2, tReach]}
          fmt={(v) => v.toFixed(0)}
          refName="Consensus"
          labelW={54}
          maxHeight={420}
        />
      </div>

      {withMeta.length > 0 && (
        <div className="card admin-card">
          <span className="eyebrow">What each source recorded about itself</span>
          <div className="admin-sources">
            {withMeta.map((s) => (
              <div key={s.name} className="admin-row">
                <div className="admin-row-main">
                  <span className="admin-name">{s.name}</span>
                  <span className="admin-status">
                    {Object.entries(s.meta ?? {})
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(', ')}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/** How each voice's view of the pool has moved week over week, and how each
 *  source's fetches have held up over time. Built purely from stored
 *  documents, so it can show a week with fewer voices than exist today —
 *  a source outage genuinely happened, and that week's row must show only
 *  the voices it actually recorded, not a zero for the ones it lacks. */
function HistorySection(
  { h, myName, chartVoices, colors }:
  { h: AdminHistory; myName: string; chartVoices: string[]; colors: Record<string, string> },
) {
  const weeks = h.weeks;
  // Union of voices across all weeks, so an outage week simply contributes
  // no column-value for the voices it's missing, rather than every week
  // being forced onto today's roster.
  const voices = Array.from(new Set(weeks.flatMap((w) => Object.keys(w.views)))).sort();
  const withMeta = h.sources.filter((s) => s.points.some((p) => p.meta != null));

  return (
    <>
      <div className="card admin-card viz">
        <span className="eyebrow">Chance of winning the pool by week, for {myName || 'the viewing commissioner'}</span>
        <div className="admin-scroll">
          <table className="proj-table admin-table">
            <thead>
              <tr>
                <th>Voice</th>
                {weeks.map((w) => <th key={w.week}>Week {w.week}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="admin-blend">Blend</td>
                {weeks.map((w) => (
                  <td key={w.week} className="admin-blend">
                    {w.blend[myName] == null ? '—' : pct(w.blend[myName])}
                  </td>
                ))}
              </tr>
              {voices.map((v) => (
                <tr key={v}>
                  <td>{v}</td>
                  {weeks.map((w) => (
                    <td key={w.week}>
                      {w.views[v]?.[myName] == null ? '—' : pct(w.views[v][myName])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <VoiceLegend voices={chartVoices} colors={colors} refName="Blend" />
        <PwinByWeek history={h} voices={chartVoices} colors={colors} myName={myName} />
      </div>

      <div className="card admin-card">
        <span className="eyebrow">Source freshness history</span>
        <div className="admin-sources">
          {h.sources.map((s) => (
            <div key={s.name} className="admin-row">
              <div className="admin-row-main">
                <span className="admin-name">{s.name}</span>
                <span className="admin-status">
                  {s.points.length === 0 ? 'No fetches recorded yet' : `${s.points.length} most recent fetches, oldest to newest`}
                </span>
              </div>
              <div className="admin-run">
                {s.points.map((p, i) => (
                  <span key={i}
                        className={`admin-run-dot ${p.ok ? 'admin-run-ok' : 'admin-run-fail'}`}
                        title={`${p.ok ? 'Succeeded' : 'Failed'} ${formatAgo(Date.now() / 1000 - p.fetched_at)}`} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {withMeta.length > 0 && (
        <div className="card admin-card">
          <span className="eyebrow">Latest recorded detail per source</span>
          <div className="admin-sources">
            {withMeta.map((s) => {
              const latest = [...s.points].reverse().find((p) => p.meta != null);
              return (
                <div key={s.name} className="admin-row">
                  <div className="admin-row-main">
                    <span className="admin-name">{s.name}</span>
                    <span className="admin-status">
                      {Object.entries(latest?.meta ?? {}).map(([k, v]) => `${k}: ${v}`).join(', ')}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}

export default function Admin({ myName }: { myName: string }) {
  const [data, setData] = useState<AdminHealth | null>(null);
  const [model, setModel] = useState<AdminModel | null>(null);
  const [history, setHistory] = useState<AdminHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    let timer: number;
    const tick = async () => {
      try {
        const d = await getAdminHealth();
        if (alive) { setData(d); setError(null); }
      } catch {
        if (alive) setError('Could not load admin health.');
      }
      // The model view needs a live projection; before the first refresh of the
      // season there isn't one, and that is not an error worth shouting about.
      try {
        const m = await getAdminModel();
        if (alive) setModel(m);
      } catch {
        if (alive) setModel(null);
      }
      try {
        const h = await getAdminHistory();
        if (alive) setHistory(h);
      } catch {
        if (alive) setHistory(null);
      }
      if (alive) timer = window.setTimeout(tick, 60_000);
    };
    tick();
    return () => { alive = false; window.clearTimeout(timer); };
  }, []);

  if (error) return <div className="card"><span className="eyebrow">Admin</span><p>{error}</p></div>;
  if (!data) return null;

  // One colour map for every chart on the tab, built from the union of voices
  // the model and the history know about, so a voice keeps its colour in a
  // week where its neighbours are missing.
  const chartVoices = allVoices(model, history);
  const colors = assignColors(chartVoices);

  return (
    <div className="admin">
      <div className="card admin-card">
        <span className="eyebrow">Rating sources</span>
        <div className="admin-sources">
          {data.sources.map((s) => (
            <div key={s.name} className={`admin-row${s.stale ? ' admin-stale' : ''}`}>
              <div className="admin-row-main">
                <span className="admin-name">{s.name}</span>
                <span className="admin-status">
                  {s.last_ok == null
                    ? 'Never succeeded'
                    : `Last successful fetch: ${formatAgo(s.age_s ?? 0)}`}
                  {' '}(limit {formatLimit(s.max_age_s)})
                </span>
              </div>
              {s.last_error && (
                <div className="admin-error">
                  Last error{s.last_error_at == null
                    ? ''
                    : ` (${formatAgo((Date.now() / 1000) - s.last_error_at)})`}: {s.last_error}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className="card admin-card">
        <span className="eyebrow">Background jobs</span>
        <div className="admin-jobs">
          {data.jobs.map((j) => (
            <div key={j.name} className="admin-row">
              <div className="admin-row-main">
                <span className="admin-name">{j.name}</span>
                <span className="admin-status">
                  {j.at == null ? 'Never run' : `Last run: ${formatAgo((Date.now() / 1000) - j.at)}`}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
      {model && <ModelSection m={model} chartVoices={chartVoices} colors={colors} />}
      {history && <HistorySection h={history} myName={myName} chartVoices={chartVoices} colors={colors} />}
    </div>
  );
}
