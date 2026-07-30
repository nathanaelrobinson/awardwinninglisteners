"""Drive the live-draft UI headlessly and capture console/network errors + screenshots.
Run: uv run python scripts/ui_probe.py  (server must be on :8000)
"""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("/private/tmp/claude-501/-Users-naterobinson-Projects-vizit/10863af2-3270-48e1-911c-216e0200b071/scratchpad")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:8000"

msgs, errors, failed = [], [], []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.on("console", lambda m: msgs.append(f"{m.type}: {m.text}"))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: failed.append(f"{r.method} {r.url} :: {r.failure}"))

    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(OUT / "ui-01-initial.png"), full_page=True)

    # pick slot 3
    try:
        page.get_by_role("button", name="3", exact=True).first.click()
        page.wait_for_timeout(800)
    except Exception as e:
        errors.append(f"slot click failed: {e}")

    # draft 8 teams (whoever is on the clock)
    for i in range(8):
        cards = page.locator("button.team-card:not(.taken):not([disabled])")
        if cards.count() == 0:
            page.wait_for_timeout(500)
            cards = page.locator("button.team-card:not(.taken):not([disabled])")
        if cards.count() == 0:
            errors.append(f"no draftable card at pick {i}")
            break
        cards.first.click()
        page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / "ui-02-after-8-picks.png"), full_page=True)

    # toggle rollout
    try:
        page.get_by_role("checkbox").first.check()
        page.wait_for_timeout(4000)
        page.screenshot(path=str(OUT / "ui-03-rollout.png"), full_page=True)
    except Exception as e:
        errors.append(f"rollout toggle failed: {e}")

    browser.close()

print("=== CONSOLE ===")
for m in msgs:
    print(m)
print("=== PAGE ERRORS ===")
for e in errors:
    print(e)
print("=== FAILED REQUESTS ===")
for f in failed:
    print(f)
print("=== screenshots written to", OUT, "===")
