# Chatbot École — RAG pédagogique

Chatbot RAG (Retrieval Augmented Generation) pour une école. Les élèves posent des questions sur les cours, la formation professionnelle, les systèmes/réseaux ou le développement.

## Stack

- **Backend** : Python 3.12, FastAPI
- **Vector DB** : ChromaDB 0.5+, sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2)
- **Reranker** : Cross-encoder (mmarco-mMiniLMv2-L12-H384-v1)
- **LLM** : OpenRouter (Qwen 3.7 Max), streaming SSE
- **Frontend** : Jinja2 templates, CSS vanilla, JS natif
- **Déploiement** : Docker Compose

## Démarrage rapide

```bash
# 1. Cloner
git clone https://github.com/zeetkt/ProjetChatbot.git
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
| `http://localhost:8080/login` | Connexion |
| `http://localhost:8080/` | Chat |
| `http://localhost:8080/admin` | Admin (upload/suppression docs) |
| `http://localhost:8080/admin/logs` | Historique des conversations |

## Pipeline RAG

```
Question → Pré-filtre OFFENSIVE_PATTERNS (refus si mot interdit)
  → Recherche vectorielle ChromaDB (k=50)
  → Si sujet détecté : recherche filtrée par source (k=20) + merge
  → Reranking cross-encoder (re-score des chunks par pertinence)
  → Diversification (max_per_source, max_total=12)
  → Génération LLM avec contexte
```

## Fonctionnalités

- **RAG** : recherche vectorielle chromadb + reranking cross-encoder + réponse LLM contextuelle
- **Détection de sujet automatique** : extrait les slugs depuis les noms de fichiers pour filtrer les sources
- **Reranking** : cross-encoder multilingue re-classe les chunks par pertinence après la recherche vectorielle
- **Streaming** : tokens affichés en temps réel (Server-Sent Events)
- **Mémoire de session** : le LLM se souvient des échanges précédents (avec héritage du sujet)
- **Import** : PDF, DOCX, TXT, MD, HTML (chunking avec chevauchement)
- **Sécurité** : rate limiting (slowapi), CSP headers, pré-filtre regex OFFENSIVE_PATTERNS, anti-injection (sandwich), validation anti-path-traversal
- **Auth** : cookie signé (itsdangerous), 24h de validité, HTTP-only SameSite=Strict
- **Journalisation** : conversations en JSON Lines (un fichier par jour)

## Configuration

Variables clés dans `.env` :

| Variable | Description |
|----------|-------------|
| `CHAT_PASSWORD` | Mot de passe unique d'accès |
| `OPENROUTER_API_KEY` | Clé API OpenRouter |
| `SECRET_KEY` | Clé pour signer les cookies |
| `OPENROUTER_MODEL` | Modèle LLM (défaut: qwen/qwen3.7-max) |

## Licence

MIT
