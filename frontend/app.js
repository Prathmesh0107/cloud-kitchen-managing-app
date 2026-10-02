const app = document.getElementById('app');
let state = {
  page: 'dashboard', orders: [], menu: [], categories: [], settings: null, reports: null, newOrder: {category: null, cart: {}},
  inventory: { month: new Date().toISOString().slice(0, 7), total_spend: 0, purchases: [], by_item: [] },
  printers: { printers: [], ports: [] }, printerSetup: { step: 1, test: null }, search: '', inventorySearch: '', orderStatus: '', paymentFilter: '', selectedOrder: null
};

const money = n => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(n || 0);
const num = n => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n || 0);
const esc = s => String(s ?? '').replace(/[&<>'"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#039;', '"':'&quot;' }[c]));
const fmtTime = iso => new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const fmtDate = iso => new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
const api = async (url, opts = {}) => {
  const r = await fetch(url, { headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) }, ...opts });
  if (!r.ok) throw new Error(await r.text() || 'Request failed');
  return r.json();
};

async function load() {
  const month = state.inventory.month || new Date().toISOString().slice(0, 7);
  [state.orders, state.menu, state.categories, state.settings, state.reports, state.inventory] = await Promise.all([
    api('/api/orders'), api('/api/menu-items'), api('/api/categories'), api('/api/settings'), api('/api/reports'), api('/api/inventory?month=' + encodeURIComponent(month))
  ]);
  render();
}
async function loadInventory() {
  state.inventory = await api('/api/inventory?month=' + encodeURIComponent(state.inventory.month) + (state.inventorySearch ? '&q=' + encodeURIComponent(state.inventorySearch) : ''));
  render();
}
async function loadPrinters() {
  state.printers = await api('/api/printers');
  render();
}
function nav(page) { state.page = page; state.selectedOrder = null; render(); if (page === 'printers') loadPrinters().catch(() => {}); }
function statusClass(s) { return String(s).toLowerCase().replace(/\s/g, '-'); }

function orderCard(o) {
  return `<article class="order-card">
    <div class="order-top"><span class="order-num">#${o.order_number}</span><span class="pill ${statusClass(o.payment_status)}">${esc(o.payment_status)}</span></div>
    <div class="customer"><div class="avatar">${esc(o.customer_name[0] || '?').toUpperCase()}</div><div><b>${esc(o.customer_name)}</b><div class="muted">${esc(o.phone)}</div></div></div>
    <div class="order-meta"><span>${esc(o.order_type)}</span><span>${fmtTime(o.created_at)}</span></div>
    <div class="items">${o.items.slice(0, 3).map(i => `<div><span>${i.quantity}× ${esc(i.item_name)}</span><strong>${money(i.unit_price * i.quantity)}</strong></div>`).join('')}${o.items.length > 3 ? '<div class="muted">+ more items</div>' : ''}</div>
    ${o.special_instructions ? `<div class="note">${esc(o.special_instructions)}</div>` : ''}
    <div class="order-foot"><strong>${money(o.total)}</strong><div class="actions"><button class="btn btn-small" onclick="showOrder(${o.id})">View</button><button class="btn btn-small btn-primary" onclick="printOrder(${o.id})">Print</button></div></div>
  </article>`;
}

