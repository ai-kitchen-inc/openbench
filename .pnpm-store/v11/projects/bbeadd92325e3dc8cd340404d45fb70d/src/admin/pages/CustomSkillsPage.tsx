import { CustomSkillsPanel } from "../../custom-skills/CustomSkillsPanel";

export function CustomSkillsPage() {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Skill kustom yang menambahkan instruksi dan SOP khusus ke agent General Chat.
        </div>
      </div>
      <section className="panel-section" aria-label="Skill kustom">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Pengelola Skill Kustom</div>
            <div className="panel-section__subtitle">
              Tambahkan skill knowledge-only agar agent mengenali kebutuhan tugas khusus.
            </div>
          </div>
        </div>
        <CustomSkillsPanel />
      </section>
    </>
  );
}
