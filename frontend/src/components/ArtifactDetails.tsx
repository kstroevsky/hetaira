export function ArtifactDetails({ value, title = 'Полный технический результат' }: {
  value: unknown
  title?: string
}) {
  return (
    <details className="artifact-details">
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}
