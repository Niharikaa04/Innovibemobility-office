import { Component } from 'react'
import type { ReactNode } from 'react'

/** Keeps a failure inside one panel (a chunk that fails to load, a render error) from blanking the whole dashboard. */
export default class ErrorBoundary extends Component<{ children: ReactNode; label?: string }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(e: unknown) { console.error('Panel failed to render:', (e as Error)?.message ?? e) }
  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="iv-err" role="alert">
        <p>{this.props.label ?? 'This section'} could not be loaded. The rest of the dashboard still works.</p>
        <button className="iv-chip" onClick={() => this.setState({ failed: false })}>Try again</button>
      </div>
    )
  }
}
