/** "Dasbor" tab of the user Settings dialog: the caller's live dashboards.
 *
 * List, pause/resume, publish toggle (with the shareable link), refresh,
 * delete, and two chat hand-offs: "Buka" re-renders the stored snapshot in
 * the conversation, "Ubah dengan prompt" sends an edit instruction to the
 * agent. Both go through the normal chat turn so the agent's live-dashboard
 * tools do the work. */
import { useChatContext } from "@openbench/chat-ui";
import { useCallback, useEffect, useState } from "react";
import { COMMON } from "../i18n/id";
import { readErrorMessage } from "../shared/apiHelpers";
import { useToast } from "../Toast";
import {
  deleteLiveDashboard,
  listLiveDashboards,
  patchLiveDashboard,
  publicDashboardUrl,
  refreshLiveDashboard,
  type LiveDashboardSummary,
} from "./api";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; items: LiveDashboardSummary[] };

/** The sentence the agent's `open_live_dashboard` tool is triggered by. */
export function openDashboardPrompt(dashboard: { id: string; title: string }): string {
  return `Buka dashboard live \`${dashboard.id}\` ("${dashboard.title}")`;
}

/** The sentence the agent's `update_live_dashboard` tool is triggered by. */
export function editDashboardPrompt(
  dashboard: { id: string; title: string },
  instruction: string,
): string {
  return `Perbarui dashboard live \`${dashboard.id}\` ("${dashboard.title}"): ${instruction.trim()}`;
}

export function formatInterval(seconds: number): string {
  if (!seconds || seconds <= 0) return "manual";
  if (seconds % 3600 === 0) return `${seconds / 3600} jam`;
  if (seconds % 60 === 0) return `${seconds / 60} mnt`;
  return `${seconds} dtk`;
}

function formatTime(iso: string | null): string {
  if (!iso) return "belum pernah";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" });
}

function statusOf(item: LiveDashboardSummary): { label: string; tone: string } {
  if (item.lastError) return { label: "error", tone: "danger" };
  if (!item.enabled) return { label: "jeda", tone: "warning" };
  return { label: "aktif", tone: "success" };
}

