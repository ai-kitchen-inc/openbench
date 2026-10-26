import { useState } from "react";
import { FunctionsPanel } from "../../functions/FunctionsPanel";

/** Hosts the existing general-chat custom function manager. The manager is a
 * self-contained dialog, so the page keeps an open/close state instead of
 * embedding it inline. */
export function FunctionsPage() {
  const [open, setOpen] = useState(true);

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Fungsi kustom (endpoint HTTP) yang didaftarkan sebagai alat tambahan bagi asisten.
        </div>
      </div>
      <section className="panel-section" aria-label="Fungsi kustom">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Pengelola Fungsi Kustom</div>
            <div className="panel-section__subtitle">
              Tambahkan, uji, dan hapus fungsi kustom yang dapat dipanggil asisten.
            </div>
          </div>
          <button type="button" className="panel-button panel-button--primary" onClick={() => setOpen(true)}>
            Buka Pengelola
          </button>
        </div>
      </section>
      <FunctionsPanel open={open} onClose={() => setOpen(false)} />
    </>
  );
}