function render() {
  const counts = { New:0, Accepted:0, Preparing:0, Ready:0, Completed:0, Cancelled:0 };
  state.orders.forEach(o => counts[o.status] = (counts[o.status] || 0) + 1);
  const pending = counts.New + counts.Accepted + counts.Preparing + counts.Ready;
  app.innerHTML = `<div class="shell">
    <aside class="sidebar"><div class="brand"><div class="brand-mark">DK</div><div><strong>${esc(state.settings?.business_name || 'Demo Kitchen')}</strong><span>Restaurant OS</span></div></div>
      <nav>${['dashboard','orders','menu','inventory','reports','printers','settings'].map(p => `<button class="nav-item ${state.page === p ? 'active' : ''}" onclick="nav('${p}')"><span>${icon(p)}</span>${p === 'printers' ? 'Printer Setup' : p[0].toUpperCase() + p.slice(1)}</button>`).join('')}</nav>
      <div class="sidebar-bottom"><div class="demo-badge">● DEMO MODE</div><button class="reset-link" onclick="resetDemo()">Reset demo data</button></div>
    </aside>
    <main class="main"><header class="topbar"><div><div class="eyebrow">${pageLabel(state.page)}</div><h1>${pageTitle(state.page)}</h1></div>
      <div class="top-actions"><div class="printer"><span class="dot"></span>${printerDisplay()} </div><div class="clock" id="clock"></div><div class="avatar me">DK</div></div>
    </header><section class="content">${pageView(pending, counts)}</section></main></div>`;
  tick();
}
function pageLabel(p) { return p === 'dashboard' ? 'Overview' : 'Management'; }
function pageTitle(p) { return ({dashboard:'Kitchen Dashboard', orders:'Order History', menu:'Menu Management', inventory:'Inventory Management', reports:'Reports & Insights', printers:'Bluetooth Printer Setup', settings:'Settings'}[p] || 'Demo Kitchen'); }
function icon(p) { return ({dashboard:'⌂', orders:'▤', menu:'▦', inventory:'◈', reports:'◔', printers:'▣', settings:'⚙'}[p] || '•'); }
function printerDisplay() {
  const s = state.settings || {};
  if ((s.printer_mode === 'windows' || s.printer_mode === 'serial') && s.printer_target) return `<b>${esc(s.printer_target)}</b><span class="connected">Ready</span>`;
  return `<b>Browser Print</b><span class="connected">Fallback</span>`;
}
function tick() { const el = document.getElementById('clock'); if (el) el.textContent = new Date().toLocaleString([], { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit' }); }
setInterval(tick, 30000);

function pageView(pending, counts) {
  if (state.page === 'dashboard') return dashboard(pending, counts);
  if (state.page === 'orders') return ordersPage();
  if (state.page === 'menu') return menuPage();
  if (state.page === 'inventory') return inventoryPage();
  if (state.page === 'reports') return reportsPage();
  if (state.page === 'printers') return printersPage();
  return settingsPage();
}

function dashboard(pending, counts) {
  const completed = counts.Completed, rev = state.reports?.today_revenue || 0;
  const inv = state.inventory?.total_spend || 0;
  return `<div class="toolbar"><div><span class="muted">Live demo environment</span><div class="subtitle">Run the complete order → kitchen → print workflow here.</div></div><button class="btn btn-primary" onclick="openNewOrder()">＋ New Order</button></div>
    <div class="stats"><div class="stat"><span>Today's Orders</span><b>${state.orders.length}</b><small>Across all statuses</small></div><div class="stat"><span>Today's Sales</span><b>${money(rev)}</b><small>Completed orders</small></div><div class="stat"><span>Pending Orders</span><b>${pending}</b><small>Waiting in kitchen</small></div><div class="stat"><span>This Month Inventory</span><b>${money(inv)}</b><small>Raw material purchases</small></div></div>
    <div class="section-head"><div><h2>Order board</h2><p>Move tickets through the kitchen in a few clicks.</p></div><div class="mini-actions"><button class="btn" onclick="openNewOrder()">New order</button><button class="btn" onclick="nav('inventory')">Inventory spend</button></div></div>
    <div class="kanban">${['New','Accepted','Preparing','Ready','Completed'].map(s => `<div class="column"><div class="column-head"><div><h3>${s}</h3><span>${counts[s] || 0} orders</span></div><span class="count">${counts[s] || 0}</span></div><div class="column-body">${state.orders.filter(o => o.status === s).map(orderCard).join('') || '<div class="empty">No orders here</div>'}</div></div>`).join('')}</div>`;
}

function ordersPage() {
  return `<div class="toolbar"><div><span class="muted">${state.orders.length} orders in demo database</span><div class="subtitle">Search, inspect and reprint tickets.</div></div><button class="btn btn-primary" onclick="openNewOrder()">＋ New Order</button></div>
  <div class="filters"><input placeholder="Search order number, customer or phone" value="${esc(state.search)}" oninput="state.search=this.value;filterOrders()"><select onchange="state.orderStatus=this.value;filterOrders()"><option value="">All statuses</option>${['New','Accepted','Preparing','Ready','Completed','Cancelled'].map(s => `<option ${state.orderStatus===s?'selected':''}>${s}</option>`).join('')}</select><select id="payment-filter" onchange="state.paymentFilter=this.value;filterOrders()"><option value="">All payments</option><option ${state.paymentFilter==='Paid'?'selected':''}>Paid</option><option ${state.paymentFilter==='Pending'?'selected':''}>Pending</option></select></div>
  <div class="history-table"><div class="table-head"><span>Order</span><span>Customer</span><span>Status</span><span>Total</span><span>Actions</span></div>${state.orders.map(o => `<div class="table-row" data-status="${o.status}" data-payment="${o.payment_status}" data-q="${esc((o.customer_name+' '+o.phone+' '+o.order_number).toLowerCase())}"><span><b>#${o.order_number}</b><small>${fmtTime(o.created_at)}</small></span><span><b>${esc(o.customer_name)}</b><small>${esc(o.order_type)}</small></span><span><span class="status-dot ${statusClass(o.status)}"></span>${o.status}</span><span><b>${money(o.total)}</b><small>${o.payment_status}</small></span><span class="actions"><button class="btn btn-small" onclick="showOrder(${o.id})">View</button><button class="btn btn-small" onclick="printOrder(${o.id})">Print</button></span></div>`).join('')}</div>`;
}
function filterOrders() {
  const q = state.search.toLowerCase(), status = state.orderStatus, pay = state.paymentFilter;
  document.querySelectorAll('.table-row').forEach(r => { r.style.display = ((!status || r.dataset.status === status) && (!q || r.dataset.q.includes(q)) && (!pay || r.dataset.payment === pay)) ? 'grid' : 'none'; });
}

function menuPage() {
  const cats = state.categories || [];
  const totalItems = state.menu.length;
  const categoryCards = cats.map((c, idx) => {
    const rows = state.menu.filter(i => i.category === c.name);
    const available = rows.filter(i => i.available).length;
    return `<div class="category-admin-card">
      <div class="category-admin-main">
        ${c.icon ? `<span class="category-admin-icon">${esc(c.icon)}</span>` : '<span class="category-admin-icon empty">•</span>'}
        <div><h3>${esc(c.name)}</h3><p>${rows.length} item${rows.length===1?'':'s'} · ${available} available</p></div>
      </div>
      <div class="category-order-tools">
        <button class="icon-btn" title="Move category up" onclick="reorderCategory(${c.id},-1)" ${idx===0?'disabled':''}>↑</button>
        <button class="icon-btn" title="Move category down" onclick="reorderCategory(${c.id},1)" ${idx===cats.length-1?'disabled':''}>↓</button>
      </div>
      <div class="menu-actions category-admin-actions">
        <button class="btn btn-small" onclick='openCategoryModal(${JSON.stringify(c).replace(/'/g,"&#39;")})'>Edit</button>
        <button class="btn btn-small btn-primary" onclick='openMenuModal(null, ${jsArg(c.name)})'>＋ Add Item</button>
        <button class="icon-btn danger" title="Delete category" onclick="deleteCategory(${c.id})">×</button>
      </div>
    </div>`;
  }).join('');

  const groups = cats.map(c => {
    const rows = state.menu.filter(i => i.category === c.name);
    return `<div class="menu-group">
      <div class="section-head tight menu-group-head">
        <div class="menu-group-title">
          ${c.icon ? `<span class="menu-group-icon">${esc(c.icon)}</span>` : ''}
          <div><h2>${esc(c.name)}</h2><p>${rows.length} item${rows.length===1?'':'s'} · ${rows.filter(i=>i.available).length} available · ${rows.filter(i=>!i.available).length} hidden</p></div>
        </div>
        <div class="mini-actions">
          <button class="btn btn-small" onclick='openCategoryModal(${JSON.stringify(c).replace(/'/g,"&#39;")})'>Edit category</button>
          <button class="btn btn-small btn-primary" onclick='openMenuModal(null, ${jsArg(c.name)})'>＋ Add dish</button>
        </div>
      </div>
      ${rows.length ? `<div class="menu-grid">${rows.map(i => `<div class="menu-card ${i.available?'':'disabled'}">
        <div><span class="category-chip">${i.available?'Available':'Hidden'}</span><h3>${esc(i.name)}</h3><b>${money(i.price)}</b></div>
        <div class="menu-actions">
          <button class="availability-toggle ${i.available?'on':'off'}" onclick="toggleMenu(${i.id},${i.available?'false':'true'})">${i.available?'✓ Available':'○ Hidden'}</button>
          <button class="btn btn-small" onclick='openMenuModal(${JSON.stringify(i).replace(/'/g,"&#39;")})'>Edit</button>
          <button class="icon-btn danger" title="Delete item" onclick="deleteMenu(${i.id})">×</button>
        </div>
      </div>`).join('')}</div>` : `<div class="menu-empty-card"><div><b>No dishes in ${esc(c.name)} yet.</b><span>Add the first dish to this category.</span></div><button class="btn btn-primary btn-small" onclick='openMenuModal(null, ${jsArg(c.name)})'>＋ Add dish</button></div>`}
    </div>`;
  }).join('');

  const uncategorized = state.menu.filter(i => !cats.some(c => c.name === i.category));
  const uncategorizedBlock = uncategorized.length ? `<div class="menu-group">
    <div class="section-head tight menu-group-head"><div><div class="menu-group-title"><div><h2>Other</h2><p>${uncategorized.length} item${uncategorized.length===1?'':'s'} not assigned to a category</p></div></div></div><button class="btn btn-small btn-primary" onclick="openCategoryModal()">＋ Create category</button></div>
    <div class="menu-grid">${uncategorized.map(i => `<div class="menu-card ${i.available?'':'disabled'}"><div><span class="category-chip">${i.available?'Available':'Hidden'}</span><h3>${esc(i.name)}</h3><b>${money(i.price)}</b></div><div class="menu-actions"><button class="availability-toggle ${i.available?'on':'off'}" onclick="toggleMenu(${i.id},${i.available?'false':'true'})">${i.available?'✓ Available':'○ Hidden'}</button><button class="btn btn-small" onclick='openMenuModal(${JSON.stringify(i).replace(/'/g,"&#39;")})'>Edit</button><button class="icon-btn danger" onclick="deleteMenu(${i.id})">×</button></div></div>`).join('')}</div>
  </div>` : '';

  return `<div class="toolbar"><div><span class="muted">${totalItems} menu items · ${cats.length} categories</span><div class="subtitle">Manage availability, category order, and dishes exactly how the restaurant wants to see them.</div></div><div class="mini-actions"><button class="btn" onclick="openCategoryModal()">＋ Category</button><button class="btn btn-primary" onclick="openMenuModal()">＋ Add Item</button></div></div>
    <div class="panel menu-structure-panel"><div class="section-head tight"><div><h2>Categories</h2><p>Use ↑ / ↓ to control the order shown in New Order. Icons are optional.</p></div><span class="muted">${cats.length} configured</span></div><div class="category-admin-grid">${categoryCards || '<div class="empty">No categories yet. Add one to start building the menu.</div>'}</div></div>
    ${groups}${uncategorizedBlock}`;
}

function openCategoryModal(category = null) {
  const itemCount = category ? state.menu.filter(i => i.category === category.name).length : 0;
  showModal(`<div class="modal-card"><div class="modal-head"><div><span class="muted">Menu structure</span><h2>${category ? 'Edit category' : 'Add category'}</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div>
    <p class="muted">Use an icon only when it helps. Leave it empty for a simple text-only category.</p>
    <form id="category-form"><label>Category name<input name="name" required value="${esc(category?.name || '')}" placeholder="Paneer"></label><label>Icon / emoji (optional)<input name="icon" maxlength="4" value="${esc(category?.icon || '')}" placeholder="🍛"></label>${category ? `<div class="hint-box">${itemCount ? `${itemCount} menu item${itemCount===1?'':'s'} use this category. Renaming it will update those items automatically.` : 'This category has no menu items yet.'}</div>` : ''}<div class="modal-foot"><button class="btn" type="button" onclick="closeModal()">Cancel</button><button class="btn btn-primary">Save category</button></div></form></div>`);
  document.getElementById('category-form').onsubmit = async e => { e.preventDefault(); const f=new FormData(e.target); try { await api(category ? '/api/categories/'+category.id : '/api/categories',{method:category?'PUT':'POST',body:JSON.stringify({name:String(f.get('name')).trim(),icon:String(f.get('icon')||'').trim()})}); closeModal(); await load(); } catch(err){ alert(err.message || 'Could not save category'); } };
}
async function reorderCategory(id, direction) {
  const ids = (state.categories || []).map(c => c.id);
  const idx = ids.indexOf(id);
  const target = idx + direction;
  if (idx < 0 || target < 0 || target >= ids.length) return;
  [ids[idx], ids[target]] = [ids[target], ids[idx]];
  try { await api('/api/categories/reorder', {method:'POST', body:JSON.stringify({category_ids:ids})}); await load(); }
  catch (err) { alert(err.message || 'Could not reorder categories'); }
}
async function deleteCategory(id) { if (!confirm('Delete this category? Categories with menu items cannot be deleted until those items are moved or deleted.')) return; try { await api('/api/categories/'+id,{method:'DELETE'}); await load(); } catch(err){ alert(err.message || 'Could not delete category'); } }

function inventoryPage() {
  const inv = state.inventory || { purchases: [], by_item: [], total_spend: 0 };
  const top = inv.by_item?.[0];
  return `<div class="toolbar"><div><span class="muted">Track raw-material spending</span><div class="subtitle">Example: Tomatoes · 1 kg · ₹100 → monthly inventory spend.</div></div><div class="mini-actions"><input class="month-input" type="month" value="${esc(inv.month)}" onchange="state.inventory.month=this.value;state.inventorySearch='';loadInventory()"><button class="btn btn-primary" onclick="openInventoryModal()">＋ Add Purchase</button></div></div>
    <div class="stats"><div class="stat"><span>${labelMonth(inv.month)} Inventory Spend</span><b>${money(inv.total_spend)}</b><small>Total purchase cost</small></div><div class="stat"><span>Purchases</span><b>${inv.purchases.length}</b><small>Purchase records</small></div><div class="stat"><span>Top Spend Item</span><b>${esc(top?.item_name || '—')}</b><small>${top ? money(top.total_cost) : 'No purchases'}</small></div><div class="stat"><span>Average Purchase</span><b>${money(inv.purchases.length ? inv.total_spend / inv.purchases.length : 0)}</b><small>Per record</small></div></div>
    <div class="inventory-layout"><div class="panel"><div class="section-head tight"><div><h2>Monthly purchases</h2><p>Every purchase contributes to the selected month's total.</p></div><input class="compact-search" placeholder="Search item" value="${esc(state.inventorySearch)}" oninput="state.inventorySearch=this.value;loadInventory()"></div>
      <div class="inventory-table"><div class="table-head inv-head"><span>Date</span><span>Item</span><span>Qty</span><span>Unit price</span><span>Total</span><span>Action</span></div>${inv.purchases.map(p => `<div class="table-row inv-row"><span>${esc(p.purchase_date)}</span><span><b>${esc(p.item_name)}</b><small>${esc(p.category)}</small></span><span>${num(p.quantity)} ${esc(p.unit)}</span><span>${money(p.unit_price)}</span><span><b>${money(p.total_cost)}</b></span><span><button class="btn btn-small" onclick="deleteInventory(${p.id})">Delete</button></span></div>`).join('') || '<div class="empty">No purchases for this month.</div>'}</div></div>
      <div class="panel"><div class="section-head tight"><div><h2>Where are we spending?</h2><p>Grouped by ingredient/material.</p></div></div>${(inv.by_item || []).map(x => `<div class="bar-row"><span>${esc(x.item_name)}</span><div class="bar"><i style="width:${inv.total_spend ? Math.min(100, (x.total_cost / inv.total_spend) * 100) : 0}%"></i></div><b>${money(x.total_cost)}</b></div>`).join('') || '<div class="empty">No spending data yet.</div>'}</div>
    </div>`;
}
function labelMonth(m) { if (!m) return 'This Month'; const [y, mo] = m.split('-'); return new Date(Number(y), Number(mo)-1, 1).toLocaleDateString('en-IN', { month:'short', year:'numeric' }); }

function reportsPage() {
  const r = state.reports || {}, inv = state.inventory || {}, top = r.most_ordered || [];
  return `<div class="stats reports"><div class="stat"><span>Revenue</span><b>${money(r.today_revenue)}</b><small>Completed orders</small></div><div class="stat"><span>Total Orders</span><b>${r.orders || 0}</b><small>Demo database</small></div><div class="stat"><span>Average Order</span><b>${money(r.average_order)}</b><small>Completed tickets</small></div><div class="stat"><span>${labelMonth(inv.month)} Inventory</span><b>${money(inv.total_spend)}</b><small>Raw material spend</small></div></div>
  <div class="report-grid"><div class="panel"><div class="section-head tight"><div><h2>Most ordered items</h2><p>Based on current demo order data.</p></div></div>${top.map(([name,qty]) => `<div class="bar-row"><span>${esc(name)}</span><div class="bar"><i style="width:${Math.min(100, qty * 18)}%"></i></div><b>${qty}</b></div>`).join('') || '<div class="empty">No data</div>'}</div>
  <div class="panel"><div class="section-head tight"><div><h2>Inventory spend</h2><p>Change the month from Inventory Management.</p></div></div>${(inv.by_item || []).slice(0, 5).map(x => `<div class="metric-line"><span>${esc(x.item_name)}</span><b>${money(x.total_cost)}</b></div>`).join('') || '<div class="empty">No purchases</div>'}<div class="metric-line"><span>Total for ${labelMonth(inv.month)}</span><b>${money(inv.total_spend)}</b></div></div></div>`;
}

function printersPage() {
  const p = state.printers || { printers: [], ports: [] }, s = state.settings || {}, ps = state.printerSetup || { step: 1, test: null };
  const step = ps.step || 1;
  const selected = s.printer_target || '';
  const selectedMode = s.printer_mode || 'browser';
  const steps = [
    ['1','Pair in Windows'], ['2','Detect device'], ['3','Select & configure'], ['4','Test & troubleshoot']
  ];
  return `<div class="toolbar"><div><span class="muted">58mm Bluetooth thermal printer wizard</span><div class="subtitle">Set up the printer once, test it, then use <b>Confirm & Print</b> on every order.</div></div>
    <div class="mini-actions"><button class="btn" onclick="loadPrinters()">↻ Refresh devices</button></div></div>
    <div class="setup-steps">${steps.map((x,i) => `<button class="setup-step ${step===i+1?'active':''} ${step>i+1?'done':''}" onclick="setPrinterStep(${i+1})"><span>${step>i+1?'✓':x[0]}</span><b>${x[1]}</b></button>`).join('')}</div>
    ${step === 1 ? printerPairStep() : ''}
    ${step === 2 ? printerDetectStep(p) : ''}
    ${step === 3 ? printerConfigureStep(p, s) : ''}
    ${step === 4 ? printerTestStep(p, s, ps) : ''}`;
}

function printerPairStep() {
  return `<div class="setup-grid"><div class="panel setup-main"><div class="section-head tight"><div><span class="eyebrow">STEP 1 OF 4</span><h2>Pair the printer with Windows</h2><p>The app cannot reliably pair classic Bluetooth thermal printers from the browser. Windows handles the Bluetooth pairing; this wizard guides you through it.</p></div><span class="connection-badge">Windows pairing</span></div>
    <div class="instruction-list">
      <div class="instruction"><span>1</span><div><b>Power on the 58mm printer</b><small>Keep the printer close to this Windows PC and make sure the Bluetooth light is active.</small></div></div>
      <div class="instruction"><span>2</span><div><b>Open Windows Bluetooth settings</b><small>Go to Bluetooth & devices → Add device → Bluetooth.</small></div></div>
      <div class="instruction"><span>3</span><div><b>Select the printer</b><small>Choose the printer name shown by the device. If Windows asks for a PIN, use the PIN printed on the device/manual or supplied by the vendor.</small></div></div>
      <div class="instruction"><span>4</span><div><b>Wait until Windows shows Connected</b><small>Do not start the test until Windows has finished pairing the device.</small></div></div>
    </div>
    <div class="hint-box"><b>Important:</b> Bluetooth pairing and Bluetooth printing are different. After pairing, Windows may expose the printer as a normal printer queue or as a COM port. The next steps detect both.</div>
    <div class="mini-actions"><a class="btn btn-primary" href="ms-settings:bluetooth">Open Windows Bluetooth settings</a><button class="btn" onclick="setPrinterStep(2);loadPrinters()">I've paired it → Detect device</button></div>
  </div>
  <div class="panel setup-side"><h2>Before you continue</h2><div class="checklist"><div>✓ Printer is powered on</div><div>✓ Printer is within Bluetooth range</div><div>✓ Windows Bluetooth is ON</div><div>✓ Printer is not connected to another PC/phone</div></div><h3 class="device-title">If pairing asks for a PIN</h3><p class="muted">Use the printer's supplied PIN rather than guessing. Common PINs vary by model, firmware and vendor.</p></div></div>`;
}

