import { useState } from 'react'
import type { ServiceCall, TimeSlot } from '../../api/types.ts'
import { useAvailability } from '../../hooks/useAvailability.ts'
import { useAppointments } from '../../hooks/useAppointments.ts'
import { SlotPicker } from '../../components/SlotPicker.tsx'
import { Button } from '../../components/Button.tsx'
import { ErrorBanner } from '../../components/ErrorBanner.tsx'
import { AppointmentCard } from '../../components/AppointmentCard.tsx'

interface BookFlowProps {
  serviceCall: ServiceCall
}

type Step = 'form' | 'slots' | 'booked'

export function BookFlow({ serviceCall }: BookFlowProps) {
  const [step, setStep] = useState<Step>('form')
  const [technicianId, setTechnicianId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [selectedSlot, setSelectedSlot] = useState<TimeSlot | null>(null)

  const availability = useAvailability()
  const appts = useAppointments()

  async function handleFetchSlots(e: React.FormEvent) {
    e.preventDefault()
    await availability.fetch({
      technician_id: technicianId,
      date_from: dateFrom,
      date_to: dateTo,
    })
    setStep('slots')
  }

  async function handleBook() {
    if (!selectedSlot) return
    await appts.book({
      service_call_id: serviceCall.id,
      technician_id: technicianId,
      start: selectedSlot.start,
      end: selectedSlot.end,
    })
    if (!appts.error) setStep('booked')
  }

  if (step === 'booked' && appts.appointment) {
    return (
      <div className="book-flow">
        <h3>Appointment Booked</h3>
        <ErrorBanner message={appts.error} onDismiss={appts.clearError} />
        <AppointmentCard
          appointment={appts.appointment}
          onReschedule={(id, start, end) => appts.reschedule(id, { start, end })}
          onCancel={appts.cancel}
          onAddDetails={appts.addDetails}
          loading={appts.loading}
        />
      </div>
    )
  }

  if (step === 'slots') {
    return (
      <div className="book-flow">
        <h3>Choose a Slot</h3>
        <ErrorBanner message={availability.error} onDismiss={() => availability.reset()} />
        <ErrorBanner message={appts.error} onDismiss={appts.clearError} />
        {availability.loading && <p>Loading slots…</p>}
        <SlotPicker
          slots={availability.slots}
          selected={selectedSlot}
          onSelect={setSelectedSlot}
        />
        <div className="book-flow__actions">
          <Button variant="secondary" onClick={() => { setStep('form'); availability.reset() }}>
            Back
          </Button>
          <Button onClick={handleBook} disabled={!selectedSlot} loading={appts.loading}>
            Book Selected Slot
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="book-flow">
      <h3>Find Availability</h3>
      <p className="book-flow__sc">Service call: <strong>{serviceCall.description}</strong></p>
      <form onSubmit={handleFetchSlots} className="form">
        <label>
          Technician UUID:
          <input
            type="text"
            value={technicianId}
            onChange={(e) => setTechnicianId(e.target.value)}
            required
            placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          />
        </label>
        <label>
          From:
          <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} required />
        </label>
        <label>
          To:
          <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} required />
        </label>
        <Button type="submit" loading={availability.loading} disabled={!technicianId.trim() || !dateFrom || !dateTo}>
          Check Availability
        </Button>
      </form>
    </div>
  )
}
