import { useCallback, useEffect, useState } from "react";
import {
  getPrivacySettings,
  getRuntimeSettings,
  putPrivacySettings,
  putRuntimeSettings,
  readErrorMessage,
  runPrivacySweep,
  type PrivacySettings,
  type RuntimeSettingsState,
} from "../../account/api";
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
      const [runtime, privacySettings] = await Promise.all([
        getRuntimeSettings(),
        getPrivacySettings(),
      ]);
      setState(runtime);
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
      } catch (error) {
        showToast(`Gagal menyimpan ${field.label}: ${readErrorMessage(error)}`, "error");
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

  if (loadError || !state || !privacy) {
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
