/**
 * StreamContext — isolated state for a single concurrent SSE stream.
 *
 * Each message gets its own:
 * - HttpAgent + RxJS subscription (independent SSE connection)
 * - A2UIMessageProcessor (isolated surface state)
 * - Event handler bound to specific sessionId/messageId
 *
 * No cross-stream contamination — events from stream A never touch stream B.
 */

import { HttpAgent } from "@ag-ui/client";
import type { BaseEvent } from "@ag-ui/core";
import { EventType } from "@ag-ui/core";
import type { ChatMessage } from "../types";
import type { createChatStore } from "./chat-store";
import { A2UIMessageProcessor } from "./message-processor";
import { generateId } from "./utils";

type Store = ReturnType<typeof createChatStore>;

export class StreamContext {
  readonly sessionId: string;
  readonly messageId: string;
  readonly processor: A2UIMessageProcessor;

  private streamUrl: string;
  private store: Store;
  private getAuthToken?: () => Promise<string | null>;
  private subscription: { unsubscribe: () => void } | null = null;
  private _disposed = false;

  constructor(config: {
    sessionId: string;
    messageId: string;
    streamUrl: string;
    store: Store;
    /** Optional async hook that returns the current ID token. */
    getAuthToken?: () => Promise<string | null>;
  }) {
    this.sessionId = config.sessionId;
    this.messageId = config.messageId;
    this.streamUrl = config.streamUrl;
    this.store = config.store;
    this.getAuthToken = config.getAuthToken;
    this.processor = new A2UIMessageProcessor();
  }

  get disposed(): boolean {
    return this._disposed;
  }

  /**
   * Start the SSE stream. Returns a Promise that resolves on completion.
   */
  async start(content: string, attachments?: unknown[]): Promise<void> {
    if (this._disposed) return;

    // Resolve the Authorization header before the SSE connection is
    // opened. Without this, auth-gated backends reject the stream with
    // 401 (seen as "Missing Bearer token in Authorization header").
    const headers: Record<string, string> = {};
    if (this.getAuthToken) {
      try {
        const token = await this.getAuthToken();
        if (token) headers.Authorization = `Bearer ${token}`;
      } catch (err) {
        console.error(`[StreamContext ${this.messageId}] getAuthToken threw:`, err);
      }
    }

    const agent = new HttpAgent({ url: this.streamUrl, headers });
    const input = {
      threadId: this.sessionId,
      runId: generateId(),
      state: {},
      messages: [{ id: generateId(), role: "user" as const, content }],
      tools: [],
      context: [],
      forwardedProps: { sessionId: this.sessionId, attachments },
    };

    return new Promise<void>((resolve, reject) => {
      const events$ = agent.run(input);

      this.subscription = events$.subscribe({
        next: (event: BaseEvent) => {
          if (this._disposed) return;
          this.handleEvent(event);
        },
        error: (err: unknown) => {
          console.error(`[StreamContext ${this.messageId}] Stream error:`, err);
          this.finalizeMessage("error", String(err));
          this.subscription = null;
          reject(err);
        },
        complete: () => {
          this.subscription = null;
          resolve();
        },
      });
    });
  }

  /** Cancel the SSE subscription (keeps processor alive for action responses). */
  cancel(): void {
    this.subscription?.unsubscribe();
    this.subscription = null;
  }

  /** Full cleanup — cancel stream and mark as disposed. */
  dispose(): void {
    this.cancel();
    this.processor.reset();
    this._disposed = true;
  }

  /**
   * Process A2UI action response for this message's surfaces.
   * Works even after the stream has completed (processor stays alive).
   */
  processActionResponse(messages: Record<string, unknown>[]): void {
    if (this._disposed) return;
    for (const msg of messages) {
      try {
        this.processor.processMessage(msg);
      } catch (err) {
        console.error(`[StreamContext ${this.messageId}] Action response error:`, err);
      }
    }
    this.syncSurfaces();
  }

