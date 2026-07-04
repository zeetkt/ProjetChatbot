# ─── Image de base : Python 3.12 légère ───────────────────────────────────────
# Utilise l'image slim pour minimiser la taille du conteneur final.
FROM python:3.12-slim

# ─── Variables d'environnement Python ─────────────────────────────────────────
# PYTHONDONTWRITEBYTECODE=1 : évite la création de fichiers .pyc (inutiles en production)
# PYTHONUNBUFFERED=1        : force la sortie stdout/stderr sans buffer (logs en temps réel)
# TORCH_INDEX_URL           : télécharge PyTorch version CPU uniquement (pas de GPU)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu \
    PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright

# ─── Répertoire de travail ────────────────────────────────────────────────────
WORKDIR /app

# ─── Installation des dépendances Python ──────────────────────────────────────
# On copie d'abord requirements.txt seul pour optimiser le cache Docker :
# tant que requirements.txt ne change pas, cette couche est réutilisée.
COPY requirements.txt .

# Installation en deux étapes :
# 1. PyTorch CPU-only (depuis l'index CPU, évite de télécharger 2 Go de CUDA)
# 2. Les autres dépendances (ChromaDB, sentence-transformers, FastAPI...)
# ──note─: sentence-transformers téléchargera son modèle (~470 Mo) au premier
# démarrage, pas au build. PyTorch (~800 Mo) est installé au build.
RUN pip install --no-cache-dir torch --index-url $TORCH_INDEX_URL \
    && pip install --no-cache-dir -r requirements.txt \
    && python3 -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')" \
    && apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 \
        libcups2t64 libdrm2 libdbus-1-3 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
        libxshmfence1 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/* \
    && PLAYWRIGHT_BROWSERS_PATH=/app/ms-playwright python3 -m playwright install chromium

# ─── Copie du code source ─────────────────────────────────────────────────────
# Le .dockerignore doit exclure chroma_db/, documents/, .env, etc.
COPY . .

# ─── Création d'un utilisateur non-root ───────────────────────────────────────
# Bonne pratique de sécurité : le conteneur ne tourne pas en root.
# L'UID 1000 est standard et évite les problèmes de permissions avec les volumes.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# ─── Port exposé ──────────────────────────────────────────────────────────────
# L'application écoute sur le port 8000 (uvicorn).
# Dans docker-compose, on mappe 8080 (hôte) → 8000 (conteneur).
EXPOSE 8000

# ─── Commande de démarrage ────────────────────────────────────────────────────
# Lance uvicorn avec l'application FastAPI sur toutes les interfaces (0.0.0.0).
# Le nombre de workers n'est pas spécifié : mode single-process (suffisant pour
# un VPS OVH entrée de gamme). Pour monter en charge, ajouter --workers 4.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
