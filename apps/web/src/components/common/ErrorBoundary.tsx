import { Component, type ReactNode } from "react";
import { ErrorAlert } from ".";

/**
 * Shows the render error instead of a blank page. "重新加载" reloads the page, or with
 * `retry` re-renders only this subtree (used for single OpenUI blocks).
 */
export class ErrorBoundary extends Component<{ children: ReactNode; retry?: boolean; style?: React.CSSProperties }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  componentDidCatch(error: Error) {
    console.error(error);
  }
  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <ErrorAlert error={error} style={this.props.style ?? { margin: 24 }}>
        <button className="btn xs" type="button" onClick={() => (this.props.retry ? this.setState({ error: null }) : window.location.reload())}>
          重新加载
        </button>
      </ErrorAlert>
    );
  }
}
