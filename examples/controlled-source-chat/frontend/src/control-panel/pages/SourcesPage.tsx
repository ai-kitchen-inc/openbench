import { SourcesSection } from "../SourcesSection";

export function SourcesPage() {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Semua yang dapat ditanyakan pengguna. Asisten hanya menjawab dari sumber-sumber ini dan
          menyebutkan nama sumbernya sebagai kutipan.
        </div>
      </div>
      <SourcesSection />
    </>
  );
}
