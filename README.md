# Chatbot École — RAG pédagogique

Chatbot问答 basé sur le RAG (Retrieval Augmented Generation) pour une école. Les élèves peuvent poser des questions sur les cours, la formation professionnelle, les systèmes/réseaux ou le développement.

## Stack

- **Backend** : Python 3.12, FastAPI
- **Vector DB** : ChromaDB 0.5+, sentence-transformers
- **LLM** : OpenRouter (Gemma 3 12B), streaming SSE
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

## Fonctionnalités

- **RAG** : recherche vectorielle dans les documents importés + réponse LLM contextuelle
- **Streaming** : tokens affichés en temps réel (Server-Sent Events)
- **Mémoire de session** : le LLM se souvient des échanges précédents
- **Import** : PDF, DOCX, TXT, MD, HTML
- **Sécurité** : rate limiting, CSP headers, pré-filtre regex, anti-injection
- **Auth** : cookie signé (itsdangerous), 24h de validité

## Configuration

Variables clés dans `.env` :

| Variable | Description |
|----------|-------------|
| `CHAT_PASSWORD` | Mot de passe unique d'accès |
| `OPENROUTER_API_KEY` | Clé API OpenRouter |
| `SECRET_KEY` | Clé pour signer les cookies |
| `OPENROUTER_MODEL` | Modèle LLM (défaut: Gemma 3 12B) |

## Licence

MIT
