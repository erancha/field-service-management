# FSM Frontend

React + TypeScript + Vite frontend for the Field Service Management system.

## Prerequisites

- Node 22+
- Backend running on `http://localhost:8001`

## Development

```bash
npm install
npm run dev
```

Vite proxies `/api`, `/auth`, and `/calendar` to `http://localhost:8001`, so the frontend and backend
can be developed independently without CORS issues.

Open `http://localhost:5173` in your browser.

## Production build

```bash
npm install
npm run build
```

Output is written to `dist/`. Serve `dist/index.html` with any static file server. In production the
frontend must be served from the same origin as the backend, or the backend must set appropriate CORS
headers and the API base URL must be configured.

## Type check (no emit)

```bash
npx tsc --noEmit
```

## Project layout

```
src/
  api/          Typed fetch wrapper, per-domain API modules, shared types
  hooks/        Custom React hooks (auth, availability, appointments)
  components/   Shared presentational components (Button, ErrorBanner, SlotPicker, AppointmentCard)
  features/
    auth/       DevModePanel (Google-unconfigured fallback), LogoutButton
    customer/   OpenServiceCall form, BookFlow (slot search + booking + appointment management)
    technician/ ConnectCalendar button, MyAppointments lookup
  pages/        HomePage (routes by auth state), CustomerPage, TechnicianPage
  styles/       global.css
```
