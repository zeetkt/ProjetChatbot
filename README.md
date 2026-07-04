# Chatbot École — RAG pédagogique

Chatbot RAG (Retrieval Augmented Generation) pour une école. Les élèves posent des questions sur les cours, la formation professionnelle, les systèmes/réseaux ou le développement.

## Stack

- **Backend** : Python 3.12, FastAPI
- **Vector DB** : ChromaDB 0.5+, sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
- **Reranker** : Cross-encoder (mmarco-mMiniLMv2-L12-H384-v1)
- **LLM** : OpenRouter (Mistral Small 3.2), streaming SSE
- **Frontend** : Jinja2 templates, CSS vanilla, JS natif (marked.js local pour Markdown)
- **Déploiement** : Docker Compose, Caddy (reverse proxy + HTTPS Let's Encrypt)

## Démarrage rapide

```bash
# 1. Cloner le dépôt
git clone <url-du-depot>
cd ProjetChatbot

# 2. Configurer
cp .env.example .env
# Editer .env : CHAT_PASSWORD, OPENROUTER_API_KEY, SECRET_KEY

# 3. Lancer
docker compose up -d --build
```

## Utilisation

| URL | Description |
|-----|-------------|
| `https://bastien.casa/login` | Connexion |
| `https://bastien.casa/` | Chat (redirige vers /login si non connecté) |
| `https://bastien.casa/admin` | Admin (upload/suppression docs, import sites web) |
| `https://bastien.casa/admin/logs` | Historique des conversations (protégé par mot de passe) |

## Pipeline RAG

```
Question → OFFENSIVE_PATTERNS (refus si match)
  → search_similar(k=50)
  → Si topic détecté : search avec filtre source (k=20) + merge dedup
  → Rerank (cross-encoder)
  → Diversify (max_per_source, max_total=12)
  → Generate_answer (LLM avec contexte)
```

## Fonctionnalités

- **RAG** : recherche vectorielle chromadb + reranking cross-encoder + réponse LLM
- **Détection de sujet** : extrait les slugs depuis les noms de fichiers pour filtrer
- **Reranking** : cross-encoder multilingue re-classe les chunks par pertinence
- **Streaming** : tokens affichés en temps réel (SSE) avec détection d'erreur OpenRouter
- **Mémoire de session** : le LLM se souvient des échanges précédents
- **Rendu Markdown** : marked.js (servi localement, pas de CDN externe)
- **Import multi-fichiers** : upload de plusieurs fichiers à la fois (50 max, 50 Mo chacun)
- **Import site web** : crawl BFS avec profondeur configurable, détection SPA headless (Playwright Chromium)
- **Arborescence crawls** : pages organisées par site, suppression individuelle ou par crawl
- **Formats supportés** : PDF, DOCX, TXT, MD, HTML
- **Logs protégés** : mot de passe dédié pour accéder à l'historique des conversations
- **Effacement logs** : bouton "Effacer les logs" avec confirmation
- **Sécurité** : rate limiting (slowapi), CSP headers, HSTS, pré-filtre OFFENSIVE_PATTERNS, anti-injection (sandwich), anti-path-traversal, anti-SSRF, docs API désactivées en prod, cookie Secure
- **Auth** : cookie signé (itsdangerous), 24h, HttpOnly + SameSite=Strict + Secure

## Configuration

Variables clés dans `.env` :

| Variable | Description |
|----------|-------------|
| `CHAT_PASSWORD` | Mot de passe unique d'accès au chat |
| `OPENROUTER_API_KEY` | Clé API OpenRouter |
| `SECRET_KEY` | Clé pour signer les cookies |
| `OPENROUTER_MODEL` | Modèle LLM (défaut: mistralai/mistral-small-3.2-24b-instruct) |
| `LOGS_PASSWORD` | Mot de passe pour les logs (défaut: Azerty78) |

## Licence

MIT
