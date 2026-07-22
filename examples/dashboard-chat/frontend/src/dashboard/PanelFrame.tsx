import { AlertCircle, RotateCw } from "lucide-react";
import { Component, type ReactNode } from "react";

/** Catches render crashes inside a single panel so one malformed spec
 * (e.g. an unexpected field shape from the agent) can never blank the
 * whole canvas. */
export class PanelErrorBoundary extends Component<
  { title: string; children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <section className="panel">
          <header className="panel__header">
            <h3 className="panel__title">{this.props.title}</h3>
          </header>
          <div className="panel__body">
            <div className="panel__error" role="alert">
              <AlertCircle size={16} strokeWidth={1.5} />
              <span>This panel could not render: {this.state.error.message}</span>
            </div>
          </div>
        </section>
      );
    }
    return this.props.children;
  }
}

/** Card chrome shared by every panel: title row, skeleton, error state. */
export function PanelFrame({
  title,
  isLoading,
  error,
  onRetry,
  meta,
  children,
}: {
  title: string;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  meta?: string;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <header className="panel__header">
        <h3 className="panel__title">{title}</h3>
        {meta && <span className="panel__meta">{meta}</span>}
      </header>
      <div className="panel__body">
        {isLoading ? (
          <div className="panel__skeleton" aria-hidden="true">
            <div className="panel__skeleton-bar" />
            <div className="panel__skeleton-bar" />
            <div className="panel__skeleton-bar" />
          </div>
        ) : error ? (
          <div className="panel__error" role="alert">
            <AlertCircle size={16} strokeWidth={1.5} />
            <span>{error}</span>
            <button type="button" className="panel__retry" onClick={onRetry}>
              <RotateCw size={14} strokeWidth={1.5} /> Retry
            </button>
          </div>
        ) : (
          children
        )}
      </div>
    </section>
  );
}
