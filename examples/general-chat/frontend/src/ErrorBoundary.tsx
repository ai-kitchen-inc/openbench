import { Component, type ErrorInfo, type ReactNode } from "react";

interface ErrorBoundaryProps {
  children: ReactNode;
  region?: string;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(
      `[ErrorBoundary${this.props.region ? ` @ ${this.props.region}` : ""}]`,
      error,
      info.componentStack,
    );
  }

  private _reset = () => this.setState({ error: null });

  render() {
    const { error } = this.state;
    if (error === null) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this._reset);

    const region = this.props.region ?? "this area";
    return (
      <div className="error-boundary" role="alert">
        <div className="error-boundary__panel">
          <div className="error-boundary__title">Something went wrong in {region}.</div>
          <div className="error-boundary__detail">{error.message}</div>
          <div className="error-boundary__actions">
            <button type="button" className="error-boundary__btn" onClick={this._reset}>
              Try again
            </button>
            <button
              type="button"
              className="error-boundary__btn error-boundary__btn--primary"
              onClick={() => window.location.reload()}
            >
              Reload page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
