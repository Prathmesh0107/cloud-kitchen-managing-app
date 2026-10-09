from datetime import datetime, timedelta
from pathlib import Path
import base64
import hashlib
import hmac
import os
import re
import secrets
import textwrap
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from psycopg import connect, errors
from psycopg.rows import dict_row

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
load_dotenv(ROOT / '.env')
DB_URL = os.getenv('DATABASE_URL', '').strip()
STATIC = ROOT / 'frontend'

_docs_on = os.getenv('ENABLE_DOCS', '').strip().lower() in ('1', 'true', 'yes', 'on')   # API docs are OFF unless asked for (and owner-only when on)
app = FastAPI(title='Demo Kitchen API', version='0.2.0',
              docs_url='/docs' if _docs_on else None, redoc_url='/redoc' if _docs_on else None, openapi_url='/openapi.json' if _docs_on else None)
_cors_origins = [o.strip() for o in os.getenv('CORS_ORIGINS', '').split(',') if o.strip()]   # the app is same-origin, so no CORS unless listed
if _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type'])

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
    customer_name: str = ''   # optional: walk-in orders have no name
    phone: str = ''           # optional
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
    food_license: str = ''
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
    quantity: float = Field(default=1, gt=0)
    unit: str = 'batch'
    unit_price: float = Field(default=0, ge=0)
    amount: Optional[float] = Field(default=None, ge=0)   # total paid. When given it wins over quantity x unit price
    purchase_date: str = ''
    notes: str = ''


def purchase_numbers(p):
    """(unit_price, total_cost) for a purchase. Just typing the amount paid is enough."""
    if p.amount is not None:
        total = round(p.amount, 2)
        return round(total / p.quantity, 2), total
    return p.unit_price, round(p.quantity * p.unit_price, 2)


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class UserCreateIn(BaseModel):
    username: str
    name: str = ''
    password: str
    role: str = 'staff'


class UserUpdateIn(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    password: Optional[str] = None


class HardwarePrintIn(BaseModel):
    order_id: int
    target: str = ''
    mode: str = ''


class HardwarePrintBatchIn(BaseModel):
    order_ids: list[int]
    target: str = ''
    mode: str = ''


def conn():
    if not DB_URL:
        raise RuntimeError('DATABASE_URL is not set. Create a .env file locally or set the Render environment variable.')
    kwargs = {'row_factory': dict_row, 'connect_timeout': 10}
    if 'sslmode=' not in DB_URL:
        kwargs['sslmode'] = 'require'
    return connect(DB_URL, **kwargs)


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def init_db():
    # The schema is created once in Supabase SQL Editor. Here we only ensure
    # baseline settings/categories exist and optionally seed demo data.
    c = conn()
    try:
        # Food license (FSSAI) number shown on receipts. Safe to run on every start.
        try:
            c.execute("ALTER TABLE settings ADD COLUMN IF NOT EXISTS food_license TEXT NOT NULL DEFAULT ''")
            c.commit()
        except Exception as exc:
            c.rollback()
            print('Could not add settings.food_license (receipts will skip it):', exc)
        ensure_auth(c)
        if not c.execute('SELECT 1 FROM settings WHERE id=1').fetchone():
            c.execute(
                'INSERT INTO settings (id,business_name,address,phone,gst_number,printer_name,paper_size,auto_print,default_order_type,tax_percent,delivery_fee,printer_mode,printer_target,printer_baudrate) VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                ('Demo Kitchen', '123 Demo Street, Pune', '98XXXXXXXX', '',
                 '58mm Mini Thermal Printer', '58mm', False, 'Pickup', 0, 0, 'browser', '', 9600)
            )

        defaults = {'Pizza':'🍕','Burgers':'🍔','Sandwiches':'🥪','Snacks':'🍟','Beverages':'🥤','Desserts':'🍰','Combos':'🍱','Paneer':''}
        existing = {r['name'] for r in c.execute('SELECT name FROM categories').fetchall()}
        default_categories = [('Pizza','🍕'),('Burgers','🍔'),('Paneer',''),('Sandwiches','🥪'),('Snacks','🍟'),('Beverages','🥤')]
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        for name, icon in default_categories:
            if name not in existing:
                max_order += 1
                c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (%s,%s,%s)', (name, icon, max_order))

        if env_flag('SEED_DEMO_DATA', False):
            if c.execute('SELECT COUNT(*) AS n FROM menu_items').fetchone()['n'] == 0:
                items = [
                    ('Margherita Pizza', 'Pizza', 199, True), ('Farmhouse Pizza', 'Pizza', 249, True),
                    ('Paneer Tikka Pizza', 'Pizza', 279, True), ('Veggie Supreme Pizza', 'Pizza', 299, True),
                    ('Veg Burger', 'Burgers', 129, True), ('Cheese Burst Burger', 'Burgers', 169, True),
                    ('Paneer Burger', 'Burgers', 159, True), ('Classic Burger', 'Burgers', 149, True),
                    ('French Fries', 'Snacks', 99, True), ('Masala Fries', 'Snacks', 119, True),
                    ('Paneer Wrap', 'Sandwiches', 149, True), ('Grilled Veg Sandwich', 'Sandwiches', 139, True),
                    ('Paneer Lababdar', 'Paneer', 229, True), ('Paneer Masala', 'Paneer', 219, True),
                    ('Cold Coffee', 'Beverages', 99, True), ('Fresh Lime Soda', 'Beverages', 79, True)
                ]
                c.executemany('INSERT INTO menu_items(name,category,price,available) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING', items)
            # Demo ORDERS are only seeded when SEED_DEMO_ORDERS=true, so clearing orders stays cleared after a restart.
            if env_flag('SEED_DEMO_ORDERS', False) and c.execute('SELECT COUNT(*) AS n FROM orders').fetchone()['n'] == 0:
                seed_orders(c)
            if c.execute('SELECT COUNT(*) AS n FROM inventory_purchases').fetchone()['n'] == 0:
                seed_inventory(c)
        c.commit()
    finally:
        c.close()

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
        oid = c.execute(
            'INSERT INTO orders(order_number,customer_name,phone,address,order_type,subtotal,delivery_fee,tax,total,special_instructions,payment_method,payment_status,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
            (1000 + idx, customer, phone, addr, ot, subtotal, delivery, tax, total, note, pm, ps, status, created)
        ).fetchone()['id']
        for n, q in items:
            mi = menu[n]
            c.execute('INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_price) VALUES (%s,%s,%s,%s,%s)', (oid, mi['id'], n, q, mi['price']))


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
        'INSERT INTO inventory_purchases(item_name,category,quantity,unit,unit_price,total_cost,purchase_date,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
        [(n, cat, q, u, p, q * p, d, note) for n, cat, q, u, p, d, note in data]
    )


