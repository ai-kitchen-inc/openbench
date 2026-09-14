import { useCallback, useEffect, useState } from "react";
import {
  getRuntimeSettings,
  putRuntimeSettings,
  readErrorMessage,
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
      "Penyimpanan vektor untuk indeks sumber. Belum diterapkan — pengaturan disimpan saja.",
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
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError("");
    try {
      setState(await getRuntimeSettings());
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

  if (isLoading) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError || !state) {
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
    </>
  );
}
