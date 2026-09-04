import { Component, type ReactNode } from "react";

/** Catches a render crash inside one page so the shell (nav, HALT, toasts) stays usable and the user
 *  gets a way back — a blank screen with a console stack was the failure mode (2026-09-04, the EM
 *  page's Analyse tab). Resets when the page changes. */
export class PageErrorBoundary extends Component<{ page: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidUpdate(prev: { page: string }) {
    if (prev.page !== this.props.page && this.state.error) this.setState({ error: null });
  }

  componentDidCatch(error: Error, info: { componentStack?: string }) {
    console.error("page crashed:", this.props.page, error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    const e = this.state.error;
    return (
      <div className="panel" style={{ margin: 16, maxWidth: 720 }}>
        <div className="panel-head">This page hit an error</div>
        <div className="panel-body">
          <p className="small">The rest of the app is still running. Reload the page, or clear this page\'s saved state if it keeps happening.</p>
          <pre className="small muted" style={{ whiteSpace: "pre-wrap" }}>{String(e?.message || e)}</pre>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="primary-btn" onClick={() => this.setState({ error: null })}>try again</button>
            <button className="ghost-btn" onClick={() => window.location.reload()}>reload</button>
            <button className="ghost-btn" onClick={() => {
              try { Object.keys(localStorage).filter((k) => k.startsWith("zargar_tq_") || k.startsWith("zargar_armed")).forEach((k) => localStorage.removeItem(k)); } catch { /* private mode */ }
              window.location.reload();
            }}>clear saved page state and reload</button>
          </div>
        </div>
      </div>
    );
  }
}
