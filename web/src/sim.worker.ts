// web/src/sim.worker.ts
//
// Rolling a hundred thousand seasons takes long enough to freeze a tab, and a
// frozen tab reads as broken. Do it here instead: the page stays live, shows
// progress, and the finished arrays come back as transfers rather than copies.
import { rollAll } from './sim';
import type { Rolled, SimModel } from './sim';

export interface RollRequest {
  id: number;
  model: SimModel;
  nSims: number;
  seed: number;
}
export type RollResponse =
  | { id: number; type: 'progress'; done: number }
  | { id: number; type: 'done'; rolled: Rolled }
  | { id: number; type: 'error'; message: string };

const post = (msg: RollResponse, transfer?: Transferable[]) =>
  (self as unknown as Worker).postMessage(msg, transfer ?? []);

self.onmessage = (e: MessageEvent<RollRequest>) => {
  const { id, model, nSims, seed } = e.data;
  try {
    const rolled = rollAll(model, nSims, seed, (done) =>
      post({ id, type: 'progress', done }));
    // hand the buffers over rather than cloning ~20 MB of them
    const transfer: Transferable[] = [
      ...rolled.paths.map((p) => p.buffer),
      rolled.winner.buffer, rolled.source.buffer,
    ];
    post({ id, type: 'done', rolled }, transfer);
  } catch (err) {
    post({ id, type: 'error', message: err instanceof Error ? err.message : String(err) });
  }
};
