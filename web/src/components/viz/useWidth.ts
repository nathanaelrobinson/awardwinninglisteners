// web/src/components/viz/useWidth.ts
import { useEffect, useRef, useState } from 'react';

/** Chart geometry is in real pixels, not a scaled viewBox: a plot that
 *  stretches with its container stops being countable. */
export function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}
