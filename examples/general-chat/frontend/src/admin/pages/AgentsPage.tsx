import { useCallback, useEffect, useState } from "react";
import {
  addAgent,
  addAgentTextSource,
  addAgentUrlSource,
  deleteAgent,
  deleteAgentSource,
  getAgentOptions,
  listAgents,
  listAgentSources,
  readErrorMessage,
  updateAgent,
  type AgentProfileItem,
  type AgentProfileOptions,
  type AgentProfilePatch,
  type GroupSourceItem,
} from "../../account/api";
import { XIcon } from "../../brand/icons";
import { COMMON } from "../../i18n/id";
import { useToast } from "../../Toast";

const PERSONA_FIELDS: { key: string; label: string; rows: number }[] = [
  { key: "soul", label: "SOUL — identitas agen", rows: 4 },
  { key: "style", label: "STYLE — gaya menjawab", rows: 3 },
  { key: "agents", label: "AGENTS — aturan kerja", rows: 4 },
  { key: "goal", label: "Goal (opsional)", rows: 2 },
];

function AgentDetail({
  agent,
  agents,
  options,
  onSaved,
}: {
  agent: AgentProfileItem;
  agents: AgentProfileItem[];
  options: AgentProfileOptions;
  onSaved: () => void;
}) {
  const { show: showToast } = useToast();
  const [draft, setDraft] = useState<AgentProfilePatch>({});
  const [sources, setSources] = useState<GroupSourceItem[] | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [isBusy, setIsBusy] = useState(false);

  const value = { ...agent, ...draft };
  const persona = (draft.persona ?? agent.persona ?? {}) as Record<string, string>;
  const escalationCandidates = agents.filter((other) => other.id !== agent.id);

  const loadSources = useCallback(async () => {
    try {
      setSources(await listAgentSources(agent.id));
    } catch (error) {
      showToast(`Gagal memuat sumber agen: ${readErrorMessage(error)}`, "error");
    }
  }, [agent.id, showToast]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const run = useCallback(
    async (action: () => Promise<void>, successMessage: string) => {
      setIsBusy(true);
      try {
        await action();
        showToast(successMessage, "success");
      } catch (error) {
        showToast(readErrorMessage(error), "error");
      } finally {
        setIsBusy(false);
      }
    },
    [showToast],
  );

  const set = (patch: AgentProfilePatch) => setDraft((prev) => ({ ...prev, ...patch }));

  const toggleListValue = (key: "skills" | "customSkillIds", item: string) => {
    const current = (value[key] ?? []) as string[];
    const next = current.includes(item)
      ? current.filter((entry) => entry !== item)
      : [...current, item];
    set({ [key]: next } as AgentProfilePatch);
  };

  return (
    <div className="panel-section__body">
      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Profil</div>
            <div className="cap-row__desc">
              Deskripsi dipakai perutean otomatis — tulis seperti petunjuk dispatch.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={value.enabled}
            aria-label="Agen aktif"
            onClick={() => set({ enabled: !value.enabled })}
          />
        </div>
      </div>
      <div className="sources-form">
        <div className="sources-form__row">
          <input
            type="text"
            aria-label="Nama agen"
            value={value.name}
            onChange={(event) => set({ name: event.target.value })}
          />
          <input
            type="text"
            aria-label="Deskripsi agen"
            placeholder="Deskripsi (dipakai perutean otomatis)"
            value={value.description}
            onChange={(event) => set({ description: event.target.value })}
          />
        </div>
        <div className="sources-form__row">
          <select
            aria-label="Model"
            value={value.model}
            onChange={(event) => set({ model: event.target.value })}
          >
            <option value="">Model bawaan (pengaturan runtime)</option>
            {options.models.map((model) => (
              <option key={model} value={model}>
                {model}
              </option>
            ))}
          </select>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            aria-label="Temperature"
            placeholder="Temperature (opsional)"
            value={value.temperature ?? ""}
            onChange={(event) =>
              set({
                temperature:
                  event.target.value === "" ? null : Number(event.target.value),
              })
            }
          />
        </div>
        <div className="sources-form__row">
          <select
            aria-label="Agen eskalasi"
            value={value.escalationAgentId}
            onChange={(event) => set({ escalationAgentId: event.target.value })}
          >
            <option value="">Tanpa eskalasi</option>
            {escalationCandidates.map((other) => (
              <option key={other.id} value={other.id}>
                Eskalasi ke: {other.name}
              </option>
            ))}
          </select>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            aria-label="Ambang keyakinan"
            title="Eskalasi saat keyakinan di bawah ambang ini"
            value={value.confidenceThreshold}
            onChange={(event) =>
              set({ confidenceThreshold: Number(event.target.value) })
            }
          />
        </div>
      </div>

      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Skill</div>
            <div className="cap-row__desc">
              Skill SDK dan skill kustom yang dimuat khusus untuk agen ini.
            </div>
          </div>
        </div>
      </div>
      <div className="agents-skill-grid">
        {options.sdkSkills.map((skill) => (
          <label key={skill} className="agents-skill-grid__item">
            <input
              type="checkbox"
              checked={(value.skills ?? []).includes(skill)}
              onChange={() => toggleListValue("skills", skill)}
            />
            {skill}
          </label>
        ))}
        {options.customSkills.map((skill) => (
          <label key={`custom-${skill}`} className="agents-skill-grid__item">
            <input
              type="checkbox"
              checked={(value.customSkillIds ?? []).includes(skill)}
              onChange={() => toggleListValue("customSkillIds", skill)}
            />
            {skill} (kustom)
          </label>
        ))}
        {options.sdkSkills.length === 0 && options.customSkills.length === 0 && (
          <div className="sources-list__empty">Tidak ada skill tersedia.</div>
        )}
      </div>

      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Persona</div>
            <div className="cap-row__desc">
              Kosongkan semua kolom untuk mewarisi persona global admin.
            </div>
          </div>
        </div>
      </div>
      <div className="sources-form">
        {PERSONA_FIELDS.map((field) => (
          <textarea
            key={field.key}
            rows={field.rows}
            aria-label={field.label}
            placeholder={field.label}
            value={persona[field.key] ?? ""}
            onChange={(event) =>
              set({ persona: { ...persona, [field.key]: event.target.value } })
            }
          />
        ))}
      </div>

      <div className="cap-group">
        <div className="cap-row">
          <div className="cap-row__main">
            <div className="cap-row__label">Sumber agen</div>
            <div className="cap-row__desc">
              Dokumen yang melandasi jawaban khusus agen ini.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            className="switch"
            aria-checked={value.useSources}
            aria-label="Gunakan sumber agen"
            onClick={() => set({ useSources: !value.useSources })}
          />
        </div>
      </div>
      {sources === null ? (
        <div className="sources-list__empty">{COMMON.loading}</div>
      ) : sources.length === 0 ? (
        <div className="sources-list__empty">Belum ada sumber agen.</div>
      ) : (
        <div className="sources-list">
          {sources.map((source) => (
            <div className="source-row" key={source.id}>
              <span className="source-row__badge source-row__badge--filled">
                {source.kind ?? "teks"}
              </span>
              <div className="source-row__main">
                <div className="source-row__name">{source.name}</div>
              </div>
              <button
                type="button"
                className="source-row__remove"
                aria-label={`Hapus ${source.name}`}
                disabled={isBusy}
                onClick={() =>
                  void run(async () => {
                    await deleteAgentSource(agent.id, source.id);
                    await loadSources();
                  }, "Sumber agen dihapus.")
                }
              >
                <XIcon />
              </button>
            </div>
          ))}
        </div>
      )}
      <form
        className="sources-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!sourceText.trim()) return;
          void run(async () => {
            await addAgentTextSource(agent.id, sourceName.trim() || "Teks", sourceText);
            setSourceName("");
            setSourceText("");
            await loadSources();
          }, "Sumber teks ditambahkan.");
        }}
      >
        <div className="sources-form__row">
          <input
            type="text"
            placeholder="Nama sumber"
            aria-label="Nama sumber"
            value={sourceName}
            onChange={(event) => setSourceName(event.target.value)}
          />
          <input
            type="text"
            placeholder="Tempel teks kebijakan/dokumen"
            aria-label="Teks sumber"
            value={sourceText}
            onChange={(event) => setSourceText(event.target.value)}
          />
          <button type="submit" className="panel-button" disabled={isBusy}>
            Tambah teks
          </button>
        </div>
        <div className="sources-form__row">
          <input
            type="url"
            placeholder="https://..."
            aria-label="URL sumber"
            value={sourceUrl}
            onChange={(event) => setSourceUrl(event.target.value)}
          />
          <button
            type="button"
            className="panel-button"
            disabled={isBusy || !sourceUrl.trim()}
            onClick={() =>
              void run(async () => {
                await addAgentUrlSource(agent.id, sourceUrl.trim());
                setSourceUrl("");
                await loadSources();
              }, "Sumber URL ditambahkan.")
            }
          >
            Tambah URL
          </button>
        </div>
      </form>

      <div className="sources-form__row">
        <button
          type="button"
          className="panel-button panel-button--primary"
          disabled={isBusy || Object.keys(draft).length === 0}
          onClick={() =>
            void run(async () => {
              await updateAgent(agent.id, draft);
              setDraft({});
              onSaved();
            }, "Agen disimpan.")
          }
        >
          Simpan agen
        </button>
      </div>
    </div>
  );
}

