import { SourcesSection } from "../SourcesSection";

export function SourcesPage() {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Sumber global yang menjadi landasan setiap percakapan. Semua pengguna dapat melihat
          daftar ini dan asisten mengutip nama sumbernya dalam jawaban.
        </div>
      </div>
      <SourcesSection />
    </>
  );
}
