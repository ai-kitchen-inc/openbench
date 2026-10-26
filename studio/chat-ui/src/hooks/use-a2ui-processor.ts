/**
 * React hook for A2UI message processing.
 *
 * Maintains surface state and triggers re-renders on changes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { A2UIMessageProcessor } from "../core/message-processor";
import type { A2UISurface } from "../types";

export interface UseA2UIProcessorReturn {
  /** The processor instance. */
  processor: A2UIMessageProcessor;
  /** All renderable surfaces (those with a root component). */
  surfaces: A2UISurface[];
  /** Get a specific surface by ID. */
  getSurface: (surfaceId: string) => A2UISurface | undefined;
  /** Process a raw message from the transport. */
  processMessage: (data: Record<string, unknown>) => void;
  /** Reset all processor state. */
  reset: () => void;
}

/**
 * Hook to process A2UI JSONL messages into renderable surfaces.
 */
export function useA2UIProcessor(): UseA2UIProcessorReturn {
  const processorRef = useRef<A2UIMessageProcessor | null>(null);
  const [surfaces, setSurfaces] = useState<A2UISurface[]>([]);

  // Create processor once
  if (!processorRef.current) {
    processorRef.current = new A2UIMessageProcessor();
  }
  const processor = processorRef.current;

  // Listen for surface changes → update React state
  useEffect(() => {
    const unsub = processor.onChange(() => {
      setSurfaces(processor.getRenderableSurfaces());
    });
    return unsub;
  }, [processor]);

  const processMessage = useCallback(
    (data: Record<string, unknown>) => {
      processor.processMessage(data);
    },
    [processor],
  );

  const getSurface = useCallback(
    (surfaceId: string) => processor.getSurface(surfaceId),
    [processor],
  );

  const reset = useCallback(() => {
    processor.reset();
    setSurfaces([]);
  }, [processor]);

  return { processor, surfaces, getSurface, processMessage, reset };
}
