import { useCallback, useEffect, useState } from "react";
import {
  applyPersonaTemplate,
  getPersona,
  listPersonaTemplates,
  readErrorMessage,
  savePersona,
  type PersonaActive,
  type PersonaState,
  type PersonaTemplate,
} from "../../account/api";
import { useToast } from "../../Toast";
import { COMMON } from "../../i18n/id";

type EditorState = {
  soul: string;
  style: string;
  agents: string;
  goal: string;
  sourceContextLabel: string;
};

const EMPTY_EDITOR: EditorState = {
  soul: "",
  style: "",
  agents: "",
  goal: "",
  sourceContextLabel: "",
};

function editorFromState(state: PersonaState): EditorState {
  const settings = state.settings;
  if (!settings) return EMPTY_EDITOR;
  return {
    soul: settings.soul ?? "",
    style: settings.style ?? "",
    agents: settings.agents ?? "",
    goal: settings.goal ?? "",
    sourceContextLabel: settings.source_context_label ?? "",
  };
}

function SourceBadge({ source }: { source: PersonaState["source"] }) {
  const label = source === "db" ? "Database" : source === "env" ? "Environment" : "Berkas";
  return <span className="source-badge">{label}</span>;
}

function ActiveSummary({ active }: { active: PersonaActive }) {
  return (
    <div className="persona-active">
      <span>SOUL: {active.soul_chars ?? 0} karakter</span>
      <span>STYLE: {active.style_chars ?? 0} karakter</span>
      <span>AGENTS: {active.agents_chars ?? 0} karakter</span>
      <span>Total: {active.total_chars ?? 0} karakter</span>
    </div>
  );
}

export function PersonaPage() {
  const { show: showToast } = useToast();
  const [templates, setTemplates] = useState<PersonaTemplate[]>([]);
  const [persona, setPersona] = useState<PersonaState | null>(null);
  const [editor, setEditor] = useState<EditorState>(EMPTY_EDITOR);
  const [isLoading, setIsLoading] = useState(true);
  const [isMutating, setIsMutating] = useState(false);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    setIsLoading(true);
    setLoadError("");
    try {
      const [personaState, templateList] = await Promise.all([
        getPersona(),
        listPersonaTemplates(),
      ]);
      setPersona(personaState);
      setEditor(editorFromState(personaState));
      setTemplates(templateList);
    } catch (error) {
      setLoadError(readErrorMessage(error));
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleApplyTemplate = async (template: PersonaTemplate) => {
    const confirmed = window.confirm(
      `Terapkan templat "${template.name}"? Ini akan menimpa persona yang tersimpan (termasuk suntingan Anda).`,
    );
    if (!confirmed) return;
    setIsMutating(true);
    try {
      const result = await applyPersonaTemplate(template.id);
      setPersona({ settings: result.settings, source: result.source, active: result.active });
      setEditor(
        editorFromState({ settings: result.settings, source: result.source, active: result.active }),
      );
      showToast(`Templat diterapkan: ${template.name}`, "success");
    } catch (error) {
      showToast(`Gagal menerapkan templat: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  const handleSave = async () => {
    if (!editor.soul.trim() && !editor.style.trim() && !editor.agents.trim()) {
      showToast("Minimal satu dari SOUL/STYLE/AGENTS harus diisi.", "error");
      return;
    }
    setIsMutating(true);
    try {
      const result = await savePersona({
        soul: editor.soul,
        style: editor.style,
        agents: editor.agents,
        goal: editor.goal,
        ...(editor.sourceContextLabel
          ? { source_context_label: editor.sourceContextLabel }
          : {}),
      });
      setPersona({ settings: result.settings, source: result.source, active: result.active });
      showToast("Persona disimpan dan agen dimuat ulang.", "success");
    } catch (error) {
      showToast(`Gagal menyimpan persona: ${readErrorMessage(error)}`, "error");
    } finally {
      setIsMutating(false);
    }
  };

  if (isLoading) {
    return <div className="sources-list__empty">{COMMON.loading}</div>;
  }

  if (loadError) {
    return (
      <div className="sources-list__empty">
        Gagal memuat persona: {loadError}{" "}
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
          Identitas dan aturan perilaku asisten. Terapkan templat siap pakai atau sunting
          langsung SOUL/STYLE/AGENTS di bawah.
        </div>
      </div>

      {persona && (
        <section className="panel-section" aria-label="Persona aktif">
          <div className="panel-section__header">
            <div>
              <div className="panel-section__title">Persona Aktif</div>
              <div className="panel-section__subtitle">
                Sumber konfigurasi yang sedang melayani percakapan.
              </div>
            </div>
            <SourceBadge source={persona.source} />
          </div>
          <div className="panel-section__body">
            <ActiveSummary active={persona.active} />
          </div>
        </section>
      )}

      <section className="panel-section" aria-label="Templat persona">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Templat</div>
            <div className="panel-section__subtitle">
              Menerapkan templat akan menimpa persona tersimpan.
            </div>
          </div>
        </div>
        <div className="panel-section__body">
          <div className="persona-templates">
            {templates.map((template) => (
              <div key={template.id} className="persona-card">
                <div className="persona-card__name">{template.name}</div>
                <div className="persona-card__desc">{template.description}</div>
                <button
                  type="button"
                  className="panel-button"
                  disabled={isMutating}
                  onClick={() => void handleApplyTemplate(template)}
                >
                  {COMMON.apply}
                </button>
              </div>
            ))}
            {templates.length === 0 && (
              <div className="sources-list__empty">Tidak ada templat tersedia.</div>
            )}
          </div>
        </div>
      </section>

      <section className="panel-section" aria-label="Penyunting persona">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Sunting Persona</div>
            <div className="panel-section__subtitle">
              Minimal satu dari SOUL/STYLE/AGENTS harus diisi.
            </div>
          </div>
          <button
            type="button"
            className="panel-button panel-button--primary"
            disabled={isMutating}
            onClick={() => void handleSave()}
          >
            Simpan Persona
          </button>
        </div>
        <div className="panel-section__body">
          <div className="persona-editor">
            <label className="persona-editor__field">
              <span>SOUL — identitas</span>
              <textarea
                value={editor.soul}
                onChange={(event) => setEditor((cur) => ({ ...cur, soul: event.target.value }))}
                placeholder="Siapa asisten ini dan apa prioritasnya..."
              />
            </label>
            <label className="persona-editor__field">
              <span>STYLE — gaya bahasa</span>
              <textarea
                value={editor.style}
                onChange={(event) => setEditor((cur) => ({ ...cur, style: event.target.value }))}
                placeholder="Bagaimana asisten menjawab (bahasa, format, nada)..."
              />
            </label>
            <label className="persona-editor__field">
              <span>AGENTS — aturan perilaku</span>
              <textarea
                value={editor.agents}
                onChange={(event) => setEditor((cur) => ({ ...cur, agents: event.target.value }))}
                placeholder="Aturan yang wajib dipatuhi asisten..."
              />
            </label>
            <label className="persona-editor__field">
              <span>Goal — tujuan agen</span>
              <input
                type="text"
                value={editor.goal}
                onChange={(event) => setEditor((cur) => ({ ...cur, goal: event.target.value }))}
                placeholder="Tujuan utama agen dalam satu kalimat..."
              />
            </label>
          </div>
        </div>
      </section>
    </>
  );
}
