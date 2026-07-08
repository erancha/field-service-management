import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminPage } from './AdminPage.tsx'
import { AuthContext } from '../features/auth/authContext.ts'
import { fetchUpcomingAppointments } from '../api/scheduling.ts'
import { fetchTechnicianRequests } from '../api/backoffice.ts'
import { FakeEventSource } from '../test/fakeEventSource.ts'

vi.mock('../api/scheduling.ts', () => ({ fetchUpcomingAppointments: vi.fn() }))
vi.mock('../api/backoffice.ts', () => ({
  fetchTechnicianRequests: vi.fn(), approveTechnicianRequest: vi.fn(), rejectTechnicianRequest: vi.fn(),
}))

describe('AdminPage', () => {
  beforeEach(() => {
    FakeEventSource.reset()
    vi.stubGlobal('EventSource', FakeEventSource)
    vi.mocked(fetchUpcomingAppointments).mockResolvedValue({ items: [] })
    vi.mocked(fetchTechnicianRequests).mockResolvedValue([])
  })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the upcoming list alongside the request queue', async () => {
    render(
      <MemoryRouter>
        <AuthContext.Provider value={{ auth: { status: 'loading' }, refresh: vi.fn() }}>
          <AdminPage />
        </AuthContext.Provider>
      </MemoryRouter>,
    )
    expect(await screen.findByText(/upcoming appointments/i)).toBeInTheDocument()
    expect(screen.getByText(/pending technician requests/i)).toBeInTheDocument()
  })
})