def serialize_order(row):
    c = conn()
    items = [dict(r) for r in c.execute('SELECT menu_item_id,item_name,quantity,unit_price FROM order_items WHERE order_id=%s', (row['id'],)).fetchall()]
    c.close()
    d = dict(row)
    d['items'] = items
    return d


def business_name(settings):
    return (settings.get('business_name') or '').strip() or 'Demo Kitchen'


def print_ticket_text(order, settings):
    width = 32
    created_value = order.get('created_at')
    created_dt = created_value if isinstance(created_value, datetime) else datetime.fromisoformat(str(created_value))
    def line(char='-'):
        return char * width
    def wrapped(label, value):
        s = f'{label}: {value}'
        return '\n'.join(textwrap.wrap(s, width=width))
    name = business_name(settings)
    lines = [t.center(width).rstrip() for t in (textwrap.wrap(name, width=width) or [name])]
    if (settings.get('food_license') or '').strip():
        lines += [t.center(width).rstrip() for t in textwrap.wrap('FSSAI Lic: ' + settings['food_license'].strip(), width=width)]
    lines += [
        ' ' * 10 + 'KITCHEN ORDER',
        line(),
        f"Order: #{order['order_number']}",
        f"Date: {created_dt.strftime('%d-%m-%Y')}",
        f"Time: {created_dt.strftime('%I:%M %p')}",
        line(),
    ]
    # name, phone and address are optional: only print what was entered
    who = []
    if (order.get('customer_name') or '').strip(): who.append(wrapped('Customer', order['customer_name'].strip()))
    if (order.get('phone') or '').strip(): who.append(wrapped('Phone', order['phone'].strip()))
    if (order.get('address') or '').strip(): who.append(wrapped('Address', order['address'].strip()))
    if who:
        lines += who + [line()]
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
        f"Payment: {'UPI' if str(order.get('payment_method') or '').strip().upper() == 'UPI' else 'Cash'}",
    ]
    if order.get('special_instructions'):
        lines += [line(), wrapped('Note', order['special_instructions'])]
    lines += [line(), ' ' * 11 + 'THANK YOU', '', '']
    return '\n'.join(lines)


def escpos_bytes(text: str) -> bytes:
    # UTF-8 matches ASCII for English names and keeps the saved business name as typed.
    return b'\x1b@\x1bG\x01\x1bE\x01\x1b!\x18' + text.encode('utf-8', errors='replace') + b'\n\n\x1dV\x41\x03'


@app.on_event('startup')
def startup():
    init_db()


# ------------------------------------------------------------------ login, sessions and users
AUTH_REQUIRED = env_flag('AUTH_REQUIRED', True)   # emergency switch: AUTH_REQUIRED=false turns the login off
COOKIE = 'dk_session'
SESSION_DAYS = 30
MIN_PASSWORD = 6
PUBLIC_API = {'/api/login', '/api/logout'}
OWNER_ONLY = {('POST', '/api/orders/clear'), ('PUT', '/api/settings'), ('POST', '/api/demo/reset')}
USERNAME_RE = re.compile(r'^[a-z0-9._-]{3,32}$')
GUEST = {'id': 0, 'username': 'guest', 'name': 'Guest', 'role': 'owner', 'active': True, 'must_change_password': False, 'auth_disabled': True}
_session_cache = {}   # token_hash -> (valid_until, user)
_login_fails = {}     # "ip|username" -> [timestamps]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode('ascii')


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    try:
        dk = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=32)
        return f'scrypt${_b64(salt)}${_b64(dk)}'
    except (AttributeError, ValueError):   # Python built without scrypt
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 240000, 32)
        return f'pbkdf2${_b64(salt)}${_b64(dk)}'


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, hash_b64 = stored.split('$')
        salt, want = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        if scheme == 'scrypt':
            got = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1, dklen=32)
        elif scheme == 'pbkdf2':
            got = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 240000, 32)
        else:
            return False
        return hmac.compare_digest(got, want)
    except Exception:
        return False


DUMMY_HASH = hash_password('not-a-real-password')   # so unknown usernames cost the same time as wrong passwords


