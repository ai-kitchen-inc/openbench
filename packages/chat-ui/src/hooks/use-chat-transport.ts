/**
 * React hook for WebSocket transport lifecycle.
 *
 * Manages connection, disconnection, and status tracking.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatTransport } from "../core/transport";
import type { TransportListener } from "../core/transport";
import type { ChatConfig, TransportStatus } from "../types";

export interface UseChatTransportReturn {
  /** Current connection status. */
  status: TransportStatus;
  /** The underlying transport instance. */
  transport: ChatTransport;
  /** Manually connect. */
  connect: () => void;
  /** Manually disconnect. */
  disconnect: () => void;
}

/**
 * Hook to manage a WebSocket transport connection.
 *
 * Automatically connects on mount and disconnects on unmount.
 * Provides status tracking and message listener registration.
 */
export function useChatTransport(
  config: ChatConfig,
  onMessage?: TransportListener,
): UseChatTransportReturn {
  const transportRef = useRef<ChatTransport | null>(null);
  const [status, setStatus] = useState<TransportStatus>("disconnected");

  // Create transport once (stable across renders)
  if (!transportRef.current) {
    transportRef.current = new ChatTransport(config);
  }
  const transport = transportRef.current;

  // Track status changes
  useEffect(() => {
    const unsub = transport.onStatusChange(setStatus);
    return unsub;
  }, [transport]);

  // Register message listener
  useEffect(() => {
    if (!onMessage) return;
    const unsub = transport.onMessage(onMessage);
    return unsub;
  }, [transport, onMessage]);

  // Auto-connect on mount, disconnect on unmount
  useEffect(() => {
    transport.connect();
    return () => {
      transport.dispose();
      transportRef.current = null;
    };
  }, [transport]);

  const connect = useCallback(() => transport.connect(), [transport]);
  const disconnect = useCallback(() => transport.disconnect(), [transport]);

  return { status, transport, connect, disconnect };
}
