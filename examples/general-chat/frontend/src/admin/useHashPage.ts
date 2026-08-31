import { useCallback, useEffect, useState } from "react";

export type AdminPage =
  | "ringkasan"
  | "sumber"
  | "persona"
  | "agen"
  | "kemampuan"
  | "pengaturan"
  | "pengguna"
  | "grup"
  | "mcp"
  | "fungsi"
  | "skill"
  | "audit"
  | "penggunaan"
  | "chat";

const DEFAULT_PAGE: AdminPage = "ringkasan";
const VALID_PAGES: readonly AdminPage[] = [
  "ringkasan",
  "sumber",
  "persona",
  "agen",
  "kemampuan",
  "pengaturan",
  "pengguna",
  "grup",
  "mcp",
  "fungsi",
  "skill",
  "audit",
  "penggunaan",
  "chat",
];

function readHash(): AdminPage {
  const slug = window.location.hash.replace(/^#\/?/, "");
  return (VALID_PAGES as readonly string[]).includes(slug) ? (slug as AdminPage) : DEFAULT_PAGE;
}

/** Router-free page state synced to location.hash (#/ringkasan, #/sumber,
 * #/persona, ...) so admin pages survive reload and are linkable. */
export function useHashPage(): [AdminPage, (page: AdminPage) => void] {
  const [page, setPageState] = useState<AdminPage>(readHash);

  useEffect(() => {
    const onHashChange = () => setPageState(readHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setPage = useCallback((next: AdminPage) => {
    window.location.hash = `#/${next}`;
    setPageState(next);
  }, []);

  return [page, setPage];
}
