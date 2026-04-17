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
import type {
  Attachment,
  ChatConfig,
  ChatMessage,
  ChatSession,
  SessionSummary,
  TransportStatus,
} from "../types";
import { generateId } from "./utils";

/** Raw shape returned by the Python ChatSession.to_dict(). */
interface WireChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  timestamp: string;
  surfaces?: ChatMessage["surfaces"];
  attachments?: ChatMessage["attachments"];
  metadata?: ChatMessage["metadata"];
}

interface WireChatSession {
  sessionId: string;
  title: string;
  messages: WireChatMessage[];
  createdAt: string;
  updatedAt: string;
}

function wireToChatSession(raw: WireChatSession): ChatSession {
  return {
    id: raw.sessionId,
    title: raw.title,
    createdAt: raw.createdAt,
    updatedAt: raw.updatedAt,
    messages: raw.messages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
      surfaces: m.surfaces,
      attachments: m.attachments,
      metadata: m.metadata,
      status: "complete" as const,
    })),
  };
}

export type AGUIEventListener = (event: BaseEvent) => void;
export type StatusListener = (status: TransportStatus) => void;

export class AGUITransport {
  private config: ChatConfig;
  private eventListeners: Set<AGUIEventListener> = new Set();
  private statusListeners: Set<StatusListener> = new Set();
  private _status: TransportStatus = "disconnected";
  private activeSub: { unsubscribe: () => void } | null = null;
  private runGeneration = 0;

  constructor(config: ChatConfig) {
    this.config = config;
  }

  /**
   * Resolve the Authorization header from the configured getAuthToken
   * hook, if any. Returns an empty object when no hook is wired or the
   * hook returns null — callers merge it into their headers map.
   */
  private async _authHeaders(): Promise<Record<string, string>> {
    if (!this.config.getAuthToken) return {};
    try {
      const token = await this.config.getAuthToken();
      if (!token) return {};
      return { Authorization: `Bearer ${token}` };
    } catch (err) {
      console.error("[AGUITransport] getAuthToken threw:", err);
      return {};
    }
  }

  /** Current transport status. */
  get status(): TransportStatus {
    return this._status;
  }

  /** Stream URL from config. */
  get streamUrl(): string {
    return this.config.streamUrl;
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

    // Increment generation so late events from the canceled stream are ignored
    this.runGeneration++;
    const currentGen = this.runGeneration;

    // Create a fresh HttpAgent per request to avoid state accumulation
    const authHeaders = await this._authHeaders();
    const agent = new HttpAgent({
      url: this.config.streamUrl,
      headers: authHeaders,
    });

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
          // Reject late events from a canceled stream
          if (this.runGeneration !== currentGen) return;
          this.setStatus("connected");
          for (const listener of this.eventListeners) {
            try {
              listener(event);
            } catch (err) {
              console.error("[AGUITransport] Listener error:", err);
            }
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
    dataModel?: Record<string, unknown>;
    threadId?: string;
  }): Promise<Record<string, unknown>[]> {
    const url = this.config.actionUrl ?? "/chat/action";

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(await this._authHeaders()),
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Action request failed: ${response.status}`);
      }

      this.setStatus("connected");

      // Return raw A2UI messages for the caller to route via StreamManager
      const messages = (await response.json()) as Record<string, unknown>[];

      // Also dispatch to shared listeners for backward compatibility
      for (const msg of messages) {
        const event = { type: "CUSTOM", name: "a2ui", value: msg } as unknown as BaseEvent;
        for (const listener of this.eventListeners) {
          try {
            listener(event);
          } catch (err) {
            console.error("[AGUITransport] Listener error:", err);
          }
        }
      }

      return messages;
    } catch (err) {
      console.error("[AGUITransport] Action error:", err);
      this.setStatus("error");
      throw err;
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
      headers: { ...(await this._authHeaders()) },
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.status}`);
    }

    return (await response.json()) as Attachment;
  }

  /**
   * List persisted chat sessions from the backend.
   *
   * Returns an empty array if the server returns a 404 / 501, so the
   * sidebar gracefully degrades when the backend has no session store.
   */
  async listSessions(limit = 50, offset = 0): Promise<SessionSummary[]> {
    const base = this.config.sessionsUrl ?? "/sessions";
    const url = `${base}?limit=${limit}&offset=${offset}`;
    try {
      const response = await fetch(url, {
        method: "GET",
        headers: { ...(await this._authHeaders()) },
      });
      if (response.status === 404 || response.status === 501) return [];
      if (!response.ok) throw new Error(`listSessions failed: ${response.status}`);
      return (await response.json()) as SessionSummary[];
    } catch (err) {
      console.error("[AGUITransport] listSessions error:", err);
      return [];
    }
  }

  /**
   * Load a persisted session by id.
   *
   * Returns null on 404 (unknown session) or if the backend has no
   * session store configured. Throws on unexpected errors.
   */
  async loadSession(sessionId: string): Promise<ChatSession | null> {
    const base = this.config.sessionsUrl ?? "/sessions";
    const url = `${base}/${encodeURIComponent(sessionId)}`;
    const response = await fetch(url, {
      method: "GET",
      headers: { ...(await this._authHeaders()) },
    });
    if (response.status === 404 || response.status === 501) return null;
    if (!response.ok) throw new Error(`loadSession failed: ${response.status}`);
    const raw = (await response.json()) as WireChatSession;
    return wireToChatSession(raw);
  }

  /**
   * Delete a persisted session by id.
   *
   * Idempotent: a 404 from the server is treated as success. Other
   * error statuses throw.
   */
  async deleteSession(sessionId: string): Promise<void> {
    const base = this.config.sessionsUrl ?? "/sessions";
    const url = `${base}/${encodeURIComponent(sessionId)}`;
    const response = await fetch(url, {
      method: "DELETE",
      headers: { ...(await this._authHeaders()) },
    });
    if (response.status === 404 || response.status === 501) return;
    if (!response.ok) throw new Error(`deleteSession failed: ${response.status}`);
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
