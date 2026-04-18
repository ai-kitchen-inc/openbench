/**
 * StreamManager — orchestrates multiple concurrent SSE streams.
 *
 * Each sendMessage creates a new StreamContext with independent:
 * - HttpAgent subscription (parallel SSE connections)
 * - A2UIMessageProcessor (isolated surface state)
 *
 * Enforces max concurrent streams (default: 3, FIFO cancel on overflow).
 * Keeps processors alive after stream completes for A2UI action responses.
 */

import type { Attachment } from "../types";
import type { createChatStore } from "./chat-store";
import { StreamContext } from "./stream-context";

type Store = ReturnType<typeof createChatStore>;

export interface StreamManagerConfig {
  streamUrl: string;
  store: Store;
  maxConcurrent?: number;
  /** Optional async hook that returns the current ID token. */
  getAuthToken?: () => Promise<string | null>;
}

export class StreamManager {
  private streamUrl: string;
  private store: Store;
  private maxConcurrent: number;
  private getAuthToken?: () => Promise<string | null>;

  /** Active streams (currently receiving SSE events). */
  private activeStreams: Map<string, StreamContext> = new Map();

  /** Processors kept alive for action responses (even after stream completes). */
  private processors: Map<string, StreamContext> = new Map();

  /** Last message sent — used for auto-scroll targeting. */
  private _lastSentMessageId: string | null = null;

  constructor(config: StreamManagerConfig) {
    this.streamUrl = config.streamUrl;
    this.store = config.store;
    this.maxConcurrent = config.maxConcurrent ?? 3;
    this.getAuthToken = config.getAuthToken;
  }

  get lastSentMessageId(): string | null {
    return this._lastSentMessageId;
  }

  get activeCount(): number {
    return this.activeStreams.size;
  }

  /**
   * Start a new parallel stream for the given message.
   *
   * If max concurrent streams reached, the oldest stream is auto-cancelled
   * (FIFO) and its message is finalized as "complete".
   */
  async startStream(
    sessionId: string,
    messageId: string,
    content: string,
    attachments?: Attachment[],
  ): Promise<void> {
    // Enforce max concurrent — cancel oldest if over limit
    if (this.activeStreams.size >= this.maxConcurrent) {
      const oldest = this.activeStreams.keys().next().value as string;
      this.cancelStream(oldest);
    }

    const context = new StreamContext({
      sessionId,
      messageId,
      streamUrl: this.streamUrl,
      store: this.store,
      getAuthToken: this.getAuthToken,
    });

    this.activeStreams.set(messageId, context);
    this.processors.set(messageId, context);
    this._lastSentMessageId = messageId;

    // Update store streaming state
    this.store.getState().startStreaming(sessionId, messageId);

    try {
      await context.start(content, attachments);
    } catch (err) {
      console.error(`[StreamManager] Stream error for ${messageId}:`, err);
    } finally {
      // Stream finished (success or error) — remove from active set
      this.activeStreams.delete(messageId);
      this.store.getState().stopStreaming(messageId);
    }
  }

  /**
   * Cancel a specific stream. The message is finalized as "complete".
   */
  cancelStream(messageId: string): void {
    const context = this.activeStreams.get(messageId);
    if (!context) return;

    // Finalize the message
    this.store.getState().updateMessageInSession(context.sessionId, messageId, (m) =>
      m.status === "streaming"
        ? {
            ...m,
            status: "complete" as const,
            steps: (m.steps ?? []).map((s) =>
              s.status === "active" ? { ...s, status: "complete" as const } : s,
            ),
          }
        : m,
    );

    context.cancel();
    this.activeStreams.delete(messageId);
    this.store.getState().stopStreaming(messageId);
  }

  /** Cancel all active streams (e.g., on component unmount). */
  cancelAll(): void {
    for (const messageId of [...this.activeStreams.keys()]) {
      this.cancelStream(messageId);
    }
  }

  /**
   * Process an A2UI action response for a specific surface.
   * Routes to the correct processor by finding which message owns the surface.
   */
  processActionResponse(surfaceId: string, messages: Record<string, unknown>[]): void {
    for (const ctx of this.processors.values()) {
      if (ctx.processor.getSurface(surfaceId)) {
        ctx.processActionResponse(messages);
        return;
      }
    }
    console.warn(`[StreamManager] No processor found for surface: ${surfaceId}`);
  }

  /** Check if a specific message is currently streaming. */
  isMessageStreaming(messageId: string): boolean {
    return this.activeStreams.has(messageId);
  }

  /** Clean up processor for a deleted message. */
  removeProcessor(messageId: string): void {
    const ctx = this.processors.get(messageId);
    if (ctx) {
      ctx.dispose();
      this.processors.delete(messageId);
    }
  }

  /** Dispose everything — cancel all streams and clean up all processors. */
  dispose(): void {
    this.cancelAll();
    for (const ctx of this.processors.values()) {
      ctx.dispose();
    }
    this.processors.clear();
  }
}