export function LiveDashboardsPanel({ onRequestClose }: { onRequestClose: () => void }) {
  const { sendMessage, isStreaming, activeSessionId, createSession } = useChatContext();
  const toast = useToast();
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [busyId, setBusyId] = useState<string | null>(null);
  const [promptFor, setPromptFor] = useState<string | null>(null);
  const [promptText, setPromptText] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setState({ status: "loading" });
    try {
      const items = await listLiveDashboards();
      setState({ status: "ready", items });
    } catch (error) {
      setState({ status: "error", message: readErrorMessage(error) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const replaceItem = (updated: Partial<LiveDashboardSummary> & { id: string }) => {
    setState((current) =>
      current.status === "ready"
        ? {
            ...current,
            items: current.items.map((item) =>
              item.id === updated.id ? { ...item, ...updated } : item,
            ),
          }
        : current,
    );
  };

  const run = async (id: string, action: () => Promise<void>, successMessage?: string) => {
    setBusyId(id);
    try {
      await action();
      if (successMessage) toast.show(successMessage, "success");
    } catch (error) {
      toast.show(readErrorMessage(error), "error");
    } finally {
      setBusyId(null);
    }
  };

  const sendToChat = (text: string) => {
    if (!activeSessionId) createSession();
    sendMessage(text);
    onRequestClose();
  };

  const togglePublic = (item: LiveDashboardSummary) =>
    run(item.id, async () => {
      const updated = await patchLiveDashboard(item.id, { public: !item.public });
      replaceItem({ id: item.id, public: updated.public });
    });

  const toggleEnabled = (item: LiveDashboardSummary) =>
    run(item.id, async () => {
      const updated = await patchLiveDashboard(item.id, { enabled: !item.enabled });
      replaceItem({ id: item.id, enabled: updated.enabled, nextRunAt: updated.nextRunAt });
    });

  const refresh = (item: LiveDashboardSummary) =>
    run(
      item.id,
      async () => {
        await refreshLiveDashboard(item.id);
        const items = await listLiveDashboards();
        setState({ status: "ready", items });
      },
      "Data dasbor dimuat ulang.",
    );

  const remove = (item: LiveDashboardSummary) => {
    if (!window.confirm(`Hapus dasbor "${item.title}"? Pembaruan otomatis dan tautan publiknya berhenti.`)) {
      return;
    }
    void run(
      item.id,
      async () => {
        await deleteLiveDashboard(item.id);
        setState((current) =>
          current.status === "ready"
            ? { ...current, items: current.items.filter((entry) => entry.id !== item.id) }
            : current,
        );
      },
      "Dasbor dihapus.",
    );
  };

  const copyLink = async (item: LiveDashboardSummary) => {
    try {
      await navigator.clipboard?.writeText(publicDashboardUrl(item.id));
      setCopiedId(item.id);
    } catch {
      toast.show("Gagal menyalin tautan.", "error");
    }
  };

  const submitPrompt = (item: LiveDashboardSummary) => {
    const instruction = promptText.trim();
    if (!instruction || isStreaming) return;
    setPromptFor(null);
    setPromptText("");
    sendToChat(editDashboardPrompt(item, instruction));
  };

  if (state.status === "loading") {
    return <div className="mcp-state">{COMMON.loading}</div>;
  }
  if (state.status === "error") {
    return (
      <div className="settings-dashboards">
        <div className="mcp-state mcp-state--error" role="alert">
          {state.message}
        </div>
        <button type="button" className="mcp-btn" onClick={() => void load()}>
          {COMMON.retry}
        </button>
      </div>
    );
  }

  return (
    <div className="settings-dashboards">
      <section className="mcp-section">
        <div className="mcp-section__header">
          <h3>Dasbor live</h3>
          <p>
            Dasbor yang terikat ke database dan diperbarui otomatis. Perubahan isi dilakukan lewat
            asisten; di sini Anda mengatur jadwal, tautan publik, dan penghapusan.
          </p>
        </div>
        {state.items.length === 0 ? (
          <div className="sources-list__empty">
            Belum ada dasbor live. Minta asisten: &ldquo;buatkan dashboard live dari database
            &hellip;&rdquo;.
          </div>
        ) : (
          <ul className="sources-list settings-dashboards__list">
            {state.items.map((item) => {
              const status = statusOf(item);
              const busy = busyId === item.id;
              const editing = promptFor === item.id;
              return (
                <li key={item.id} className="source-row settings-dashboards__row">
                  <div className="source-row__main">
                    <div className="source-row__name">{item.title}</div>
                    <div className="source-row__meta">
                      <span className={`status-pill status-pill--${status.tone}`} title={item.lastError ?? undefined}>
                        {status.label}
                      </span>
                      {" · "}
                      {formatInterval(item.refreshIntervalSeconds)}
                      {" · diperbarui "}
                      {formatTime(item.lastRefreshAt)}
                      {" · versi "}
                      {item.version}
                    </div>
                    {item.public && (
                      <div className="source-row__meta settings-dashboards__link">
                        <a href={publicDashboardUrl(item.id)} target="_blank" rel="noreferrer">
                          {publicDashboardUrl(item.id)}
                        </a>
                        <button type="button" className="mcp-btn" onClick={() => void copyLink(item)}>
                          {copiedId === item.id ? "Tersalin" : "Salin"}
                        </button>
                      </div>
                    )}
                    <div className="settings-dashboards__actions">
                      <button
                        type="button"
                        className="mcp-btn mcp-btn--primary"
                        disabled={busy || isStreaming}
                        onClick={() => sendToChat(openDashboardPrompt(item))}
                      >
                        Buka
                      </button>
                      <button
                        type="button"
                        className="mcp-btn"
                        disabled={busy || isStreaming}
                        onClick={() => {
                          setPromptFor(editing ? null : item.id);
                          setPromptText("");
                        }}
                      >
                        Ubah dengan prompt
                      </button>
                      <button type="button" className="mcp-btn" disabled={busy} onClick={() => void refresh(item)}>
                        {COMMON.refresh}
                      </button>
                      <button type="button" className="mcp-btn" disabled={busy} onClick={() => void toggleEnabled(item)}>
                        {item.enabled ? "Jeda" : "Lanjutkan"}
                      </button>
                      <button type="button" className="mcp-btn" disabled={busy} onClick={() => void togglePublic(item)}>
                        {item.public ? "Jadikan privat" : "Publikasikan"}
                      </button>
                      <button type="button" className="mcp-btn settings-dashboards__danger" disabled={busy} onClick={() => remove(item)}>
                        {COMMON.remove}
                      </button>
                    </div>
                    {editing && (
                      <form
                        className="settings-dashboards__prompt"
                        onSubmit={(event) => {
                          event.preventDefault();
                          submitPrompt(item);
                        }}
                      >
                        <label className="mcp-field">
                          <span>Instruksi untuk asisten</span>
                          <textarea
                            rows={3}
                            value={promptText}
                            placeholder="contoh: tambahkan grafik pendapatan per bulan dan ubah refresh jadi 5 menit"
                            onChange={(event) => setPromptText(event.target.value)}
                          />
                        </label>
                        <div className="mcp-dialog__actions">
                          <button
                            type="submit"
                            className="mcp-btn mcp-btn--primary"
                            disabled={isStreaming || !promptText.trim()}
                          >
                            Kirim ke asisten
                          </button>
                          <button type="button" className="mcp-btn" onClick={() => setPromptFor(null)}>
                            {COMMON.cancel}
                          </button>
                        </div>
                      </form>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
