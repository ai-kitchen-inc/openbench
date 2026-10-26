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

/** Optional query params carried after the page slug: `#/mcp?tambah=1`. */
export type HashParams = Record<string, string>;

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

type HashState = { page: AdminPage; params: HashParams };

function parseHash(): HashState {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const queryAt = raw.indexOf("?");
  const slug = queryAt === -1 ? raw : raw.slice(0, queryAt);
  const query = queryAt === -1 ? "" : raw.slice(queryAt + 1);
  if (!(VALID_PAGES as readonly string[]).includes(slug)) {
    return { page: DEFAULT_PAGE, params: {} };
  }
  return { page: slug as AdminPage, params: Object.fromEntries(new URLSearchParams(query)) };
}

function formatHash(page: AdminPage, params?: HashParams): string {
  const query = params ? new URLSearchParams(params).toString() : "";
  return query ? `#/${page}?${query}` : `#/${page}`;
}

/** Router-free page state synced to location.hash (#/ringkasan, #/sumber,
 * #/persona, ...) so admin pages survive reload and are linkable. A page
 * may carry query params (`#/mcp?tambah=1`) for deep links into a page's
 * sub-state; they are returned as the third tuple item. */
export function useHashPage(): [
  AdminPage,
  (page: AdminPage, params?: HashParams) => void,
  HashParams,
] {
  const [state, setState] = useState<HashState>(parseHash);

  useEffect(() => {
    const onHashChange = () => setState(parseHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const setPage = useCallback((next: AdminPage, params?: HashParams) => {
    window.location.hash = formatHash(next, params);
    setState({ page: next, params: params ?? {} });
  }, []);

  return [state.page, setPage, state.params];
}
