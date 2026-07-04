"""
Module de navigation headless (Playwright) pour le rendu des pages SPA.

Certains sites web modernes (React, Vue, Angular) generent leur contenu
via JavaScript. Un simple fetch HTTP ne recupere que la coquille HTML vide.
Ce module utilise Playwright + Chromium headless pour executer le JS
et retourner le HTML complet renderise.

Cycle de vie :
  - render_page(url) → rend une URL et retourne le HTML final
  - close() → ferme le navigateur (appele au shutdown de l'app)
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_browser = None
_playwright = None


def render_page(url: str, timeout: int = 30000) -> Optional[str]:
    """
    Ouvre une page dans Chromium headless et retourne le HTML renderise.

    Args:
        url: URL a charger.
        timeout: Timeout en ms (defaut 30s).

    Returns:
        str: HTML complet apres execution JS, ou None si erreur.
    """
    global _browser, _playwright
    try:
        if _browser is None:
            from playwright.sync_api import sync_playwright
            _playwright = sync_playwright().start()
            _browser = _playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            logger.info("Playwright Chromium lance")

        context = _browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout)
        html = page.content()
        page.close()
        context.close()
        return html
    except Exception as e:
        logger.warning("Erreur rendu Playwright %s: %s", url, e, exc_info=True)
        return None


def close():
    """Ferme le navigateur et libere les ressources."""
    global _browser, _playwright
    if _browser:
        try:
            _browser.close()
        except Exception as e:
            logger.warning("Erreur fermeture browser: %s", e)
        _browser = None
    if _playwright:
        try:
            _playwright.stop()
        except Exception as e:
            logger.warning("Erreur arret playwright: %s", e)
        _playwright = None
    logger.info("Playwright ferme")
