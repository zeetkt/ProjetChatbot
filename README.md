# Chatbot École — RAG pédagogique

Chatbot RAG (Retrieval Augmented Generation) pour une école. Les élèves posent des questions sur les cours, la formation professionnelle, les systèmes/réseaux ou le développement.

## Stack

- **Backend** : Python 3.12, FastAPI
- **Vector DB** : ChromaDB 0.5+, sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
- **Reranker** : Cross-encoder (mmarco-mMiniLMv2-L12-H384-v1)
- **LLM** : OpenRouter (Mistral Small 3.2), streaming SSE
- **Frontend** : Jinja2 templates, CSS vanilla, JS natif (marked.js pour Markdown)
- **Déploiement** : Docker Compose, Caddy (reverse proxy + HTTPS auto)

## Démarrage rapide

```bash
# 1. Cloner
git clone https://github.com/zeetkt/ProjetChatbot.git
cd ProjetChatbot

# 2. Configurer
cp .env.example .env
# Editer .env : CHAT_PASSWORD, OPENROUTER_API_KEY, SECRET_KEY

# 3. Lancer (dev local)
docker compose up -d --build
```

## Utilisation (dev local)

| URL | Description |
|-----|-------------|
| `http://localhost:8080/login` | Connexion |
| `http://localhost:8080/` | Chat (redirige vers /login si non connecté) |
| `http://localhost:8080/admin` | Admin (upload/suppression docs) |
| `http://localhost:8080/admin/logs` | Historique des conversations |

En production derrière Caddy, remplacer `http://localhost:8080` par le domaine HTTPS.

## Pipeline RAG

```
Question → OFFENSIVE_PATTERNS (refus si match)
  → search_similar(k=50) [recherche large]
  → Si topic détecté : search avec filtre source (k=20) + merge dedup
  → Rerank (cross-encoder, re-score tout)
  → Diversify (max_per_source, max_total=12)
  → Generate_answer (LLM avec contexte)
```

## Fonctionnalités

- **RAG** : recherche vectorielle chromadb + reranking cross-encoder + réponse LLM contextuelle
- **Détection de sujet automatique** : extrait les slugs depuis les noms de fichiers pour filtrer les sources
- **Reranking** : cross-encoder multilingue re-classe les chunks par pertinence après la recherche vectorielle
- **Streaming** : tokens affichés en temps réel (SSE) avec détection d'erreur OpenRouter
- **Mémoire de session** : le LLM se souvient des échanges précédents (avec héritage du sujet)
- **Rendu Markdown** : les réponses du LLM sont affichées en Markdown (titres, listes, code, citations)
- **Import** : PDF, DOCX, TXT, MD, HTML (chunking avec chevauchement)
- **Sécurité** : rate limiting (slowapi 60/min global), CSP headers, HSTS, pré-filtre OFFENSIVE_PATTERNS, anti-injection (sandwich), anti-path-traversal, docs API désactivées en prod
- **Auth** : cookie signé (itsdangerous), 24h, HttpOnly + SameSite=Strict + Secure

## Configuration

Variables clés dans `.env` :

| Variable | Description |
|----------|-------------|
| `CHAT_PASSWORD` | Mot de passe unique d'accès |
| `OPENROUTER_API_KEY` | Clé API OpenRouter |
| `SECRET_KEY` | Clé pour signer les cookies |
| `OPENROUTER_MODEL` | Modèle LLM (défaut: mistralai/mistral-small-3.2-24b-instruct) |

## Licence

MIT
