import { Component, type ReactNode } from 'react';

interface ErrorBoundaryState {
  readonly error: Error | null;
}

/**
 * The app's top-level safety net.
 *
 * Found necessary directly, not speculatively: with none, a render error
 * anywhere in the tree unmounts the whole app to a blank `<div id="root">`
 * with nothing in the DOM to say why — React logs a warning recommending
 * exactly this component, but only to the console, which a user never
 * opens. This is deliberately the *only* error boundary: one top-level net
 * that shows what broke and lets a developer copy the message, not a
 * per-feature scattering that would each need its own recovery UI.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, ErrorBoundaryState> {
  override state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  override componentDidCatch(error: Error, info: { componentStack?: string }): void {
    // The console is still the right place for the full stack — this UI's
    // job is to make sure *something* is visible without opening dev tools.
    console.error('OpenStateGraph crashed:', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div
        style={{
          padding: '2rem',
          fontFamily: 'monospace',
          whiteSpace: 'pre-wrap',
          color: '#c00',
          background: '#fff',
        }}
      >
        <h1 style={{ fontSize: '1.1rem' }}>OpenStateGraph hit an unrecoverable error</h1>
        <p>
          Reloading the page usually clears a bad autosave. If it keeps happening, this is the
          detail to report:
        </p>
        <pre>
          {error.message}
          {error.stack}
        </pre>
      </div>
    );
  }
}
