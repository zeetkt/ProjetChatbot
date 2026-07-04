# Contexte du projet Chatbot Ecole

## Stack technique
- **Backend** : Python 3.12, FastAPI, ChromaDB 0.5+, sentence-transformers, OpenRouter (Gemma 3 12B)
- **Frontend** : Jinja2 templates, CSS vanilla, JS natif (Streaming SSE)
- **Déploiement** : Docker Compose, VPS OVH (IP directe, pas de HTTPS)
- **Auth** : Mot de passe unique (env CHAT_PASSWORD), session signée itsdangerous (24h)

## Architecture
- **app/config.py** : toutes les variables de configuration (chemins, clés API, limites)
- **app/security.py** : rate limiting (slowapi), middleware headers sécurité + CSP, validation HTML
- **app/auth.py** : création/vérification de session signée (cookie HTTP-only SameSite=Strict)
- **app/embeddings.py** : wrapper sentence-transformers (compatible ChromaDB, paramètre `input`)
- **app/database.py** : client ChromaDB persistant, collection singleton, gestion des erreurs
- **app/llm.py** : client AsyncOpenAI → OpenRouter, prompt système avec 4 domaines autorisés + sandwich anti-injection, streaming
- **app/ingestion.py** : parseurs PDF/DOCX/TXT/MD/HTML + chunking avec chevauchement
- **app/rag.py** : pipeline ask() = pré-filtre OFFENSIVE_PATTERNS → search_similar → generate_answer
- **app/chat_logger.py** : journalisation conversations (JSON Lines, un fichier par jour)

## Routers
- **auth_router** : GET/POST /login, GET /logout (rate limit 5/min)
- **chat_router** : GET / (chat HTML), POST /api/chat (SSE streaming, rate limit 30/min)
- **admin_router** : GET /admin, POST /admin/upload, POST /admin/delete/{filename}, GET /admin/logs

## Sécurité
- **Pré-filtre regex** (OFFENSIVE_PATTERNS) : refuse les questions interdites avant tout appel LLM
- **Sandwich anti-injection** : rappel des règles APRÈS la question utilisateur dans le prompt
- **Headers HTTP** : CSP, X-Frame-Options, X-Content-Type-Options, Permissions-Policy, etc.
- **Rate limiting** : slowapi (global 60/min, login 5/min, chat 30/min, upload 10/min, delete 30/min)
- **Validation entrées** : anti path traversal (Path().name + os.path.realpath), taille max, extensions autorisées

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

# Test rapide du streaming
curl -X POST http://localhost:8080/api/chat \
  -H "Content-Type: application/json" \
  -H "Cookie: session=<votre_session>" \
  -d '{"message": "Bonjour"}'
```

## Dépendances critiques (premier démarrage)
- sentence-transformers télécharge le modèle (~470 Mo, 30-60s)
- ChromaDB télécharge ONNX all-MiniLM-L6-v2 (~79 Mo, warning ignorable)
- PyTorch CPU-only installé au build Docker (~800 Mo)

## URLs
- Chat : http://vps-ea164745.vps.ovh.net:8080/
- Login : http://vps-ea164745.vps.ovh.net:8080/login
- Admin : http://vps-ea164745.vps.ovh.net:8080/admin
- Logs : http://vps-ea164745.vps.ovh.net:8080/admin/logs
- OpenRouter API : https://openrouter.ai/keys (Gemma 3 12B ~0.02$/M tokens)
