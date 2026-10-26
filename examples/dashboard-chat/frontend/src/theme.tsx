import { useEffect, useState } from "react";

const THEME_STORAGE_KEY = "dashboard-chat-theme";

function loadInitialDark(): boolean {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "dark") return true;
    if (stored === "light") return false;
  } catch {
    // Storage unavailable (private mode) — fall through to OS preference.
  }
  if (typeof window !== "undefined") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  }
  return false;
}

export function useDarkMode() {
  const [dark, setDark] = useState(loadInitialDark);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, dark ? "dark" : "light");
    } catch {
      // Ignore — theme still applies for the session without persistence.
    }
  }, [dark]);

  return [dark, () => setDark((current) => !current)] as const;
}
