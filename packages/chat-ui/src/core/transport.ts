/**
 * AG-UI protocol transport for @openbench/chat-ui.
 *
 * Uses HttpAgent from @ag-ui/client for SSE streaming with AG-UI events.
 * A2UI messages are wrapped inside CustomEvent(name="a2ui") payloads.
 *
 * - run(): POST → SSE (AG-UI event stream)
 * - sendAction(): POST → JSON (A2UI button clicks, form submits)
 * - upload(): POST → multipart (file uploads)
 */

import { HttpAgent } from "@ag-ui/client";
import type { BaseEvent } from "@ag-ui/core";
import type { Attachment, ChatConfig, TransportStatus } from "../types";
import { generateId } from "./utils";

export type AGUIEventListener = (event: BaseEvent) => void;
export type StatusListener = (status: TransportStatus) => void;

export class AGUITransport {
  private config: ChatConfig;
  private eventListeners: Set<AGUIEventListener> = new Set();
  private statusListeners: Set<StatusListener> = new Set();
  private _status: TransportStatus = "disconnected";
  private activeSub: { unsubscribe: () => void } | null = null;

  constructor(config: ChatConfig) {
    this.config = config;
  }

  /** Current transport status. */
  get status(): TransportStatus {
    return this._status;
  }

  /**
   * Send a message via AG-UI SSE stream.
   *
   * Creates an HttpAgent, constructs a RunAgentInput, and subscribes
   * to the Observable for AG-UI events. Events are dispatched to
   * registered listeners progressively.
   */
  async run(content: string, sessionId?: string, attachments?: Attachment[]): Promise<void> {
    // Cancel any in-flight stream
    this.cancel();

    // Create a fresh HttpAgent per request to avoid state accumulation
    const agent = new HttpAgent({ url: this.config.streamUrl });

    const input = {
      threadId: sessionId || generateId(),
      runId: generateId(),
      state: {},
      messages: [{ id: generateId(), role: "user" as const, content }],
      tools: [],
      context: [],
      forwardedProps: { sessionId, attachments },
    };

    return new Promise<void>((resolve, reject) => {
      const events$ = agent.run(input);

      this.activeSub = events$.subscribe({
        next: (event: BaseEvent) => {
          this.setStatus("connected");
          for (const listener of this.eventListeners) {
            listener(event);
          }
        },
        error: (err: unknown) => {
          console.error("[AGUITransport] Stream error:", err);
          this.setStatus("error");
          this.activeSub = null;
          reject(err);
        },
        complete: () => {
          this.activeSub = null;
          resolve();
        },
      });
    });
  }

  /**
   * Send an A2UI action via REST (POST → JSON).
   *
   * AG-UI does not define an action mechanism, so this remains
   * a standard REST POST. Response messages are dispatched through
   * the same event listeners.
   */
  async sendAction(payload: {
    name: string;
    surfaceId: string;
    sourceComponentId: string;
    timestamp: string;
    context: Record<string, unknown>;
  }): Promise<void> {
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

      // Response is A2UI messages array — wrap each as a CustomEvent-like object
      const messages = (await response.json()) as Record<string, unknown>[];
      for (const msg of messages) {
        const event = { type: "CUSTOM", name: "a2ui", value: msg } as unknown as BaseEvent;
        for (const listener of this.eventListeners) {
          listener(event);
        }
      }
    } catch (err) {
      console.error("[AGUITransport] Action error:", err);
      this.setStatus("error");
    }
  }

  /**
   * Upload a file to the server.
   *
   * Posts the file as multipart/form-data and returns
   * the server's Attachment response.
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

  /** Cancel any in-flight AG-UI stream. */
  cancel(): void {
    this.activeSub?.unsubscribe();
    this.activeSub = null;
  }

  /** Register a listener for incoming AG-UI events. */
  onEvent(listener: AGUIEventListener): () => void {
    this.eventListeners.add(listener);
    return () => {
      this.eventListeners.delete(listener);
    };
  }

  /** Register a listener for status changes. */
  onStatusChange(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  /** Remove all listeners and cancel in-flight streams. */
  dispose(): void {
    this.cancel();
    this.setStatus("disconnected");
    this.eventListeners.clear();
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
