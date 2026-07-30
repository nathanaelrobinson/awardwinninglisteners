"""Drive draft + auto-sim tabs headlessly; capture console errors + screenshots.
Run: uv run python scripts/ui_probe2.py  (server on :8000)
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("/private/tmp/claude-501/-Users-naterobinson-Projects-vizit/"
           "10863af2-3270-48e1-911c-216e0200b071/scratchpad")
URL = "http://127.0.0.1:8000"
errors, failed = [], []

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1400, "height": 950})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("requestfailed", lambda r: failed.append(f"{r.method} {r.url} :: {r.failure}"))
    pg.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
          if m.type in ("error", "warning") else None)

    pg.goto(URL, wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.get_by_role("button", name="3", exact=True).first.click()
    pg.wait_for_timeout(800)
    pg.screenshot(path=str(OUT / "v2-01-draft-initial.png"), full_page=True)

    # draft 12 teams so pick 13 (slot 3) is on the clock
    for _ in range(12):
        cards = pg.locator("button.team-card:not(.taken)")
        if cards.count() == 0:
            break
        cards.first.click()
        pg.wait_for_timeout(500)
    pg.wait_for_timeout(1200)
    pg.screenshot(path=str(OUT / "v2-02-draft-onclock.png"), full_page=True)

    # auto-sim tab
    try:
        pg.get_by_role("button", name="Auto-sim").click()
        pg.wait_for_timeout(500)
        pg.get_by_role("button", name="Run").click()
        pg.wait_for_timeout(4000)
        pg.screenshot(path=str(OUT / "v2-03-autosim.png"), full_page=True)
    except Exception as e:
        errors.append(f"autosim flow failed: {e}")

    b.close()

print("=== PAGE ERRORS / CONSOLE ===")
for e in errors:
    print(e)
print("=== FAILED REQUESTS ===")
for f in failed:
    print(f)
print("screenshots ->", OUT)
