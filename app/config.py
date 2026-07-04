"""
Module de configuration centralise.

Toutes les variables de configuration du chatbot sont definies ici.
Les valeurs sensibles (mots de passe, cles API) sont lues depuis le fichier .env
via python-dotenv. Les valeurs non sensibles ont des valeurs par defaut
qui peuvent etre surchargees dans le .env.
"""

import os
from dotenv import load_dotenv

# Charge les variables du fichier .env dans les variables d'environnement
load_dotenv()

# ─── Authentification ───────────────────────────────────────────────────────────
# Mot de passe unique pour acceder au chatbot.
# Doit etre defini dans le fichier .env (variable CHAT_PASSWORD).
# Utilise os.environ["VAR"] (sans .get) pour echouer IMMEDIATEMENT si absent.
CHAT_PASSWORD = os.environ["CHAT_PASSWORD"]

# Duree de validite d'une session utilisateur (en secondes).
# 86400 secondes = 24 heures. Apres ce delai, l'utilisateur doit se reconnecter.
SESSION_MAX_AGE = 86400

# Cle secrete utilisee par itsdangerous pour signer les cookies de session.
# Cette cle permet de verifier que le cookie n'a pas ete modifie par le client.
# Doit etre une chaine aleatoire longue (minimum 32 caracteres).
SECRET_KEY = os.environ["SECRET_KEY"]

# ─── OpenRouter (API LLM) ───────────────────────────────────────────────────────
# Cle API OpenRouter. Permet d'appeler les modeles de langage via OpenRouter.
# OpenRouter est une plateforme qui donne acces a de nombreux modeles LLM
# (Gemma, GPT, Claude, etc.) via une API compatible OpenAI.
# Obtenir une cle sur : https://openrouter.ai/keys
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

# Identifiant du modele utilise sur OpenRouter.
# google/gemma-4-12b-it : modele open-source de Google, 12 milliards de parametres,
# optimise pour les instructions, support multilingue (francais inclus).
# 256k tokens de contexte, licence Apache 2.0.
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "google/gemma-4-12b-it")

# URL de base de l'API OpenRouter.
# L'API OpenRouter est compatible avec le format OpenAI, donc on utilise
# le meme client Python "openai" avec une URL de base differente.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# ─── Decoupage des documents (chunking) ─────────────────────────────────────────
# Taille maximale d'un "chunk" (passage) en nombre de caracteres.
# Les documents sont decoupes en passages de cette taille avant d'etre indexes.
# 1000 caracteres ≈ 200-250 tokens, ce qui permet d'avoir des passages
# suffisamment longs pour etre significatifs mais assez courts pour etre precis.
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1000"))

# Nombre de caracteres de chevauchement entre deux chunks consecutifs.
# Le chevauchement permet de ne pas couper une phrase ou une idee importante
# entre deux chunks. 200 caracteres ≈ 20% de CHUNK_SIZE.
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))

# ─── Upload de fichiers ─────────────────────────────────────────────────────────
# Taille maximale d'un fichier uploade (en mega-octets).
# Limite a 20 Mo par defaut pour eviter les fichiers trop volumineux
# qui pourraient saturer le serveur ou ralentir l'indexation.
MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "20"))

# Taille maximale en octets (calculee automatiquement depuis MAX_UPLOAD_SIZE_MB).
# 1 Mo = 1024 * 1024 octets.
MAX_UPLOAD_SIZE = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# Extensions de fichiers autorisees a l'upload.
# Chaque extension correspond a un parseur specifique dans ingestion.py.
# - .pdf : PDF Portable Document Format
# - .docx / .doc : Documents Microsoft Word
# - .txt : Fichiers texte brut
# - .md : Fichiers Markdown
# - .html / .htm : Pages web
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html", ".htm"}

# ─── Chemins de stockage ────────────────────────────────────────────────────────
# Chemin vers le dossier de la base vectorielle ChromaDB.
# ChromaDB stocke les embeddings (representations vectorielles) des documents
# et permet de faire des recherches par similarite semantique.
# Les donnees sont persistees sur le disque entre les redemarrages.
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "./chroma_db")

# Chemin vers le dossier des documents importes.
# Les fichiers uploades via l'interface admin sont stockes ici.
DOCUMENTS_PATH = os.environ.get("DOCUMENTS_PATH", "./documents")

# Chemin vers le dossier des logs de chat.
# Les conversations (question + reponse) sont stockees ici, un fichier par jour,
# au format JSON Lines (.jsonl). Chaque ligne est un objet JSON.
LOGS_PATH = os.environ.get("LOGS_PATH", "./chat_logs")

# Nom de la collection ChromaDB qui contient les embeddings des documents.
# Une collection est l'equivalent d'une table dans une base de donnees classique.
COLLECTION_NAME = "school_docs"

# ─── Modele d'embedding ─────────────────────────────────────────────────────────
# Nom du modele sentence-transformers utilise pour generer les embeddings.
# paraphrase-multilingual-MiniLM-L12-v2 : modele multilingue qui supporte
# le francais (parmi 50+ langues). Il genere des embeddings de dimension 384
# et offre un bon equilibre entre qualite et rapidite.
# Autres valeurs possibles :
# - all-MiniLM-L6-v2 : anglais uniquement, plus rapide
# - intfloat/multilingual-e5-small : multilingue, meilleure qualite
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
