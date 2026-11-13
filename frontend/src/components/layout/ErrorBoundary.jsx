import { Component } from 'react'
import Alert from '../ui/Alert'
import Button from '../ui/Button'

/** Shows a readable message instead of a blank page if a page crashes. */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Page crashed:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <Alert variant="error" title="Something went wrong on this page"
        action={<Button variant="secondary" size="sm" onClick={() => window.location.reload()}>Reload page</Button>}>
        {this.state.error.message}
      </Alert>
    )
  }
}
