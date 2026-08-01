interface PageHeaderProps {
  title: string
  // Account identifier surfaced only as a hover tooltip on the title, keeping the rarely needed id
  // out of the visible layout.
  accountId?: string
}

/**
 * The page title row, rendered by each page beneath the AppShell's global brand bar.
 */
export function PageHeader({ title, accountId }: PageHeaderProps) {
  return (
    <header className="page__header">
      <h2 title={accountId}>{title}</h2>
    </header>
  )
}
