import { useCallback, useEffect, useState } from "react";
import { useToast } from "../Toast";
import { deleteCustomSkill, listCustomSkills, saveCustomSkill } from "./api";
import type { CustomSkill } from "./types";

const DEFAULT_INSTRUCTIONS = `Saat skill ini relevan, ikuti SOP berikut:
1. Pahami tujuan user dan konteks yang tersedia.
2. Gunakan istilah yang konsisten dengan domain skill.
3. Jika data tidak cukup, jelaskan asumsi dan minta input yang spesifik.
4. Tutup dengan hasil yang bisa langsung dipakai user.`;

function triggersFromText(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.replace(/^[-*]\s*/, "").trim())
    .filter(Boolean);
}

function textFromTriggers(triggers: string[]): string {
  return triggers.join("\n");
}

export function CustomSkillsPanel() {
  const toast = useToast();
  const [skills, setSkills] = useState<CustomSkill[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [triggers, setTriggers] = useState("");
  const [instructions, setInstructions] = useState(DEFAULT_INSTRUCTIONS);
  const [version, setVersion] = useState("0.1.0");

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

  function resetForm() {
    setId("");
    setName("");
    setDescription("");
    setTriggers("");
    setInstructions(DEFAULT_INSTRUCTIONS);
    setVersion("0.1.0");
    setFormError(null);
  }

  function handleEdit(skill: CustomSkill) {
    setId(skill.id);
    setName(skill.name);
    setDescription(skill.description ?? "");
    setTriggers(textFromTriggers(skill.triggers ?? []));
    setInstructions(skill.instructions || DEFAULT_INSTRUCTIONS);
    setVersion(skill.version || "0.1.0");
    setFormError(null);
  }

  async function handleSave() {
    setSaving(true);
    setFormError(null);
    try {
      const saved = await saveCustomSkill({
        id: id.trim(),
        name: name.trim(),
        description: description.trim(),
        triggers: triggersFromText(triggers),
        instructions: instructions.trim(),
        version: version.trim() || "0.1.0",
      });
      toast.show(`Skill "${saved.name}" tersimpan dan agent dimuat ulang`, "success");
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Gagal menyimpan skill");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(skill: CustomSkill) {
    try {
      await deleteCustomSkill(skill.id);
      toast.show(`Skill "${skill.name}" dihapus dan agent dimuat ulang`, "success");
      await load();
      if (id === skill.id) resetForm();
    } catch (error) {
      toast.show(error instanceof Error ? error.message : "Gagal menghapus skill", "error");
    }
  }

  return (
    <div className="mcp-catalog">
      <section className="mcp-section">
        <div className="mcp-section__header">
          <div>
            <h3>Definisikan skill</h3>
            <p>
              Skill tersimpan sebagai OpenBench Skill dan masuk ke prompt agent setelah disimpan.
            </p>
          </div>
          <div className="mcp-section__actions">
            <button type="button" className="mcp-btn" onClick={resetForm}>
              Kosongkan
            </button>
          </div>
        </div>
        <label className="mcp-field">
          <span>Skill ID</span>
          <input
            value={id}
            placeholder="id unik skill, huruf kecil dan tanda hubung"
            onChange={(event) => setId(event.target.value)}
          />
        </label>
        <label className="mcp-field">
          <span>Nama skill</span>
          <input
            value={name}
            placeholder="nama skill yang tampil di daftar"
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <label className="mcp-field">
          <span>Deskripsi</span>
          <input
            value={description}
            placeholder="ringkasan singkat tujuan atau kemampuan skill"
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label className="mcp-field">
          <span>Trigger, satu per baris</span>
          <textarea
            value={triggers}
            spellCheck={false}
            rows={4}
            placeholder={[
              "kondisi kapan skill perlu digunakan",
              "jenis permintaan user yang relevan",
              "kata kunci atau situasi pemicu",
            ].join("\n")}
            onChange={(event) => setTriggers(event.target.value)}
          />
        </label>
        <label className="mcp-field">
          <span>Instruksi skill</span>
          <textarea
            value={instructions}
            spellCheck={false}
            rows={12}
            placeholder="tulis SOP, aturan jawaban, format output, batasan, atau langkah kerja agent"
            onChange={(event) => setInstructions(event.target.value)}
          />
        </label>
        <label className="mcp-field">
          <span>Versi</span>
          <input
            value={version}
            placeholder="versi skill"
            onChange={(event) => setVersion(event.target.value)}
          />
        </label>
        {formError && (
          <div className="mcp-state mcp-state--error" role="alert">
            {formError}
          </div>
        )}
        <div className="mcp-dialog__actions">
          <button
            type="button"
            className="mcp-btn mcp-btn--primary"
            onClick={() => void handleSave()}
            disabled={saving || !id.trim() || !name.trim() || !instructions.trim()}
          >
            {saving ? "Menyimpan..." : "Simpan skill"}
          </button>
        </div>
      </section>

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
          <div className="mcp-state">Belum ada skill. Buat satu di formulir.</div>
        )}
        <div className="mcp-config-list">
          {skills.map((skill) => (
            <div key={skill.id} className="mcp-section__header">
              <div>
                <h3>{skill.name}</h3>
                <p>
                  {skill.description || "Tanpa deskripsi"} | ID: {skill.id} |{" "}
                  {skill.context_chars} karakter konteks
                </p>
              </div>
              <div className="mcp-section__actions">
                <button type="button" className="mcp-btn" onClick={() => handleEdit(skill)}>
                  Edit
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
