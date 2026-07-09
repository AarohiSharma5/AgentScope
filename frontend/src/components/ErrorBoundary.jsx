import { Component } from "react";

// Top-level guard so a render error in one page shows a recoverable fallback
// instead of white-screening the whole SPA.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  handleReload = () => {
    this.setState({ error: null });
    window.location.reload();
  };

  render() {
    if (!this.state.error) {
      return this.props.children;
    }
    return (
      <div
        role="alert"
        className="mx-auto mt-16 max-w-lg rounded-xl border border-ink-500 bg-ink-800/50 px-6 py-10 text-center"
      >
        <div
          aria-hidden
          className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full border border-red-500/40 bg-red-500/10 text-xl text-red-400"
        >
          !
        </div>
        <p className="text-base font-semibold text-gray-100">
          Something went wrong
        </p>
        <p className="mt-2 text-sm text-gray-500">
          The dashboard hit an unexpected error while rendering this view.
        </p>
        {this.state.error?.message && (
          <pre className="mt-4 overflow-auto rounded-lg bg-ink-900 px-3 py-2 text-left text-xs text-gray-400">
            {String(this.state.error.message)}
          </pre>
        )}
        <button
          type="button"
          onClick={this.handleReload}
          className="mt-6 rounded-lg border border-ink-500 bg-ink-700 px-4 py-2 text-sm text-gray-200 transition-colors hover:bg-ink-600"
        >
          Reload
        </button>
      </div>
    );
  }
}
