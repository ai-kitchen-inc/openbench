import { useCallback, useEffect, useState } from "react";

export type AdminPage = "ringkasan" | "sumber" | "mcp" | "pengguna";

const DEFAULT_PAGE: AdminPage = "ringkasan";
const VALID_PAGES: readonly AdminPage[] = ["ringkasan", "sumber", "mcp", "pengguna"];

function readHash(): AdminPage {
  const slug = window.location.hash.replace(/^#\/?/, "");
  return (VALID_PAGES as readonly string[]).includes(slug) ? (slug as AdminPage) : DEFAULT_PAGE;
}

/** Router-free page state synced to location.hash (#/ringkasan, #/sumber,
 * #/mcp, #/pengguna) so admin pages survive reload and are linkable. */
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
