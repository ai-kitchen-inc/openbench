/**
 * Bounded-concurrency task runner for attachment uploads.
 *
 * `Promise.all` over N uploads has two problems when N is large: it fires
 * every request at once, and a single rejection discards the settled
 * results of every other file. Sending a batch of files should degrade
 * per-file, not fail as a unit.
 *
 * `runWithConcurrency` caps how many run at a time and preserves input
 * order in the result array. It never rejects as long as `fn` doesn't —
 * callers are expected to return an outcome object rather than throw.
 */
export async function runWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  const results = new Array<R>(items.length);
  if (items.length === 0) return results;

  const max = Math.max(1, Math.min(limit, items.length));
  let next = 0;

  const worker = async (): Promise<void> => {
    while (next < items.length) {
      const index = next++;
      results[index] = await fn(items[index] as T, index);
    }
  };

  await Promise.all(Array.from({ length: max }, worker));
  return results;
}
