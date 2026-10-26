import { useState, type ReactNode } from "react";
import type { AuthUser } from "../api";
import { BrandMark } from "../brand/BrandMark";
import { BookIcon, LayoutIcon, MessageIcon, ServerIcon, UsersIcon } from "../brand/icons";
import { APP_NAME, APP_TAGLINE, COMMON } from "../i18n/id";
import { ThemeIcon, useDarkMode } from "../theme";
import { DashboardPage } from "./pages/DashboardPage";
import { McpServersPage } from "./pages/McpServersPage";
import { SourcesPage } from "./pages/SourcesPage";
import { UsersPage } from "./pages/UsersPage";
import { TestChatDock } from "./TestChatDock";
import { useHashPage, type AdminPage } from "./useHashPage";

const NAV_ITEMS: { page: AdminPage; label: string; icon: ReactNode }[] = [
  { page: "ringkasan", label: "Ringkasan", icon: <LayoutIcon /> },
  { page: "sumber", label: "Sumber Pengetahuan", icon: <BookIcon /> },
  { page: "mcp", label: "Server MCP", icon: <ServerIcon /> },
  { page: "pengguna", label: "Pengguna", icon: <UsersIcon /> },
];

const PAGE_TITLES: Record<AdminPage, string> = {
  ringkasan: "Ringkasan",
  sumber: "Sumber Pengetahuan",
  mcp: "Server MCP",
  pengguna: "Pengguna",
};

export function AdminShell({ user, onSignOut }: { user: AuthUser; onSignOut: () => void }) {
  const [dark, toggleDark] = useDarkMode();
  const [page, setPage] = useHashPage();
  // Open by default so the admin lands with a live preview of the guest
  // experience; it docks beside the pages (not a modal) and survives page
  // switches without remounting, so the conversation state is kept.
  const [testChatOpen, setTestChatOpen] = useState(true);

  return (
    <div className="admin-shell">
      <aside className="admin-sidebar">
        <div className="admin-sidebar__brand">
          <BrandMark size={38} />
          <span className="brand-lockup__text">
            <span className="brand-lockup__name">{APP_NAME}</span>
            <span className="brand-lockup__tagline">{APP_TAGLINE}</span>
          </span>
        </div>
        <nav className="admin-nav" aria-label="Navigasi admin">
          <div className="admin-nav__label">Panel Kendali</div>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.page}
              type="button"
              className={`admin-nav__item${page === item.page ? " admin-nav__item--active" : ""}`}
              aria-current={page === item.page ? "page" : undefined}
              onClick={() => setPage(item.page)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="admin-sidebar__footer">
          <div className="admin-sidebar__user">
            <span className="admin-sidebar__avatar" aria-hidden="true">
              {user.username.slice(0, 1)}
            </span>
            <span className="admin-sidebar__user-info">
              <span className="admin-sidebar__username" title={user.username}>
                {user.username}
              </span>
              <span className="admin-sidebar__role">Administrator</span>
            </span>
          </div>
          <div className="admin-sidebar__footer-actions">
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleDark}
              title={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
              aria-label={dark ? "Beralih ke mode terang" : "Beralih ke mode gelap"}
            >
              <ThemeIcon dark={dark} />
            </button>
            <button type="button" className="admin-sidebar__signout" onClick={onSignOut}>
              {COMMON.signOut}
            </button>
          </div>
        </div>
      </aside>
      <div className="admin-content">
        <div className="admin-main">
          <header className="admin-topbar">
            <div className="admin-topbar__title">{PAGE_TITLES[page]}</div>
            <button
              type="button"
              className={`btn${testChatOpen ? "" : " btn--primary"}`}
              onClick={() => setTestChatOpen((open) => !open)}
            >
              <MessageIcon size={14} />
              {testChatOpen ? "Sembunyikan Uji Coba Chat" : "Uji Coba Chat"}
            </button>
          </header>
          <main className="admin-page">
            <div className="admin-page__inner">
              {page === "ringkasan" && <DashboardPage onNavigate={setPage} />}
              {page === "sumber" && <SourcesPage />}
              {page === "mcp" && <McpServersPage />}
              {page === "pengguna" && <UsersPage currentUsername={user.username} />}
            </div>
          </main>
        </div>
        {testChatOpen && <TestChatDock onClose={() => setTestChatOpen(false)} />}
      </div>
    </div>
  );
}
