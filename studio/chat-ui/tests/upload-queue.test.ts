/**
 * Tests for the bounded-concurrency upload runner.
 *
 * Sending several files previously used `Promise.all`: every upload fired
 * at once, and a single rejection discarded the files that had already
 * succeeded, leaving the assistant bubble spinning forever.
 */

import { describe, expect, it } from "vitest";
import { runWithConcurrency } from "../src/core/upload-queue";

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("runWithConcurrency", () => {
  it("preserves input order regardless of completion order", async () => {
    const items = [30, 10, 20];
    const results = await runWithConcurrency(items, 3, async (ms) => {
      await new Promise((resolve) => setTimeout(resolve, ms));
      return ms;
    });
    expect(results).toEqual([30, 10, 20]);
  });

  it("never exceeds the concurrency limit", async () => {
    let active = 0;
    let peak = 0;
    await runWithConcurrency(Array.from({ length: 10 }, (_, i) => i), 3, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await tick();
      active -= 1;
      return null;
    });
    expect(peak).toBeLessThanOrEqual(3);
  });

  it("keeps going after one item fails", async () => {
    const results = await runWithConcurrency([1, 2, 3], 2, async (n) => {
      if (n === 2) {
        try {
          throw new Error("boom");
        } catch {
          return null;
        }
      }
      return n;
    });
    expect(results).toEqual([1, null, 3]);
  });

  it("returns an empty array for no items", async () => {
    expect(await runWithConcurrency([], 3, async () => 1)).toEqual([]);
  });

  it("clamps a limit larger than the item count", async () => {
    let peak = 0;
    let active = 0;
    await runWithConcurrency([1, 2], 99, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await tick();
      active -= 1;
      return null;
    });
    expect(peak).toBeLessThanOrEqual(2);
  });
});
