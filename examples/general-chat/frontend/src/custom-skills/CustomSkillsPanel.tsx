import { useCallback, useEffect, useState } from "react";
import { useToast } from "../Toast";
import {
  createCustomSkillFromPrompt,
  deleteCustomSkill,
  listCustomSkills,
  saveCustomSkillMarkdown,
} from "./api";
import type { CustomSkill } from "./types";

const PROMPT_PLACEHOLDER = [
  "Jelaskan skill kustom yang ingin ditambahkan ke agent.",
  "Tuliskan tujuan skill, kapan harus dipakai, gaya jawaban, aturan khusus, batasan, atau format output yang kamu inginkan.",
].join("\n");

function markdownForSkill(skill: CustomSkill): string {
  return (
    skill.skill_md ||
    [
      `# ${skill.name}`,
      "",
      skill.description || "Custom General Chat skill.",
      "",
      "## Triggers",
      "",
      ...(skill.triggers.length > 0 ? skill.triggers.map((trigger) => `- ${trigger}`) : ["- Use when relevant."]),
      "",
      "## Instructions",
      "",
      skill.instructions || "Tuliskan instruksi skill di sini.",
      "",
      "## Version",
      "",
      skill.version || "0.1.0",
    ].join("\n")
  );
}

export function CustomSkillsPanel() {
  const toast = useToast();
  const [skills, setSkills] = useState<CustomSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [savingPrompt, setSavingPrompt] = useState(false);
  const [savingMarkdown, setSavingMarkdown] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [editingSkill, setEditingSkill] = useState<CustomSkill | null>(null);
  const [markdownDraft, setMarkdownDraft] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSkills(await listCustomSkills());
    } catch (error) {
      toast.show(error instanceof Error ? error.message : "Gagal memuat skill", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  function resetPrompt() {
    setPrompt("");
    setFormError(null);
  }

  function closeEditor() {
    setEditingSkill(null);
    setMarkdownDraft("");
    setFormError(null);
  }

  function handleEdit(skill: CustomSkill) {
    setEditingSkill(skill);
    setMarkdownDraft(markdownForSkill(skill));
    setFormError(null);
  }

  async function handleCreateFromPrompt() {
    setSavingPrompt(true);
    setFormError(null);
    try {
      const saved = await createCustomSkillFromPrompt(prompt.trim());
      toast.show(`Skill "${saved.name}" dibuat dan agent dimuat ulang`, "success");
      setPrompt("");
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Gagal membuat skill");
    } finally {
      setSavingPrompt(false);
    }
  }

  async function handleSaveMarkdown() {
    if (!editingSkill) return;
    setSavingMarkdown(true);
    setFormError(null);
    try {
      const saved = await saveCustomSkillMarkdown(editingSkill.id, markdownDraft.trim());
      toast.show(`Skill "${saved.name}" diperbarui dan agent dimuat ulang`, "success");
      setEditingSkill(saved);
      setMarkdownDraft(markdownForSkill(saved));
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Gagal menyimpan markdown skill");
    } finally {
      setSavingMarkdown(false);
    }
  }

  async function handleDelete(skill: CustomSkill) {
    try {
      await deleteCustomSkill(skill.id);
      toast.show(`Skill "${skill.name}" dihapus dan agent dimuat ulang`, "success");
      await load();
      if (editingSkill?.id === skill.id) closeEditor();
    } catch (error) {
      toast.show(error instanceof Error ? error.message : "Gagal menghapus skill", "error");
    }
  }

  return (
    <div className="mcp-catalog custom-skills">
      <section className="mcp-section custom-skills__composer">
        <div className="mcp-section__header">
          <div>
            <h3>Buat skill dari prompt</h3>
            <p>
              Tulis kebutuhan skill dalam bahasa natural. Sistem akan menyusun ID unik, nama,
              deskripsi, trigger, instruksi, dan versi dalam format SKILL.md.
            </p>
          </div>
          <div className="mcp-section__actions">
            <button type="button" className="mcp-btn" onClick={resetPrompt}>
              Kosongkan
            </button>
          </div>
        </div>

        <label className="mcp-field custom-skills__prompt">
          <span>Prompt kebutuhan skill</span>
          <textarea
            value={prompt}
            rows={9}
            placeholder={PROMPT_PLACEHOLDER}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </label>

        {formError && !editingSkill && (
          <div className="mcp-state mcp-state--error" role="alert">
            {formError}
          </div>
        )}

        <div className="mcp-dialog__actions custom-skills__actions">
          <button
            type="button"
            className="mcp-btn mcp-btn--primary"
            onClick={() => void handleCreateFromPrompt()}
            disabled={savingPrompt || !prompt.trim()}
          >
            {savingPrompt ? "Menyusun skill..." : "Buat dan simpan skill"}
          </button>
        </div>
      </section>

      {editingSkill && (
        <section className="mcp-section custom-skills__editor">
          <div className="mcp-section__header">
            <div>
              <h3>Edit SKILL.md</h3>
              <p>
                Mengedit {editingSkill.name} | ID tetap: {editingSkill.id}
              </p>
            </div>
            <div className="mcp-section__actions">
              <button type="button" className="mcp-btn" onClick={closeEditor}>
                Tutup editor
              </button>
            </div>
          </div>

          <label className="mcp-field custom-skills__markdown">
            <span>Markdown skill</span>
            <textarea
              value={markdownDraft}
              spellCheck={false}
              rows={18}
              onChange={(event) => setMarkdownDraft(event.target.value)}
            />
          </label>

          {formError && (
            <div className="mcp-state mcp-state--error" role="alert">
              {formError}
            </div>
          )}

          <div className="mcp-dialog__actions custom-skills__actions">
            <button
              type="button"
              className="mcp-btn mcp-btn--primary"
              onClick={() => void handleSaveMarkdown()}
              disabled={savingMarkdown || !markdownDraft.trim()}
            >
              {savingMarkdown ? "Menyimpan..." : "Simpan perubahan MD"}
            </button>
          </div>
        </section>
      )}

      <section className="mcp-section">
        <div className="mcp-section__header">
          <div>
            <h3>Skill tersimpan</h3>
            <p>{skills.length} skill kustom aktif</p>
          </div>
          <div className="mcp-section__actions">
            <button type="button" className="mcp-btn" onClick={() => void load()}>
              Refresh
            </button>
          </div>
        </div>
        {loading && <div className="mcp-state">Memuat skill...</div>}
        {!loading && skills.length === 0 && (
          <div className="mcp-state">Belum ada skill. Tulis kebutuhan skill di prompt.</div>
        )}
        <div className="mcp-catalog-list custom-skills__list">
          {skills.map((skill) => (
            <div key={skill.id} className="mcp-catalog-row custom-skills__item">
              <div>
                <strong>{skill.name}</strong>
                <span>
                  {skill.description || "Tanpa deskripsi"} | ID: {skill.id} |{" "}
                  {skill.context_chars} karakter konteks
                </span>
              </div>
              <div className="mcp-catalog-row__actions">
                <button type="button" className="mcp-btn" onClick={() => handleEdit(skill)}>
                  Edit MD
                </button>
                <button
                  type="button"
                  className="mcp-btn"
                  onClick={() => void handleDelete(skill)}
                >
                  Hapus
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