def ensure_auth(c):
    """Create the login tables and the first owner. Safe to run on every start."""
    try:
        c.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'staff', active BOOLEAN NOT NULL DEFAULT TRUE, must_change_password BOOLEAN NOT NULL DEFAULT FALSE, created_at TEXT NOT NULL DEFAULT '')")
        c.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL)')
        c.commit()
    except Exception as exc:
        c.rollback()
        print('Could not create the users/sessions tables (login will not work until they exist):', exc)
        return
    if c.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 0:
        username = (os.getenv('ADMIN_USERNAME') or 'admin').strip().lower()
        password = os.getenv('ADMIN_PASSWORD') or ''
        is_default = not password
        if is_default:
            password = 'admin123'
        c.execute(
            'INSERT INTO users(username,name,password_hash,role,active,must_change_password,created_at) VALUES (%s,%s,%s,%s,TRUE,%s,%s)',
            (username, 'Owner', hash_password(password), 'owner', is_default, datetime.now().isoformat(timespec='seconds'))
        )
        c.commit()


def public_user(row):
    return {'id': row['id'], 'username': row['username'], 'name': row['name'] or row['username'], 'role': row['role'],
            'active': bool(row['active']), 'must_change_password': bool(row['must_change_password'])}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def create_session(c, user):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    c.execute('DELETE FROM sessions WHERE expires_at < %s', (now,))
    c.execute('INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES (%s,%s,%s,%s)', (_token_hash(token), user['id'], now, now + SESSION_DAYS * 86400))
    c.commit()
    _session_cache[_token_hash(token)] = (time.time() + 60, user)
    return token


def lookup_session(token: str):
    th = _token_hash(token)
    now = time.time()
    hit = _session_cache.get(th)
    if hit and hit[0] > now:
        return hit[1]
    c = conn()
    try:
        row = c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=%s AND s.expires_at>%s AND u.active', (th, int(now))).fetchone()
    finally:
        c.close()
    if not row:
        _session_cache.pop(th, None)
        return None
    user = public_user(row)
    _session_cache[th] = (now + 60, user)
    return user


def forget_sessions(user_id: int):
    for key, (_, user) in list(_session_cache.items()):
        if user['id'] == user_id:
            _session_cache.pop(key, None)


def current_user(request: Request):
    return GUEST if not AUTH_REQUIRED else getattr(request.state, 'user', None)


def _is_https(request: Request) -> bool:
    return request.url.scheme == 'https' or request.headers.get('x-forwarded-proto', '').split(',')[0].strip() == 'https'


def _client_ip(request: Request) -> str:
    # The proxy in front (Render) APPENDS the real client address, so the LAST entry is trustworthy; earlier entries can be forged.
    hops = [h.strip() for h in request.headers.get('x-forwarded-for', '').split(',') if h.strip()]
    return hops[-1] if hops else (request.client.host if request.client else '?')


def _locked(key: str, limit: int) -> bool:
    now = time.time()
    fails = [t for t in _login_fails.get(key, []) if now - t < 600]
    _login_fails[key] = fails
    return len(fails) >= limit


def _harden(resp, request: Request, path: str):
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    resp.headers['X-Frame-Options'] = 'DENY'
    resp.headers['Referrer-Policy'] = 'same-origin'
    if _is_https(request):
        resp.headers['Strict-Transport-Security'] = 'max-age=15552000'
    if path.startswith('/api/'):
        resp.headers['Cache-Control'] = 'no-store'   # never keep orders / logins in a shared device's cache
    return resp


@app.middleware('http')
async def auth_guard(request: Request, call_next):
    path = request.url.path.rstrip('/') or '/'
    docs = path in ('/docs', '/redoc', '/openapi.json', '/docs/oauth2-redirect')
    if not AUTH_REQUIRED or not (path.startswith('/api/') or docs) or path in PUBLIC_API or request.method == 'OPTIONS':
        return _harden(await call_next(request), request, path)
    token = request.cookies.get(COOKIE)
    user = None
    if token:
        try:
            user = await run_in_threadpool(lookup_session, token)
        except Exception as exc:
            print('Login lookup failed:', exc)   # details stay in the server log, never in the response
            return _harden(JSONResponse({'detail': 'The login service is not available right now. Please try again in a moment.'}, status_code=503), request, path)
    if not user:
        return _harden(JSONResponse({'detail': 'Please log in.'}, status_code=401), request, path)
    if (docs or path.startswith('/api/users') or (request.method, path) in OWNER_ONLY) and user['role'] != 'owner':
        return _harden(JSONResponse({'detail': 'Only the owner can do this.'}, status_code=403), request, path)
    request.state.user = user
    return _harden(await call_next(request), request, path)


@app.post('/api/login')
def login(payload: LoginIn, request: Request):
    username = payload.username.strip().lower()
    ip_key, user_key = f'{_client_ip(request)}|{username}', f'user|{username}'
    if _locked(ip_key, 6) or _locked(user_key, 12):   # per address, and per account (so rotating addresses does not help)
        raise HTTPException(429, 'Too many wrong attempts. Please wait 10 minutes and try again.')
    c = conn()
    try:
        row = c.execute('SELECT * FROM users WHERE username=%s', (username,)).fetchone()
        ok = verify_password(payload.password, row['password_hash'] if row else DUMMY_HASH) and bool(row) and bool(row['active'])
        if not ok:
            _login_fails.setdefault(ip_key, []).append(time.time())
            _login_fails.setdefault(user_key, []).append(time.time())
            raise HTTPException(401, 'Wrong username or password.')
        _login_fails.pop(ip_key, None)
        _login_fails.pop(user_key, None)
        user = public_user(row)
        token = create_session(c, user)
    finally:
        c.close()
    resp = JSONResponse(user)
    resp.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite='lax', secure=_is_https(request), path='/')
    return resp


@app.post('/api/logout')
def logout(request: Request):
    token = request.cookies.get(COOKIE)
    if token:
        th = _token_hash(token)
        _session_cache.pop(th, None)
        try:
            c = conn()
            try:
                c.execute('DELETE FROM sessions WHERE token_hash=%s', (th,))
                c.commit()
            finally:
                c.close()
        except Exception:
            pass
    resp = JSONResponse({'ok': True})
    resp.delete_cookie(COOKIE, path='/')
    return resp


