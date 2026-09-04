/** ChatGPT-style agent dropdown rendered beside the composer. Replaces
 * the old settings-modal picker: selection is per-session
 * (session.metadata.agentId), "auto" routes each message. */

import { useChatContext } from "@openbench/chat-ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../Toast";
import { readErrorMessage } from "../shared/apiHelpers";
import {
  getAgentSelection,
  listChatAgents,
  putAgentSelection,
  type ChatAgentItem,
} from "./agentsApi";

const AUTO_OPTION: ChatAgentItem = {
  id: "auto",
  name: "Otomatis",
  description: "Sistem memilihkan agen terbaik untuk setiap pesan.",
};

const DEFAULT_OPTION: ChatAgentItem = {
  id: "",
  name: "Asisten bawaan",
  description: "Asisten umum tanpa spesialisasi.",
};

export function AgentSelect({
  enabled = true,
  direction = "down",
}: {
  enabled?: boolean;
  /** "up" opens the menu above the trigger (composer placement). */
  direction?: "down" | "up";
}) {
  const { activeSessionId } = useChatContext();
  const toast = useToast();
  const [agents, setAgents] = useState<ChatAgentItem[]>([]);
  const [selection, setSelection] = useState("auto");
  const [isOpen, setIsOpen] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  // A choice made before the first message is applied once a session exists.
  const pendingRef = useRef<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const list = await listChatAgents();
        if (!cancelled) setAgents(list.agents);
      } catch {
        if (!cancelled) setAgents([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  useEffect(() => {
    if (!activeSessionId) return undefined;
    let cancelled = false;
    (async () => {
      const pending = pendingRef.current;
      pendingRef.current = null;
      try {
        if (pending !== null) {
          await putAgentSelection(activeSessionId, pending);
          if (!cancelled) setSelection(pending);
          return;
        }
        const current = await getAgentSelection(activeSessionId);
        if (!cancelled) setSelection(current);
      } catch {
        // Keep the local value; the picker still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeSessionId]);

  // Close on any outside click.
  useEffect(() => {
    if (!isOpen) return undefined;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setIsOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [isOpen]);

  const choose = useCallback(
    async (agentId: string) => {
      setSelection(agentId);
      setIsOpen(false);
      if (!activeSessionId) {
        pendingRef.current = agentId;
        return;
      }
      setIsBusy(true);
      try {
        await putAgentSelection(activeSessionId, agentId);
      } catch (error) {
        toast.show(`Gagal menyimpan pilihan agen: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsBusy(false);
      }
    },
    [activeSessionId, toast],
  );

  if (!enabled || agents.length === 0) return null;

  const options = [AUTO_OPTION, ...agents, DEFAULT_OPTION];
  const active = options.find((option) => option.id === selection) ?? AUTO_OPTION;

  return (
    <div
      className={`agent-select${direction === "up" ? " agent-select--up" : ""}`}
      ref={rootRef}
    >
      <button
        type="button"
        className="agent-select__trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-label="Pilih agen"
        disabled={isBusy}
        onClick={() => setIsOpen((value) => !value)}
      >
        <span className="agent-select__label">{active.name}</span>
        <svg
          aria-hidden="true"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {isOpen && (
        <div className="agent-select__menu" role="listbox" aria-label="Agen tersedia">
          {options.map((option) => (
            <button
              key={option.id || "default"}
              type="button"
              role="option"
              aria-selected={selection === option.id}
              className={`agent-select__option${
                selection === option.id ? " agent-select__option--active" : ""
              }`}
              onClick={() => void choose(option.id)}
            >
              <span className="agent-select__name">{option.name}</span>
              {option.description && (
                <span className="agent-select__desc">{option.description}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
