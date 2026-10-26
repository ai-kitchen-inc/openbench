import { useEffect, useState } from "react";
import { AlertIcon, BookIcon, ServerIcon, UsersIcon } from "../../brand/icons";
import { listServers } from "../../mcp-catalog/api";
import type { RegisteredMCPServer } from "../../mcp-catalog/types";
import { listSources, readErrorMessage, sourceKindLabel, type SourceItem } from "../sourcesApi";
import { listUsers, type UserItem } from "../usersApi";
import type { AdminPage } from "../useHashPage";

type Loadable<T> = { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

async function toLoadable<T>(promise: Promise<T>): Promise<Loadable<T>> {
  try {
    return { status: "ready", data: await promise };
  } catch (error) {
    return { status: "error", message: readErrorMessage(error) };
  }
}

/** Ringkasan: live counts assembled from the existing list endpoints —
 * no dedicated dashboard API. */
export function DashboardPage({ onNavigate }: { onNavigate: (page: AdminPage) => void }) {
  const [sources, setSources] = useState<Loadable<SourceItem[]>>({ status: "loading" });
  const [users, setUsers] = useState<Loadable<UserItem[]>>({ status: "loading" });
  const [servers, setServers] = useState<Loadable<RegisteredMCPServer[]>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    void toLoadable(listSources()).then((result) => {
      if (!cancelled) setSources(result);
    });
    void toLoadable(listUsers()).then((result) => {
      if (!cancelled) setUsers(result);
    });
    void toLoadable(listServers().then((payload) => payload.servers)).then((result) => {
      if (!cancelled) setServers(result);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const failedSources =
    sources.status === "ready" ? sources.data.filter((s) => s.status === "failed") : [];
  const recentSources =
    sources.status === "ready"
      ? [...sources.data]
          .sort((a, b) => (b.createdAt ?? "").localeCompare(a.createdAt ?? ""))
          .slice(0, 5)
      : [];

  return (
    <>
      <div className="admin-page__header">
        <div className="admin-page__desc">
          Pantau kondisi basis pengetahuan, akun pengguna, dan perangkat MCP dalam satu tampilan.
        </div>
      </div>

      {failedSources.length > 0 && (
        <div className="dash-banner" role="alert">
          <AlertIcon size={16} />
          <span>
            {failedSources.length} sumber gagal diproses. Buka halaman Sumber Pengetahuan untuk
            memeriksa dan mengunggah ulang.
          </span>
        </div>
      )}

      <div className="dash-grid">
        <StatCard
          label="Sumber Pengetahuan"
          icon={<BookIcon />}
          state={sources}
          onClick={() => onNavigate("sumber")}
          value={(items) => items.length}
          meta={(items) => {
            const ready = items.filter((s) => s.status === "ready").length;
            const processing = items.filter((s) => s.status === "processing").length;
            const failed = items.filter((s) => s.status === "failed").length;
            return (
              <>
                <span className="status-pill status-pill--success">{ready} siap</span>
                {processing > 0 && (
                  <span className="status-pill status-pill--warning">{processing} diproses</span>
                )}
                {failed > 0 && (
                  <span className="status-pill status-pill--danger">{failed} gagal</span>
                )}
              </>
            );
          }}
        />
        <StatCard
          label="Pengguna"
          icon={<UsersIcon />}
          state={users}
          onClick={() => onNavigate("pengguna")}
          value={(items) => items.length}
          meta={(items) => {
            const admins = items.filter((u) => u.role === "admin").length;
            return (
              <>
                <span className="status-pill status-pill--info">{admins} admin</span>
                <span className="status-pill status-pill--info">{items.length - admins} tamu</span>
              </>
            );
          }}
        />
        <StatCard
          label="Server MCP"
          icon={<ServerIcon />}
          state={servers}
          onClick={() => onNavigate("mcp")}
          value={(items) => items.length}
          meta={(items) => {
            const enabled = items.filter((s) => s.enabled).length;
            const tools = items.reduce((sum, s) => sum + (s.enabledToolsCount ?? 0), 0);
            return (
              <>
                <span className="status-pill status-pill--success">{enabled} aktif</span>
                <span className="status-pill status-pill--info">{tools} alat aktif</span>
              </>
            );
          }}
        />
      </div>

      <section className="panel-section" aria-label="Sumber terbaru">
        <div className="panel-section__header">
          <div>
            <div className="panel-section__title">
              <BookIcon />
              Sumber Terbaru
            </div>
            <div className="panel-section__subtitle">
              Lima sumber yang paling baru ditambahkan ke basis pengetahuan.
            </div>
          </div>
          <button type="button" className="btn" onClick={() => onNavigate("sumber")}>
            Kelola Sumber
          </button>
        </div>
        <div className="panel-section__body">
          {sources.status === "loading" && <div className="sources-list__empty">Memuat sumber...</div>}
          {sources.status === "error" && (
            <div className="sources-list__empty">Gagal memuat sumber: {sources.message}</div>
          )}
          {sources.status === "ready" && recentSources.length === 0 && (
            <div className="sources-list__empty">
              Belum ada sumber. Tambahkan dokumen, teks, atau URL pada halaman Sumber Pengetahuan.
            </div>
          )}
          {recentSources.length > 0 && (
            <div className="sources-list">
              {recentSources.map((source) => (
                <div key={source.id} className="source-row">
                  <div className="source-row__badge">{sourceKindLabel(source)}</div>
                  <div className="source-row__main">
                    <div className="source-row__name">{source.name}</div>
                  </div>
                  <StatusPill status={source.status} />
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </>
  );
}

function StatusPill({ status }: { status: SourceItem["status"] }) {
  if (status === "ready") return <span className="status-pill status-pill--success">Siap</span>;
  if (status === "processing")
    return <span className="status-pill status-pill--warning">Diproses</span>;
  return <span className="status-pill status-pill--danger">Gagal</span>;
}

function StatCard<T>({
  label,
  icon,
  state,
  value,
  meta,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  state: Loadable<T[]>;
  value: (items: T[]) => number;
  meta: (items: T[]) => React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button type="button" className="dash-card" onClick={onClick}>
      <div className="dash-card__head">
        <span className="dash-card__label">{label}</span>
        {icon}
      </div>
      {state.status === "loading" && <div className="dash-skeleton" aria-label="Memuat" />}
      {state.status === "error" && <div className="dash-card__error">{state.message}</div>}
      {state.status === "ready" && (
        <>
          <div className="dash-card__value">{value(state.data)}</div>
          <div className="dash-card__meta">{meta(state.data)}</div>
        </>
      )}
    </button>
  );
}
