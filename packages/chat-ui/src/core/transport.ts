/**
 * SSE + REST transport for @openbench/chat-ui.
 *
 * - stream(): POST → SSE (progressive message streaming)
 * - sendAction(): POST → JSON (button clicks, form submits)
 *
 * No persistent connection. No reconnect logic.
 */

import type {
  Attachment,
  ChatConfig,
  ClientAction,
  ClientMessage,
  TransportStatus,
} from "../types";

export type TransportListener = (data: Record<string, unknown>) => void;
export type StatusListener = (status: TransportStatus) => void;

export class ChatTransport {
  private config: ChatConfig;
  private messageListeners: Set<TransportListener> = new Set();
  private statusListeners: Set<StatusListener> = new Set();
  private _status: TransportStatus = "disconnected";
  private abortController: AbortController | null = null;

  constructor(config: ChatConfig) {
    this.config = config;
  }

  /** Current transport status. */
  get status(): TransportStatus {
    return this._status;
  }

  /**
   * Send a message via SSE (POST + read event stream).
   *
   * Each SSE event is dispatched to message listeners progressively,
   * enabling real-time step indicators and surface rendering.
   */
  async stream(payload: ClientMessage): Promise<void> {
    // Abort any in-flight stream
    this.abortController?.abort();

    const controller = new AbortController();
    this.abortController = controller;

    try {
      const response = await fetch(this.config.streamUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`SSE request failed: ${response.status}`);
      }

      this.setStatus("connected");

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
      this.setStatus("error");
    } finally {
      if (this.abortController === controller) {
        this.abortController = null;
      }
    }
  }

  /**
   * Send an action via REST (POST → JSON).
   *
   * Response messages are dispatched through the same messageListeners
   * as SSE events for consistent processing.
   */
  async sendAction(payload: ClientAction): Promise<void> {
    const url = this.config.actionUrl ?? "/chat/action";

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Action request failed: ${response.status}`);
      }

      this.setStatus("connected");

      const messages = (await response.json()) as Record<string, unknown>[];
      for (const msg of messages) {
        for (const listener of this.messageListeners) {
          listener(msg);
        }
      }
    } catch (err) {
      console.error("[ChatTransport] Action error:", err);
      this.setStatus("error");
    }
  }

  /**
   * Upload a file to the server.
   *
   * Posts the file as multipart/form-data and returns
   * the server's Attachment response (with server URL and extracted text).
   */
  async upload(file: File): Promise<Attachment> {
    const url = this.config.uploadUrl ?? "/chat/upload";
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(url, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.status}`);
    }

    return (await response.json()) as Attachment;
  }

  /** Abort any in-flight SSE stream. */
  abort(): void {
    this.abortController?.abort();
    this.abortController = null;
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

  /** Remove all listeners and abort in-flight requests. */
  dispose(): void {
    this.abort();
    this.setStatus("disconnected");
    this.messageListeners.clear();
    this.statusListeners.clear();
  }

  // ── Internal ──

  private setStatus(status: TransportStatus): void {
    if (this._status === status) return;
    this._status = status;
    for (const listener of this.statusListeners) {
      listener(status);
    }
  }
}