function printerDetectStep(p) {
  const printers = p.printers || [], ports = p.ports || [];
  return `<div class="setup-grid"><div class="panel setup-main"><div class="section-head tight"><div><span class="eyebrow">STEP 2 OF 4</span><h2>Detect the paired device</h2><p>Refresh the local computer and choose how Windows exposed the printer.</p></div><span class="connection-badge">${printers.length || ports.length ? 'Device found' : 'Waiting for device'}</span></div>
    <div class="mini-actions"><button class="btn btn-primary" onclick="loadPrinters()">↻ Scan again</button><button class="btn" onclick="setPrinterStep(1)">← Back</button></div>
    <h3 class="device-title">Windows printer queues</h3>${printers.map(x => `<div class="device-row selectable"><div><b>${esc(x.name)}</b><small>${esc(x.driver || 'Printer')} ${x.port ? '· Windows port '+esc(x.port) : ''}</small></div><button class="btn btn-small btn-primary" onclick="pickPrinter('windows',${JSON.stringify(x.name)})">Select</button></div>`).join('') || '<div class="empty">No Windows printer queue detected.</div>'}
    <h3 class="device-title">Bluetooth / COM ports</h3>${ports.map(x => `<div class="device-row selectable"><div><b>${esc(x.port)}</b><small>${esc(x.name)}${x.manufacturer ? ' · '+esc(x.manufacturer) : ''}</small></div><button class="btn btn-small btn-primary" onclick="pickPrinter('serial',${JSON.stringify(x.port)})">Select</button></div>`).join('') || '<div class="empty">No COM/serial port detected.</div>'}
  </div>
  <div class="panel setup-side"><h2>Which one should I choose?</h2><div class="choice-card"><b>Windows printer queue</b><p>Choose this when the printer appears under Windows Printers & scanners and has a printer name.</p><span>Good first choice</span></div><div class="choice-card"><b>COM port</b><p>Choose this when Device Manager shows something like COM3, COM5 or COM8 for the Bluetooth printer.</p><span>ESC/POS direct</span></div><div class="hint-box">If you only see a COM port, that is normal for some Bluetooth SPP thermal printers.</div></div></div>`;
}

