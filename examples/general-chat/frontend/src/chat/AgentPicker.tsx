/** Per-session specialist agent picker (chat settings "Agen" view). */

import { useEffect, useState } from "react";
import { useToast } from "../Toast";
import {
  getAgentSelection,
  putAgentSelection,
  type ChatAgentItem,
} from "./agentsApi";
import { readErrorMessage } from "./uploads";

export function AgentPickerPanel({
  sessionId,
  agents,
}: {
  sessionId: string | null;
  agents: ChatAgentItem[];
}) {
  const toast = useToast();
  const [selection, setSelection] = useState<string>("auto");
  const [isBusy, setIsBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!sessionId) return undefined;
    (async () => {
      try {
        const current = await getAgentSelection(sessionId);
        if (!cancelled) setSelection(current);
      } catch {
        // Keep the default; the picker still works.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const choose = async (agentId: string) => {
    setSelection(agentId);
    if (!sessionId) return;
    setIsBusy(true);
    try {
      await putAgentSelection(sessionId, agentId);
      toast.show("Pilihan agen disimpan.", "success");
    } catch (error) {
      toast.show(`Gagal menyimpan pilihan agen: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsBusy(false);
    }
  };

  const optionRow = (id: string, name: string, description: string) => (
    <label key={id || "default"} className="agent-picker__option">
      <input
        type="radio"
        name="agent-selection"
        aria-label={name}
        checked={selection === id}
        disabled={isBusy || !sessionId}
        onChange={() => void choose(id)}
      />
      <span className="agent-picker__main">
        <span className="agent-picker__name">{name}</span>
        {description && <span className="agent-picker__desc">{description}</span>}
      </span>
    </label>
  );

  return (
    <div className="agent-picker">
      {!sessionId && (
        <div className="sources-list__empty">
          Mulai percakapan terlebih dahulu untuk memilih agen sesi ini.
        </div>
      )}
      {optionRow("auto", "Otomatis", "Sistem memilihkan agen terbaik untuk setiap pesan.")}
      {agents.map((agent) => optionRow(agent.id, agent.name, agent.description))}
      {optionRow("", "Asisten bawaan", "Asisten umum tanpa spesialisasi.")}
    </div>
  );
}
