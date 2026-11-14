import PageHeader from '../components/layout/PageHeader'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Panel from '../components/ui/Panel'

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Panel>
        <EmptyState title="This address doesn’t match any page" action={<Button to="/">Go to Overview</Button>}>
          The address may be mistyped, or the page may have moved.
        </EmptyState>
      </Panel>
    </>
  )
}
