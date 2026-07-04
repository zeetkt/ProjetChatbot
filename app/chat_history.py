"""
Module de gestion de l'historique des conversations par session.

Stocke en memoire l'historique des echanges (questions + reponses)
pour chaque session de chat identifiee par un session_id unique.

L'historique est utilise pour fournir un contexte de conversation
au LLM, lui permettant de se souvenir des echanges precedents
dans la meme session.

Structure :
    {session_id: [
        {"role": "user", "content": "question"},
        {"role": "assistant", "content": "reponse"},
        ...
    ]}

Nettoyage :
    Les sessions inactives depuis plus de SESSION_TTL secondes
    sont automatiquement purgees a chaque acces.
"""

import time
from typing import Optional

SESSION_TTL = 7200
MAX_HISTORY_TURNS = 10

_history: dict[str, list[dict]] = {}


def _cleanup():
    now = time.time()
    cutoff = now - SESSION_TTL
    expired = [
        sid for sid in list(_history.keys())
        if _history[sid].get("_last_access", 0) < cutoff
    ]
    for sid in expired:
        del _history[sid]


def add_message(session_id: str, role: str, content: str):
    if session_id not in _history:
        _history[session_id] = {"messages": [], "_last_access": time.time()}
    _history[session_id]["messages"].append({"role": role, "content": content})
    _history[session_id]["_last_access"] = time.time()


def get_history(session_id: str, max_turns: Optional[int] = None) -> list[dict]:
    if max_turns is None:
        max_turns = MAX_HISTORY_TURNS
    _cleanup()
    entry = _history.get(session_id)
    if not entry:
        return []
    entry["_last_access"] = time.time()
    messages = entry["messages"]
    max_messages = max_turns * 2
    return messages[-max_messages:]
