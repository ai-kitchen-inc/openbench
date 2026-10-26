import { ChatPanel, ChatProvider } from "@openbench/chat-ui";
import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { transcribeAudio } from "../api";
import { XIcon } from "../brand/icons";
import { buildChatConfig } from "../chat/config";
import { ErrorBoundary } from "../ErrorBoundary";

const TEST_SUGGESTIONS = [
  "Ringkas cakupan seluruh sumber",
  "Tanyakan sesuatu yang hanya dijawab oleh sumber",
  "Tanyakan hal di luar sumber untuk menguji penolakan",
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
 * Sits beside the admin pages so settings stay editable while it is open,
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
      aria-label="Uji coba chat"
      style={{ flex: `0 0 ${width}px`, width: `${width}px` }}
    >
      <div
        className="test-chat-dock__resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Ubah lebar uji coba chat"
        tabIndex={0}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onKeyDown={handleKeyDown}
      />
      <div className="drawer__header">
        <div className="drawer__title">Uji Coba Chat</div>
        <button type="button" className="drawer__close" onClick={onClose} aria-label="Tutup">
          <XIcon size={16} />
        </button>
      </div>
      <div className="drawer__body drawer__body--chat">
        <ErrorBoundary region="uji coba chat">
          <ChatProvider config={chatConfig}>
            <ChatPanel
              title="Uji Coba Chat"
              greeting="Uji basis pengetahuan yang telah dikurasi"
              suggestions={TEST_SUGGESTIONS}
              placeholder="Tanyakan persis seperti yang akan ditanyakan pengguna..."
              allowAttachments={false}
              onTranscribe={transcribeAudio}
            />
          </ChatProvider>
        </ErrorBoundary>
      </div>
    </aside>
  );
}
