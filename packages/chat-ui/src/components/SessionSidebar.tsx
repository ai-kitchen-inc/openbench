/**
 * SessionSidebar — session list with create, switch, delete, and rename.
 */

import { useRef, useState } from "react";
import { formatRelativeTime } from "../core/utils";
import type { ChatSession } from "../types";
import { useChatContext } from "./ChatProvider";

export interface SessionSidebarProps {
  /** Additional CSS class. */
  className?: string;
}

export function SessionSidebar({ className = "" }: SessionSidebarProps) {
  const {
    sessions,
    activeSessionId,
    createSession,
    switchSession,
    deleteSession,
    renameSession,
    sidebarOpen,
    setSidebarOpen,
  } = useChatContext();

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  // Ref to distinguish cancel (Escape) from normal blur
  const cancelledRef = useRef(false);

  if (!sidebarOpen) return null;

  const startEditing = (session: ChatSession) => {
    cancelledRef.current = false;
    setEditingId(session.id);
    setEditValue(session.title);
  };

  const commitRename = (id: string, value: string) => {
    const trimmed = value.trim();
    if (trimmed) {
      renameSession(id, trimmed);
    }
    setEditingId(null);
    setEditValue("");
  };

  const cancelEditing = () => {
    cancelledRef.current = true;
    setEditingId(null);
    setEditValue("");
  };

  const handleBlur = (sessionId: string) => {
    // Skip if Escape was pressed (cancelEditing already ran)
    if (cancelledRef.current) {
      cancelledRef.current = false;
      return;
    }
    commitRename(sessionId, editValue);
  };

  // Group sessions by date
  const grouped = groupSessionsByDate(sessions);

  return (
    <aside className={`chat-sidebar ${className}`}>
      <div className="chat-sidebar__header">
        <h3 className="chat-sidebar__title">Chats</h3>
        <div className="chat-sidebar__actions">
          <button
            className="chat-sidebar__new-btn"
            onClick={createSession}
            type="button"
            aria-label="New chat"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="12" y1="5" x2="12" y2="19" />
              <line x1="5" y1="12" x2="19" y2="12" />
            </svg>
            New
          </button>
          <button
            className="chat-sidebar__close-btn"
            onClick={() => setSidebarOpen(false)}
            type="button"
            aria-label="Close sidebar"
          >
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      <div className="chat-sidebar__list">
        {grouped.map(({ label, sessions: groupSessions }) => (
          <div key={label} className="chat-sidebar__group">
            <div className="chat-sidebar__group-label">{label}</div>
            {groupSessions.map((session) => (
              <div
                key={session.id}
                className={`chat-sidebar__item ${
                  session.id === activeSessionId ? "chat-sidebar__item--active" : ""
                }`}
              >
                {editingId === session.id ? (
                  <div className="chat-sidebar__item-edit">
                    <input
                      className="chat-sidebar__item-input"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onBlur={() => handleBlur(session.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          commitRename(session.id, editValue);
                        } else if (e.key === "Escape") {
                          e.preventDefault();
                          cancelEditing();
                        }
                      }}
                      ref={(el: HTMLInputElement | null) => el?.focus()}
                      aria-label="Rename session"
                    />
                  </div>
                ) : (
                  <button
                    className="chat-sidebar__item-btn"
                    onClick={() => switchSession(session.id)}
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      e.preventDefault();
                      startEditing(session);
                    }}
                    type="button"
                  >
                    <span className="chat-sidebar__item-title">{session.title}</span>
                    <span className="chat-sidebar__item-time">
                      {formatRelativeTime(session.updatedAt)}
                    </span>
                  </button>
                )}
                <button
                  className="chat-sidebar__item-delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    deleteSession(session.id);
                  }}
                  type="button"
                  aria-label={`Delete ${session.title}`}
                >
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  );
}

// ── Helpers ──

interface SessionGroup {
  label: string;
  sessions: ChatSession[];
}

function groupSessionsByDate(sessions: ChatSession[]): SessionGroup[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const groups: Record<string, ChatSession[]> = {
    Today: [],
    Yesterday: [],
    "This Week": [],
    Older: [],
  };

  for (const session of sessions) {
    const date = new Date(session.updatedAt);
    if (date >= today) {
      groups.Today?.push(session);
    } else if (date >= yesterday) {
      groups.Yesterday?.push(session);
    } else if (date >= weekAgo) {
      groups["This Week"]?.push(session);
    } else {
      groups.Older?.push(session);
    }
  }

  return Object.entries(groups)
    .filter(([, sessions]) => sessions.length > 0)
    .map(([label, sessions]) => ({ label, sessions }));
}
