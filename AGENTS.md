# Contexte du projet Chatbot Ecole

## Stack technique
- **Backend** : Python 3.12, FastAPI, ChromaDB 0.5+, sentence-transformers, OpenRouter (google/gemini-3.5-flash)
- **Frontend** : Jinja2 templates, CSS vanilla, JS natif (Streaming SSE, marked.js local), dark mode
- **Déploiement** : Docker Compose, Caddy (reverse proxy + HTTPS Let's Encrypt), VPS OVH
- **Auth** : Mot de passe unique (env CHAT_PASSWORD), session signée itsdangerous (24h)

## Architecture
- **app/config.py** : toutes les variables de configuration (chemins, clés API, limites, reranker, LOGS_PASSWORD obligatoire)
- **app/security.py** : rate limiting (slowapi), middleware headers sécurité + CSP, validation HTML
- **app/auth.py** : création/vérification de session signée (cookie HTTP-only SameSite=Strict Secure), log_access serializer
- **app/embeddings.py** : wrapper sentence-transformers (compatible ChromaDB, paramètre `input`)
- **app/database.py** : client ChromaDB persistant, collection singleton, déduplication startup + post-ingest, gestion des erreurs, `deduplicate_collection()` force un second passage
- **app/reranker.py** : cross-encoder (mmarco-mMiniLMv2-L12-H384-v1) pour reclasser les chunks, filtre `content: None`
- **app/llm.py** : client AsyncOpenAI → OpenRouter, prompt système avec 4 domaines autorisés + sandwich anti-injection + règle "ne pas parler négativement de l'ADRAR/Pôle Numérique", streaming, détection erreurs OpenRouter
- **app/ingestion.py** : parseurs PDF/DOCX/TXT/MD/HTML + chunking avec chevauchement + crawl web BFS avec Playwright
- **app/rag.py** : pipeline ask() = pré-filtre OFFENSIVE_PATTERNS → search → topic_filter → rerank → diversify → generate_answer, cache des slugs/sources avec invalidation
- **app/chat_logger.py** : journalisation conversations (JSON Lines, un fichier par jour), clear_logs()

## Routers
- **auth_router** : GET/POST /login, GET /logout (rate limit 5/min), `secrets.compare_digest()`
- **chat_router** : GET / (chat HTML), POST /api/chat (SSE streaming, rate limit 30/min)
- **admin_router** : GET /admin, POST /admin/upload (multi-fichiers), POST /admin/import-url, POST /admin/delete/{filename}, GET/POST /admin/logs (protégé par LOGS_PASSWORD), POST /admin/logs/clear, POST /admin/delete-webpage/{filename}, POST /admin/delete-website/{crawl_id}, invalidation cache fichiers

## Pipeline RAG complet
```
Question → OFFENSIVE_PATTERNS (refus si match)
  → search_similar(k=50) [recherche large]
  → si topic détecté: search avec filtre source (k=20) + merge dedup
  → rerank (cross-encoder, re-score tout)
  → diversify (max_per_source, max_total=12)
  → generate_answer (LLM avec contexte)
```

## Bugs corrigés
- `hash()` → `hashlib.sha256` pour les IDs de chunks (déterministe entre conteneurs)
- `collection.upsert` remplace `get→delete→add` (atomicité, évite race condition)
- `secrets.compare_digest()` pour la vérification du mot de passe
- `LOGS_PASSWORD` obligatoire (plus de valeur par défaut `Azerty78`)
- Cache `_get_file_slugs`/`_get_file_sources` avec `clear_file_cache()` après upload/delete
- `ingest_directory` exécuté dans un thread pool (`asyncio.to_thread`) au démarrage
- Crash `content: None` dans `_merge_dedup` et `reranker.py`
- Dédup forcé APRÈS `ingest_directory` pour nettoyer les doublons créés par changement de scheme d'IDs

## Sécurité
- **Pré-filtre regex** (OFFENSIVE_PATTERNS) : refuse les questions interdites avant tout appel LLM
- **Sandwich anti-injection** : rappel des règles APRÈS la question utilisateur dans le prompt
- **Headers HTTP** : CSP (script-src 'self' 'unsafe-inline'), HSTS 1 an, X-Frame-Options, X-Content-Type-Options, Permissions-Policy, etc.
- **Rate limiting** : slowapi (global 60/min, login 5/min, chat 30/min, upload 10/min, import-url 5/min, delete 30/min)
- **Validation entrées** : anti path traversal (Path().name + os.path.realpath), taille max, extensions autorisées
- **Anti-SSRF** : blocage IPs privées/loopback/169.254.169.254, vérifié aussi sur les redirections
- **Logs protégés** : mot de passe dédié (LOGS_PASSWORD, cookie signé log_access 24h)
- **CSP stricte** : pas de CDN externe (marked.js servi localement depuis /static/)

## Particularités ChromaDB 0.5+
- `EmbeddingFunction.__call__` prend `input` (pas `texts`)
- Collection inexistante lève `InvalidCollectionException` (pas `ValueError`)

## Déploiement (VPS)
```bash
# Connexion SSH
ssh -p 40682 debian@vps-ea164745.vps.ovh.net

# Build & démarrage (sur le VPS)
cd ~/chatbot
sg docker -c 'docker compose up -d --build'

# Logs temps réel
docker compose logs -f

# Arrêt
docker compose down
```

## Dépendances critiques (premier démarrage)
- sentence-transformers télécharge le modèle (~470 Mo, 30-60s)
- Cross-encoder reranker télécharge le modèle (~80 Mo, téléchargé au build Docker)
- ChromaDB télécharge ONNX all-MiniLM-L6-v2 (~79 Mo, warning ignorable)
- PyTorch CPU-only installé au build Docker (~800 Mo)
- Playwright Chromium (~300 Mo, installé au build Docker)

## URLs
- Chat : https://bastien.casa/
- Login : https://bastien.casa/login
- Admin : https://bastien.casa/admin
- Logs : https://bastien.casa/admin/logs (mot de passe : Azerty78)
- OpenRouter API : https://openrouter.ai/keys (modèle: deepseek/deepseek-v4-flash)
