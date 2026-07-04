"""
Module de journalisation des conversations du chat.

Stocke chaque echange (question utilisateur + reponse) dans des fichiers
JSON Lines, un fichier par jour. Le format JSONL permet de lire et
d'ecrire facilement, meme avec de gros volumes.

Structure : chat_logs/chat_YYYY-MM-DD.jsonl
Chaque ligne : {"timestamp": "...", "question": "...", "answer": "..."}

Fonctions:
  log_conversation(question, answer) → ecrit une ligne
  log_refused(question, reason) → ecrit une ligne avec marqueur [REFUSE]
  get_logs(days, limit, offset) → lit les logs recents tries par date decroissante
"""

import json
import os
from datetime import datetime, timedelta
import app.config as cfg


def _write_entry(question: str, answer: str) -> None:
    """
    Ecrit une ligne JSON dans le fichier de logs du jour.
    
    Fonction interne mutualisee par log_conversation() et log_refused().
    """
    os.makedirs(cfg.LOGS_PATH, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(cfg.LOGS_PATH, f"chat_{date_str}.jsonl")
    entry = {
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer,
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_conversation(question: str, answer: str) -> None:
    """
    Ecrit une conversation dans le fichier de logs du jour.

    Format : un fichier .jsonl par jour, chaque ligne est un objet JSON.
    Le dossier de logs est cree automatiquement s'il n'existe pas.

    Args:
        question: La question posee par l'utilisateur.
        answer: La reponse complete du chatbot.
    """
    _write_entry(question, answer)


def log_refused(question: str, reason: str) -> None:
    """
    Logue une question qui a ete refusee (hors-sujet ou motif interdit).

    Ecrit dans le meme fichier .jsonl que les conversations normales,
    mais la reponse est marquee [REFUSE] pour filtrage facile dans les logs.

    Args:
        question: La question qui a ete refusee.
        reason: La raison du refus (ex: "motif interdit: piratage").
    """
    _write_entry(question, f"[REFUSE] {reason}")


def get_logs(days: int = 7, limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Recupere les conversations recentes depuis les fichiers de logs.

    Parcourt les fichiers des N derniers jours, les trie par timestamp
    decroissant (plus recent en premier), et applique pagination.

    Args:
        days: Nombre de jours a remonter (defaut: 7).
        limit: Nombre maximum d'entrees a retourner (defaut: 100).
        offset: Index de depart pour la pagination (defaut: 0).

    Returns:
        list[dict]: Liste des conversations, chaque dict contient :
            - timestamp (str): date ISO 8601
            - question (str): la question utilisateur
            - answer (str): la reponse complete
    """
    entries = []
    cutoff = datetime.now() - timedelta(days=days)

    # Parcourt les fichiers de logs existants dans le dossier
    if not os.path.isdir(cfg.LOGS_PATH):
        return []

    for fname in sorted(os.listdir(cfg.LOGS_PATH), reverse=True):
        if not fname.startswith("chat_") or not fname.endswith(".jsonl"):
            continue

        fpath = os.path.join(cfg.LOGS_PATH, fname)

        # Saute les fichiers modifies avant la date limite
        # (approxime par le nom du fichier qui contient la date)
        try:
            file_date_str = fname.replace("chat_", "").replace(".jsonl", "")
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
            if file_date < cutoff:
                continue
        except ValueError:
            continue

        try:
            with open(fpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            continue

    # Trie par timestamp decroissant (plus recent en premier)
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    return entries[offset:offset + limit]
