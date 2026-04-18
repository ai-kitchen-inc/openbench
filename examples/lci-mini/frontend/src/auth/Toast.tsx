/**
 * Tiny toast system — one host, N toasts stacked bottom-right.
 *
 * Deliberately minimal: no animations, no queueing strategy, no
 * portals. Designed for the auth layer's "sign-in failed" /
 * "Drive connect failed" / "Drive disconnected" signals where we just
 * need to tell the user something beyond a silent console.error.
 */

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type ToastKind = "info" | "success" | "error";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  show: (message: string, kind?: ToastKind, durationMs?: number) => number;
  dismiss: (id: number) => void;
  toasts: ToastItem[];
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION_MS = 4000;

export interface ToastProviderProps {
  children: ReactNode;
  /** Override default dismiss delay (ms). Set to 0 to disable auto-dismiss. */
  durationMs?: number;
}

export function ToastProvider({ children, durationMs = DEFAULT_DURATION_MS }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (message: string, kind: ToastKind = "info", overrideMs?: number) => {
      const id = _nextId();
      setToasts((prev) => [...prev, { id, kind, message }]);
      const effective = overrideMs ?? durationMs;
      if (effective > 0) {
        setTimeout(() => dismiss(id), effective);
      }
      return id;
    },
    [dismiss, durationMs],
  );

  const value = useMemo(() => ({ show, dismiss, toasts }), [show, dismiss, toasts]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastHost toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used inside <ToastProvider>");
  }
  return ctx;
}

/**
 * Optional version that returns a no-op when no provider is mounted —
 * lets components use toasts when available without making the
 * provider mandatory everywhere.
 */
export function useOptionalToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  return ctx ?? _noopToast;
}

function ToastHost({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    // No-op — keep hook presence consistent with React 19 rules.
  }, []);
  if (toasts.length === 0) return null;
  return (
    <div className="toast-host" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast toast--${t.kind}`}>
          <span className="toast__message">{t.message}</span>
          <button
            type="button"
            className="toast__close"
            onClick={() => onDismiss(t.id)}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

let _toastIdCounter = 0;
function _nextId(): number {
  _toastIdCounter += 1;
  return _toastIdCounter;
}

const _noopToast: ToastContextValue = {
  show: () => 0,
  dismiss: () => {},
  toasts: [],
};
