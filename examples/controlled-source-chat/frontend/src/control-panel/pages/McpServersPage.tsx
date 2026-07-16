import { McpCatalog } from "../../mcp-catalog/McpCatalogPanel";

export function McpServersPage() {
  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Perangkat (tools) yang dapat dipanggil asisten saat percakapan. Hasil perangkat dihitung
          sebagai sumber yang dapat dikutip.
        </div>
      </div>
      <McpCatalog />
    </>
  );
}
