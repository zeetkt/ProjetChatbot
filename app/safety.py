import logging
import httpx
import app.config as cfg

logger = logging.getLogger(__name__)

SAFETY_MODEL = "nvidia/nemotron-3.5-content-safety:free"

async def check_prompt_safety(question: str) -> bool:
    """
    Verifie si une question utilisateur est safe via Nemotron 3.5 Content Safety.

    Appelle le modele gratuit sur OpenRouter qui retourne un verdict
    structure : "User Safety: safe" ou "User Safety: unsafe".
    En cas d'erreur (timeout, API), on laisse passer par securite.

    Returns:
        True si la question est safe (ou si le check a echoue),
        False si elle est classee unsafe par Nemotron.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{cfg.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": SAFETY_MODEL,
                    "messages": [{"role": "user", "content": question}],
                    "max_tokens": 256,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            result = data["choices"][0]["message"]["content"].strip()

            for line in result.split("\n"):
                line = line.strip()
                if line.startswith("User Safety:"):
                    verdict = line.split(":", 1)[1].strip().lower()
                    is_safe = verdict == "safe"
                    if not is_safe:
                        logger.info("Nemotron a refuse la question: %s", result)
                    return is_safe

            logger.warning("Reponse Nemotron inattendue: %s", result)
            return True
    except Exception as e:
        logger.warning("Erreur appel Nemotron: %s", e)
        return True
