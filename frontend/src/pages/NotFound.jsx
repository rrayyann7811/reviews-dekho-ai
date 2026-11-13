import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Panel from '../components/ui/Panel'

export default function NotFound() {
  return (
    <Panel className="mt-8">
      <EmptyState title="Page not found" action={<Button to="/">Go to Overview</Button>}>
        The address may be mistyped, or the page may have moved.
      </EmptyState>
    </Panel>
  )
}