@app.get('/api/me')
def whoami(request: Request):
    return current_user(request)


@app.post('/api/me/password')
def change_my_password(payload: PasswordChangeIn, request: Request):
    user = current_user(request)
    if user.get('auth_disabled'):
        raise HTTPException(400, 'Login is switched off on this server.')
    if len(payload.new_password) < MIN_PASSWORD:
        raise HTTPException(400, f'The new password must be at least {MIN_PASSWORD} characters.')
    c = conn()
    try:
        row = c.execute('SELECT * FROM users WHERE id=%s', (user['id'],)).fetchone()
        if not row or not verify_password(payload.current_password, row['password_hash']):
            raise HTTPException(400, 'Your current password is not correct.')
        if payload.new_password == payload.current_password:
            raise HTTPException(400, 'Please choose a different password from the current one.')
        c.execute('UPDATE users SET password_hash=%s, must_change_password=FALSE WHERE id=%s', (hash_password(payload.new_password), user['id']))
        c.execute('DELETE FROM sessions WHERE user_id=%s AND token_hash<>%s', (user['id'], _token_hash(request.cookies.get(COOKIE, ''))))   # other devices must log in again
        c.commit()
    finally:
        c.close()
    forget_sessions(user['id'])
    return {'ok': True}


def _owner_count(c) -> int:
    return c.execute("SELECT COUNT(*) AS n FROM users WHERE role='owner' AND active").fetchone()['n']


@app.get('/api/users')
def list_users():
    c = conn()
    try:
        return [public_user(r) for r in c.execute('SELECT * FROM users ORDER BY id').fetchall()]
    finally:
        c.close()


@app.post('/api/users')
def create_user(payload: UserCreateIn):
    username = payload.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(400, 'Username must be 3 to 32 characters: letters, numbers, dot, dash or underscore.')
    if len(payload.password) < MIN_PASSWORD:
        raise HTTPException(400, f'The password must be at least {MIN_PASSWORD} characters.')
    role = 'owner' if payload.role == 'owner' else 'staff'
    c = conn()
    try:
        if c.execute('SELECT 1 FROM users WHERE username=%s', (username,)).fetchone():
            raise HTTPException(409, 'That username is already taken.')
        row = c.execute(
            'INSERT INTO users(username,name,password_hash,role,active,must_change_password,created_at) VALUES (%s,%s,%s,%s,TRUE,FALSE,%s) RETURNING *',
            (username, payload.name.strip(), hash_password(payload.password), role, datetime.now().isoformat(timespec='seconds'))
        ).fetchone()
        c.commit()
        return public_user(row)
    finally:
        c.close()