export function AgentsPage() {
  const { show: showToast } = useToast();
  const [agents, setAgents] = useState<AgentProfileItem[] | null>(null);
  const [options, setOptions] = useState<AgentProfileOptions | null>(null);
  const [loadError, setLoadError] = useState("");
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const [agentList, optionValues] = await Promise.all([listAgents(), getAgentOptions()]);
      setAgents(agentList);
      setOptions(optionValues);
    } catch (error) {
      setLoadError(readErrorMessage(error));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createAgent = useCallback(async () => {
    if (!newName.trim() || !newDescription.trim()) return;
    setIsBusy(true);
    try {
      await addAgent(newName.trim(), newDescription.trim());
      setNewName("");
      setNewDescription("");
      await load();
      showToast("Agen dibuat.", "success");
    } catch (error) {
      showToast(`Gagal membuat agen: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsBusy(false);
    }
  }, [load, newDescription, newName, showToast]);

  const removeAgent = useCallback(
    async (agent: AgentProfileItem) => {
      if (
        !window.confirm(
          `Hapus agen "${agent.name}"? Sumber agen ikut terhapus dan rujukan eskalasi dilepas.`,
        )
      ) {
        return;
      }
      setIsBusy(true);
      try {
        await deleteAgent(agent.id);
        await load();
        showToast("Agen dihapus.", "success");
      } catch (error) {
        showToast(`Gagal menghapus agen: ${readErrorMessage(error)}`, "error");
      } finally {
        setIsBusy(false);
      }
    },
    [load, showToast],
  );

  if (agents === null && !loadError) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError) {
    return (
      <div className="sources-list__empty">
        Gagal memuat agen: {loadError}{" "}
        <button type="button" className="panel-button" onClick={() => void load()}>
          {COMMON.retry}
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Agen spesialis per bidang: persona, skill, sumber pengetahuan, dan model sendiri.
          Mode "Otomatis" memilihkan agen terbaik untuk setiap pesan; keyakinan rendah dapat
          dieskalasi ke agen yang lebih kuat.
        </div>
      </div>

      <section className="panel-section" aria-label="Agen">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Agen</div>
            <div className="panel-section__subtitle">
              {agents?.length ?? 0} agen terdaftar.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <form
            className="sources-form"
            onSubmit={(event) => {
              event.preventDefault();
              void createAgent();
            }}
          >
            <div className="sources-form__row">
              <input
                type="text"
                placeholder="Nama agen (mis. Analis Keuangan)"
                aria-label="Nama agen"
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
              />
              <input
                type="text"
                placeholder="Deskripsi untuk perutean (mis. laporan keuangan, pajak)"
                aria-label="Deskripsi agen"
                value={newDescription}
                onChange={(event) => setNewDescription(event.target.value)}
              />
              <button
                type="submit"
                className="panel-button panel-button--primary"
                disabled={isBusy || !newName.trim() || !newDescription.trim()}
              >
                Buat agen
              </button>
            </div>
          </form>

          {agents && agents.length === 0 ? (
            <div className="sources-list__empty">Belum ada agen.</div>
          ) : (
            <div className="sources-list">
              {(agents ?? []).map((agent) => (
                <div key={agent.id}>
                  <div className="source-row">
                    <span
                      className={`source-row__badge${agent.enabled ? " source-row__badge--filled" : ""}`}
                    >
                      {agent.enabled ? "aktif" : "nonaktif"}
                    </span>
                    <div className="source-row__main">
                      <div className="source-row__name">{agent.name}</div>
                      <div className="source-row__meta">
                        {agent.id}
                        {agent.description ? ` · ${agent.description}` : ""}
                        {agent.escalationAgentId
                          ? ` · eskalasi: ${agent.escalationAgentId}`
                          : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="panel-button"
                      onClick={() =>
                        setExpanded(expanded === agent.id ? null : agent.id)
                      }
                    >
                      {expanded === agent.id ? "Tutup" : "Kelola"}
                    </button>
                    <button
                      type="button"
                      className="source-row__remove"
                      aria-label={`Hapus ${agent.name}`}
                      disabled={isBusy}
                      onClick={() => void removeAgent(agent)}
                    >
                      <XIcon />
                    </button>
                  </div>
                  {expanded === agent.id && options && (
                    <AgentDetail
                      agent={agent}
                      agents={agents ?? []}
                      options={options}
                      onSaved={() => void load()}
                    />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}