function printerConfigureStep(p, s) {
  const printers = p.printers || [], ports = p.ports || [];
  return `<div class="setup-grid"><div class="panel setup-main"><div class="section-head tight"><div><span class="eyebrow">STEP 3 OF 4</span><h2>Select the printing path</h2><p>Save the device that should receive kitchen tickets.</p></div><span class="connection-badge">${selectedLabel(s)}</span></div>
    <div class="form-grid"><label>Connection type<select id="p-mode" onchange="syncPrinterTargets()"><option value="windows" ${s.printer_mode==='windows'?'selected':''}>Windows printer queue</option><option value="serial" ${s.printer_mode==='serial'?'selected':''}>Bluetooth / COM (ESC/POS)</option><option value="browser" ${s.printer_mode==='browser'?'selected':''}>Browser print fallback</option></select></label>
    <label>Printer / COM target<select id="p-target"><option value="">Select a device</option>${(printers||[]).map(x => `<option data-mode="windows" ${s.printer_mode==='serial'?'hidden':''} value="${esc(x.name)}" ${s.printer_mode==='windows'&&s.printer_target===x.name?'selected':''}>${esc(x.name)}${x.port?' · '+esc(x.port):''}</option>`).join('')}${(ports||[]).map(x => `<option data-mode="serial" ${s.printer_mode!=='serial'?'hidden':''} value="${esc(x.port)}" ${s.printer_mode==='serial'&&s.printer_target===x.port?'selected':''}>${esc(x.port)} · ${esc(x.name)}</option>`).join('')}</select></label></div>
    <div class="form-grid"><label>Displayed printer name<input id="p-name" value="${esc(s.printer_name || '58mm Mini Thermal Printer')}"></label><label>COM baud rate<select id="p-baud"><option value="9600" ${Number(s.printer_baudrate||9600)===9600?'selected':''}>9600</option><option value="19200" ${Number(s.printer_baudrate)===19200?'selected':''}>19200</option><option value="38400" ${Number(s.printer_baudrate)===38400?'selected':''}>38400</option><option value="57600" ${Number(s.printer_baudrate)===57600?'selected':''}>57600</option><option value="115200" ${Number(s.printer_baudrate)===115200?'selected':''}>115200</option></select></label></div>
    <div class="hint-box"><b>COM-port note:</b> 9600 is the starting value. If the port opens but the printer produces nothing or garbage text, check the printer documentation/vendor settings and try the correct baud rate.</div>
    <div class="mini-actions"><button class="btn" onclick="setPrinterStep(2)">← Back</button><button class="btn" onclick="loadPrinters()">↻ Refresh list</button><button class="btn btn-primary" onclick="savePrinterConfig(true)">Save & test →</button></div>
  </div>
  <div class="panel setup-side"><h2>Current configuration</h2><div class="metric-line"><span>Mode</span><b>${esc(s.printer_mode || 'browser')}</b></div><div class="metric-line"><span>Target</span><b>${esc(s.printer_target || 'Not selected')}</b></div><div class="metric-line"><span>Baud</span><b>${s.printer_baudrate || 9600}</b></div><p class="muted">The selected device is used by automatic order printing after confirmation.</p></div></div>`;
}

function selectedLabel(s) {
  if (!s.printer_target || s.printer_mode === 'browser') return 'Not configured';
  return 'Configured: ' + (s.printer_target || 'device');
}