  // ── Internal event handlers ──

  private handleEvent(event: BaseEvent): void {
    try {
      const raw = event as unknown as Record<string, unknown>;
      const eventType = raw.type as string;

      if (eventType === EventType.RUN_STARTED) {
        // Nothing extra — placeholder message already created by sendMessage
        return;
      }

      if (eventType === EventType.STEP_STARTED) {
        const stepName = raw.stepName as string;
        const stepId = generateId();
        this.updateMessage((m) => ({
          ...m,
          steps: [...(m.steps ?? []), { stepId, stepName, status: "active" as const }],
        }));
        return;
      }

      if (eventType === EventType.STEP_FINISHED) {
        this.updateMessage((m) => {
          const activeStep = m.steps?.find((s) => s.status === "active");
          if (!activeStep) return m;
          return {
            ...m,
            steps: (m.steps ?? []).map((s) =>
              s.stepId === activeStep.stepId ? { ...s, status: "complete" as const } : s,
            ),
          };
        });
        return;
      }

      if (eventType === EventType.CUSTOM) {
        if ((raw.name as string) === "a2ui") {
          try {
            this.processor.processMessage(raw.value as Record<string, unknown>);
            this.syncSurfaces();
          } catch (err) {
            console.error(`[StreamContext ${this.messageId}] A2UI error:`, err);
          }
        }
        return;
      }

      if (eventType === EventType.TEXT_MESSAGE_CONTENT) {
        const delta = (raw.delta as string) ?? "";
        this.updateMessage((m) => ({ ...m, content: m.content + delta }));
        return;
      }

      if (eventType === EventType.RUN_FINISHED) {
        const result = raw.result as
          | { content?: string; metadata?: Record<string, unknown> }
          | undefined;
        this.finalizeMessage(
          "complete",
          result?.content,
          result?.metadata as ChatMessage["metadata"],
        );
        return;
      }

      if (eventType === EventType.RUN_ERROR) {
        const errorMessage = (raw.message as string) ?? "An error occurred";
        this.finalizeMessage("error", errorMessage);
        return;
      }
    } catch (err) {
      console.error(`[StreamContext ${this.messageId}] Event handler error:`, err);
    }
  }

  private updateMessage(updater: (msg: ChatMessage) => ChatMessage): void {
    this.store.getState().updateMessageInSession(this.sessionId, this.messageId, updater);
  }

  private syncSurfaces(): void {
    const surfaces = this.processor.getRenderableSurfaces();
    this.updateMessage((m) => ({
      ...m,
      surfaces: surfaces.length > 0 ? [...surfaces] : m.surfaces,
    }));
  }

  private finalizeMessage(
    status: "complete" | "error",
    contentFallback?: string,
    metadata?: ChatMessage["metadata"],
  ): void {
    let surfaces = this.processor.getRenderableSurfaces();
    try {
      surfaces = this.processor.getRenderableSurfaces();
    } catch {
      surfaces = [];
    }

    this.updateMessage((m) => {
      // On error, mirror the backend's aborted-turn placeholder semantics
      // on the in-flight message so the retry button appears immediately —
      // without this, the placeholder only surfaces after a session
      // reload (backend persists a separate placeholder row to storage).
      const mergedMetadata =
        status === "error"
          ? {
              ...(m.metadata ?? {}),
              ...(metadata ?? {}),
              aborted: true as const,
              error: (m.metadata?.error ?? metadata?.error ?? contentFallback ?? "").slice(0, 200),
            }
          : metadata
            ? { ...(m.metadata ?? {}), ...metadata }
            : m.metadata;

      return {
        ...m,
        status,
        metadata: mergedMetadata,
        surfaces: surfaces.length > 0 ? [...surfaces] : m.surfaces,
        content: !m.content && contentFallback ? contentFallback : m.content,
        steps: (m.steps ?? []).map((s) =>
          s.status === "active" ? { ...s, status: "complete" as const } : s,
        ),
      };
    });
  }
}
