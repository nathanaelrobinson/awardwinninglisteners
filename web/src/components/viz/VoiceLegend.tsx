// web/src/components/viz/VoiceLegend.tsx
import { OVERFLOW_COLOR } from './palette';

/** The colour key. It repeats above every chart rather than sitting once at
 *  the top of the tab, because the charts are now spread down the page beside
 *  the tables they explain, and a key three cards away is no key at all. */
export default function VoiceLegend(
  { voices, colors, refName }: { voices: string[]; colors: Record<string, string>; refName: string },
) {
  return (
    <div className="viz-legend">
      {voices.map((v) => (
        <span key={v} className="viz-leg">
          <span className="viz-swatch" style={{ background: colors[v] }} />
          {v}{colors[v] === OVERFLOW_COLOR ? ' (no colour slot left)' : ''}
        </span>
      ))}
      <span className="viz-leg">
        <span className="viz-swatch viz-swatch-ring" />
        {refName}
      </span>
    </div>
  );
}