function printerTestStep(p, s, ps) {
  const test = ps.test;
  return `<div class="setup-grid"><div class="panel setup-main"><div class="section-head tight"><div><span class="eyebrow">STEP 4 OF 4</span><h2>Test the connection</h2><p>Send a real 58mm test receipt using the selected path.</p></div><span class="connection-badge">${test ? (test.ok ? 'Test passed' : 'Test failed') : 'Ready to test'}</span></div>
    <div class="connection-summary"><div><span>Method</span><b>${esc(s.printer_mode || 'browser')}</b></div><div><span>Target</span><b>${esc(s.printer_target || 'Browser print')}</b></div><div><span>Paper</span><b>58mm</b></div></div>
    ${test ? `<div class="test-result ${test.ok?'success':'failure'}"><b>${test.ok?'✓ Connection test passed':'⚠ Connection test failed'}</b><p>${esc(test.message)}</p></div>` : '<div class="empty setup-empty">No test has been run yet.</div>'}
    <div class="mini-actions"><button class="btn" onclick="setPrinterStep(3)">← Change device</button><button class="btn btn-primary" onclick="testHardwarePrint()">${s.printer_mode==='browser'?'Open print test':'Print test receipt again'}</button><button class="btn" onclick="goToDashboardAfterPrinter()">Finish setup</button></div>
    <div class="hint-box"><b>Next:</b> Create an order and press <b>Confirm & Print</b>. The same configured printer will receive the full customer/order ticket.</div>
  </div>
  <div class="panel setup-side"><h2>Troubleshooting</h2><details open><summary>Printer does not appear</summary><p>Confirm Windows says the Bluetooth device is connected. Turn the printer off/on, then click Refresh devices. For COM printing, open Device Manager → Ports (COM & LPT) and verify a COM port exists.</p></details><details><summary>COM port is visible but print fails</summary><p>Close any other app that may be using the COM port. Recheck the selected COM number and try the baud rate specified by the printer vendor.</p></details><details><summary>Windows printer queue is visible but no paper prints</summary><p>Use Windows' own Print Test Page first. If Windows cannot print, fix the driver/queue before testing from Demo Kitchen.</p></details><details><summary>Garbage characters print</summary><p>The baud rate or printer language may be wrong for a serial connection. Verify ESC/POS support and the printer's serial settings.</p></details><details><summary>Printer paired, then disconnects</summary><p>Keep the printer powered and charged, remove old pairings from other phones/PCs, then reconnect it in Windows and scan again.</p></details></div></div>`;
}

function settingsPage() {
  const s = state.settings || {};
  return `<div class="settings-grid"><div class="panel"><h2>Business settings</h2><label>Business name<input id="s-name" value="${esc(s.business_name)}"></label><label>Address<textarea id="s-address">${esc(s.address)}</textarea></label><label>Phone<input id="s-phone" value="${esc(s.phone)}"></label><label>GST number<input id="s-gst" value="${esc(s.gst_number)}"></label></div>
  <div class="panel"><h2>Printer defaults</h2><label>Printer name<input id="s-printer" value="${esc(s.printer_name)}"></label><label>Paper size<select id="s-paper"><option ${s.paper_size==='58mm'?'selected':''}>58mm</option></select></label><label class="switchline"><input id="s-auto" type="checkbox" ${s.auto_print?'checked':''}> Auto-print new orders</label><button class="btn" onclick="nav('printers')">Open Printer Center</button></div>
  <div class="panel"><h2>Order settings</h2><p>Simple defaults for the trial.</p><label>Default order type<select id="s-default"><option ${s.default_order_type==='Pickup'?'selected':''}>Pickup</option><option ${s.default_order_type==='Delivery'?'selected':''}>Delivery</option></select></label><label>Tax %<input id="s-tax" type="number" value="${s.tax_percent}"></label><label>Delivery fee<input id="s-fee" type="number" value="${s.delivery_fee}"></label><button class="btn btn-primary" onclick="saveSettings()">Save settings</button></div></div>`;
}

