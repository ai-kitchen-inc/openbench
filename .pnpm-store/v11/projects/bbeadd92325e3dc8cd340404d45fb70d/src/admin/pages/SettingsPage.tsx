import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  getModelCatalog,
  getPrivacySettings,
  getRuntimeSettings,
  putModelCatalog,
  putPrivacySettings,
  putRuntimeSettings,
  readErrorMessage,
  runPrivacySweep,
  type ModelCatalogState,
  type PrivacySettings,
  type RuntimeSettingsState,
} from "../../account/api";
import { XIcon } from "../../brand/icons";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

type FieldDefinition = {
  id: string;
  label: string;
  description: string;
};

const FIELDS: FieldDefinition[] = [
  {
    id: "llm_model",
    label: "Model LLM",
    description: "Model bahasa utama untuk percakapan.",
  },
  {
    id: "vlm_model",
    label: "Model VLM",
    description:
      "Model visi untuk membaca gambar. Belum diterapkan — pengaturan disimpan saja.",
  },
  {
    id: "vector_store",
    label: "Basis Data Vektor",
    description:
      "Penyimpanan vektor untuk indeks sumber. Berlaku segera; worker perlu restart untuk ikut berpindah.",
  },
  {
    id: "embedding_model",
    label: "Model Embedding",
    description:
      "Model embedding untuk indeks sumber, dari katalog model. Mengganti model membuat vektor lama tidak cocok sampai sumber diindeks ulang.",
  },
];

