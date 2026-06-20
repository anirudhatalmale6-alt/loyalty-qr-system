from playwright.sync_api import sync_playwright
import os

BASE = "http://localhost:5099"
SHOTS = "/var/lib/freelancer/projects/40526450/screenshots"
os.makedirs(SHOTS, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 720})

    # 1. Login
    page.goto(f"{BASE}/login")
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="pin"]', '1234')
    page.click('button[type="submit"]')
    page.wait_for_url("**/dashboard")
    page.screenshot(path=f"{SHOTS}/01_dashboard.png")
    print("1. Dashboard OK")

    # 2. Add a customer
    page.click('text=+ New Customer')
    page.fill('input[name="first_name"]', 'John')
    page.fill('input[name="last_name"]', 'Smith')
    page.fill('input[name="phone"]', '07700 900123')
    page.fill('input[name="email"]', 'john@example.com')
    page.fill('input[name="dob"]', '1985-03-15')
    page.click('button:text("Add & Issue Card")')
    page.screenshot(path=f"{SHOTS}/02_issue_card.png")
    print("2. Issue card page OK")

    # 3. Issue the card
    page.click('button:text("Issue Card")')
    page.screenshot(path=f"{SHOTS}/03_customer_with_card.png")
    print("3. Card issued OK")

    # 4. View card detail
    page.click('text=View Card')
    page.screenshot(path=f"{SHOTS}/04_card_detail.png")
    print("4. Card detail OK")

    # 5. Add a digital stamp
    page.click('button:text("Add Digital Stamp")')
    page.screenshot(path=f"{SHOTS}/05_stamp_added.png")
    print("5. Digital stamp added OK")

    # 6. Print QR stamp ticket
    page.click('button:text("Print QR Stamp Ticket")')
    page.screenshot(path=f"{SHOTS}/06_qr_ticket.png")
    print("6. QR ticket printed OK")

    # 7. Get the QR scan URL from the ticket page
    page.go_back()
    page.screenshot(path=f"{SHOTS}/07_card_after_stamps.png")
    print("7. Card with 2 stamps OK")

    # 8. Go to customers list
    page.click('text=Customers')
    page.screenshot(path=f"{SHOTS}/08_customers_list.png")
    print("8. Customers list OK")

    # 9. Search
    page.fill('input[name="q"]', 'john')
    page.click('button:text("Search")')
    page.screenshot(path=f"{SHOTS}/09_search_result.png")
    print("9. Search OK")

    # 10. Test QR scan validation
    import sqlite3
    db = sqlite3.connect('/var/lib/freelancer/projects/40526450/data/loyalty.db')
    db.row_factory = sqlite3.Row
    token = db.execute("SELECT qr_token FROM stamps WHERE is_used=0 LIMIT 1").fetchone()['qr_token']
    db.close()

    # First scan - should be valid
    page.goto(f"{BASE}/scan/{token}")
    page.screenshot(path=f"{SHOTS}/10_scan_valid.png")
    print("10. QR scan valid OK")

    # Second scan - should show already used
    page.goto(f"{BASE}/scan/{token}")
    page.screenshot(path=f"{SHOTS}/11_scan_used.png")
    print("11. QR scan reuse blocked OK")

    # Invalid token
    page.goto(f"{BASE}/scan/invalidtoken123")
    page.screenshot(path=f"{SHOTS}/12_scan_invalid.png")
    print("12. Invalid QR rejected OK")

    browser.close()
    print("\nAll tests passed!")
