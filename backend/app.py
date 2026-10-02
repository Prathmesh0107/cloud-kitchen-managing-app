from datetime import datetime, timedelta
from pathlib import Path
import os
import sqlite3
import textwrap
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
DB_PATH = BASE / 'demo_kitchen.db'
STATIC = ROOT / 'frontend'

app = FastAPI(title='Demo Kitchen API', version='0.2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

STATUSES = ['New', 'Accepted', 'Preparing', 'Ready', 'Completed', 'Cancelled']


class MenuItemIn(BaseModel):
    name: str
    category: str
    price: float = Field(gt=0)
    available: bool = True


class CategoryIn(BaseModel):
    name: str
    icon: str = ''


class CategoryOrderIn(BaseModel):
    category_ids: list[int]


class OrderItemIn(BaseModel):
    menu_item_id: int
    quantity: int = Field(ge=1)


class OrderIn(BaseModel):
    customer_name: str
    phone: str
    address: str = ''
    order_type: str = 'Pickup'
    items: list[OrderItemIn]
    special_instructions: str = ''
    payment_method: str = 'Cash'
    payment_status: str = 'Pending'
    delivery_fee: float = 0
    auto_print: bool = False


class SettingsIn(BaseModel):
    business_name: str
    address: str = ''
    phone: str = ''
    gst_number: str = ''
    printer_name: str = '58mm Mini Thermal Printer'
    paper_size: str = '58mm'
    auto_print: bool = False
    default_order_type: str = 'Pickup'
    tax_percent: float = 0
    delivery_fee: float = 0
    printer_mode: str = 'browser'
    printer_target: str = ''
    printer_baudrate: int = 9600


class InventoryPurchaseIn(BaseModel):
    item_name: str
    category: str = 'Raw Material'
    quantity: float = Field(gt=0)
    unit: str = 'kg'
    unit_price: float = Field(ge=0)
    purchase_date: str = ''
    notes: str = ''


class HardwarePrintIn(BaseModel):
    order_id: int
    target: str = ''
    mode: str = ''


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def add_column_if_missing(c, table: str, column: str, definition: str):
    cols = {r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
    if column not in cols:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def init_db():
    c = conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS settings (
      id INTEGER PRIMARY KEY CHECK(id=1), business_name TEXT NOT NULL, address TEXT, phone TEXT,
      gst_number TEXT, printer_name TEXT, paper_size TEXT, auto_print INTEGER, default_order_type TEXT,
      tax_percent REAL, delivery_fee REAL, printer_mode TEXT DEFAULT 'browser', printer_target TEXT DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS menu_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
      price REAL NOT NULL, available INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS categories (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, icon TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_number INTEGER UNIQUE NOT NULL,
      customer_name TEXT NOT NULL, phone TEXT NOT NULL, address TEXT, order_type TEXT NOT NULL,
      subtotal REAL NOT NULL, delivery_fee REAL NOT NULL, tax REAL NOT NULL, total REAL NOT NULL,
      special_instructions TEXT, payment_method TEXT, payment_status TEXT, status TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS order_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, menu_item_id INTEGER NOT NULL,
      item_name TEXT NOT NULL, quantity INTEGER NOT NULL, unit_price REAL NOT NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id)
    );
    CREATE TABLE IF NOT EXISTS inventory_purchases (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      item_name TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'Raw Material',
      quantity REAL NOT NULL,
      unit TEXT NOT NULL DEFAULT 'kg',
      unit_price REAL NOT NULL DEFAULT 0,
      total_cost REAL NOT NULL DEFAULT 0,
      purchase_date TEXT NOT NULL,
      notes TEXT DEFAULT ''
    );
    ''')
    add_column_if_missing(c, 'settings', 'printer_mode', "TEXT DEFAULT 'browser'")
    add_column_if_missing(c, 'settings', 'printer_target', "TEXT DEFAULT ''")
    add_column_if_missing(c, 'settings', 'printer_baudrate', "INTEGER DEFAULT 9600")
    if not c.execute('SELECT 1 FROM settings WHERE id=1').fetchone():
        c.execute('INSERT INTO settings (id,business_name,address,phone,gst_number,printer_name,paper_size,auto_print,default_order_type,tax_percent,delivery_fee,printer_mode,printer_target,printer_baudrate) VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
            'Demo Kitchen', '123 Demo Street, Pune', '98XXXXXXXX', '',
            '58mm Mini Thermal Printer', '58mm', 0, 'Pickup', 0, 0, 'browser', '', 9600
        ))
    if c.execute('SELECT COUNT(*) AS n FROM menu_items').fetchone()['n'] == 0:
        items = [
            ('Margherita Pizza', 'Pizza', 199, 1), ('Farmhouse Pizza', 'Pizza', 249, 1),
            ('Paneer Tikka Pizza', 'Pizza', 279, 1), ('Veggie Supreme Pizza', 'Pizza', 299, 1),
            ('Veg Burger', 'Burgers', 129, 1), ('Cheese Burst Burger', 'Burgers', 169, 1),
            ('Paneer Burger', 'Burgers', 159, 1), ('Classic Burger', 'Burgers', 149, 1),
            ('French Fries', 'Snacks', 99, 1), ('Masala Fries', 'Snacks', 119, 1),
            ('Paneer Wrap', 'Sandwiches', 149, 1), ('Grilled Veg Sandwich', 'Sandwiches', 139, 1),
            ('Paneer Lababdar', 'Paneer', 229, 1), ('Paneer Masala', 'Paneer', 219, 1),
            ('Cold Coffee', 'Beverages', 99, 1), ('Fresh Lime Soda', 'Beverages', 79, 1)
        ]
        c.executemany('INSERT INTO menu_items(name,category,price,available) VALUES (?,?,?,?)', items)
    # Ensure category configuration exists for every menu category. Icons are optional.
    defaults = {'Pizza':'🍕','Burgers':'🍔','Sandwiches':'🥪','Snacks':'🍟','Beverages':'🥤','Desserts':'🍰','Combos':'🍱','Paneer':''}
    existing = {r['name'] for r in c.execute('SELECT name FROM categories').fetchall()}
    for idx, name in enumerate([r['category'] for r in c.execute('SELECT DISTINCT category FROM menu_items ORDER BY category').fetchall()]):
        if name not in existing:
            c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (?,?,?)', (name, defaults.get(name,''), idx))
    if c.execute('SELECT COUNT(*) AS n FROM orders').fetchone()['n'] == 0:
        seed_orders(c)
    if c.execute('SELECT COUNT(*) AS n FROM inventory_purchases').fetchone()['n'] == 0:
        seed_inventory(c)
    c.commit(); c.close()


def seed_orders(c):
    menu = {r['name']: r for r in c.execute('SELECT * FROM menu_items').fetchall()}
    seed = [
        ('Rahul Sharma', '9876543210', 'Baner, Pune', 'Pickup', [('Veg Burger', 2), ('French Fries', 1)], 'Less spicy', 'UPI', 'Paid', 'New', 10),
        ('Neha Patil', '9822001122', 'Aundh, Pune', 'Delivery', [('Margherita Pizza', 1), ('Cold Coffee', 2)], 'Call on arrival', 'UPI', 'Paid', 'Accepted', 25),
        ('Amit Joshi', '9890012345', 'Wakad, Pune', 'Delivery', [('Paneer Wrap', 2), ('Masala Fries', 1)], 'No onion', 'Cash', 'Pending', 'Preparing', 30),
        ('Priya Desai', '9765012345', 'Kothrud, Pune', 'Pickup', [('Farmhouse Pizza', 1)], 'Extra cheese', 'Card', 'Paid', 'Ready', 0),
        ('Vikram Kulkarni', '9712345678', 'Hinjewadi, Pune', 'Delivery', [('Cheese Burst Burger', 2), ('Cold Coffee', 1)], 'Pack separately', 'UPI', 'Paid', 'Completed', 30),
        ('Sneha More', '9811112233', 'Viman Nagar, Pune', 'Pickup', [('Margherita Pizza', 2)], '', 'UPI', 'Paid', 'Completed', 0),
        ('Arjun Shah', '9900011223', 'Kharadi, Pune', 'Delivery', [('Veg Burger', 1), ('French Fries', 2)], 'Extra ketchup', 'Cash', 'Paid', 'Completed', 20),
        ('Pooja Kale', '9822334455', 'Pimple Saudagar, Pune', 'Pickup', [('Paneer Wrap', 1), ('Cold Coffee', 1)], '', 'UPI', 'Paid', 'Cancelled', 0),
        ('Rohan Gawde', '9898989898', 'Bavdhan, Pune', 'Delivery', [('Farmhouse Pizza', 1), ('French Fries', 1)], 'Well done', 'UPI', 'Paid', 'Preparing', 25),
        ('Meera Rao', '9988776655', 'Magarpatta, Pune', 'Pickup', [('Veg Burger', 1), ('Masala Fries', 1)], '', 'Card', 'Paid', 'Completed', 0),
    ]
    start = datetime.now() - timedelta(hours=8)
    for idx, rec in enumerate(seed, start=1):
        customer, phone, addr, ot, items, note, pm, ps, status, delivery = rec
        subtotal = sum(menu[n]['price'] * q for n, q in items)
        tax = 0
        total = subtotal + delivery
        created = (start + timedelta(minutes=idx * 37)).isoformat(timespec='seconds')
        cur = c.execute(
            'INSERT INTO orders(order_number,customer_name,phone,address,order_type,subtotal,delivery_fee,tax,total,special_instructions,payment_method,payment_status,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (1000 + idx, customer, phone, addr, ot, subtotal, delivery, tax, total, note, pm, ps, status, created)
        )
        oid = cur.lastrowid
        for n, q in items:
            mi = menu[n]
            c.execute('INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_price) VALUES (?,?,?,?,?)', (oid, mi['id'], n, q, mi['price']))


def seed_inventory(c):
    today = datetime.now().date().isoformat()
    month_offset = (datetime.now().replace(day=1) - timedelta(days=10)).replace(day=10).date().isoformat()
    data = [
        ('Tomatoes', 'Vegetables', 5, 'kg', 100, today, 'Demo purchase'),
        ('Onion', 'Vegetables', 5, 'kg', 55, today, ''),
        ('Paneer', 'Dairy', 3, 'kg', 280, month_offset, ''),
        ('Burger Buns', 'Bakery', 50, 'pcs', 8, month_offset, ''),
        ('Cheese', 'Dairy', 2, 'kg', 420, month_offset, ''),
    ]
    c.executemany(
        'INSERT INTO inventory_purchases(item_name,category,quantity,unit,unit_price,total_cost,purchase_date,notes) VALUES (?,?,?,?,?,?,?,?)',
        [(n, cat, q, u, p, q * p, d, note) for n, cat, q, u, p, d, note in data]
    )


def serialize_order(row):
    c = conn()
    items = [dict(r) for r in c.execute('SELECT menu_item_id,item_name,quantity,unit_price FROM order_items WHERE order_id=?', (row['id'],)).fetchall()]
    c.close()
    d = dict(row)
    d['items'] = items
    return d


def print_ticket_text(order, settings):
    width = 32
    def line(char='-'):
        return char * width
    def wrapped(label, value):
        s = f'{label}: {value}'
        return '\n'.join(textwrap.wrap(s, width=width))
    lines = [
        ' ' * max(0, (width - len(settings.get('business_name', 'Demo Kitchen'))) // 2) + settings.get('business_name', 'Demo Kitchen'),
        ' ' * 10 + 'KITCHEN ORDER',
        line(),
        f"Order: #{order['order_number']}",
        f"Date: {datetime.fromisoformat(order['created_at']).strftime('%d-%m-%Y')}",
        f"Time: {datetime.fromisoformat(order['created_at']).strftime('%I:%M %p')}",
        line(),
        wrapped('Customer', order['customer_name']),
        wrapped('Phone', order['phone']),
    ]
    if order.get('address'):
        lines.append(wrapped('Address', order['address']))
    lines.append(line())
    for item in order['items']:
        name = item['item_name'][:20]
        price = f"Rs {item['unit_price'] * item['quantity']:.0f}"
        lines.append(f"{item['quantity']}x {name:<20} {price:>7}")
    lines += [
        line(),
        f"{'Subtotal':<23} Rs {order['subtotal']:.0f}",
        f"{'Delivery':<23} Rs {order['delivery_fee']:.0f}",
        f"{'Tax':<23} Rs {order['tax']:.0f}",
        f"{'TOTAL':<23} Rs {order['total']:.0f}",
        line(),
        f"Type: {order['order_type']}",
        f"Payment: {order['payment_status']}",
    ]
    if order.get('special_instructions'):
        lines += [line(), wrapped('Note', order['special_instructions'])]
    lines += [line(), ' ' * 11 + 'THANK YOU', '', '']
    return '\n'.join(lines)


def escpos_bytes(text: str) -> bytes:
    return b'\x1b@' + text.encode('ascii', errors='replace') + b'\n\n\x1dV\x41\x03'


@app.on_event('startup')
def startup():
    init_db()


@app.get('/')
def root():
    return FileResponse(STATIC / 'index.html')


@app.get('/static/{path:path}')
def static_files(path: str):
    return FileResponse(STATIC / path)


@app.get('/api/settings')
def get_settings():
    c = conn(); r = c.execute('SELECT * FROM settings WHERE id=1').fetchone(); c.close(); return dict(r)


@app.put('/api/settings')
def update_settings(payload: SettingsIn):
    c = conn()
    c.execute(
        'UPDATE settings SET business_name=?,address=?,phone=?,gst_number=?,printer_name=?,paper_size=?,auto_print=?,default_order_type=?,tax_percent=?,delivery_fee=?,printer_mode=?,printer_target=?,printer_baudrate=? WHERE id=1',
        (payload.business_name, payload.address, payload.phone, payload.gst_number, payload.printer_name,
         payload.paper_size, int(payload.auto_print), payload.default_order_type, payload.tax_percent,
         payload.delivery_fee, payload.printer_mode, payload.printer_target, payload.printer_baudrate)
    )
    c.commit(); c.close(); return get_settings()


@app.get('/api/categories')
def get_categories():
    c = conn(); rows = [dict(r) for r in c.execute('SELECT * FROM categories ORDER BY sort_order, name')]; c.close(); return rows


@app.post('/api/categories')
def add_category(payload: CategoryIn):
    name = payload.name.strip()
    icon = payload.icon.strip()
    if not name:
        raise HTTPException(400, 'Category name is required')
    c = conn()
    try:
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        cur = c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (?,?,?)', (name, icon, max_order + 1))
        c.commit(); row = c.execute('SELECT * FROM categories WHERE id=?', (cur.lastrowid,)).fetchone()
        return dict(row)
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'A category with this name already exists')
    finally:
        c.close()


@app.put('/api/categories/{category_id}')
def update_category(category_id: int, payload: CategoryIn):
    name = payload.name.strip(); icon = payload.icon.strip()
    if not name: raise HTTPException(400, 'Category name is required')
    c = conn(); row = c.execute('SELECT * FROM categories WHERE id=?', (category_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404, 'Category not found')
    old_name = row['name']
    try:
        c.execute('UPDATE categories SET name=?, icon=? WHERE id=?', (name, icon, category_id))
        if old_name != name:
            c.execute('UPDATE menu_items SET category=? WHERE category=?', (name, old_name))
        c.commit(); out = c.execute('SELECT * FROM categories WHERE id=?', (category_id,)).fetchone(); return dict(out)
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'A category with this name already exists')
    finally:
        c.close()


@app.post('/api/categories/reorder')
def reorder_categories(payload: CategoryOrderIn):
    c = conn()
    try:
        existing = [r['id'] for r in c.execute('SELECT id FROM categories ORDER BY sort_order, id').fetchall()]
        requested = []
        seen = set()
        for cid in payload.category_ids:
            if cid in existing and cid not in seen:
                requested.append(cid); seen.add(cid)
        requested += [cid for cid in existing if cid not in seen]
        for idx, cid in enumerate(requested):
            c.execute('UPDATE categories SET sort_order=? WHERE id=?', (idx, cid))
        c.commit()
        return [dict(r) for r in c.execute('SELECT * FROM categories ORDER BY sort_order, name').fetchall()]
    finally:
        c.close()


@app.delete('/api/categories/{category_id}')
def delete_category(category_id: int):
    c = conn(); row = c.execute('SELECT * FROM categories WHERE id=?', (category_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404, 'Category not found')
    count = c.execute('SELECT COUNT(*) AS n FROM menu_items WHERE category=?', (row['name'],)).fetchone()['n']
    if count:
        c.close(); raise HTTPException(409, f'Cannot delete {row["name"]} while it still has {count} menu item(s). Move or delete those items first.')
    c.execute('DELETE FROM categories WHERE id=?', (category_id,)); c.commit(); c.close(); return {'ok': True}


@app.get('/api/menu-items')
def get_menu_items():
    c = conn(); rows = [dict(r) for r in c.execute('SELECT * FROM menu_items ORDER BY category,name')]; c.close(); return rows


@app.post('/api/menu-items')
def add_menu_item(payload: MenuItemIn):
    c = conn(); category = payload.category.strip() or 'Other'
    if not c.execute('SELECT 1 FROM categories WHERE name=?', (category,)).fetchone():
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (?,?,?)', (category, '', max_order + 1))
    cur = c.execute('INSERT INTO menu_items(name,category,price,available) VALUES (?,?,?,?)', (payload.name, category, payload.price, int(payload.available))); c.commit(); r = c.execute('SELECT * FROM menu_items WHERE id=?', (cur.lastrowid,)).fetchone(); c.close(); return dict(r)


@app.put('/api/menu-items/{item_id}')
def update_menu_item(item_id: int, payload: MenuItemIn):
    c = conn()
    if not c.execute('SELECT 1 FROM menu_items WHERE id=?', (item_id,)).fetchone(): c.close(); raise HTTPException(404, 'Menu item not found')
    category = payload.category.strip() or 'Other'
    if not c.execute('SELECT 1 FROM categories WHERE name=?', (category,)).fetchone():
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (?,?,?)', (category, '', max_order + 1))
    c.execute('UPDATE menu_items SET name=?,category=?,price=?,available=? WHERE id=?', (payload.name, category, payload.price, int(payload.available), item_id)); c.commit(); r = c.execute('SELECT * FROM menu_items WHERE id=?', (item_id,)).fetchone(); c.close(); return dict(r)


@app.delete('/api/menu-items/{item_id}')
def delete_menu_item(item_id: int):
    c = conn(); c.execute('DELETE FROM menu_items WHERE id=?', (item_id,)); c.commit(); c.close(); return {'ok': True}


@app.get('/api/orders')
def get_orders(status: Optional[str] = None, q: Optional[str] = None):
    c = conn(); sql = 'SELECT * FROM orders WHERE 1=1'; args = []
    if status: sql += ' AND status=?'; args.append(status)
    if q: sql += ' AND (CAST(order_number AS TEXT) LIKE ? OR customer_name LIKE ? OR phone LIKE ?)'; like = f'%{q}%'; args += [like, like, like]
    sql += ' ORDER BY datetime(created_at) DESC'
    rows = c.execute(sql, args).fetchall(); c.close(); return [serialize_order(r) for r in rows]


@app.get('/api/orders/{order_id}')
def get_order(order_id: int):
    c = conn(); r = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404, 'Order not found')
    return serialize_order(r)


@app.post('/api/orders')
def create_order(payload: OrderIn):
    c = conn()
    if not payload.items:
        raise HTTPException(400, 'Add at least one item')
    placeholders = ','.join('?' for _ in payload.items)
    rows = c.execute(f'SELECT * FROM menu_items WHERE id IN ({placeholders})', tuple(i.menu_item_id for i in payload.items)).fetchall()
    by_id = {r['id']: r for r in rows}
    if any(i.menu_item_id not in by_id for i in payload.items): raise HTTPException(400, 'Invalid menu item')
    subtotal = sum(by_id[i.menu_item_id]['price'] * i.quantity for i in payload.items)
    settings = c.execute('SELECT * FROM settings WHERE id=1').fetchone()
    tax = subtotal * (settings['tax_percent'] or 0) / 100
    delivery = payload.delivery_fee
    if delivery == 0 and payload.order_type == 'Delivery': delivery = settings['delivery_fee'] or 0
    total = subtotal + tax + delivery
    next_num = c.execute('SELECT COALESCE(MAX(order_number),1000)+1 AS n FROM orders').fetchone()['n']
    created = datetime.now().isoformat(timespec='seconds')
    cur = c.execute(
        'INSERT INTO orders(order_number,customer_name,phone,address,order_type,subtotal,delivery_fee,tax,total,special_instructions,payment_method,payment_status,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (next_num, payload.customer_name, payload.phone, payload.address, payload.order_type, subtotal, delivery, tax, total, payload.special_instructions, payload.payment_method, payload.payment_status, 'New', created)
    )
    oid = cur.lastrowid
    for i in payload.items:
        mi = by_id[i.menu_item_id]
        c.execute('INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_price) VALUES (?,?,?,?,?)', (oid, mi['id'], mi['name'], i.quantity, mi['price']))
    c.commit(); r = c.execute('SELECT * FROM orders WHERE id=?', (oid,)).fetchone(); c.close(); return serialize_order(r)


@app.put('/api/orders/{order_id}')
def update_order(order_id: int, payload: dict):
    allowed = {'status', 'payment_status', 'special_instructions'}
    changes = {k: v for k, v in payload.items() if k in allowed}
    if 'status' in changes and changes['status'] not in STATUSES: raise HTTPException(400, 'Invalid status')
    if not changes: raise HTTPException(400, 'No supported changes')
    c = conn()
    if not c.execute('SELECT 1 FROM orders WHERE id=?', (order_id,)).fetchone(): raise HTTPException(404, 'Order not found')
    set_clause = ', '.join(f'{k}=?' for k in changes)
    c.execute(f'UPDATE orders SET {set_clause} WHERE id=?', (*changes.values(), order_id)); c.commit(); r = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); c.close(); return serialize_order(r)


@app.get('/api/reports')
def reports():
    c = conn(); orders = c.execute('SELECT * FROM orders').fetchall(); completed = [o for o in orders if o['status'] == 'Completed']
    revenue = sum(o['total'] for o in completed); total_orders = len(orders); avg = (revenue / len(completed)) if completed else 0
    counts = {}
    for r in c.execute('SELECT item_name, SUM(quantity) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.status != "Cancelled" GROUP BY item_name ORDER BY qty DESC').fetchall(): counts[r['item_name']] = r['qty']
    c.close(); return {'today_revenue': round(revenue, 2), 'orders': total_orders, 'average_order': round(avg, 2), 'most_ordered': list(counts.items())[:5], 'completed': len(completed), 'cancelled': len([o for o in orders if o['status'] == 'Cancelled'])}


@app.get('/api/inventory')
def get_inventory(month: Optional[str] = Query(default=None, pattern=r'^\d{4}-\d{2}$'), q: Optional[str] = None):
    month = month or datetime.now().strftime('%Y-%m')
    c = conn()
    sql = "SELECT * FROM inventory_purchases WHERE substr(purchase_date,1,7)=?"
    args = [month]
    if q:
        sql += ' AND (item_name LIKE ? OR category LIKE ?)'; like = f'%{q}%'; args.extend([like, like])
    sql += ' ORDER BY purchase_date DESC, id DESC'
    rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    total = sum(r['total_cost'] for r in rows)
    by_item = [dict(r) for r in c.execute(
        "SELECT item_name, category, unit, ROUND(SUM(quantity),2) quantity, ROUND(SUM(total_cost),2) total_cost FROM inventory_purchases WHERE substr(purchase_date,1,7)=? GROUP BY item_name, category, unit ORDER BY total_cost DESC",
        (month,)
    ).fetchall()]
    c.close()
    return {'month': month, 'total_spend': round(total, 2), 'purchases': rows, 'by_item': by_item}


@app.post('/api/inventory')
def add_inventory(payload: InventoryPurchaseIn):
    date = payload.purchase_date or datetime.now().date().isoformat()
    total = round(payload.quantity * payload.unit_price, 2)
    c = conn(); cur = c.execute(
        'INSERT INTO inventory_purchases(item_name,category,quantity,unit,unit_price,total_cost,purchase_date,notes) VALUES (?,?,?,?,?,?,?,?)',
        (payload.item_name.strip(), payload.category.strip() or 'Raw Material', payload.quantity, payload.unit.strip() or 'kg', payload.unit_price, total, date, payload.notes.strip())
    ); c.commit(); r = c.execute('SELECT * FROM inventory_purchases WHERE id=?', (cur.lastrowid,)).fetchone(); c.close(); return dict(r)


@app.delete('/api/inventory/{purchase_id}')
def delete_inventory(purchase_id: int):
    c = conn(); c.execute('DELETE FROM inventory_purchases WHERE id=?', (purchase_id,)); c.commit(); c.close(); return {'ok': True}


@app.post('/api/demo/reset')
def reset_demo():
    c = conn(); c.execute('DELETE FROM order_items'); c.execute('DELETE FROM orders'); c.execute('DELETE FROM inventory_purchases'); c.commit(); seed_orders(c); seed_inventory(c); c.commit(); c.close(); return {'ok': True}


@app.get('/api/print/{order_id}')
def print_order(order_id: int):
    c = conn(); r = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404, 'Order not found')
    return serialize_order(r)


@app.get('/api/printers')
def list_printers():
    printers = []
    ports = []
    # Windows printer queues (Bluetooth/USB printers installed with a driver usually appear here).
    try:
        import win32print
        for p in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS, None, 2):
            printers.append({'name': p.get('pPrinterName'), 'driver': p.get('pDriverName', ''), 'port': p.get('pPortName', ''), 'kind': 'windows'})
    except Exception:
        pass
    # Bluetooth SPP devices and USB serial devices often appear as COM ports.
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            ports.append({'name': p.description or p.device, 'port': p.device, 'manufacturer': p.manufacturer or '', 'kind': 'serial'})
    except Exception:
        pass
    return {'printers': printers, 'ports': ports, 'platform': os.name}


def send_windows_raw(printer_name: str, data: bytes):
    import win32print
    handle = win32print.OpenPrinter(printer_name)
    try:
        job = win32print.StartDocPrinter(handle, 1, ('Demo Kitchen', None, 'RAW'))
        try:
            win32print.StartPagePrinter(handle)
            win32print.WritePrinter(handle, data)
            win32print.EndPagePrinter(handle)
        finally:
            win32print.EndDocPrinter(handle)
    finally:
        win32print.ClosePrinter(handle)
    return job


def send_serial(port: str, data: bytes, baudrate: int = 9600):
    import serial
    with serial.Serial(port=port, baudrate=baudrate, timeout=2, write_timeout=2) as s:
        s.write(data)
        s.flush()


@app.post('/api/printers/test')
def test_hardware_print():
    c = conn(); settings = dict(c.execute('SELECT * FROM settings WHERE id=1').fetchone()); c.close()
    mode = settings.get('printer_mode') or 'browser'; target = settings.get('printer_target') or ''
    if mode == 'browser':
        return {'ok': True, 'mode': 'browser', 'message': 'Browser print fallback selected. Use the Settings > Printer Center test print.'}
    data = escpos_bytes((settings.get('business_name') or 'Demo Kitchen') + '\n' + 'THERMAL PRINTER TEST\n' + '-'*32 + '\n58mm PAPER\nPrinter connection OK\n\n')
    try:
        if mode == 'windows' and target:
            send_windows_raw(target, data)
        elif mode == 'serial' and target:
            send_serial(target, data, int(settings.get('printer_baudrate') or 9600))
        else:
            raise ValueError('Printer mode or target is not configured')
    except Exception as e:
        raise HTTPException(400, f'Printer test failed: {e}')
    return {'ok': True, 'mode': mode, 'target': target, 'message': 'Printer test sent successfully.'}


@app.post('/api/printers/print')
def hardware_print(payload: HardwarePrintIn):
    c = conn(); order_row = c.execute('SELECT * FROM orders WHERE id=?', (payload.order_id,)).fetchone(); settings_row = c.execute('SELECT * FROM settings WHERE id=1').fetchone(); c.close()
    if not order_row: raise HTTPException(404, 'Order not found')
    order = serialize_order(order_row)
    settings = dict(settings_row)
    mode = payload.mode or settings.get('printer_mode') or 'browser'
    target = payload.target or settings.get('printer_target') or ''
    text = print_ticket_text(order, settings)
    if mode == 'browser':
        return {'ok': True, 'mode': 'browser', 'message': 'Use the browser print preview.', 'text': text}
    data = escpos_bytes(text)
    try:
        if mode == 'windows' and target:
            send_windows_raw(target, data)
        elif mode == 'serial' and target:
            send_serial(target, data, int(settings.get('printer_baudrate') or 9600))
        else:
            raise ValueError('Printer mode or target is not configured')
    except Exception as e:
        raise HTTPException(400, f'Could not print to {target or "selected printer"}: {e}')
    return {'ok': True, 'mode': mode, 'target': target, 'message': 'Print job sent successfully.'}
