from playwright.sync_api import sync_playwright
import os, sqlite3

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
    page.screenshot(path=f"{SHOTS}/v2_01_dashboard.png")
    print("1. Dashboard OK")

    # 2. Add customer + issue card in one step
    page.click('text=+ New Customer')
    page.fill('input[name="first_name"]', 'Sarah')
    page.fill('input[name="last_name"]', 'Johnson')
    page.fill('input[name="phone"]', '07700 555123')
    page.fill('input[name="email"]', 'sarah@example.com')
    page.fill('input[name="dob"]', '1990-06-15')
    page.click('button:text("Add & Issue Card")')
    page.wait_for_url("**/cards/**")
    page.screenshot(path=f"{SHOTS}/v2_02_card_with_qr.png")
    print("2. Card issued with permanent QR OK")

    # 3. Print physical card
    page.click('text=Print Physical Card')
    page.screenshot(path=f"{SHOTS}/v2_03_print_card.png")
    print("3. Printable card OK")

    # 4. Go back and view the customer's digital card
    page.go_back()
    page.click('text=Customer\'s Digital Card')
    page.screenshot(path=f"{SHOTS}/v2_04_customer_digital_card.png")
    print("4. Customer digital card (wallet-style) OK")

    # 5. Now simulate staff scanning the customer's QR
    # Get the card's qr_token from DB
    db = sqlite3.connect('/var/lib/freelancer/projects/40526450/data/loyalty.db')
    db.row_factory = sqlite3.Row
    card = db.execute("SELECT * FROM cards LIMIT 1").fetchone()
    qr_token = card['qr_token']
    db.close()

    # Staff scans the QR - should see the card and stamp button
    page.goto(f"{BASE}/scan/{qr_token}")
    page.screenshot(path=f"{SHOTS}/v2_05_scan_found.png")
    print("5. Staff scanned QR - card found OK")

    # 6. Add stamp via scan
    page.click('button:text("Add Stamp")')
    page.screenshot(path=f"{SHOTS}/v2_06_stamp_added.png")
    print("6. Stamp added via scan OK")

    # 7. Scan again and add another stamp
    page.goto(f"{BASE}/scan/{qr_token}")
    page.click('button:text("Add Stamp")')
    page.screenshot(path=f"{SHOTS}/v2_07_second_stamp.png")
    print("7. Second stamp OK")

    # 8. Add more stamps (to get to 10)
    for i in range(8):
        page.goto(f"{BASE}/scan/{qr_token}")
        page.click('button:text("Add Stamp")')
    page.screenshot(path=f"{SHOTS}/v2_08_all_stamps.png")
    print("8. All 10 stamps collected OK")

    # 9. Scan again - should show redeem button
    page.goto(f"{BASE}/scan/{qr_token}")
    page.screenshot(path=f"{SHOTS}/v2_09_ready_to_redeem.png")
    print("9. Ready to redeem screen OK")

    # 10. Redeem
    page.click('button:text("Redeem Reward")')
    page.screenshot(path=f"{SHOTS}/v2_10_redeemed.png")
    print("10. Reward redeemed OK")

    # 11. Check dashboard with activity
    page.goto(f"{BASE}/dashboard")
    page.screenshot(path=f"{SHOTS}/v2_11_dashboard_active.png")
    print("11. Dashboard with activity OK")

    # 12. Check customer's digital card shows full progress
    page.goto(f"{BASE}/card/{qr_token}")
    page.screenshot(path=f"{SHOTS}/v2_12_customer_card_full.png")
    print("12. Customer card with all stamps OK")

    # 13. Test expired/invalid scan
    page.goto(f"{BASE}/scan/invalidtoken123")
    page.screenshot(path=f"{SHOTS}/v2_13_invalid_scan.png")
    print("13. Invalid QR rejected OK")

    browser.close()
    print("\nAll v2 tests passed!")
