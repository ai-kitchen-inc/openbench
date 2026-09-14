import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../Toast";
import {
  createCustomSkillPackage,
  createCustomSkillFromPrompt,
  deleteCustomSkill,
  listCustomSkills,
  saveCustomSkillMarkdown,
} from "./api";
import type { CustomSkill } from "./types";

const PROMPT_PLACEHOLDER = [
  "Jelaskan skill kustom yang ingin ditambahkan ke agent.",
  "Tuliskan tujuan skill, kapan harus dipakai, gaya jawaban, aturan khusus, batasan, format output, dan kebutuhan tool/script jika ada.",
].join("\n");

function toolingSummary(skill: CustomSkill): string {
  const required = skill.tooling?.required ?? [];
  if (required.length === 0) return "Knowledge-only";
  const available = required.filter((tool) => tool.status === "available").length;
  const created = skill.tooling?.created_functions?.length ?? 0;
  const missing = required.filter((tool) => tool.status === "missing").length;
  const parts = [`${available}/${required.length} tool tersedia`];
  if (created > 0) parts.push(`${created} fungsi dibuat`);
  if (missing > 0) parts.push(`${missing} belum tersedia`);
  return parts.join(" | ");
}

function resourceSummary(skill: CustomSkill): string {
  const resources = skill.resources;
  if (!resources) return "Tanpa resource tambahan";
  const parts = [
    ["references", "reference"],
    ["assets", "asset"],
    ["examples", "example"],
    ["scripts", "script"],
  ] as const;
  const counts = parts
    .map(([key, label]) => {
      const count = resources[key]?.length ?? 0;
      return count > 0 ? `${count} ${label}` : "";
    })
    .filter(Boolean);
  return counts.length > 0 ? counts.join(" | ") : "Tanpa resource tambahan";
}

function selectedFileSummary(files: File[]): string {
  if (files.length === 0) return "Belum ada file dipilih";
  return files.map((file) => `${file.name} (${Math.ceil(file.size / 1024)} KB)`).join(", ");
}

function fileExtension(file: File): string {
  const extension = file.name.split(".").pop()?.trim();
  return extension ? extension.slice(0, 4).toUpperCase() : "FILE";
}

function fileKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function mergeFiles(current: File[], incoming: File[]): File[] {
  const seen = new Set(current.map(fileKey));
  const merged = [...current];
  for (const file of incoming) {
    const key = fileKey(file);
    if (seen.has(key)) continue;
    seen.add(key);
    merged.push(file);
  }
  return merged;
}

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
  const [resourceFiles, setResourceFiles] = useState<File[]>([]);
  const [isDraggingResource, setIsDraggingResource] = useState(false);
  const [editingSkill, setEditingSkill] = useState<CustomSkill | null>(null);
  const [markdownDraft, setMarkdownDraft] = useState("");
  const resourceInputRef = useRef<HTMLInputElement | null>(null);

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
    setResourceFiles([]);
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

  function addResourceFiles(files: FileList | File[]) {
    setResourceFiles((current) => mergeFiles(current, Array.from(files)));
  }

  function removeResourceFile(target: File) {
    const targetKey = fileKey(target);
    setResourceFiles((current) => current.filter((file) => fileKey(file) !== targetKey));
  }

  async function handleCreateFromPrompt() {
    setSavingPrompt(true);
    setFormError(null);
    try {
      const saved =
        resourceFiles.length > 0
          ? await createCustomSkillPackage(prompt.trim(), resourceFiles)
          : await createCustomSkillFromPrompt(prompt.trim());
      toast.show(`Skill "${saved.name}" dibuat dan agent dimuat ulang`, "success");
      setPrompt("");
      setResourceFiles([]);
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
      setSkills((current) => current.filter((item) => item.id !== skill.id));
      toast.show(`Skill "${skill.name}" dihapus dan agent dimuat ulang`, "success");
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
              deskripsi, trigger, instruksi, dependency tool opsional, references, assets,
              examples, dan versi dalam paket Agent Skill. Script baru dibuat lewat Fungsi
              Kustom saat memang diperlukan.
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

        <div className="custom-skills__upload">
          <input
            aria-label="Upload SOP, knowledge, contoh, atau template"
            className="custom-skills__file-input"
            ref={resourceInputRef}
            type="file"
            multiple
            onChange={(event) => addResourceFiles(event.target.files ?? [])}
          />
          <div className="custom-skills__upload-shell">
            <button
              type="button"
              className={`custom-skills__dropzone${isDraggingResource ? " custom-skills__dropzone--active" : ""}`}
              onClick={() => resourceInputRef.current?.click()}
              onDragEnter={(event) => {
                event.preventDefault();
                setIsDraggingResource(true);
              }}
              onDragOver={(event) => {
                event.preventDefault();
                setIsDraggingResource(true);
              }}
              onDragLeave={() => setIsDraggingResource(false)}
              onDrop={(event) => {
                event.preventDefault();
                setIsDraggingResource(false);
                addResourceFiles(event.dataTransfer.files);
              }}
            >
              <svg
                className="custom-skills__drop-icon"
                viewBox="0 0 48 48"
                aria-hidden="true"
                focusable="false"
              >
                <path d="M24 30V8" />
                <path d="M15 17l9-9 9 9" />
                <path d="M15 24h-3a5 5 0 0 0-5 5v8a5 5 0 0 0 5 5h24a5 5 0 0 0 5-5v-8a5 5 0 0 0-5-5h-3" />
              </svg>
              <strong>Drag and drop file here</strong>
              <span className="custom-skills__drop-separator">-OR-</span>
              <span className="custom-skills__browse-button">Browse Files</span>
              <small>{selectedFileSummary(resourceFiles)}</small>
            </button>
            <section className="custom-skills__upload-list" aria-label="File resource terpilih">
              <div className="custom-skills__upload-list-header">
                <strong>Upload Files</strong>
                <span>{resourceFiles.length} file</span>
              </div>
              {resourceFiles.length > 0 ? (
                <ul className="custom-skills__file-list">
                  {resourceFiles.map((file) => (
                    <li key={fileKey(file)}>
                      <span className="custom-skills__file-badge">{fileExtension(file)}</span>
                      <span className="custom-skills__file-main">
                        <span className="custom-skills__file-name">{file.name}</span>
                        <span className="custom-skills__file-bar" aria-hidden="true">
                          <span />
                        </span>
                      </span>
                      <button
                        type="button"
                        className="custom-skills__file-remove"
                        onClick={() => removeResourceFile(file)}
                      >
                        Hapus
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="custom-skills__upload-empty">
                  File SOP, reference, contoh, atau template akan tampil di sini.
                </div>
              )}
            </section>
          </div>
        </div>

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
                  {skill.context_chars} karakter konteks | {toolingSummary(skill)} |{" "}
                  {resourceSummary(skill)}
                </span>
                {(skill.tooling?.required?.length ?? 0) > 0 && (
                  <div className="custom-skills__tooling">
                    {skill.tooling?.required.map((tool) => (
                      <code key={`${tool.capability}-${tool.name ?? tool.status}`}>
                        {tool.status === "available"
                          ? `${tool.type === "mcp" ? "MCP" : "Fungsi"}: ${tool.name}`
                          : `${tool.label}: belum tersedia`}
                      </code>
                    ))}
                  </div>
                )}
                {skill.resources && (
                  <div className="custom-skills__resources">
                    {skill.template_tool && <code>tool: {skill.template_tool}</code>}
                    {(["references", "assets", "examples", "scripts"] as const).flatMap((bucket) =>
                      (skill.resources?.[bucket] ?? []).map((resource) => (
                        <code key={`${bucket}-${resource.path ?? resource.filename}`}>
                          {bucket}: {resource.path ?? resource.filename}
                        </code>
                      )),
                    )}
                  </div>
                )}
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
