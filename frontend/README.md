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

Run the vitest suite with:

```bash
npm test
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

Code under `src/` is organized by responsibility, with `features/` split one folder per feature area:

- `api/` — typed fetch wrapper, per-domain API modules, and shared request/response types
- `hooks/` — custom React hooks for data fetching and auth state
- `components/` — shared presentational components reused across features
- `features/` — feature-specific screens and flows: one folder per user role (`auth`, `customer`,
  `technician`, `backoffice`) plus the cross-role `profile` onboarding/editing flow
- `pages/` — top-level route components; `HomePage` dispatches by auth state and role
- `utils/` — shared pure helpers (slot search window and time-range formatting)
- `test/` — vitest setup (jest-dom matchers, per-test DOM cleanup)
- `styles/` — global CSS
