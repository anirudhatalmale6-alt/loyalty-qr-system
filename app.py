import os
import sqlite3
import uuid
import io
import base64
from datetime import datetime, timedelta
from functools import wraps

import qrcode
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session, g, send_file, make_response
)

app = Flask(__name__)
app.secret_key = os.urandom(32)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'loyalty.db')
EXPIRY_WEEKS = 10
STAMPS_FOR_REWARD = 10

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            dob TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            card_number TEXT UNIQUE NOT NULL,
            qr_token TEXT UNIQUE NOT NULL,
            issued_at TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL,
            stamps_collected INTEGER NOT NULL DEFAULT 0,
            stamps_required INTEGER NOT NULL DEFAULT 10,
            reward_redeemed INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE TABLE IF NOT EXISTS stamps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id INTEGER NOT NULL,
            stamped_by TEXT,
            stamped_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (card_id) REFERENCES cards(id)
        );

        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            pin TEXT NOT NULL,
            name TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
        CREATE INDEX IF NOT EXISTS idx_customers_email ON customers(email);
        CREATE INDEX IF NOT EXISTS idx_cards_customer ON cards(customer_id);
        CREATE INDEX IF NOT EXISTS idx_cards_number ON cards(card_number);
        CREATE INDEX IF NOT EXISTS idx_cards_qr ON cards(qr_token);
        CREATE INDEX IF NOT EXISTS idx_stamps_card ON stamps(card_id);
    """)
    existing = db.execute("SELECT id FROM staff WHERE is_admin=1").fetchone()
    if not existing:
        db.execute(
            "INSERT INTO staff (username, pin, name, is_admin) VALUES (?, ?, ?, 1)",
            ('admin', '1234', 'Admin')
        )
    db.commit()
    db.close()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'staff_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def generate_card_number():
    return 'LC-' + uuid.uuid4().hex[:8].upper()


def generate_qr_token():
    return uuid.uuid4().hex


def make_qr_base64(data, size=6):
    qr = qrcode.QRCode(version=1, box_size=size, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('utf-8')


def card_status(card):
    now = datetime.utcnow()
    expires = datetime.fromisoformat(card['expires_at'])
    if not card['is_active']:
        return 'inactive', 'Deactivated'
    if now > expires:
        return 'expired', 'Expired'
    if card['reward_redeemed']:
        return 'redeemed', 'Reward Redeemed'
    if card['stamps_collected'] >= card['stamps_required']:
        return 'complete', 'Ready for Reward'
    days_left = (expires - now).days
    return 'active', f'Active ({days_left} days left)'


# --- Routes ---

@app.route('/')
def index():
    if 'staff_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        pin = request.form.get('pin', '').strip()
        db = get_db()
        staff = db.execute(
            "SELECT * FROM staff WHERE username=? AND pin=?",
            (username, pin)
        ).fetchone()
        if staff:
            session['staff_id'] = staff['id']
            session['staff_name'] = staff['name']
            session['is_admin'] = bool(staff['is_admin'])
            next_url = request.args.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        flash('Invalid username or PIN', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    total_customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
    active_cards = db.execute("SELECT COUNT(*) FROM cards WHERE is_active=1").fetchone()[0]
    now = datetime.utcnow().isoformat()
    expired_cards = db.execute(
        "SELECT COUNT(*) FROM cards WHERE is_active=1 AND expires_at < ?", (now,)
    ).fetchone()[0]
    stamps_today = db.execute(
        "SELECT COUNT(*) FROM stamps WHERE date(stamped_at)=date('now')"
    ).fetchone()[0]
    recent_stamps = db.execute("""
        SELECT s.stamped_at, c.first_name || ' ' || c.last_name as customer_name,
               cd.card_number, s.stamped_by
        FROM stamps s
        JOIN cards cd ON s.card_id = cd.id
        JOIN customers c ON cd.customer_id = c.id
        ORDER BY s.stamped_at DESC LIMIT 10
    """).fetchall()
    return render_template('dashboard.html',
                           total_customers=total_customers,
                           active_cards=active_cards,
                           expired_cards=expired_cards,
                           stamps_today=stamps_today,
                           recent_stamps=recent_stamps)


# --- Customer routes ---

@app.route('/customers')
@login_required
def customers():
    db = get_db()
    search = request.args.get('q', '').strip()
    if search:
        like = f'%{search}%'
        rows = db.execute("""
            SELECT * FROM customers
            WHERE first_name LIKE ? OR last_name LIKE ? OR phone LIKE ? OR email LIKE ?
            ORDER BY last_name, first_name
        """, (like, like, like, like)).fetchall()
    else:
        rows = db.execute("SELECT * FROM customers ORDER BY last_name, first_name").fetchall()
    return render_template('customers.html', customers=rows, search=search)


@app.route('/customers/new', methods=['GET', 'POST'])
@login_required
def new_customer():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        dob = request.form.get('dob', '').strip()

        if not first_name or not last_name:
            flash('First and last name are required', 'error')
            return render_template('customer_form.html', editing=False)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO customers (first_name, last_name, phone, email, dob) VALUES (?, ?, ?, ?, ?)",
            (first_name, last_name, phone or None, email or None, dob or None)
        )
        db.commit()
        customer_id = cursor.lastrowid

        if request.form.get('issue_card'):
            now = datetime.utcnow()
            expires = now + timedelta(weeks=EXPIRY_WEEKS)
            card_num = generate_card_number()
            qr_token = generate_qr_token()
            db.execute(
                "INSERT INTO cards (customer_id, card_number, qr_token, issued_at, expires_at, stamps_required) VALUES (?, ?, ?, ?, ?, ?)",
                (customer_id, card_num, qr_token, now.isoformat(), expires.isoformat(), STAMPS_FOR_REWARD)
            )
            db.commit()
            card = db.execute("SELECT * FROM cards WHERE card_number=?", (card_num,)).fetchone()
            flash(f'Customer added and card {card_num} issued!', 'success')
            return redirect(url_for('view_card', card_id=card['id']))

        flash('Customer added successfully', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    return render_template('customer_form.html', editing=False)


@app.route('/customers/<int:customer_id>')
@login_required
def view_customer(customer_id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        flash('Customer not found', 'error')
        return redirect(url_for('customers'))
    cards = db.execute(
        "SELECT * FROM cards WHERE customer_id=? ORDER BY issued_at DESC",
        (customer_id,)
    ).fetchall()
    cards_with_status = []
    for c in cards:
        status_class, status_text = card_status(c)
        cards_with_status.append({**dict(c), 'status_class': status_class, 'status_text': status_text})
    return render_template('customer_detail.html', customer=customer, cards=cards_with_status)


@app.route('/customers/<int:customer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_customer(customer_id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        flash('Customer not found', 'error')
        return redirect(url_for('customers'))
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        dob = request.form.get('dob', '').strip()
        if not first_name or not last_name:
            flash('First and last name are required', 'error')
            return render_template('customer_form.html', editing=True, customer=customer)
        db.execute(
            "UPDATE customers SET first_name=?, last_name=?, phone=?, email=?, dob=? WHERE id=?",
            (first_name, last_name, phone or None, email or None, dob or None, customer_id)
        )
        db.commit()
        flash('Customer updated', 'success')
        return redirect(url_for('view_customer', customer_id=customer_id))
    return render_template('customer_form.html', editing=True, customer=customer)


# --- Card routes ---

@app.route('/customers/<int:customer_id>/issue-card', methods=['GET', 'POST'])
@login_required
def issue_card(customer_id):
    db = get_db()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        flash('Customer not found', 'error')
        return redirect(url_for('customers'))
    if request.method == 'POST':
        now = datetime.utcnow()
        expires = now + timedelta(weeks=EXPIRY_WEEKS)
        card_num = generate_card_number()
        qr_token = generate_qr_token()
        db.execute(
            "INSERT INTO cards (customer_id, card_number, qr_token, issued_at, expires_at, stamps_required) VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, card_num, qr_token, now.isoformat(), expires.isoformat(), STAMPS_FOR_REWARD)
        )
        db.commit()
        card = db.execute("SELECT * FROM cards WHERE card_number=?", (card_num,)).fetchone()
        flash(f'Card {card_num} issued -- expires {expires.strftime("%d %b %Y")}', 'success')
        return redirect(url_for('view_card', card_id=card['id']))
    expiry_date = (datetime.utcnow() + timedelta(weeks=EXPIRY_WEEKS)).strftime('%d %b %Y')
    return render_template('issue_card.html', customer=customer, expiry_date=expiry_date)


@app.route('/cards/<int:card_id>')
@login_required
def view_card(card_id):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))
    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()
    stamps = db.execute(
        "SELECT * FROM stamps WHERE card_id=? ORDER BY stamped_at DESC", (card_id,)
    ).fetchall()
    status_class, status_text = card_status(card)
    card_url = request.host_url.rstrip('/') + url_for('customer_card', token=card['qr_token'])
    qr_b64 = make_qr_base64(card_url, size=8)
    return render_template('card_detail.html', card=card, customer=customer,
                           stamps=stamps, status_class=status_class, status_text=status_text,
                           qr_b64=qr_b64, card_url=card_url)


@app.route('/cards/<int:card_id>/print')
@login_required
def print_card(card_id):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))
    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()
    status_class, status_text = card_status(card)
    card_url = request.host_url.rstrip('/') + url_for('customer_card', token=card['qr_token'])
    qr_b64 = make_qr_base64(card_url, size=10)
    expires_at = datetime.fromisoformat(card['expires_at']).strftime('%d %b %Y')
    return render_template('print_card.html', card=card, customer=customer,
                           qr_b64=qr_b64, expires_at=expires_at)


# --- Scan / Stamp routes (staff scans customer's QR to add stamp) ---

@app.route('/scan/<token>')
def scan_card(token):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE qr_token=?", (token,)).fetchone()
    if not card:
        return render_template('scan_result.html', status='invalid',
                               message='This QR code is not recognised.')
    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()
    status_class, status_text = card_status(card)

    if status_class == 'expired':
        return render_template('scan_result.html', status='expired',
                               message='This card has expired.',
                               customer=customer, card=card, status_text=status_text)
    if status_class == 'inactive':
        return render_template('scan_result.html', status='expired',
                               message='This card has been deactivated.',
                               customer=customer, card=card, status_text=status_text)

    if 'staff_id' not in session:
        return redirect(url_for('login', next=url_for('scan_card', token=token)))

    return render_template('scan_result.html', status='found',
                           message='Card found! Add a stamp?',
                           customer=customer, card=card, status_text=status_text,
                           can_stamp=status_class == 'active',
                           can_redeem=status_class == 'complete')


@app.route('/scan/<token>/stamp', methods=['POST'])
@login_required
def stamp_card(token):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE qr_token=?", (token,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))

    status_class, _ = card_status(card)
    if status_class != 'active':
        flash('Cannot stamp this card', 'error')
        return redirect(url_for('scan_card', token=token))

    staff_name = session.get('staff_name', 'Unknown')
    db.execute(
        "INSERT INTO stamps (card_id, stamped_by, stamped_at) VALUES (?, ?, ?)",
        (card['id'], staff_name, datetime.utcnow().isoformat())
    )
    db.execute(
        "UPDATE cards SET stamps_collected = stamps_collected + 1 WHERE id=?",
        (card['id'],)
    )
    db.commit()

    updated_card = db.execute("SELECT * FROM cards WHERE id=?", (card['id'],)).fetchone()
    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()

    return render_template('scan_result.html', status='stamped',
                           message=f'Stamp added! ({updated_card["stamps_collected"]}/{updated_card["stamps_required"]})',
                           customer=customer, card=updated_card,
                           status_text=f'{updated_card["stamps_collected"]}/{updated_card["stamps_required"]} stamps')


@app.route('/scan/<token>/redeem', methods=['POST'])
@login_required
def redeem_from_scan(token):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE qr_token=?", (token,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))
    if card['stamps_collected'] < card['stamps_required']:
        flash('Not enough stamps', 'error')
        return redirect(url_for('scan_card', token=token))
    if card['reward_redeemed']:
        flash('Already redeemed', 'error')
        return redirect(url_for('scan_card', token=token))

    db.execute("UPDATE cards SET reward_redeemed=1 WHERE id=?", (card['id'],))
    db.commit()

    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()
    return render_template('scan_result.html', status='redeemed',
                           message='Reward redeemed!',
                           customer=customer, card=card,
                           status_text='Reward Redeemed')


# --- Customer-facing card page (what the QR links to for the customer) ---

@app.route('/card/<token>')
def customer_card(token):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE qr_token=?", (token,)).fetchone()
    if not card:
        return render_template('customer_card.html', found=False)
    customer = db.execute("SELECT * FROM customers WHERE id=?", (card['customer_id'],)).fetchone()
    status_class, status_text = card_status(card)
    expires_at = datetime.fromisoformat(card['expires_at']).strftime('%d %b %Y')
    scan_url = request.host_url.rstrip('/') + url_for('scan_card', token=token)
    qr_b64 = make_qr_base64(scan_url, size=8)
    return render_template('customer_card.html', found=True,
                           card=card, customer=customer,
                           status_class=status_class, status_text=status_text,
                           expires_at=expires_at, qr_b64=qr_b64,
                           scan_url=scan_url)


# --- Card management from staff view ---

@app.route('/cards/<int:card_id>/add-stamp', methods=['POST'])
@login_required
def add_stamp(card_id):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))

    status_class, _ = card_status(card)
    if status_class == 'expired':
        flash('Cannot add stamp -- card has expired', 'error')
        return redirect(url_for('view_card', card_id=card_id))
    if status_class == 'inactive':
        flash('Cannot add stamp -- card is deactivated', 'error')
        return redirect(url_for('view_card', card_id=card_id))
    if card['stamps_collected'] >= card['stamps_required']:
        flash('Card already has all stamps', 'error')
        return redirect(url_for('view_card', card_id=card_id))

    staff_name = session.get('staff_name', 'Unknown')
    db.execute(
        "INSERT INTO stamps (card_id, stamped_by, stamped_at) VALUES (?, ?, ?)",
        (card_id, staff_name, datetime.utcnow().isoformat())
    )
    db.execute(
        "UPDATE cards SET stamps_collected = stamps_collected + 1 WHERE id=?",
        (card_id,)
    )
    db.commit()
    flash('Stamp added!', 'success')
    return redirect(url_for('view_card', card_id=card_id))


@app.route('/cards/<int:card_id>/redeem', methods=['POST'])
@login_required
def redeem_reward(card_id):
    db = get_db()
    card = db.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()
    if not card:
        flash('Card not found', 'error')
        return redirect(url_for('dashboard'))
    if card['stamps_collected'] < card['stamps_required']:
        flash('Not enough stamps to redeem', 'error')
        return redirect(url_for('view_card', card_id=card_id))
    if card['reward_redeemed']:
        flash('Reward already redeemed', 'error')
        return redirect(url_for('view_card', card_id=card_id))
    db.execute("UPDATE cards SET reward_redeemed=1 WHERE id=?", (card_id,))
    db.commit()
    flash('Reward redeemed!', 'success')
    return redirect(url_for('view_card', card_id=card_id))


# --- Staff management ---

@app.route('/staff')
@login_required
def staff_list():
    if not session.get('is_admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    db = get_db()
    staff = db.execute("SELECT * FROM staff ORDER BY name").fetchall()
    return render_template('staff.html', staff=staff)


@app.route('/staff/new', methods=['GET', 'POST'])
@login_required
def new_staff():
    if not session.get('is_admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        pin = request.form.get('pin', '').strip()
        name = request.form.get('name', '').strip()
        is_admin = 1 if request.form.get('is_admin') else 0
        if not username or not pin or not name:
            flash('All fields required', 'error')
            return render_template('staff_form.html')
        db = get_db()
        try:
            db.execute(
                "INSERT INTO staff (username, pin, name, is_admin) VALUES (?, ?, ?, ?)",
                (username, pin, name, is_admin)
            )
            db.commit()
            flash(f'Staff member {name} added', 'success')
            return redirect(url_for('staff_list'))
        except sqlite3.IntegrityError:
            flash('Username already exists', 'error')
    return render_template('staff_form.html')


@app.route('/settings')
@login_required
def settings():
    if not session.get('is_admin'):
        flash('Admin access required', 'error')
        return redirect(url_for('dashboard'))
    return render_template('settings.html',
                           expiry_weeks=EXPIRY_WEEKS,
                           stamps_required=STAMPS_FOR_REWARD)


init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5099))
    app.run(debug=True, host='0.0.0.0', port=port)
