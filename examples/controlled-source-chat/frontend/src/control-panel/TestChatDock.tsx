import { ChatPanel, ChatProvider } from "@openbench/chat-ui";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { transcribeAudio } from "../api";
import { buildChatConfig } from "../chat/config";
import { ErrorBoundary } from "../ErrorBoundary";

const TEST_SUGGESTIONS = [
  "Summarize what the sources cover",
  "Ask something only a source can answer",
  "Ask something off-source to verify the refusal",
];

const MIN_WIDTH = 320;
const MAX_WIDTH = 760;
const DEFAULT_WIDTH = 460;
const KEYBOARD_STEP = 24;
const WIDTH_STORAGE_KEY = "controlled-chat-dock-width";

function clampWidth(value: number): number {
  return Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, value));
}

function loadWidth(): number {
  try {
    const stored = Number(window.localStorage.getItem(WIDTH_STORAGE_KEY));
    if (Number.isFinite(stored) && stored > 0) return clampWidth(stored);
  } catch {
    // Storage unavailable (private mode) — fall back to the default.
  }
  return DEFAULT_WIDTH;
}

/** In-flow docked panel (not a modal) where the admin talks to the exact chat
 * guests get — same curated grounding, same disabled composer attachments.
 * Sits beside the control panel so settings stay editable while it is open,
 * and its width is drag-resizable (persisted per browser). */
export function TestChatDock({ onClose }: { onClose: () => void }) {
  const chatConfig = useMemo(buildChatConfig, []);
  const [width, setWidth] = useState(loadWidth);
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  useEffect(() => {
    try {
      window.localStorage.setItem(WIDTH_STORAGE_KEY, String(width));
    } catch {
      // Ignore — resizing still works for the session without persistence.
    }
  }, [width]);

  const handlePointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = { startX: event.clientX, startWidth: width };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const handlePointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    // The handle is on the dock's left edge, so dragging left widens it.
    setWidth(clampWidth(drag.startWidth - (event.clientX - drag.startX)));
  };

  const handlePointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setWidth((current) => clampWidth(current + KEYBOARD_STEP));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setWidth((current) => clampWidth(current - KEYBOARD_STEP));
    }
  };

  return (
    <aside
      className="test-chat-dock"
      aria-label="Test chat"
      style={{ flex: `0 0 ${width}px`, width: `${width}px` }}
    >
      <div
        className="test-chat-dock__resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize test chat"
        tabIndex={0}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onKeyDown={handleKeyDown}
      />
      <div className="drawer__header">
        <div className="drawer__title">Test chat</div>
        <button type="button" className="drawer__close" onClick={onClose} aria-label="Close">
          <svg
            aria-hidden="true"
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      </div>
      <div className="drawer__body drawer__body--chat">
        <ErrorBoundary region="the test chat">
          <ChatProvider config={chatConfig}>
            <ChatPanel
              title="Test chat"
              greeting="Test the curated knowledge base"
              suggestions={TEST_SUGGESTIONS}
              placeholder="Ask exactly what a user would ask..."
              allowAttachments={false}
              onTranscribe={transcribeAudio}
            />
          </ChatProvider>
        </ErrorBoundary>
      </div>
    </aside>
  );
}
