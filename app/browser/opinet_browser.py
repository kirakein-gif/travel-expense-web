from pathlib import Path
from playwright.async_api import async_playwright
async def capture_opinet_evidence(target_url: str, output_path: str, *, wait_ms: int = 1500) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = await browser.new_page(viewport={"width": 1440, "height": 1600})
        await page.goto(target_url, wait_until="networkidle", timeout=60_000)
        await page.wait_for_timeout(wait_ms)
        await page.screenshot(path=output_path, full_page=True)
        await browser.close()
    return output_path
