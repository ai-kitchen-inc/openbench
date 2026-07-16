import { useState } from "react";
import { McpCatalogPanel } from "../../mcp-catalog/McpCatalogPanel";

/** Hosts the existing general-chat MCP catalog manager. The manager is a
 * self-contained dialog, so the page keeps an open/close state instead of
 * embedding it inline. */
export function McpServersPage() {
  const [open, setOpen] = useState(true);

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Perangkat (tools) yang dapat dipanggil asisten saat percakapan: server MCP,
          katalog ToolHive, dan alat per server.
        </div>
      </div>
      <section className="panel-section" aria-label="Server MCP">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">Pengelola Server MCP</div>
            <div className="panel-section__subtitle">
              Daftarkan server MCP, aktifkan/nonaktifkan server, dan pilih alat yang tersedia.
            </div>
          </div>
          <button type="button" className="panel-button panel-button--primary" onClick={() => setOpen(true)}>
            Buka Pengelola
          </button>
        </div>
      </section>
      <McpCatalogPanel open={open} onClose={() => setOpen(false)} />
    </>
  );
}
