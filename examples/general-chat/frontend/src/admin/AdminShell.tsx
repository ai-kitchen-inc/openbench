import type { User } from "firebase/auth";
import type { ReactNode } from "react";
import type { Me } from "../account/api";
import { setLocalRole } from "../api";
import { BrandMark } from "../brand/BrandMark";
import {
  BookIcon,
  CodeIcon,
  LayoutIcon,
  MessageIcon,
  PersonaIcon,
  ServerIcon,
  SettingsIcon,
  SlidersIcon,
  UsersIcon,
} from "../brand/icons";
import { UserChat } from "../chat/UserChat";
import { APP_NAME, APP_TAGLINE, COMMON, LOCAL_ROLE } from "../i18n/id";
import { ThemeIcon, useDarkMode } from "../theme";
import { CapabilitiesPage } from "./pages/CapabilitiesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { FunctionsPage } from "./pages/FunctionsPage";
import { McpServersPage } from "./pages/McpServersPage";
import { PersonaPage } from "./pages/PersonaPage";
import { SettingsPage } from "./pages/SettingsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { UsersPage } from "./pages/UsersPage";
import { useHashPage, type AdminPage } from "./useHashPage";

const NAV_ITEMS: { page: AdminPage; label: string; icon: ReactNode }[] = [
  { page: "ringkasan", label: "Ringkasan", icon: <LayoutIcon /> },
  { page: "sumber", label: "Sumber Global", icon: <BookIcon /> },
  { page: "persona", label: "Persona", icon: <PersonaIcon /> },
  { page: "kemampuan", label: "Kemampuan", icon: <SlidersIcon /> },
  { page: "pengaturan", label: "Pengaturan", icon: <SettingsIcon /> },
  { page: "pengguna", label: "Pengguna", icon: <UsersIcon /> },
  { page: "mcp", label: "Server MCP", icon: <ServerIcon /> },
  { page: "fungsi", label: "Fungsi Kustom", icon: <CodeIcon /> },
  { page: "chat", label: "Buka Chat", icon: <MessageIcon /> },
];

const PAGE_TITLES: Record<AdminPage, string> = {
  ringkasan: "Ringkasan",
  sumber: "Sumber Global",
  persona: "Persona",
  kemampuan: "Kemampuan",
  pengaturan: "Pengaturan",
  pengguna: "Pengguna",
  mcp: "Server MCP",
  fungsi: "Fungsi Kustom",
  chat: "Buka Chat",
};

export function AdminShell({
  me,
  user,
  onSignOut,
}: {
  me: Me;
  user: User | null;
  onSignOut: () => void;
}) {
  const [dark, toggleDark] = useDarkMode();
  const [page, setPage] = useHashPage();
  const email = me.email || user?.email || "";

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
              {email.slice(0, 1).toUpperCase()}
            </span>
            <span className="admin-sidebar__user-info">
              <span className="admin-sidebar__username" title={email}>
                {email}
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
            {me.authDisabled && (
              <button
                type="button"
                className="admin-sidebar__signout"
                onClick={() => {
                  setLocalRole("user");
                  window.location.reload();
                }}
              >
                {LOCAL_ROLE.viewAsUser}
              </button>
            )}
            <button type="button" className="admin-sidebar__signout" onClick={onSignOut}>
              {COMMON.signOut}
            </button>
          </div>
        </div>
      </aside>
      {page === "chat" ? (
        // Full-width embedded chat: the admin talks to the exact chat users
        // get (admins carry all capabilities from /account/me).
        <div className="admin-chat-host">
          <UserChat me={me} user={user} onSignOut={onSignOut} />
        </div>
      ) : (
        <div className="admin-content">
          <div className="admin-main">
            <header className="admin-topbar">
              <div className="admin-topbar__title">{PAGE_TITLES[page]}</div>
            </header>
            <main className="admin-page">
              <div className="admin-page__inner">
                {page === "ringkasan" && <DashboardPage onNavigate={setPage} />}
                {page === "sumber" && <SourcesPage />}
                {page === "persona" && <PersonaPage />}
                {page === "kemampuan" && <CapabilitiesPage />}
                {page === "pengaturan" && <SettingsPage />}
                {page === "pengguna" && <UsersPage currentEmail={me.email} />}
                {page === "mcp" && <McpServersPage />}
                {page === "fungsi" && <FunctionsPage />}
              </div>
            </main>
          </div>
        </div>
      )}
    </div>
  );
}
