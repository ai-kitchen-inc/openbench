/**
 * Transport client for @openbench/chat-ui.
 *
 * Supports two modes:
 * - WebSocket: bidirectional, used for actions and fallback messaging
 * - SSE (via streamUrl): progressive streaming for message responses
 *
 * No React dependency -- usable in any JavaScript environment.
 */

import type { ChatConfig, ClientMessage, ClientPayload, TransportStatus } from "../types";

export type TransportListener = (data: Record<string, unknown>) => void;
export type StatusListener = (status: TransportStatus) => void;

const DEFAULT_RECONNECT_INTERVAL = 3000;
const DEFAULT_MAX_RECONNECT_ATTEMPTS = 5;

export class ChatTransport {
  private ws: WebSocket | null = null;
  private config: ChatConfig;
  private messageListeners: Set<TransportListener> = new Set();
  private statusListeners: Set<StatusListener> = new Set();
  private _status: TransportStatus = "disconnected";
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private sseAbortController: AbortController | null = null;

  constructor(config: ChatConfig) {
    this.config = config;
  }

  /** Whether SSE streaming is configured. */
  get hasSSE(): boolean {
    return !!this.config.streamUrl;
  }

  /** Current connection status. */
  get status(): TransportStatus {
    return this._status;
  }

  /** Connect to the WebSocket server. */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.setStatus("connecting");

    try {
      this.ws = new WebSocket(this.config.wsUrl);
      this.ws.onopen = this.handleOpen;
      this.ws.onmessage = this.handleMessage;
      this.ws.onclose = this.handleClose;
      this.ws.onerror = this.handleError;
    } catch {
      this.setStatus("error");
    }
  }

  /** Disconnect from the server. */
  disconnect(): void {
    this.clearReconnectTimer();
    if (this.ws) {
      this.ws.onclose = null; // Prevent reconnect on intentional close
      this.ws.close();
      this.ws = null;
    }
    this.setStatus("disconnected");
  }

  /** Send a message or action to the server. */
  send(payload: ClientPayload): void {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      console.warn("[ChatTransport] Cannot send: not connected");
      return;
    }
    this.ws.send(JSON.stringify(payload));
  }

  /** Register a listener for incoming messages. */
  onMessage(listener: TransportListener): () => void {
    this.messageListeners.add(listener);
    return () => {
      this.messageListeners.delete(listener);
    };
  }

  /** Register a listener for status changes. */
  onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  /**
   * Send a message via SSE (POST + read event stream).
   *
   * Each SSE event is dispatched to message listeners progressively,
   * enabling real-time step indicators and surface rendering.
   */
  async streamViaSSE(payload: ClientMessage): Promise<void> {
    const url = this.config.streamUrl;
    if (!url) {
      console.warn("[ChatTransport] streamUrl not configured, falling back to WebSocket");
      this.send(payload);
      return;
    }

    // Abort any in-flight SSE stream
    this.sseAbortController?.abort();

    const controller = new AbortController();
    this.sseAbortController = controller;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`SSE request failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? ""; // Keep incomplete last chunk

        for (const event of events) {
          const line = event.trim();
          if (!line.startsWith("data: ")) continue;

          const json = line.slice(6);
          try {
            const data = JSON.parse(json) as Record<string, unknown>;
            for (const listener of this.messageListeners) {
              listener(data);
            }
          } catch {
            // Skip malformed JSON
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return; // Intentional abort
      console.error("[ChatTransport] SSE stream error:", err);
    } finally {
      if (this.sseAbortController === controller) {
        this.sseAbortController = null;
      }
    }
  }

  /** Remove all listeners and disconnect. */
  dispose(): void {
    this.sseAbortController?.abort();
    this.disconnect();
    this.messageListeners.clear();
    this.statusListeners.clear();
  }

  // ── Internal handlers ──

  private handleOpen = (): void => {
    this.reconnectAttempts = 0;
    this.setStatus("connected");
  };

  private handleMessage = (event: MessageEvent): void => {
    try {
      const data = JSON.parse(event.data as string) as Record<string, unknown>;
      for (const listener of this.messageListeners) {
        listener(data);
      }
    } catch (err) {
      console.error("[ChatTransport] Failed to parse message:", err);
    }
  };

  private handleClose = (): void => {
    this.ws = null;
    this.setStatus("disconnected");
    this.attemptReconnect();
  };

  private handleError = (): void => {
    this.setStatus("error");
  };

  private setStatus(status: TransportStatus): void {
    this._status = status;
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }

  private attemptReconnect(): void {
    if (this.config.reconnect === false) return;

    const maxAttempts = this.config.maxReconnectAttempts ?? DEFAULT_MAX_RECONNECT_ATTEMPTS;
    if (this.reconnectAttempts >= maxAttempts) {
      this.setStatus("error");
      return;
    }

    const interval = this.config.reconnectInterval ?? DEFAULT_RECONNECT_INTERVAL;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this.connect();
    }, interval);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
