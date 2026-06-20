# Loyalty Card System - Expiry Logic & Dynamic QR Codes

A lightweight web app that adds **automatic card expiry** and **single-use QR stamp tickets** to your loyalty programme.

## Features

- **Auto Expiry**: Every card expires exactly 10 weeks after issue — no manual input needed
- **Dynamic QR Codes**: Each physical stamp gets a unique, single-use QR code
- **Printable Tickets**: Staff hits "Print QR Stamp Ticket" and hands the customer a ticket
- **Scan Verification**: Scanning a QR shows valid/used/expired/invalid status
- **Customer Management**: Search by name, phone, or email
- **Staff Accounts**: Admin can add staff with PIN login
- **Dashboard**: Overview of customers, cards, stamps, and activity

## Quick Start

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5099 in your browser.

**Default login**: admin / 1234

## How It Works

1. **Add a customer** (name, phone, email, DOB)
2. **Issue a card** — expiry date is calculated automatically (10 weeks)
3. **Add stamps** — either digital (one click) or print a QR ticket for paper cards
4. Each QR code can only be scanned **once** — reuse is blocked
5. When all 10 stamps are collected, staff can **redeem the reward**

## Tech Stack

- Python / Flask
- SQLite database
- QR code generation (qrcode + Pillow)
- Responsive HTML/CSS (works on phone, tablet, desktop)