@app.put('/api/users/{user_id}')
def update_user(user_id: int, payload: UserUpdateIn, request: Request):
    me = current_user(request)
    c = conn()
    try:
        row = c.execute('SELECT * FROM users WHERE id=%s', (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        name = row['name'] if payload.name is None else payload.name.strip()
        role = row['role'] if payload.role is None else ('owner' if payload.role == 'owner' else 'staff')
        active = bool(row['active']) if payload.active is None else payload.active
        if row['role'] == 'owner' and row['active'] and (role != 'owner' or not active) and _owner_count(c) <= 1:
            raise HTTPException(400, 'There must always be at least one active owner.')
        if user_id == me['id'] and not active:
            raise HTTPException(400, "You can't switch off your own login.")
        new_password = (payload.password or '')
        if new_password and len(new_password) < MIN_PASSWORD:
            raise HTTPException(400, f'The password must be at least {MIN_PASSWORD} characters.')
        c.execute('UPDATE users SET name=%s, role=%s, active=%s WHERE id=%s', (name, role, active, user_id))
        if new_password:
            c.execute('UPDATE users SET password_hash=%s, must_change_password=FALSE WHERE id=%s', (hash_password(new_password), user_id))
        if new_password or not active:
            keep = _token_hash(request.cookies.get(COOKIE, '')) if user_id == me['id'] else ''
            c.execute('DELETE FROM sessions WHERE user_id=%s AND token_hash<>%s', (user_id, keep))
        c.commit()
        updated = c.execute('SELECT * FROM users WHERE id=%s', (user_id,)).fetchone()
    finally:
        c.close()
    forget_sessions(user_id)
    return public_user(updated)


@app.delete('/api/users/{user_id}')
def delete_user(user_id: int, request: Request):
    if user_id == current_user(request)['id']:
        raise HTTPException(400, "You can't remove your own login.")
    c = conn()
    try:
        row = c.execute('SELECT * FROM users WHERE id=%s', (user_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        if row['role'] == 'owner' and row['active'] and _owner_count(c) <= 1:
            raise HTTPException(400, 'There must always be at least one active owner.')
        c.execute('DELETE FROM sessions WHERE user_id=%s', (user_id,))
        c.execute('DELETE FROM users WHERE id=%s', (user_id,))
        c.commit()
    finally:
        c.close()
    forget_sessions(user_id)
    return {'ok': True}


@app.get('/')
def root():
    return FileResponse(STATIC / 'index.html')


@app.get('/static/{path:path}')
def static_files(path: str):
    base = STATIC.resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():   # never serve anything outside frontend/ (e.g. .env)
        raise HTTPException(404, 'Not found')
    return FileResponse(target)


@app.get('/api/settings')
def get_settings():
    c = conn(); r = c.execute('SELECT * FROM settings WHERE id=1').fetchone(); c.close(); return dict(r)


@app.put('/api/settings')
def update_settings(payload: SettingsIn):
    name = (payload.business_name or '').strip()
    if not name:
        raise HTTPException(400, 'Business name is required')
    c = conn()
    c.execute(
        'UPDATE settings SET business_name=%s,address=%s,phone=%s,gst_number=%s,printer_name=%s,paper_size=%s,auto_print=%s,default_order_type=%s,tax_percent=%s,delivery_fee=%s,printer_mode=%s,printer_target=%s,printer_baudrate=%s WHERE id=1',
        (name, payload.address, payload.phone, payload.gst_number, payload.printer_name,
         payload.paper_size, payload.auto_print, payload.default_order_type, payload.tax_percent,
         payload.delivery_fee, payload.printer_mode, payload.printer_target, payload.printer_baudrate)
    )
    c.commit()
    try:  # separate statement so the other settings still save even if the column is missing
        c.execute('UPDATE settings SET food_license=%s WHERE id=1', (payload.food_license.strip(),))
        c.commit()
    except Exception as exc:
        c.rollback()
        print('Could not save food_license:', exc)
    c.close(); return get_settings()


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
        row = c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (%s,%s,%s) RETURNING id', (name, icon, max_order + 1)).fetchone()
        category_id = row['id']
        c.commit(); row = c.execute('SELECT * FROM categories WHERE id=%s', (category_id,)).fetchone()
        return dict(row)
    except errors.UniqueViolation:
        raise HTTPException(409, 'A category with this name already exists')
    finally:
        c.close()


@app.put('/api/categories/{category_id}')
def update_category(category_id: int, payload: CategoryIn):
    name = payload.name.strip(); icon = payload.icon.strip()
    if not name: raise HTTPException(400, 'Category name is required')
    c = conn(); row = c.execute('SELECT * FROM categories WHERE id=%s', (category_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404, 'Category not found')
    old_name = row['name']
    try:
        c.execute('UPDATE categories SET name=%s, icon=%s WHERE id=%s', (name, icon, category_id))
        if old_name != name:
            c.execute('UPDATE menu_items SET category=%s WHERE category=%s', (name, old_name))
        c.commit(); out = c.execute('SELECT * FROM categories WHERE id=%s', (category_id,)).fetchone(); return dict(out)
    except errors.UniqueViolation:
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
            c.execute('UPDATE categories SET sort_order=%s WHERE id=%s', (idx, cid))
        c.commit()
        return [dict(r) for r in c.execute('SELECT * FROM categories ORDER BY sort_order, name').fetchall()]
    finally:
        c.close()


@app.delete('/api/categories/{category_id}')
def delete_category(category_id: int):
    c = conn(); row = c.execute('SELECT * FROM categories WHERE id=%s', (category_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404, 'Category not found')
    count = c.execute('SELECT COUNT(*) AS n FROM menu_items WHERE category=%s', (row['name'],)).fetchone()['n']
    if count:
        c.close(); raise HTTPException(409, f'Cannot delete {row["name"]} while it still has {count} menu item(s). Move or delete those items first.')
    c.execute('DELETE FROM categories WHERE id=%s', (category_id,)); c.commit(); c.close(); return {'ok': True}


@app.get('/api/menu-items')
def get_menu_items():
    c = conn(); rows = [dict(r) for r in c.execute('SELECT * FROM menu_items ORDER BY category,name')]; c.close(); return rows


@app.post('/api/menu-items')
def add_menu_item(payload: MenuItemIn):
    c = conn(); category = payload.category.strip() or 'Other'
    if not c.execute('SELECT 1 FROM categories WHERE name=%s', (category,)).fetchone():
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (%s,%s,%s)', (category, '', max_order + 1))
    r = c.execute('INSERT INTO menu_items(name,category,price,available) VALUES (%s,%s,%s,%s) RETURNING *', (payload.name, category, payload.price, payload.available)).fetchone(); c.commit(); c.close(); return dict(r)


@app.put('/api/menu-items/{item_id}')
def update_menu_item(item_id: int, payload: MenuItemIn):
    c = conn()
    if not c.execute('SELECT 1 FROM menu_items WHERE id=%s', (item_id,)).fetchone(): c.close(); raise HTTPException(404, 'Menu item not found')
    category = payload.category.strip() or 'Other'
    if not c.execute('SELECT 1 FROM categories WHERE name=%s', (category,)).fetchone():
        max_order = c.execute('SELECT COALESCE(MAX(sort_order), -1) AS n FROM categories').fetchone()['n']
        c.execute('INSERT INTO categories(name,icon,sort_order) VALUES (%s,%s,%s)', (category, '', max_order + 1))
    c.execute('UPDATE menu_items SET name=%s,category=%s,price=%s,available=%s WHERE id=%s', (payload.name, category, payload.price, int(payload.available), item_id)); c.commit(); r = c.execute('SELECT * FROM menu_items WHERE id=%s', (item_id,)).fetchone(); c.close(); return dict(r)


@app.delete('/api/menu-items/{item_id}')
def delete_menu_item(item_id: int):
    c = conn(); c.execute('DELETE FROM menu_items WHERE id=%s', (item_id,)); c.commit(); c.close(); return {'ok': True}


@app.get('/api/orders')
def get_orders(status: Optional[str] = None, q: Optional[str] = None, month: Optional[str] = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    month = month or datetime.now().strftime('%Y-%m')
    start = datetime.strptime(month + '-01', '%Y-%m-%d')
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    c = conn(); sql = 'SELECT * FROM orders WHERE created_at >= %s AND created_at < %s'; args = [start, end]
    if status: sql += ' AND status=%s'; args.append(status)
    if q: sql += ' AND (CAST(order_number AS TEXT) LIKE %s OR customer_name LIKE %s OR phone LIKE %s)'; like = f'%{q}%'; args += [like, like, like]
    sql += ' ORDER BY created_at DESC'
    rows = c.execute(sql, args).fetchall(); c.close(); return [serialize_order(r) for r in rows]


@app.get('/api/orders/{order_id}')
def get_order(order_id: int):
    c = conn(); r = c.execute('SELECT * FROM orders WHERE id=%s', (order_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404, 'Order not found')
    return serialize_order(r)


@app.post('/api/orders')
def create_order(payload: OrderIn):
    c = conn()
    if not payload.items:
        raise HTTPException(400, 'Add at least one item')
    method = 'UPI' if str(payload.payment_method or '').strip().upper() == 'UPI' else 'Cash'
    payload.payment_method = method
    payload.payment_status = 'Paid'
    placeholders = ','.join('%s' for _ in payload.items)
    rows = c.execute(f'SELECT * FROM menu_items WHERE id IN ({placeholders})', tuple(i.menu_item_id for i in payload.items)).fetchall()
    by_id = {r['id']: r for r in rows}
    if any(i.menu_item_id not in by_id for i in payload.items): raise HTTPException(400, 'Invalid menu item')
    subtotal = sum(float(by_id[i.menu_item_id]['price']) * i.quantity for i in payload.items)
    settings = c.execute('SELECT * FROM settings WHERE id=1').fetchone()
    tax = subtotal * float(settings['tax_percent'] or 0) / 100
    delivery = float(payload.delivery_fee or 0)
    if delivery == 0 and payload.order_type == 'Delivery': delivery = float(settings['delivery_fee'] or 0)
    total = subtotal + tax + delivery
    next_num = c.execute('SELECT COALESCE(MAX(order_number),1000)+1 AS n FROM orders').fetchone()['n']
    created = datetime.now().isoformat(timespec='seconds')
    oid = c.execute(
        'INSERT INTO orders(order_number,customer_name,phone,address,order_type,subtotal,delivery_fee,tax,total,special_instructions,payment_method,payment_status,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
        (next_num, payload.customer_name, payload.phone, payload.address, payload.order_type, subtotal, delivery, tax, total, payload.special_instructions, payload.payment_method, payload.payment_status, 'New', created)
    ).fetchone()['id']
    for i in payload.items:
        mi = by_id[i.menu_item_id]
        c.execute('INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_price) VALUES (%s,%s,%s,%s,%s)', (oid, mi['id'], mi['name'], i.quantity, mi['price']))
    c.commit()
    r = c.execute('SELECT * FROM orders WHERE id=%s', (oid,)).fetchone()
    # Return the newly-created order using the same DB connection. The old
    # implementation called serialize_order(), which opened a second
    # connection just to fetch order_items and added noticeable latency.
    d = dict(r)
    # Build the item list from the already-loaded menu rows.
    d['items'] = [
        {
            'menu_item_id': item.menu_item_id,
            'item_name': by_id[item.menu_item_id]['name'],
            'quantity': item.quantity,
            'unit_price': by_id[item.menu_item_id]['price'],
        }
        for item in payload.items
    ]
    c.close()
    return d


@app.put('/api/orders/{order_id}')
def update_order(order_id: int, payload: dict):
    c = conn()
    try:
        current = c.execute('SELECT * FROM orders WHERE id=%s', (order_id,)).fetchone()
        if not current:
            raise HTTPException(404, 'Order not found')

        allowed_fields = {'customer_name','phone','address','order_type','payment_status','special_instructions','status','payment_method'}
        changes = {k: v for k, v in payload.items() if k in allowed_fields and v is not None}
        if 'status' in changes and changes['status'] not in STATUSES:
            raise HTTPException(400, 'Invalid status')
        if 'payment_method' in changes:
            changes['payment_method'] = 'UPI' if str(changes['payment_method']).strip().upper() == 'UPI' else 'Cash'
            changes['payment_status'] = 'Paid'

        items_payload = payload.get('items', None)
        subtotal = float(current['subtotal'] or 0)
        delivery = float(current['delivery_fee'] or 0)
        tax = float(current['tax'] or 0)
        total = float(current['total'] or 0)

        if items_payload is not None:
            if not items_payload:
                raise HTTPException(400, 'Keep at least one item in the order')
            item_ids = [int(i['menu_item_id']) for i in items_payload]
            placeholders = ','.join('%s' for _ in item_ids)
            menu_rows = c.execute(f'SELECT * FROM menu_items WHERE id IN ({placeholders})', tuple(item_ids)).fetchall()
            by_id = {r['id']: r for r in menu_rows}
            if any(int(i['menu_item_id']) not in by_id for i in items_payload):
                raise HTTPException(400, 'One or more menu items are invalid')
            if any(int(i.get('quantity',0)) < 1 for i in items_payload):
                raise HTTPException(400, 'Item quantities must be at least 1')
            subtotal = sum(float(by_id[int(i['menu_item_id'])]['price']) * int(i['quantity']) for i in items_payload)
            settings = c.execute('SELECT * FROM settings WHERE id=1').fetchone()
            tax = subtotal * float(settings['tax_percent'] or 0) / 100
            delivery = float(payload.get('delivery_fee', current['delivery_fee']) or 0)
            if delivery == 0 and payload.get('order_type', current['order_type']) == 'Delivery':
                delivery = float(settings['delivery_fee'] or 0)
            total = subtotal + delivery + tax
            c.execute('DELETE FROM order_items WHERE order_id=%s', (order_id,))
            for item in items_payload:
                mi = by_id[int(item['menu_item_id'])]
                c.execute('INSERT INTO order_items(order_id,menu_item_id,item_name,quantity,unit_price) VALUES (%s,%s,%s,%s,%s)', (order_id, mi['id'], mi['name'], int(item['quantity']), mi['price']))

        if items_payload is not None:
            changes.update({'subtotal':subtotal,'delivery_fee':delivery,'tax':tax,'total':total})
        if not changes and items_payload is None:
            raise HTTPException(400, 'No supported changes')

        if changes:
            set_clause = ', '.join(f'{k}=%s' for k in changes)
            c.execute(f'UPDATE orders SET {set_clause} WHERE id=%s', (*changes.values(), order_id))
        c.commit()
        row = c.execute('SELECT * FROM orders WHERE id=%s', (order_id,)).fetchone()
        d = dict(row)
        d['items'] = [dict(r) for r in c.execute('SELECT menu_item_id,item_name,quantity,unit_price FROM order_items WHERE order_id=%s ORDER BY id', (order_id,)).fetchall()]
        return d
    finally:
        c.close()


@app.delete('/api/orders/{order_id}')
def delete_order(order_id: int):
    c = conn()
    try:
        if not c.execute('SELECT 1 FROM orders WHERE id=%s', (order_id,)).fetchone():
            raise HTTPException(404, 'Order not found')
        c.execute('DELETE FROM order_items WHERE order_id=%s', (order_id,))
        c.execute('DELETE FROM orders WHERE id=%s', (order_id,))
        c.commit()
        return {'ok': True}
    finally:
        c.close()


class ClearOrdersIn(BaseModel):
    confirm: str = ''


@app.post('/api/orders/clear')
def clear_orders(payload: ClearOrdersIn):
    # Start again from zero orders. Menu, categories, inventory and settings are kept.
    if payload.confirm != 'RESET':
        raise HTTPException(400, 'Type RESET to confirm')
    c = conn()
    try:
        n = c.execute('SELECT COUNT(*) AS n FROM orders').fetchone()['n']
        c.execute('DELETE FROM order_items')
        c.execute('DELETE FROM orders')
        c.commit()
        return {'ok': True, 'deleted': n}
    finally:
        c.close()


@app.get('/api/reports')
def reports(month: Optional[str] = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    month = month or datetime.now().strftime('%Y-%m')
    start = datetime.strptime(month + '-01', '%Y-%m-%d')
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    c = conn()
    orders = c.execute('SELECT * FROM orders WHERE created_at >= %s AND created_at < %s', (start, end)).fetchall()
    completed = [o for o in orders if o['status'] == 'Completed']
    revenue = sum(float(o['total'] or 0) for o in completed)
    total_orders = len(orders)
    avg = (revenue / len(completed)) if completed else 0
    counts = {}
    for r in c.execute("SELECT item_name, SUM(quantity) qty FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE o.created_at >= %s AND o.created_at < %s AND o.status != 'Cancelled' GROUP BY item_name ORDER BY qty DESC", (start, end)).fetchall():
        counts[r['item_name']] = r['qty']
    c.close()
    return {'month': month, 'revenue': round(revenue, 2), 'orders': total_orders, 'average_order': round(avg, 2), 'most_ordered': list(counts.items())[:5], 'completed': len(completed), 'cancelled': len([o for o in orders if o['status'] == 'Cancelled'])}


@app.get('/api/inventory')
def get_inventory(month: Optional[str] = Query(default=None, pattern=r'^\d{4}-\d{2}$'), q: Optional[str] = None):
    month = month or datetime.now().strftime('%Y-%m')
    c = conn()
    sql = "SELECT * FROM inventory_purchases WHERE purchase_date::text LIKE %s"
    args = [month + '%']
    if q:
        sql += ' AND (item_name ILIKE %s OR category ILIKE %s)'; like = f'%{q}%'; args.extend([like, like])
    sql += ' ORDER BY purchase_date DESC, id DESC'
    rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    total = sum(r['total_cost'] for r in rows)
    by_item = [dict(r) for r in c.execute(
        "SELECT item_name, category, unit, ROUND(SUM(quantity),2) quantity, ROUND(SUM(total_cost),2) total_cost FROM inventory_purchases WHERE purchase_date::text LIKE %s GROUP BY item_name, category, unit ORDER BY total_cost DESC",
        (month + '%',)
    ).fetchall()]
    c.close()
    return {'month': month, 'total_spend': round(total, 2), 'purchases': rows, 'by_item': by_item}


@app.get('/api/inventory/items')
def inventory_items():
    """Every item ever bought (all months), for the one-tap stock buttons and the all-time spending ranking."""
    c = conn()
    try:
        rows = c.execute('SELECT id, item_name, category, unit, quantity, total_cost, purchase_date::text AS purchase_date FROM inventory_purchases ORDER BY purchase_date DESC, id DESC').fetchall()
    finally:
        c.close()
    items = {}
    for r in rows:
        name = (r['item_name'] or '').strip()
        cat = (r['category'] or 'Other').strip() or 'Other'
        key = (name.lower(), cat.lower())
        it = items.get(key)
        if it is None:   # rows are newest first, so the first one seen is the latest purchase
            it = items[key] = {'item_name': name, 'category': cat, 'last_date': r['purchase_date'], 'last_total': float(r['total_cost']), 'last_unit': r['unit'], 'times_bought': 0, 'all_time_total': 0.0}
        it['times_bought'] += 1
        it['all_time_total'] = round(it['all_time_total'] + float(r['total_cost']), 2)
    return sorted(items.values(), key=lambda x: (x['category'].lower(), x['item_name'].lower()))


@app.post('/api/inventory')
def add_inventory(payload: InventoryPurchaseIn):
    date = payload.purchase_date or datetime.now().date().isoformat()
    unit_price, total = purchase_numbers(payload)
    c = conn()
    try:
        r = c.execute(
            'INSERT INTO inventory_purchases(item_name,category,quantity,unit,unit_price,total_cost,purchase_date,notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *',
            (payload.item_name.strip(), payload.category.strip() or 'Raw Material', payload.quantity, payload.unit.strip() or 'kg', unit_price, total, date, payload.notes.strip())
        ).fetchone()
        c.commit()
        return dict(r)
    finally:
        c.close()


@app.put('/api/inventory/{purchase_id}')
def update_inventory(purchase_id: int, payload: InventoryPurchaseIn):
    date = payload.purchase_date or datetime.now().date().isoformat()
    unit_price, total = purchase_numbers(payload)
    c = conn()
    try:
        if not c.execute('SELECT 1 FROM inventory_purchases WHERE id=%s', (purchase_id,)).fetchone():
            raise HTTPException(404, 'Inventory purchase not found')
        r = c.execute(
            'UPDATE inventory_purchases SET item_name=%s,category=%s,quantity=%s,unit=%s,unit_price=%s,total_cost=%s,purchase_date=%s,notes=%s WHERE id=%s RETURNING *',
            (payload.item_name.strip(), payload.category.strip() or 'Raw Material', payload.quantity, payload.unit.strip() or 'kg', unit_price, total, date, payload.notes.strip(), purchase_id)
        ).fetchone()
        c.commit()
        return dict(r)
    finally:
        c.close()


@app.delete('/api/inventory/{purchase_id}')
def delete_inventory(purchase_id: int):
    c = conn(); c.execute('DELETE FROM inventory_purchases WHERE id=%s', (purchase_id,)); c.commit(); c.close(); return {'ok': True}


@app.post('/api/demo/reset')
def reset_demo():
    if not env_flag('SEED_DEMO_DATA', False):
        raise HTTPException(403, 'Demo reset is disabled in production mode.')
    c = conn(); c.execute('DELETE FROM order_items'); c.execute('DELETE FROM orders'); c.execute('DELETE FROM inventory_purchases'); c.commit(); seed_orders(c); seed_inventory(c); c.commit(); c.close(); return {'ok': True}


@app.get('/api/print/{order_id}')
def print_order(order_id: int):
    c = conn(); r = c.execute('SELECT * FROM orders WHERE id=%s', (order_id,)).fetchone(); c.close()
    if not r: raise HTTPException(404, 'Order not found')
    return serialize_order(r)


@app.post('/api/printers/print-batch')
def hardware_print_batch(payload: HardwarePrintBatchIn, request: Request):
    if not payload.order_ids:
        raise HTTPException(400, 'No orders selected')
    c = conn()
    try:
        settings_row = c.execute('SELECT * FROM settings WHERE id=1').fetchone()
        owner = current_user(request).get('role') == 'owner'   # only the owner may name a printer / port; everyone else uses the saved settings
        mode = (payload.mode if owner else '') or settings_row['printer_mode'] or 'browser'
        target = (payload.target if owner else '') or settings_row['printer_target'] or ''
        rows = c.execute('SELECT * FROM orders WHERE id = ANY(%s)', (payload.order_ids,)).fetchall()
        by_id = {r['id']: r for r in rows}
        missing = [oid for oid in payload.order_ids if oid not in by_id]
        if missing:
            raise HTTPException(404, f'Order not found: {missing[0]}')
        item_rows = c.execute(
            'SELECT order_id,menu_item_id,item_name,quantity,unit_price FROM order_items WHERE order_id = ANY(%s) ORDER BY order_id,id',
            (payload.order_ids,)
        ).fetchall()
        grouped = {}
        for item in item_rows:
            grouped.setdefault(item['order_id'], []).append(dict(item))
        orders = []
        for oid in payload.order_ids:
            d = dict(by_id[oid])
            d['items'] = grouped.get(oid, [])
            orders.append(d)
        settings = dict(settings_row)
    finally:
        c.close()

    if mode == 'browser':
        return {'ok': True, 'mode': 'browser', 'message': 'Use browser print preview.', 'order_ids': payload.order_ids}

    try:
        if mode == 'windows' and target:
            for order in orders:
                send_windows_raw(target, escpos_bytes(print_ticket_text(order, settings)))
        elif mode == 'serial' and target:
            for order in orders:
                send_serial(target, escpos_bytes(print_ticket_text(order, settings)), int(settings.get('printer_baudrate') or 9600))
        else:
            raise ValueError('Printer mode or target is not configured')
    except Exception as e:
        raise HTTPException(400, f'Could not print the order batch to {target or "selected printer"}: {e}')
    return {'ok': True, 'mode': mode, 'target': target, 'count': len(orders), 'message': 'Order batch sent successfully.'}


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
        job = win32print.StartDocPrinter(handle, 1, (printer_name, None, 'RAW'))
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
    data = escpos_bytes(business_name(settings) + '\n' + 'THERMAL PRINTER TEST\n' + '-'*32 + '\n58mm PAPER\nPrinter connection OK\n\n')
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
def hardware_print(payload: HardwarePrintIn, request: Request):
    c = conn(); order_row = c.execute('SELECT * FROM orders WHERE id=%s', (payload.order_id,)).fetchone(); settings_row = c.execute('SELECT * FROM settings WHERE id=1').fetchone(); c.close()
    if not order_row: raise HTTPException(404, 'Order not found')
    order = serialize_order(order_row)
    settings = dict(settings_row)
    owner = current_user(request).get('role') == 'owner'
    mode = (payload.mode if owner else '') or settings.get('printer_mode') or 'browser'
    target = (payload.target if owner else '') or settings.get('printer_target') or ''
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
