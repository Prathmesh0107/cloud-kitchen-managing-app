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
