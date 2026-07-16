import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useToast } from "../Toast";
import { deleteFunction, listFunctions, runFunction, saveFunction } from "./api";
import type { CustomFunction, FunctionRunResult } from "./types";

const CODE_PLACEHOLDER = `def add(a, b):
    """Return the sum of a and b."""
    return a + b
`;

function Dialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = "";
      previous?.focus();
    };
  }, [onClose]);

  return (
    <div
      className="mcp-dialog"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <div
        className="mcp-dialog__panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="mcp-dialog__header">
          <h2>{title}</h2>
          <button type="button" className="mcp-btn" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function FunctionsPanel({
  open,
  onClose,
  embedded = false,
}: {
  open: boolean;
  onClose: () => void;
  embedded?: boolean;
}) {
  const toast = useToast();
  const [functions, setFunctions] = useState<CustomFunction[]>([]);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [code, setCode] = useState(CODE_PLACEHOLDER);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [runArgs, setRunArgs] = useState("{}");
  const [runTarget, setRunTarget] = useState<string | null>(null);
  const [runResult, setRunResult] = useState<FunctionRunResult | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setFunctions(await listFunctions());
    } catch (error) {
      toast.show(error instanceof Error ? error.message : "Failed to load functions", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  if (!open) return null;

  async function handleSave() {
    setSaving(true);
    setFormError(null);
    try {
      await saveFunction(name.trim(), code, description.trim());
      toast.show(`Saved function "${name.trim()}"`, "success");
      await load();
    } catch (error) {
      setFormError(error instanceof Error ? error.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(fnName: string) {
    try {
      await deleteFunction(fnName);
      toast.show(`Deleted "${fnName}"`, "success");
      await load();
    } catch (error) {
      toast.show(error instanceof Error ? error.message : "Delete failed", "error");
    }
  }

  async function handleRun(fnName: string) {
    setRunning(true);
    setRunTarget(fnName);
    setRunResult(null);
    try {
      let kwargs: Record<string, unknown> = {};
      if (runArgs.trim()) {
        const parsed: unknown = JSON.parse(runArgs);
        if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
          throw new Error("Arguments must be a JSON object, e.g. {\"a\": 2}");
        }
        kwargs = parsed as Record<string, unknown>;
      }
      setRunResult(await runFunction(fnName, kwargs));
    } catch (error) {
      setRunResult({ ok: false, error: error instanceof Error ? error.message : "Run failed" });
    } finally {
      setRunning(false);
    }
  }

  function handleEdit(fn: CustomFunction) {
    setName(fn.name);
    setDescription(fn.description ?? "");
    setCode(fn.code);
    setFormError(null);
  }

  const content = (
      <div className="mcp-catalog">
        <section className="mcp-section">
          <div className="mcp-section__header">
            <div>
              <h3>Define a function</h3>
              <p>
                One Python function per entry. The agent runs it in an isolated sandbox
                (no network, fixed libraries: pandas, numpy, matplotlib, openpyxl).
              </p>
            </div>
          </div>
          <label className="mcp-field">
            <span>Function name</span>
            <input
              value={name}
              placeholder="add_numbers"
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="mcp-field">
            <span>Description</span>
            <input
              value={description}
              placeholder="What does this function do?"
              onChange={(event) => setDescription(event.target.value)}
            />
          </label>
          <label className="mcp-field">
            <span>Python code</span>
            <textarea
              value={code}
              spellCheck={false}
              rows={12}
              onChange={(event) => setCode(event.target.value)}
            />
          </label>
          {formError && (
            <div className="mcp-state mcp-state--error" role="alert">
              {formError}
            </div>
          )}
          <div className="mcp-dialog__actions">
            <button
              type="button"
              className="mcp-btn mcp-btn--primary"
              onClick={() => void handleSave()}
              disabled={saving || !name.trim() || !code.trim()}
            >
              {saving ? "Saving…" : "Save function"}
            </button>
          </div>
        </section>

        <section className="mcp-section">
          <div className="mcp-section__header">
            <div>
              <h3>Saved functions</h3>
              <p>{functions.length} defined</p>
            </div>
            <div className="mcp-section__actions">
              <button type="button" className="mcp-btn" onClick={() => void load()}>
                Refresh
              </button>
            </div>
          </div>
          <label className="mcp-field">
            <span>Test arguments (JSON object)</span>
            <input
              value={runArgs}
              placeholder='{"a": 2, "b": 3}'
              onChange={(event) => setRunArgs(event.target.value)}
            />
          </label>
          {loading && <div className="mcp-state">Loading functions…</div>}
          {!loading && functions.length === 0 && (
            <div className="mcp-state">No functions yet — define one above.</div>
          )}
          <div className="mcp-config-list">
            {functions.map((fn) => (
              <div key={fn.name} className="mcp-section__header">
                <div>
                  <h3>{fn.name}</h3>
                  <p>{fn.description || "No description"}</p>
                </div>
                <div className="mcp-section__actions">
                  <button type="button" className="mcp-btn" onClick={() => handleEdit(fn)}>
                    Edit
                  </button>
                  <button
                    type="button"
                    className="mcp-btn"
                    onClick={() => void handleRun(fn.name)}
                    disabled={running}
                  >
                    {running && runTarget === fn.name ? "Running…" : "Test run"}
                  </button>
                  <button
                    type="button"
                    className="mcp-btn"
                    onClick={() => void handleDelete(fn.name)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
          {runResult && (
            <div
              className={runResult.ok ? "mcp-state" : "mcp-state mcp-state--error"}
              role={runResult.ok ? undefined : "alert"}
            >
              {runResult.ok ? (
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {`${runTarget} → ${JSON.stringify(runResult.result)}`}
                  {runResult.stdout ? `\nstdout: ${runResult.stdout}` : ""}
                </pre>
              ) : (
                `${runTarget ?? "run"} failed: ${runResult.error ?? "unknown error"}`
              )}
            </div>
          )}
        </section>
      </div>
  );

  if (embedded) {
    return content;
  }

  return (
    <Dialog title="Custom Functions" onClose={onClose}>
      {content}
    </Dialog>
  );
}
