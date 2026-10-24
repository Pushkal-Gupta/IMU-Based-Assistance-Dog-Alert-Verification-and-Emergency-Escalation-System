# PAWSAFE React Dashboard

This is a new React/Vite frontend for the Assistance Dog Alert Verification project. It does not replace or modify the Python backend, BLE relay, ESP32 firmware, Twilio settings, or the existing `dashboard/` files.

## Requirements
- Node.js 20.19+ (Node 22 LTS recommended)
- Existing Python backend on `http://127.0.0.1:8080`
- Existing relay and control API on `http://127.0.0.1:8765`

## Install and run
1. Copy this entire `frontend` folder into the project root, alongside `dashboard`, `gateway`, `tools`, and `firmware`.
2. Open a new terminal at the project root and run:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

3. Open `http://127.0.0.1:5173/`.

Routes:
- `/` — Assistance Dog Alert History
- `/owner` — Owner response
- `/caregiver` — Caregiver console
- `/emergency` — Emergency contact

Vite proxies history API requests to the existing backend on port 8080, and relay health/control/alert requests to port 8765. Keep the backend and relay running in their usual separate terminals.

## Production build (optional)
From `frontend/` run `npm run build`. The static production output is created in `frontend/dist/`. This patch intentionally does not overwrite the existing Python-served `dashboard/` pages; test the Vite frontend first before deciding to switch the default server over.

## Notes
- The pages poll for updates every 2 seconds.
- Owner and caregiver acknowledgements use the existing relay endpoints.
- The emergency acknowledgement is labelled as a demo-only receipt; it does not contact emergency services.
- The interface is a prototype, not a validated medical or emergency-response service.