function SettingRow({
  field,
  value,
  options,
  disabled,
  onChange,
}: {
  field: FieldDefinition;
  value: string;
  options: string[];
  disabled: boolean;
  onChange: (next: string) => void;
}) {
  return (
    <div className="cap-row settings-model-row">
      <div className="cap-row__main">
        <div className="cap-row__label">{field.label}</div>
        <div className="cap-row__desc">{field.description}</div>
      </div>
      <select
        className="settings-model-select"
        aria-label={field.label}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SettingsPage() {
  const { show: showToast } = useToast();
  const [state, setState] = useState<RuntimeSettingsState | null>(null);
  const [catalog, setCatalog] = useState<ModelCatalogState | null>(null);
  const [privacy, setPrivacy] = useState<PrivacySettings | null>(null);
  const [retentionDraft, setRetentionDraft] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [isSweeping, setIsSweeping] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError("");
    try {
      const [runtime, modelCatalog, privacySettings] = await Promise.all([
        getRuntimeSettings(),
        getModelCatalog(),
        getPrivacySettings(),
      ]);
      setState(runtime);
      setCatalog(modelCatalog);
      setPrivacy(privacySettings);
      setRetentionDraft(String(privacySettings.retentionDays));
    } catch (error) {
      setLoadError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleChange = useCallback(
    async (field: FieldDefinition, next: string) => {
      setSavingId(field.id);
      try {
        const resolved = await putRuntimeSettings({ [field.id]: next });
        setState(resolved);
        showToast(`${field.label} disimpan: ${next}.`, "success");
        if (resolved.embedding?.warning) {
          showToast(resolved.embedding.warning, "info", 9000);
        }
      } catch (error) {
        showToast(`Gagal menyimpan ${field.label}: ${readErrorMessage(error)}`, "error");
      } finally {
        setSavingId(null);
      }
    },
    [showToast],
  );

  const saveCatalog = useCallback(
    async (next: Partial<ModelCatalogState>, label: string) => {
      setSavingId("catalog");
      try {
        const resolved = await putModelCatalog(next);
        setCatalog(resolved);
        // Runtime option lists follow the catalog.
        setState(await getRuntimeSettings());
        showToast(`${label} disimpan.`, "success");
      } catch (error) {
        showToast(`Gagal menyimpan ${label}: ${readErrorMessage(error)}`, "error");
      } finally {
        setSavingId(null);
      }
    },
    [showToast],
  );

  const makeDefaultModel = useCallback(
    async (modelId: string) => {
      setSavingId("catalog");
      try {
        const resolved = await putRuntimeSettings({ llm_model: modelId });
        setState(resolved);
        showToast(`Model bawaan: ${modelId}.`, "success");
      } catch (error) {
        showToast(`Gagal mengganti model bawaan: ${readErrorMessage(error)}`, "error");
      } finally {
        setSavingId(null);
      }
    },
    [showToast],
  );

  const savePrivacy = useCallback(
    async (patch: Partial<PrivacySettings>, label: string) => {
      setSavingId("privacy");
      try {
        const resolved = await putPrivacySettings(patch);
        setPrivacy(resolved);
        setRetentionDraft(String(resolved.retentionDays));
        showToast(`${label} disimpan.`, "success");
      } catch (error) {
        showToast(`Gagal menyimpan ${label}: ${readErrorMessage(error)}`, "error");
      } finally {
        setSavingId(null);
      }
    },
    [showToast],
  );

  const handleRetentionCommit = useCallback(() => {
    if (!privacy) return;
    const parsed = Number.parseInt(retentionDraft, 10);
    if (Number.isNaN(parsed) || parsed < 0) {
      setRetentionDraft(String(privacy.retentionDays));
      showToast("Retensi harus berupa angka hari (0 = nonaktif).", "error");
      return;
    }
    if (parsed === privacy.retentionDays) return;
    void savePrivacy({ retentionDays: parsed }, "Retensi sesi");
  }, [privacy, retentionDraft, savePrivacy, showToast]);

  const handleSweep = useCallback(async () => {
    setIsSweeping(true);
    try {
      const result = await runPrivacySweep();
      showToast(`Pembersihan selesai: ${result.deletedSessions} sesi dihapus.`, "success");
    } catch (error) {
      showToast(`Gagal menjalankan pembersihan: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsSweeping(false);
    }
  }, [showToast]);

  if (isLoading) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError || !state || !privacy || !catalog) {
    return (
      <div className="sources-list__empty">
        Gagal memuat pengaturan: {loadError}{" "}
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
          Pilih model dan penyimpanan yang digunakan asisten. Perubahan tersimpan otomatis.
        </div>
      </div>

      <section className="panel-section" aria-label="Model dan penyimpanan">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Model &amp; Penyimpanan</div>
            <div className="panel-section__subtitle">
              Berlaku untuk seluruh deployment. Perubahan tersimpan otomatis.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            {FIELDS.map((field) => (
              <SettingRow
                key={field.id}
                field={field}
                value={state.values[field.id] ?? ""}
                options={state.options[field.id] ?? []}
                disabled={savingId !== null}
                onChange={(next) => void handleChange(field, next)}
              />
            ))}
          </div>
        </div>
      </section>

      <ModelCatalogSection
        catalog={catalog}
        activeModel={state.values.llm_model ?? ""}
        disabled={savingId !== null}
        onSave={saveCatalog}
        onMakeDefault={makeDefaultModel}
      />

      <section className="panel-section" aria-label="Privasi">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Privasi</div>
            <div className="panel-section__subtitle">
              Retensi data percakapan dan redaksi data pribadi sebelum dikirim ke model.
            </div>
          </div>
          <button
            type="button"
            className="panel-button"
            disabled={isSweeping}
            onClick={() => void handleSweep()}
          >
            {isSweeping ? "Membersihkan..." : "Jalankan pembersihan sekarang"}
          </button>
        </div>
        <div className="panel-section__body">
          <div className="cap-group">
            <div className="cap-row settings-model-row">
              <div className="cap-row__main">
                <div className="cap-row__label">Retensi sesi (hari)</div>
                <div className="cap-row__desc">
                  Sesi yang tidak aktif lebih lama dari ini dihapus permanen beserta
                  sumber dan memorinya. 0 = nonaktif.
                </div>
              </div>
              <input
                className="settings-model-select"
                type="number"
                min={0}
                aria-label="Retensi sesi (hari)"
                value={retentionDraft}
                disabled={savingId !== null}
                onChange={(event) => setRetentionDraft(event.target.value)}
                onBlur={handleRetentionCommit}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.currentTarget.blur();
                }}
              />
            </div>
            <div className="cap-row">
              <div className="cap-row__main">
                <div className="cap-row__label">Redaksi PII</div>
                <div className="cap-row__desc">
                  Samarkan NIK, NPWP, email, nomor telepon, dan nomor kartu dari pesan
                  pengguna sebelum diproses model.
                </div>
              </div>
              <button
                type="button"
                role="switch"
                className="switch"
                aria-checked={privacy.piiRedaction}
                aria-label="Redaksi PII"
                disabled={savingId !== null}
                onClick={() =>
                  void savePrivacy({ piiRedaction: !privacy.piiRedaction }, "Redaksi PII")
                }
              />
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function ModelCatalogSection({
  catalog,
  activeModel,
  disabled,
  onSave,
  onMakeDefault,
}: {
  catalog: ModelCatalogState;
  activeModel: string;
  disabled: boolean;
  onSave: (next: Partial<ModelCatalogState>, label: string) => Promise<void>;
  onMakeDefault: (modelId: string) => Promise<void>;
}) {
  const [newChatId, setNewChatId] = useState("");
  const [newChatLabel, setNewChatLabel] = useState("");
  const [newEmbId, setNewEmbId] = useState("");
  const [newEmbProvider, setNewEmbProvider] = useState("google");
  const [newEmbDimension, setNewEmbDimension] = useState("1536");

  const handleAddChatModel = (event: FormEvent) => {
    event.preventDefault();
    const id = newChatId.trim();
    if (!id) return;
    void onSave(
      {
        chatModels: [
          ...catalog.chatModels,
          { id, label: newChatLabel.trim() || id },
        ],
      },
      "Katalog model",
    ).then(() => {
      setNewChatId("");
      setNewChatLabel("");
    });
  };

  const handleAddEmbeddingModel = (event: FormEvent) => {
    event.preventDefault();
    const id = newEmbId.trim();
    const dimension = Number.parseInt(newEmbDimension, 10);
    if (!id || Number.isNaN(dimension)) return;
    void onSave(
      {
        embeddingModels: [
          ...catalog.embeddingModels,
          { id, provider: newEmbProvider, dimension, label: id },
        ],
      },
      "Katalog embedding",
    ).then(() => setNewEmbId(""));
  };

  return (
    <section className="panel-section" aria-label="Katalog model">
      <div className="panel-section__header">
        <div>
          <div className="panel-section__title">Katalog Model</div>
          <div className="panel-section__subtitle">
            Kelola model chat dan embedding yang bisa dipilih di pengaturan runtime dan
            profil agen. Model bawaan aktif tidak bisa dihapus.
          </div>
        </div>
      </div>
      <div className="panel-section__body">
        <div className="sources-list">
          {catalog.chatModels.map((model) => (
            <div className="source-row" key={model.id}>
              <span
                className={`source-row__badge${
                  model.id === activeModel ? " source-row__badge--filled" : ""
                }`}
              >
                {model.id === activeModel ? "bawaan" : "chat"}
              </span>
              <div className="source-row__main">
                <div className="source-row__name">{model.label}</div>
                <div className="source-row__meta">{model.id}</div>
              </div>
              {model.id !== activeModel && (
                <button
                  type="button"
                  className="panel-button"
                  disabled={disabled}
                  onClick={() => void onMakeDefault(model.id)}
                >
                  Jadikan bawaan
                </button>
              )}
              <button
                type="button"
                className="source-row__remove"
                aria-label={`Hapus ${model.id}`}
                disabled={disabled || model.id === activeModel}
                onClick={() =>
                  void onSave(
                    {
                      chatModels: catalog.chatModels.filter(
                        (entry) => entry.id !== model.id,
                      ),
                    },
                    "Katalog model",
                  )
                }
              >
                <XIcon size={14} />
              </button>
            </div>
          ))}
        </div>
        <form className="sources-form" onSubmit={handleAddChatModel}>
          <div className="sources-form__row">
            <input
              type="text"
              placeholder="ID model (mis. gemini-4-pro-preview)"
              aria-label="ID model chat"
              value={newChatId}
              onChange={(event) => setNewChatId(event.target.value)}
            />
            <input
              type="text"
              placeholder="Label (opsional)"
              aria-label="Label model chat"
              value={newChatLabel}
              onChange={(event) => setNewChatLabel(event.target.value)}
            />
            <button
              type="submit"
              className="panel-button panel-button--primary"
              disabled={disabled || !newChatId.trim()}
            >
              Tambah model chat
            </button>
          </div>
        </form>

        <div className="sources-list">
          {catalog.embeddingModels.map((model) => (
            <div className="source-row" key={model.id}>
              <span className="source-row__badge">embedding</span>
              <div className="source-row__main">
                <div className="source-row__name">{model.label}</div>
                <div className="source-row__meta">
                  {model.id} · {model.provider} · dim {model.dimension}
                </div>
              </div>
              <button
                type="button"
                className="source-row__remove"
                aria-label={`Hapus ${model.id}`}
                disabled={disabled}
                onClick={() =>
                  void onSave(
                    {
                      embeddingModels: catalog.embeddingModels.filter(
                        (entry) => entry.id !== model.id,
                      ),
                    },
                    "Katalog embedding",
                  )
                }
              >
                <XIcon size={14} />
              </button>
            </div>
          ))}
        </div>
        <form className="sources-form" onSubmit={handleAddEmbeddingModel}>
          <div className="sources-form__row">
            <input
              type="text"
              placeholder="ID model embedding"
              aria-label="ID model embedding"
              value={newEmbId}
              onChange={(event) => setNewEmbId(event.target.value)}
            />
            <select
              aria-label="Provider embedding"
              value={newEmbProvider}
              onChange={(event) => setNewEmbProvider(event.target.value)}
            >
              <option value="google">google</option>
              <option value="openai">openai</option>
            </select>
            <input
              type="number"
              min={1}
              max={2000}
              placeholder="Dimensi"
              aria-label="Dimensi embedding"
              value={newEmbDimension}
              onChange={(event) => setNewEmbDimension(event.target.value)}
            />
            <button
              type="submit"
              className="panel-button panel-button--primary"
              disabled={disabled || !newEmbId.trim()}
            >
              Tambah model embedding
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}
