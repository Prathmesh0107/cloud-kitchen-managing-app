/*
 * Demo Kitchen — Bluetooth thermal printing straight from the browser (Web Bluetooth + ESC/POS).
 *
 * Loaded BEFORE app.js. Exposes window.DKBT.
 * Works in: Chrome / Edge on Android, Windows, macOS, ChromeOS (page must be https:// or localhost).
 * Does NOT work in: iPhone/iPad Safari or Chrome, Firefox. (On iPhone use the free "Bluefy" browser.)
 * Only Bluetooth Low Energy (BLE) printers can be reached from a browser.
 */
(function (root) {
  'use strict';

  const WIDTH = 32;      // characters per line on 58mm paper
  const CHUNK = 20;      // bytes per Bluetooth write. 20 works on every printer; try 100 for faster printing
  const GAP_MS = 20;     // pause between writes for printers that use "write without response"
  const PREF_KEY = 'dk_bt_printer';   // remembers (per browser) the Bluetooth printer used on this device
  const OFF_KEY = 'dk_bt_off';        // set when someone chooses normal browser printing on this device

  // Services used by common 58mm BLE printers, best guess first. Chrome only lets a page
  // talk to services that are listed here, so add a UUID here if a printer is not recognised.
  const SERVICES = [
    '000018f0-0000-1000-8000-00805f9b34fb',
    '0000ff00-0000-1000-8000-00805f9b34fb',
    'e7810a71-73ae-499d-8c15-faa9aef0c3f2',
    '49535343-fe7d-4ae5-8fa9-9fafd205e455',
    '0000ffe5-0000-1000-8000-00805f9b34fb',
    '0000ffe0-0000-1000-8000-00805f9b34fb',
    '0000fee7-0000-1000-8000-00805f9b34fb',
    '0000ae30-0000-1000-8000-00805f9b34fb',
    '00010203-0405-0607-0809-0a0b0c0d1912',
    '0000fff0-0000-1000-8000-00805f9b34fb'
  ];

  // ---------------------------------------------------------------- state
  const S = { device: null, char: null, serviceUuid: '', charUuid: '', mode: '', name: '' };
  const listeners = new Set();
  let chain = Promise.resolve();      // print jobs run one at a time, never interleaved

  const notify = () => listeners.forEach(fn => { try { fn(); } catch (e) { /* UI errors must not break printing */ } });
  const store = {
    get(k) { try { return root.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { root.localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
    del(k) { try { root.localStorage.removeItem(k); } catch (e) { /* private mode */ } }
  };
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const timeout = (p, ms, code) => new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error(code)), ms);
    p.then(v => { clearTimeout(t); res(v); }, e => { clearTimeout(t); rej(e); });
  });
  const rank = uuid => { const i = SERVICES.indexOf(String(uuid).toLowerCase()); return i < 0 ? 99 : i; };
  const short = u => { const m = /^0000([0-9a-f]{4})-0000-1000-8000-00805f9b34fb$/i.exec(u || ''); return m ? '0x' + m[1].toUpperCase() : (u || ''); };

  const supported = () => typeof navigator !== 'undefined' && !!navigator.bluetooth;
  const secure = () => root.isSecureContext !== false;
  const status = () => supported() ? 'ok' : (!secure() ? 'insecure' : 'unsupported');
  const savedName = () => store.get(PREF_KEY) || '';
  const preferred = () => supported() && !!savedName();
  const optedOut = () => store.get(OFF_KEY) === '1';
  const connected = () => !!(S.char && S.device && S.device.gatt && S.device.gatt.connected);
  const name = () => S.name || savedName();
  const info = () => connected() ? short(S.serviceUuid) + ' \u2192 ' + short(S.charUuid) + ' (' + S.mode + ')' : '';

  // ---------------------------------------------------------------- connection
  function onDisconnected(ev) {
    if (!ev || ev.target === S.device) { S.char = null; notify(); }   // keep S.device so we can reconnect quietly
  }

  async function open(device) {
    device.addEventListener('gattserverdisconnected', onDisconnected);
    const server = await device.gatt.connect();
    let services = [];
    try { services = await server.getPrimaryServices(); } catch (e) { services = []; }
    services.sort((a, b) => rank(a.uuid) - rank(b.uuid));
    let found = null;
    for (const svc of services) {
      let chars = [];
      try { chars = await svc.getCharacteristics(); } catch (e) { continue; }
      const c = chars.find(x => x.properties.write) || chars.find(x => x.properties.writeWithoutResponse);
      if (c) { found = { svc, c }; break; }
    }
    if (!found) {
      try { device.gatt.disconnect(); } catch (e) { /* already closed */ }
      const err = new Error('NO_WRITABLE');
      err.deviceName = device.name || '';
      throw err;
    }
    S.device = device;
    S.char = found.c;
    S.serviceUuid = found.svc.uuid;
    S.charUuid = found.c.uuid;
    S.mode = found.c.properties.write ? 'write' : 'writeWithoutResponse';
    S.name = device.name || 'Bluetooth printer';
    store.set(PREF_KEY, S.name);
    store.del(OFF_KEY);
    notify();
  }

  // Opens the browser's device chooser. Must be called straight from a tap/click.
  async function connect() {
    if (!supported()) throw new Error('UNSUPPORTED');
    const dev = await navigator.bluetooth.requestDevice({ acceptAllDevices: true, optionalServices: SERVICES });
    if (S.device && S.device !== dev) { try { S.device.gatt.disconnect(); } catch (e) { /* ignore */ } }
    try { await timeout(open(dev), 15000, 'TIMEOUT'); }
    catch (e) { try { dev.gatt.disconnect(); } catch (x) { /* ignore */ } throw e; }
    return S.name;
  }

  // Quietly reconnect to the printer chosen earlier in this page session.
  async function reconnect() {
    try { await timeout(open(S.device), 8000, 'UNREACHABLE'); }
    catch (e) {
      try { S.device.gatt.disconnect(); } catch (x) { /* ignore */ }
      if (e && e.message === 'NO_WRITABLE') throw e;
      throw new Error('UNREACHABLE');
    }
  }

  // Make sure we can print: already connected -> nothing; known printer -> reconnect; otherwise the chooser.
  async function ensure() {
    if (connected()) return;
    if (S.device) return reconnect();
    await connect();
  }

  // Disconnect and go back to normal browser printing on this device.
  function disconnect() {
    try { if (S.device && S.device.gatt && S.device.gatt.connected) S.device.gatt.disconnect(); } catch (e) { /* ignore */ }
    S.char = null; S.device = null; S.name = '';
    store.del(PREF_KEY);
    store.set(OFF_KEY, '1');
    notify();
  }

  // ---------------------------------------------------------------- sending
  async function writeNow(bytes) {
    const ch = S.char;
    if (!connected()) throw new Error('NOT_CONNECTED');
    const data = bytes instanceof Uint8Array ? bytes : Uint8Array.from(bytes);
    for (let i = 0; i < data.length; i += CHUNK) {
      if (!connected()) throw new Error('NOT_CONNECTED');       // printer switched off mid-print
      const part = data.slice(i, i + CHUNK);
      if (ch.properties.write && ch.writeValueWithResponse) await ch.writeValueWithResponse(part);
      else if (ch.writeValueWithoutResponse) { await ch.writeValueWithoutResponse(part); await sleep(GAP_MS); }
      else await ch.writeValue(part);
    }
  }
  function write(bytes) {
    const job = chain.then(() => writeNow(bytes));
    chain = job.catch(() => {});
    return job;
  }

  // ---------------------------------------------------------------- ESC/POS receipt
  // The printer only understands plain ASCII here, so clean up anything else.
  const ascii = s => String(s == null ? '' : s)
    .replace(/\u20B9/g, 'Rs ')
    .replace(/[\u00D7\u2715\u2716]/g, 'x')
    .replace(/[\u2013\u2014\u2212]/g, '-')
    .replace(/[\u2018\u2019]/g, "'").replace(/[\u201C\u201D]/g, '"')
    .replace(/[\u00A0\u2000-\u200B\u202F\u205F\u3000]/g, ' ')
    .replace(/\r\n?/g, '\n')
    .normalize('NFKD').replace(/[\u0300-\u036F]/g, '')
    .replace(/[^\x20-\x7E\n]/g, '?');

  function wrap(text, width) {
    const out = [];
    for (const para of ascii(text).split('\n')) {
      let line = '';
      for (let word of para.split(/ +/).filter(Boolean)) {
        while (word.length > width) {
          if (line) { out.push(line); line = ''; }
          out.push(word.slice(0, width));
          word = word.slice(width);
        }
        if (!line) line = word;
        else if (line.length + 1 + word.length <= width) line += ' ' + word;
        else { out.push(line); line = word; }
      }
      out.push(line);
    }
    return out;
  }

  // "left ........ right" on one line; long left text wraps onto extra lines.
  function row(left, right) {
    const r = ascii(right);
    const parts = wrap(left, Math.max(WIDTH - r.length - 1, 8));
    const first = parts.shift() || '';
    return [first.padEnd(Math.max(WIDTH - r.length, first.length)) + r].concat(parts);
  }

  const rs = n => 'Rs ' + Math.round(Number(n) || 0).toLocaleString('en-IN');
  const pad2 = n => String(n).padStart(2, '0');
  function stamp(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return { date: '', time: '' };
    let h = d.getHours();
    const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return { date: pad2(d.getDate()) + '-' + pad2(d.getMonth() + 1) + '-' + d.getFullYear(), time: pad2(h) + ':' + pad2(d.getMinutes()) + ' ' + ap };
  }

  function builder() {
    const out = [];
    const b = {
      out,
      raw: (...v) => { out.push(...v); },
      text(t) { const a = ascii(t); for (let i = 0; i < a.length; i++) out.push(a.charCodeAt(i)); },
      line(t) { b.text(t == null ? '' : t); out.push(0x0A); },
      lines(arr) { arr.forEach(x => b.line(x)); },
      align: n => b.raw(0x1B, 0x61, n),        // 0 left, 1 centre, 2 right
      style: n => b.raw(0x1B, 0x21, n),        // 0x08 bold, 0x10 double height, 0x20 double width
      rule: () => b.line('-'.repeat(WIDTH)),
      feed: n => { for (let i = 0; i < n; i++) out.push(0x0A); }
    };
    b.raw(0x1B, 0x40);                          // initialise printer
    b.raw(0x1B, 0x47, 0x01);                    // double-strike: darker print
    b.raw(0x1B, 0x45, 0x01);                    // emphasized / bold
    b.style(0x18);                              // bold + double height
    return b;
  }

  function receipt(o, s) {
    s = s || {};
    const b = builder();
    const t = stamp(o.created_at);

    b.align(1); b.lines(wrap(s.business_name || 'Demo Kitchen', WIDTH));
    if (s.gst_number) b.line('GSTIN: ' + s.gst_number);
    if (s.food_license) b.lines(wrap('FSSAI Lic: ' + s.food_license, WIDTH));
    b.align(0); b.rule();
    b.align(1); b.line('ORDER #' + o.order_number);
    b.line('KITCHEN ORDER'); b.align(0); b.rule();

    b.lines(row('Date', t.date));
    b.lines(row('Time', t.time));
    b.rule();
    // name, phone and address are optional: only print what was entered
    const who = String(o.customer_name || '').trim(), tel = String(o.phone || '').trim(), where = String(o.address || '').trim();
    if (who) b.lines(wrap('Customer: ' + who, WIDTH));
    if (tel) b.lines(wrap('Phone: ' + tel, WIDTH));
    if (where) b.lines(wrap('Address: ' + where, WIDTH));
    if (who || tel || where) b.rule();

    (o.items || []).forEach(i => b.lines(row(i.quantity + 'x ' + i.item_name, rs(i.unit_price * i.quantity))));
    b.rule();

    b.lines(row('Subtotal', rs(o.subtotal)));
    if (Number(o.delivery_fee) > 0) b.lines(row('Delivery', rs(o.delivery_fee)));
    if (Number(o.tax) > 0) b.lines(row('Tax', rs(o.tax)));
    b.lines(row('TOTAL', rs(o.total)));
    b.rule();
    b.lines(wrap('Type: ' + o.order_type, WIDTH));
    b.lines(wrap('Payment: ' + (String(o.payment_method || '').toUpperCase() === 'UPI' ? 'UPI' : 'Cash'), WIDTH));
    if (o.special_instructions) {
      b.rule(); b.lines(wrap('Note: ' + o.special_instructions, WIDTH));
    }
    b.rule(); b.align(1); b.line('THANK YOU'); b.align(0);
    b.feed(4);
    return b.out;
  }

  // One slip with every order of the day and the grand total.  t = { orders, cancelled, total, paid, pending, items }
  function summarySlip(t, s) {
    s = s || {};
    const b = builder();
    const now = stamp(new Date());
    b.align(1); b.lines(wrap(s.business_name || 'Demo Kitchen', WIDTH));
    if (s.food_license) b.lines(wrap('FSSAI Lic: ' + s.food_license, WIDTH));
    b.line("TODAY'S ORDERS"); b.align(0); b.rule();
    b.lines(row('Date', now.date));
    b.lines(row('Printed', now.time));
    b.rule();
    (t.orders || []).forEach(o => {
      b.lines(row('#' + o.order_number + ' ' + stamp(o.created_at).time, rs(o.total)));
      const list = (o.items || []).map(i => i.quantity + 'x ' + i.item_name).join(', ');
      if (list) wrap(list, WIDTH - 1).forEach(l => b.line(' ' + l));
    });
    b.rule();
    b.lines(row('Total orders', String((t.orders || []).length)));
    b.lines(row('Items sold', String(t.items || 0)));
    if (t.pending > 0) { b.lines(row('Paid', rs(t.paid))); b.lines(row('Payment pending', rs(t.pending))); }
    if (t.cancelled) b.lines(row('Cancelled (not counted)', String(t.cancelled)));
    b.lines(row('TOTAL', rs(t.total)));
    b.rule(); b.align(1); b.line('END OF REPORT'); b.align(0);
    b.feed(4);
    return b.out;
  }

  function testPage(s) {
    s = s || {};
    const b = builder();
    b.align(1); b.lines(wrap(s.business_name || 'Demo Kitchen', WIDTH));
    b.line('BLUETOOTH PRINTER TEST'); b.align(0); b.rule();
    b.line('58mm paper, 32 columns:');
    b.line('12345678901234567890123456789012');
    b.rule();
    b.align(1); b.line('Printer connection OK'); b.align(0);
    b.feed(4);
    return b.out;
  }

  // ---------------------------------------------------------------- friendly errors
  // Returns a message for the person at the counter, or null when they simply closed the chooser.
  function explain(err) {
    const msg = String((err && err.message) || err || '');
    const nm = err && err.name;
    if (nm === 'NotFoundError' && /cancel/i.test(msg)) return null;
    if (/adapter/i.test(msg)) return 'Bluetooth is switched off on this device. Turn it on and try again.';
    if (nm === 'NotFoundError') return 'No printer was found. Switch the printer on, keep it close, and try again.';
    if (msg === 'UNSUPPORTED' || nm === 'NotSupportedError') return "This browser can't use Bluetooth printing. Use Chrome or Edge on Android, Windows or Mac.";
    if (nm === 'SecurityError') return 'The browser only opens the printer list right after a tap. Tap "Connect printer" (or the printer chip at the top) and choose your printer.';
    if (nm === 'NotAllowedError') return 'Bluetooth permission was blocked. Allow Bluetooth / Nearby devices for this site, make sure Bluetooth is on, and try again.';
    if (msg === 'UNREACHABLE' || msg === 'TIMEOUT') return 'Could not reach the printer. Check that it is switched on, has paper and is close to this device, then tap the printer chip at the top. If it still fails, open Printer Setup and choose the printer again.';
    if (msg === 'NOT_CONNECTED' || nm === 'NetworkError') return 'The printer connection dropped. Switch the printer off and on, then try again.';
    if (msg === 'NO_WRITABLE') return 'Connected to "' + (err.deviceName || 'the printer') + '", but it has no print channel this app recognises. Try the other Bluetooth name of the same printer (some show a second "BLE" name), or a different model.';
    return msg || 'Bluetooth printing failed.';
  }

  // ---------------------------------------------------------------- public API
  const api = {
    supported, secure, status, preferred, optedOut, savedName, name, connected, info,
    connect, ensure, disconnect, explain,
    onChange(fn) { listeners.add(fn); },
    printOrder: (o, s) => write(receipt(o, s)),
    printOrders: (list, s) => write([].concat(...list.map(o => receipt(o, s)))),
    printSummary: (t, s) => write(summarySlip(t, s)),
    printTest: s => write(testPage(s))
  };
  root.DKBT = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = { api, ascii, wrap, row, receipt, summarySlip, testPage, SERVICES, WIDTH };
})(typeof window !== 'undefined' ? window : globalThis);
