Demo Kitchen v21 — clear steps on iPhone / browsers without Bluetooth

- On iPhone/iPad Safari or Chrome, Web Bluetooth is blocked by Apple. Printer Setup now shows exactly
  what to do (install Bluefy, copy the app link, open it there) plus a "Copy app link" button,
  and hides the greyed-out printer controls that only caused confusion.
- Android / laptop Chrome and Edge need nothing extra.

----------------------------------------------------------------------

Demo Kitchen v20 — Print never opens the browser print page when Bluetooth is available

- Print now uses Bluetooth by default on any browser that supports it. The first Print asks you to
  pick the printer once (small popup), then every Print goes straight to the printer.
- Print uses the order already on screen, so there is no server wait before printing starts.
- Top-bar printer chip shows "Tap to connect" in amber until a printer is connected; tap it to
  connect or reconnect from any screen.
- Printer Setup > "Use browser printing instead" switches a device back to the normal print page.
- A configured Windows / COM printer keeps working exactly as before.
- After reloading the page, tap the printer chip once to reconnect (browsers require a tap).

----------------------------------------------------------------------

Demo Kitchen v19 — Bluetooth printing from the phone (Web Bluetooth)

New file:
- frontend/bluetooth.js  (loaded before app.js)

Changed files:
- frontend/app.js, frontend/styles.css, frontend/index.html (backend is unchanged)

What it does:
- Printer Setup now has a "Phone / Bluetooth" tab: Connect printer, Print test receipt, Disconnect.
- Once connected, every Print / Print all button sends a 58mm ESC/POS receipt straight to the printer.
- The printer chip in the top bar shows the Bluetooth printer; tap it to reconnect.
- Works in Chrome / Edge (Android, Windows, Mac) over https:// or localhost. Not iPhone Safari/Chrome (use Bluefy).
- Only Bluetooth Low Energy printers appear. The choice is remembered per browser, not on the server.
- Windows / COM printing and browser print still work exactly as before.

----------------------------------------------------------------------

Demo Kitchen v16 — fast order confirmation / iOS fixes

Files:
- frontend/app.js
- frontend/styles.css
- frontend/index.html
- backend/app.py
- backend/requirements.txt
- run.py

Changes:
- Confirm Order no longer calls the six-resource load() before returning to dashboard.
- No success alert after order creation.
- Newly created order is inserted into local dashboard state immediately after POST succeeds.
- Orders refresh runs in the background and never blocks dashboard rendering.
- Backend create_order returns order items using the existing DB connection; it no longer opens a second connection to serialize the new order.
- Print is separate from order creation.
- iOS mobile form controls use 16px font to prevent Safari focus zoom.
- v14 mobile modal fixes remain included.
- Asset URLs in index.html are cache-busted with ?v=16.
