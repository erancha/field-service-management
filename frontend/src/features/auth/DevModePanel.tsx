import { useState } from 'react'
import { Button } from '../../components/Button.tsx'

export type DevRole = 'customer' | 'technician'

interface DevModePanelProps {
  onEnter: (role: DevRole, uuid: string) => void
}

export function DevModePanel({ onEnter }: DevModePanelProps) {
  const [role, setRole] = useState<DevRole>('customer')
  const [uuid, setUuid] = useState('')

  function generateUuid() {
    // Produces a random UUID v4.
    const hex = Array.from(crypto.getRandomValues(new Uint8Array(16)))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('')
    setUuid(
      `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-${((parseInt(hex[16], 16) & 0x3) | 0x8).toString(16)}${hex.slice(17, 20)}-${hex.slice(20, 32)}`,
    )
  }

  function handleSubmit() {
    if (uuid.trim()) onEnter(role, uuid.trim())
  }

  return (
    <div className="dev-mode-panel">
      <h3>Dev Mode (Google auth not configured)</h3>
      <p>Enter your role and UUID to use the scheduling API directly.</p>
      <div className="dev-mode-panel__row">
        <label>
          Role:
          <select value={role} onChange={(e) => setRole(e.target.value as DevRole)}>
            <option value="customer">Customer</option>
            <option value="technician">Technician</option>
          </select>
        </label>
      </div>
      <div className="dev-mode-panel__row">
        <label>
          UUID:
          <input
            type="text"
            value={uuid}
            onChange={(e) => setUuid(e.target.value)}
            placeholder="xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
          />
        </label>
        <Button variant="secondary" onClick={generateUuid} type="button">
          Generate
        </Button>
      </div>
      <Button onClick={handleSubmit} disabled={!uuid.trim()}>
        Proceed as {role}
      </Button>
    </div>
  )
}
