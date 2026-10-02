# Demo Kitchen Trial

A working cloud-kitchen order management demo with:

- Order board: New → Accepted → Preparing → Ready → Completed
- Order creation and full customer/order details
- 58mm receipt preview
- Inventory purchase tracking with monthly spend totals and spend-by-item breakdown
- Menu management
- Order history and reprint
- Printer Center for Windows printer queues and COM/serial thermal printers
- Browser-print fallback
- SQLite + FastAPI REST API

## Run

```bash
pip install -r backend/requirements.txt
python run.py
```

Open `http://127.0.0.1:8000`

## Bluetooth thermal printer trial

For many 58mm Bluetooth printers, pair the printer in Windows first. Then open **Printer Center** in the app.

Two direct-print paths are supported:

1. **Windows printer queue** – choose the installed printer. The backend sends RAW ESC/POS data through the Windows print spooler.
2. **Bluetooth / COM port** – if Windows exposes the paired printer as a COM port, select that port. The backend sends ESC/POS data at 9600 baud.

If the printer is not exposed as either a Windows printer queue or a COM port, use the **Browser print fallback** or install the printer's Windows driver/bridge.

The **Confirm & Print** button opens the print target before the API request so browser popup blocking does not break the trial workflow.