function categoryIcon(category) {
  const name = typeof category === 'string' ? category : category?.name;
  const cat = (state.categories || []).find(c => c.name === name);
  return cat?.icon || '';
}
function jsArg(value) { return JSON.stringify(String(value)).replace(/'/g, '&#39;'); }

function renderOrderPicker() {
  const wrap = document.getElementById('order-item-picker');
  if (!wrap) return;
  const items = state.menu.filter(i => i.available);
  const cart = state.newOrder?.cart || {};
  const cartCount = Object.values(cart).reduce((sum,q)=>sum+Number(q||0),0);
  const cartTotal = Object.entries(cart).reduce((sum,[id,q]) => { const item=items.find(i=>i.id===Number(id)); return sum+(item?item.price*Number(q||0):0); },0);
  const categoryRows = (state.categories || []).map(c => ({...c, count:items.filter(i=>(i.category||'Other')===c.name).length})).filter(c=>c.count>0);
  // Include any legacy/unknown categories so old menu data never disappears.
  const knownNames = new Set(categoryRows.map(c=>c.name));
  items.forEach(i=>{ const name=i.category||'Other'; if(!knownNames.has(name)){categoryRows.push({id:'legacy-'+name,name,icon:'',count:items.filter(x=>(x.category||'Other')===name).length}); knownNames.add(name);} });

  if (!state.newOrder.category) {
    wrap.innerHTML = `<div class="order-picker-head"><div><b>Choose a category</b><span class="muted">Tap a category to see its dishes.</span></div><div class="mini-actions"><span class="order-cart-badge">${cartCount} item${cartCount===1?'':'s'}</span></div></div>
      <div class="order-category-grid">${categoryRows.map(c => `<button type="button" class="order-category-card" onclick='selectOrderCategory(${jsArg(c.name)})'>${c.icon ? `<span class="order-category-icon">${esc(c.icon)}</span>` : ''}<span class="order-category-name">${esc(c.name)}</span><span class="order-category-count">${c.count} item${c.count===1?'':'s'}</span></button>`).join('')}</div>
      <div class="order-cart-summary ${cartCount?'has-items':''}"><span>${cartCount?`Selected: ${cartCount} item${cartCount===1?'':'s'}`:'No items selected yet'}</span><b>${money(cartTotal)}</b></div>`;
    return;
  }
  const categoryItems = items.filter(i=>(i.category||'Other')===state.newOrder.category);
  const search=String(state.newOrder.search||'').trim().toLowerCase();
  const catItems=search?categoryItems.filter(i=>String(i.name||'').toLowerCase().includes(search)):categoryItems;
  const icon=categoryIcon(state.newOrder.category);
  wrap.innerHTML = `<div class="order-picker-head"><div><button type="button" class="btn btn-small" onclick="selectOrderCategory(null)">← Categories</button><span class="order-category-title">${icon ? esc(icon)+' ' : ''}${esc(state.newOrder.category)}</span></div><span class="order-cart-badge">${cartCount} item${cartCount===1?'':'s'}</span></div>
    <div class="order-item-search"><span class="search-icon">⌕</span><input id="order-item-search" type="search" autocomplete="off" placeholder="Search ${esc(state.newOrder.category)}..." value="${esc(state.newOrder.search||'')}" oninput="setOrderSearch(this.value)"><button type="button" class="clear-search" onclick="setOrderSearch('')" aria-label="Clear search">×</button></div>
    <div class="order-search-meta">${search?`${catItems.length} result${catItems.length===1?'':'s'} in ${esc(state.newOrder.category)}`:`${categoryItems.length} item${categoryItems.length===1?'':'s'} in ${esc(state.newOrder.category)}`}</div>
    <div class="order-product-grid">${catItems.map(i=>{const qty=Number(cart[i.id]||0);return `<div class="order-product-card ${qty?'selected':''}"><div class="product-main"><div class="product-icon">${icon ? esc(icon) : '•'}</div><div><b>${esc(i.name)}</b><span>${money(i.price)}</span></div></div><div class="product-controls">${qty?`<button type="button" class="qty-btn" onclick="changeOrderQty(${i.id},-1)">−</button><strong>${qty}</strong><button type="button" class="qty-btn" onclick="changeOrderQty(${i.id},1)">+</button>`:`<button type="button" class="btn btn-primary btn-small add-item-btn" onclick="changeOrderQty(${i.id},1)">Add</button>`}</div></div>`;}).join('')||'<div class="order-search-empty">No items match your search.</div>'}</div>
    <div class="order-cart-summary ${cartCount?'has-items':''}"><span>${cartCount?`Selected: ${cartCount} item${cartCount===1?'':'s'}`:'No items selected'}</span><b>${money(cartTotal)}</b></div>`;
}
function selectOrderCategory(category) { state.newOrder.category=category; state.newOrder.search=''; renderOrderPicker(); }

function setOrderSearch(value) {
  const input = document.getElementById('order-item-search');
  const start = input ? input.selectionStart : null;
  state.newOrder.search = value;
  renderOrderPicker();
  const next = document.getElementById('order-item-search');
  if (next) {
    next.focus();
    const pos = start == null ? value.length : Math.min(start, value.length);
    next.setSelectionRange(pos, pos);
  }
}

function changeOrderQty(id, delta) {
  const current = Number(state.newOrder?.cart?.[id] || 0) + delta;
  if (current <= 0) delete state.newOrder.cart[id];
  else state.newOrder.cart[id] = current;
  renderOrderPicker();
}

function newOrderSelectedItems() {
  const availableIds = new Set(state.menu.filter(i => i.available).map(i => i.id));
  return Object.entries(state.newOrder.cart || {})
    .filter(([id, q]) => availableIds.has(Number(id)) && Number(q) > 0)
    .map(([id, quantity]) => {
      const item = state.menu.find(i => i.id === Number(id));
      return item ? {...item, quantity:Number(quantity), line_total:item.price * Number(quantity)} : null;
    }).filter(Boolean);
}
function newOrderCartTotals() {
  const items = newOrderSelectedItems();
  const subtotal = items.reduce((sum, i) => sum + i.line_total, 0);
  const delivery = Number(state.newOrder.form?.order_type === 'Delivery' ? (state.settings?.delivery_fee || 0) : 0);
  const tax = subtotal * Number(state.settings?.tax_percent || 0) / 100;
  return {items, subtotal, delivery, tax, total: subtotal + delivery + tax};
}
function captureNewOrderForm(form) {
  const f = new FormData(form);
  state.newOrder.form = {
    customer_name: String(f.get('customer_name') || ''), phone: String(f.get('phone') || ''),
    order_type: String(f.get('order_type') || 'Pickup'), payment_status: String(f.get('payment_status') || 'Paid'),
    address: String(f.get('address') || ''), special_instructions: String(f.get('special_instructions') || '')
  };
}
function orderFormHtml() {
  const f = state.newOrder.form || {};
  return `<div class="new-order-fields"><div class="form-grid"><label>Customer name<input name="customer_name" required value="${esc(f.customer_name || '')}" placeholder="Rahul Sharma"></label><label>Phone<input name="phone" required value="${esc(f.phone || '')}" placeholder="98XXXXXXXX"></label></div>
    <div class="form-grid"><label>Order type<select name="order_type"><option ${f.order_type!=='Delivery'?'selected':''}>Pickup</option><option ${f.order_type==='Delivery'?'selected':''}>Delivery</option></select></label><label>Payment<select name="payment_status"><option ${f.payment_status!=='Pending'?'selected':''}>Paid</option><option ${f.payment_status==='Pending'?'selected':''}>Pending</option></select></label></div>
    <label>Address<input name="address" value="${esc(f.address || '')}" placeholder="Optional"></label></div>`;
}
function reviewOrderHtml() {
  const {items, subtotal, delivery, tax, total} = newOrderCartTotals();
  const f = state.newOrder.form || {};
  return `<div class="review-order-wrap"><div class="review-banner"><div><span class="muted">FINAL CHECK</span><h2>Review order before billing</h2><p>Check the selected dishes, quantities and customer details. Nothing is printed yet.</p></div><span class="review-total">${money(total)}</span></div>
    <div class="review-customer-grid"><div><span>Customer</span><b>${esc(f.customer_name || '—')}</b></div><div><span>Phone</span><b>${esc(f.phone || '—')}</b></div><div><span>Order type</span><b>${esc(f.order_type || 'Pickup')}</b></div><div><span>Payment</span><b>${esc(f.payment_status || 'Paid')}</b></div><div class="full"><span>Address</span><b>${esc(f.address || '—')}</b></div></div>
    <div class="review-items"><div class="review-items-head"><h3>Selected items</h3><button type="button" class="btn btn-small" onclick="backToNewOrderEdit()">← Add / edit items</button></div>${items.map(i => `<div class="review-item"><div><b>${i.quantity}× ${esc(i.name)}</b><span>${money(i.price)} each</span></div><div class="review-item-actions"><button class="qty-btn" type="button" onclick="adjustReviewQty(${i.id},-1)">−</button><strong>${i.quantity}</strong><button class="qty-btn" type="button" onclick="adjustReviewQty(${i.id},1)">+</button><button class="icon-btn danger" type="button" onclick="removeReviewItem(${i.id})" title="Remove item">×</button><b>${money(i.line_total)}</b></div></div>`).join('') || '<div class="empty">No items selected.</div>'}</div>
    ${f.special_instructions ? `<div class="note large">Note: ${esc(f.special_instructions)}</div>` : ''}
    <div class="review-totals"><div><span>Subtotal</span><b>${money(subtotal)}</b></div><div><span>Delivery</span><b>${money(delivery)}</b></div><div><span>Tax</span><b>${money(tax)}</b></div><div class="grand"><span>Total</span><b>${money(total)}</b></div></div>
    <div class="modal-foot"><button type="button" class="btn" onclick="backToNewOrderEdit()">Back to edit</button><button type="button" class="btn btn-primary" onclick="confirmReviewedOrder()">Confirm order & Print</button></div></div>`;
}
function renderNewOrderReview() {
  const modal = document.querySelector('#modal .order-modal');
  if (!modal) return;
  modal.innerHTML = `<div class="modal-head"><div><span class="muted">Quick ticket</span><h2>Review New Order</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div>${reviewOrderHtml()}`;
}
function reviewNewOrder(form) {
  captureNewOrderForm(form);
  const {items} = newOrderCartTotals();
  if (!items.length) return alert('Choose at least one item before reviewing the order.');
  renderNewOrderReview();
}
function backToNewOrderEdit() {
  const modal = document.querySelector('#modal .order-modal');
  if (!modal) return;
  modal.innerHTML = `<div class="modal-head"><div><span class="muted">Quick ticket</span><h2>New Order</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div><form id="order-form">${orderFormHtml()}<div id="order-item-picker"></div><label>Special instructions<textarea name="special_instructions" placeholder="Less spicy, extra sauce...">${esc(state.newOrder.form?.special_instructions || '')}</textarea></label><div class="modal-foot"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn btn-primary" type="submit">Review Order →</button></div></form>`;
  renderOrderPicker();
  const form = document.getElementById('order-form');
  form.onsubmit = async e => { e.preventDefault(); reviewNewOrder(e.target); };
}
function adjustReviewQty(id, delta) { changeOrderQty(id, delta); renderNewOrderReview(); }
function removeReviewItem(id) { delete state.newOrder.cart[id]; renderNewOrderReview(); }

async function confirmReviewedOrder() {
  const f = state.newOrder.form || {};
  const {items} = newOrderCartTotals();
  if (!items.length) return alert('Add at least one item before confirming.');
  if (!f.customer_name || !f.phone) return alert('Customer name and phone are required.');

  const selected = items.map(i => ({menu_item_id:i.id, quantity:i.quantity}));
  const printWin = openPrintShell();

  try {
    // Create the order once. Do not wait for the whole dashboard to reload.
    const o = await api('/api/orders', {
      method:'POST',
      body:JSON.stringify({
        customer_name:f.customer_name,
        phone:f.phone,
        address:f.address,
        order_type:f.order_type,
        items:selected,
        special_instructions:f.special_instructions,
        payment_method:'UPI',
        payment_status:f.payment_status,
        delivery_fee:0,
        auto_print:true
      })
    });

    // Update the dashboard immediately using the order returned by the API.
    // This removes the visible delay caused by re-fetching six endpoints.
    state.orders = [o, ...state.orders.filter(existing => existing.id !== o.id)];
    state.newOrder = {category:null, cart:{}, search:'', form:{customer_name:'', phone:'', order_type:'Pickup', payment_status:'Paid', address:'', special_instructions:''}};
    closeModal();
    render();

    // Refresh secondary dashboard data in the background; it must not block the order UI.
    api('/api/reports').then(data => { state.reports = data; render(); }).catch(() => {});

    // Printing happens after the order is visible. Any direct-printer failure falls back
    // to the browser print preview without interrupting the dashboard with an alert.
    printOrderInto(o, printWin).catch(() => {});
  } catch (err) {
    if (printWin) printWin.close();
    alert(err.message || 'Could not create order');
  }
}

function openNewOrder() {
  state.newOrder = {category: null, cart: {}, search: '', form: {customer_name:'', phone:'', order_type:'Pickup', payment_status:'Paid', address:'', special_instructions:''}};
  const html = `<div class="modal-card order-modal"><div class="modal-head"><div><span class="muted">Quick ticket</span><h2>New Order</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div>
  <form id="order-form">${orderFormHtml()}<div id="order-item-picker"></div><label>Special instructions<textarea name="special_instructions" placeholder="Less spicy, extra sauce..."></textarea></label><div class="modal-foot"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn btn-primary" type="submit">Review Order →</button></div></form></div>`;
  showModal(html);
  renderOrderPicker();
  document.getElementById('order-form').onsubmit = async e => { e.preventDefault(); reviewNewOrder(e.target); };
}

function showModal(html) { let m = document.getElementById('modal'); if (!m) { m = document.createElement('div'); m.id = 'modal'; document.body.appendChild(m); } m.innerHTML = html; m.classList.add('show'); }
function closeModal() { document.getElementById('modal')?.classList.remove('show'); }
async function showOrder(id) { const o = await api('/api/orders/' + id); state.selectedOrder = o; showModal(orderDetails(o)); }
function orderDetails(o) { return `<div class="modal-card wide"><div class="modal-head"><div><span class="muted">Order details</span><h2>#${o.order_number} · ${esc(o.customer_name)}</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div><div class="detail-grid"><div><span>Status</span><b>${o.status}</b></div><div><span>Total</span><b>${money(o.total)}</b></div><div><span>Type</span><b>${o.order_type}</b></div><div><span>Payment</span><b>${o.payment_status}</b></div></div><div class="detail-items">${o.items.map(i => `<div><span>${i.quantity}× ${esc(i.item_name)}</span><b>${money(i.unit_price*i.quantity)}</b></div>`).join('')}<div><span>Customer phone</span><b>${esc(o.phone)}</b></div>${o.address?`<div><span>Address</span><b>${esc(o.address)}</b></div>`:''}</div>${o.special_instructions?`<div class="note large">${esc(o.special_instructions)}</div>`:''}<div class="status-flow">${['New','Accepted','Preparing','Ready','Completed'].map(s => `<button class="flow-btn ${o.status===s?'current':''}" onclick="moveOrder(${o.id},'${s}')">${s}</button>`).join('')}</div><div class="modal-foot"><button class="btn" onclick="printOrder(${o.id})">Print order</button><button class="btn btn-primary" onclick="closeModal()">Done</button></div></div>`; }
async function moveOrder(id, status) { await api('/api/orders/' + id, { method:'PUT', body:JSON.stringify({status}) }); closeModal(); await load(); }

function receiptHtml(o) {
  const s = state.settings || {};
  return `<html><head><title>Order #${o.order_number}</title><style>@page{size:58mm auto;margin:0}body{width:58mm;margin:0;padding:7px;font-family:monospace;font-size:11px;color:#000}.center{text-align:center}.row{display:flex;justify-content:space-between;gap:5px}.line{border-top:1px dashed #000;margin:7px 0}.total{font-weight:bold;font-size:13px}.note{white-space:pre-wrap}.thanks{text-align:center;margin-top:10px}</style></head><body><div class="center"><b>${esc(s.business_name || 'Demo Kitchen')}</b><br>KITCHEN ORDER</div><div class="line"></div><div class="row"><span>Order</span><span>#${o.order_number}</span></div><div class="row"><span>Date</span><span>${fmtDate(o.created_at)}</span></div><div class="row"><span>Time</span><span>${fmtTime(o.created_at)}</span></div><div class="line"></div><div>Customer: ${esc(o.customer_name)}</div><div>Phone: ${esc(o.phone)}</div>${o.address?`<div>Address: ${esc(o.address)}</div>`:''}<div class="line"></div>${o.items.map(i=>`<div class="row"><span>${i.quantity}× ${esc(i.item_name)}</span><span>${money(i.unit_price*i.quantity)}</span></div>`).join('')}<div class="line"></div><div class="row"><span>Subtotal</span><span>${money(o.subtotal)}</span></div><div class="row"><span>Delivery</span><span>${money(o.delivery_fee)}</span></div><div class="row"><span>Tax</span><span>${money(o.tax)}</span></div><div class="row total"><span>TOTAL</span><span>${money(o.total)}</span></div><div class="line"></div><div>Type: ${esc(o.order_type)}</div><div>Payment: ${esc(o.payment_status)}</div>${o.special_instructions?`<div class="line"></div><div class="note">Note: ${esc(o.special_instructions)}</div>`:''}<div class="thanks">THANK YOU</div><script>window.onload=()=>setTimeout(()=>window.print(),250)</script></body></html>`;
}
function openPrintShell() {
  try { const win = window.open('', '_blank', 'width=420,height=700'); if (win) { win.document.write('<html><body style="font-family:system-ui;padding:24px">Preparing ticket…</body></html>'); win.document.close(); } return win; } catch { return null; }
}
async function printOrderInto(o, win) {
  const s = state.settings || {};
  if ((s.printer_mode === 'windows' || s.printer_mode === 'serial') && s.printer_target) {
    try {
      const result = await api('/api/printers/print', { method:'POST', body:JSON.stringify({order_id:o.id}) });
      if (win) win.close();
      return;
    } catch (err) {
      if (win) { win.document.open(); win.document.write(receiptHtml(o)); win.document.close(); }
      return;
    }
  }
  if (win) { win.document.open(); win.document.write(receiptHtml(o)); win.document.close(); }
  else window.print();
}
async function printOrder(id) {
  const win = openPrintShell();
  try { const o = await api('/api/print/' + id); await printOrderInto(o, win); }
  catch (err) { if (win) win.close(); alert(err.message || 'Could not print order'); }
}
async function testHardwarePrint() {
  const s = state.settings || {};
  if (!s.printer_target || !['windows','serial'].includes(s.printer_mode)) return testPrint();
  try { const result = await api('/api/printers/test', { method:'POST' }); alert(result.message || 'Test print sent.'); }
  catch (err) { alert(err.message || 'Printer test failed'); }
}
function testPrint() {
  const win = openPrintShell(); if (!win) return alert('Allow popups to use browser print.');
  const name = state.settings?.business_name || 'Demo Kitchen';
  win.document.open(); win.document.write(`<html><head><title>Printer Test</title><style>@page{size:58mm auto;margin:0}body{width:58mm;padding:10px;font-family:monospace;text-align:center}hr{border:0;border-top:1px dashed #000}</style></head><body><h3>${esc(name)}</h3><p>THERMAL PRINTER TEST</p><hr><p>58mm PAPER</p><p>Customer: Test User</p><p>Phone: 98XXXXXXXX</p><hr><p>Printer connection OK</p><p>Thank you</p><script>window.onload=()=>setTimeout(()=>window.print(),250)</script></body></html>`); win.document.close();
}

function openMenuModal(item = null, presetCategory = '') {
  const currentCategory = item?.category || presetCategory || state.categories?.[0]?.name || '';
  const categoryOptions = (state.categories || []).map(c => `<option value="${esc(c.name)}" ${currentCategory===c.name?'selected':''}>${esc(c.name)}</option>`).join('');
  showModal(`<div class="modal-card"><div class="modal-head"><div><span class="muted">Menu item</span><h2>${item ? 'Edit dish' : 'Add dish'}</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div>
    <p class="muted">Add the dish here, choose which category it belongs to, and it will appear under that category in New Order.</p>
    <form id="menu-form">
      <label>Item name<input name="name" required value="${esc(item?.name || '')}" placeholder="Paneer Lababdar"></label>
      <label>Category<select name="category" required>${categoryOptions || '<option value="">Create a category first</option>'}</select></label>
      <div class="form-grid"><label>Price (₹)<input name="price" type="number" min="1" step="1" required value="${item?.price || ''}" placeholder="229"></label><label class="switchline"><input name="available" type="checkbox" ${item?.available !== false ? 'checked' : ''}> Available for order</label></div>
      <div class="hint-box"><b>Tip:</b> You can move an existing dish to another category here. The New Order screen will immediately use the new structure.</div>
      <div class="modal-foot"><button class="btn" type="button" onclick="closeModal()">Cancel</button>${state.categories?.length ? '<button class="btn btn-primary">Save item</button>' : ''}</div>
    </form></div>`);
  const form = document.getElementById('menu-form');
  if (!form) return;
  form.onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const category = String(f.get('category') || '').trim();
    if (!category) return alert('Create a category before adding a dish.');
    try {
      const payload = { name:String(f.get('name')||'').trim(), category, price:Number(f.get('price')), available:f.get('available') === 'on' };
      await api(item ? '/api/menu-items/' + item.id : '/api/menu-items', { method:item ? 'PUT' : 'POST', body:JSON.stringify(payload) });
      closeModal(); await load();
    } catch (err) { alert(err.message || 'Could not save item'); }
  };
}

async function toggleMenu(id, available) { const i = state.menu.find(x => x.id === id); await api('/api/menu-items/' + id, { method:'PUT', body:JSON.stringify({name:i.name,category:i.category,price:i.price,available}) }); await load(); }
async function deleteMenu(id) { if (confirm('Delete this menu item?')) { await api('/api/menu-items/' + id, {method:'DELETE'}); await load(); } }

function openInventoryModal() {
  showModal(`<div class="modal-card"><div class="modal-head"><div><span class="muted">Inventory</span><h2>Add purchase</h2></div><button class="icon-btn" onclick="closeModal()">×</button></div><form id="inventory-form"><div class="form-grid"><label>Item name<input name="item_name" required placeholder="Tomatoes"></label><label>Category<input name="category" value="Vegetables"></label></div><div class="form-grid"><label>Quantity<input name="quantity" type="number" step="0.01" min="0.01" value="1" required></label><label>Unit<select name="unit"><option>kg</option><option>g</option><option>litre</option><option>ml</option><option>pcs</option><option>box</option><option>packet</option></select></label></div><div class="form-grid"><label>Price per unit (₹)<input name="unit_price" type="number" step="0.01" min="0" value="100" required></label><label>Purchase date<input name="purchase_date" type="date" value="${new Date().toISOString().slice(0,10)}"></label></div><label>Notes<input name="notes" placeholder="Supplier, quality, etc."></label><div class="inventory-total-preview" id="inventory-total-preview">Total purchase: ₹100</div><div class="modal-foot"><button type="button" class="btn" onclick="closeModal()">Cancel</button><button class="btn btn-primary">Add purchase</button></div></form></div>`);
  const form = document.getElementById('inventory-form');
  const updateTotal = () => { const f = new FormData(form); document.getElementById('inventory-total-preview').textContent = 'Total purchase: ' + money(Number(f.get('quantity') || 0) * Number(f.get('unit_price') || 0)); };
  form.addEventListener('input', updateTotal);
  form.onsubmit = async e => { e.preventDefault(); const f = new FormData(e.target); await api('/api/inventory', {method:'POST', body:JSON.stringify({item_name:f.get('item_name'),category:f.get('category'),quantity:Number(f.get('quantity')),unit:f.get('unit'),unit_price:Number(f.get('unit_price')),purchase_date:f.get('purchase_date'),notes:f.get('notes')})}); closeModal(); state.inventory.month = String(f.get('purchase_date')).slice(0,7); await loadInventory(); };
}
async function deleteInventory(id) { if (confirm('Delete this purchase record?')) { await api('/api/inventory/' + id, {method:'DELETE'}); await loadInventory(); } }

function setPrinterStep(step) { state.printerSetup.step = step; render(); if (step === 2) loadPrinters().catch(() => {}); }
async function pickPrinter(mode, target) { state.settings.printer_mode = mode; state.settings.printer_target = target; state.printerSetup.step = 3; state.printerSetup.test = null; render(); }
function syncPrinterTargets() { const mode = document.getElementById('p-mode')?.value; const target = document.getElementById('p-target'); if (!target) return; [...target.options].forEach(o => { o.hidden = o.value && o.dataset.mode && o.dataset.mode !== mode; }); const selected = [...target.options].find(o => !o.hidden && o.value === state.settings.printer_target); if (selected) target.value = selected.value; else if (mode === 'browser') target.value = ''; }
async function savePrinterConfig(goToTest = false) {
  const s = state.settings || {};
  const mode = document.getElementById('p-mode').value, target = document.getElementById('p-target').value, name = document.getElementById('p-name').value;
  const baud = Number(document.getElementById('p-baud')?.value || s.printer_baudrate || 9600);
  if (mode !== 'browser' && !target) return alert('Select a printer or COM port first.');
  state.settings = await api('/api/settings', {method:'PUT', body:JSON.stringify({...s, printer_mode:mode, printer_target:target, printer_name:name, printer_baudrate:baud})});
  state.printerSetup.step = goToTest ? 4 : 3;
  state.printerSetup.test = null;
  render();
  if (goToTest) setTimeout(() => testHardwarePrint(), 80);
}
async function testHardwarePrint() {
  const s = state.settings || {};
  if (!s.printer_target || !['windows','serial'].includes(s.printer_mode)) {
    state.printerSetup.test = {ok:true, message:'Browser print fallback selected. A 58mm print preview will open.'};
    render();
    testPrint();
    return;
  }
  try {
    const result = await api('/api/printers/test', { method:'POST' });
    state.printerSetup.test = {ok:true, message: result.message || 'Test print sent successfully.'};
  } catch (err) {
    state.printerSetup.test = {ok:false, message:err.message || 'Printer test failed.'};
  }
  state.printerSetup.step = 4;
  render();
}
function goToDashboardAfterPrinter() { state.printerSetup.test = null; nav('dashboard'); }

async function saveSettings() { const s = state.settings || {}; const p = {business_name:document.getElementById('s-name').value,address:document.getElementById('s-address').value,phone:document.getElementById('s-phone').value,gst_number:document.getElementById('s-gst').value,printer_name:document.getElementById('s-printer').value,paper_size:document.getElementById('s-paper').value,auto_print:document.getElementById('s-auto').checked,default_order_type:document.getElementById('s-default').value,tax_percent:Number(document.getElementById('s-tax').value || 0),delivery_fee:Number(document.getElementById('s-fee').value || 0),printer_mode:s.printer_mode || 'browser',printer_target:s.printer_target || '',printer_baudrate:Number(s.printer_baudrate || 9600)}; state.settings = await api('/api/settings',{method:'PUT',body:JSON.stringify(p)}); render(); alert('Settings saved.'); }
async function resetDemo() { if (confirm('Reset demo orders and inventory to the sample dataset?')) { await api('/api/demo/reset',{method:'POST'}); await load(); } }

window.nav=nav; window.openNewOrder=openNewOrder; window.selectOrderCategory=selectOrderCategory; window.reviewNewOrder=reviewNewOrder; window.backToNewOrderEdit=backToNewOrderEdit; window.adjustReviewQty=adjustReviewQty; window.removeReviewItem=removeReviewItem; window.confirmReviewedOrder=confirmReviewedOrder; window.reorderCategory=reorderCategory; window.changeOrderQty=changeOrderQty; window.showOrder=showOrder; window.printOrder=printOrder; window.moveOrder=moveOrder; window.filterOrders=filterOrders; window.openMenuModal=openMenuModal; window.openCategoryModal=openCategoryModal; window.deleteCategory=deleteCategory; window.toggleMenu=toggleMenu; window.deleteMenu=deleteMenu; window.openInventoryModal=openInventoryModal; window.deleteInventory=deleteInventory; window.saveSettings=saveSettings; window.loadPrinters=loadPrinters; window.pickPrinter=pickPrinter; window.savePrinterConfig=savePrinterConfig; window.setPrinterStep=setPrinterStep; window.syncPrinterTargets=syncPrinterTargets; window.testHardwarePrint=testHardwarePrint; window.goToDashboardAfterPrinter=goToDashboardAfterPrinter; window.testPrint=testPrint; window.resetDemo=resetDemo; window.closeModal=closeModal; window.loadInventory=loadInventory;

load().catch(e => { app.innerHTML = `<div style="padding:40px;font-family:system-ui"><h1>Could not start Demo Kitchen</h1><p>${esc(e.message)}</p></div>`; });
