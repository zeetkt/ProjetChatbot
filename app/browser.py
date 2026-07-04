import logging
from typing import Optional

logger = logging.getLogger(__name__)

_browser = None
_playwright = None


async def render_page(url: str, timeout: int = 30000) -> Optional[str]:
    global _browser, _playwright
    try:
        if _browser is None:
            from playwright.async_api import async_playwright
            _playwright = await async_playwright().start()
            _browser = await _playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            logger.info("Playwright Chromium lance")

        context = await _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=timeout)
        html = await page.content()
        await page.close()
        await context.close()
        return html
    except Exception as e:
        logger.warning("Erreur rendu Playwright %s: %s", url, e, exc_info=True)
        return None


async def close():
    global _browser, _playwright
    if _browser:
        try:
            await _browser.close()
        except Exception as e:
            logger.warning("Erreur fermeture browser: %s", e)
        _browser = None
    if _playwright:
        try:
            await _playwright.stop()
        except Exception as e:
            logger.warning("Erreur arret playwright: %s", e)
        _playwright = None
    logger.info("Playwright ferme")
