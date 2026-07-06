import { useState } from 'react'
import { createServiceCall } from '../../api/scheduling.ts'
import type { ServiceCall } from '../../api/types.ts'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { errorMessage } from '../../utils/errors.ts'

interface OpenServiceCallProps {
  onCreated: (serviceCall: ServiceCall) => void
}

export function OpenServiceCall({ onCreated }: OpenServiceCallProps) {
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const sc = await createServiceCall({ description })
      onCreated(sc)
    } catch (err) {
      setError(errorMessage(err, 'Failed to create service call'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="open-service-call">
      <h3>Open a Service Call</h3>
      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      <form onSubmit={handleSubmit} className="form">
        <label>
          Description:
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            rows={20}
            placeholder="Describe the issue…"
          />
        </label>
        <Button type="submit" loading={loading} disabled={!description.trim()}>
          Open Service Call
        </Button>
      </form>
    </div>
  )
}
