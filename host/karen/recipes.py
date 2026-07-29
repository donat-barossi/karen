"""Ricette curate e normalizzazione ASR per richieste di cucina."""

from __future__ import annotations

import re

# Testo già in prosa, 3 frasi, adatto al TTS.
CURATED_RECIPES: dict[str, str] = {
    "carbonara": (
        "Per la carbonara servono spaghetti, guanciale, tuorli d'uovo, pecorino romano e pepe nero. "
        "Cuoci la pasta in acqua salata e rosola il guanciale in padella senza olio. "
        "Scola la pasta al dente, uniscila al guanciale fuori dal fuoco e amalgama con tuorli e pecorino, mescolando subito."
    ),
    "amatriciana": (
        "Per l'amatriciana servono spaghetti, guanciale, pomodoro pelato, pecorino romano e pepe. "
        "Rosola il guanciale, aggiungi il pomodoro e cuoci la salsa per dieci minuti. "
        "Lessa la pasta, scolala e condiscila con la salsa e abbondante pecorino."
    ),
    "cacio e pepe": (
        "Per il cacio e pepe servono tonnarelli o spaghetti, pecorino romano grattugiato e pepe nero. "
        "Cuoci la pasta e tosta il pepe in padella con un mestolo di acqua di cottura. "
        "Scola la pasta, saltala in padella e amalgama fuori dal fuoco con pecorino e acqua di cottura."
    ),
    "risotto": (
        "Per un risotto servono riso arborio, brodo caldo, cipolla, burro e parmigiano. "
        "Tosta il riso con la cipolla, sfuma con vino bianco e cuoci mescolando aggiungendo brodo poco alla volta. "
        "Fuori dal fuoco manteca con burro e parmigiano, poi lascia riposare un minuto prima di servire."
    ),
}

_DISH_ALIASES: tuple[tuple[str, str], ...] = (
    ("passata carbonara", "pasta alla carbonara"),
    ("passata alla carbonara", "pasta alla carbonara"),
    ("pasta da carbonara", "pasta alla carbonara"),
    ("pasta la carbonara", "pasta alla carbonara"),
    ("pasta carbonara", "pasta alla carbonara"),
    ("la carbonara", "pasta alla carbonara"),
)

_DISH_KEYS: tuple[tuple[str, str], ...] = (
    ("cacio e pepe", "cacio e pepe"),
    ("cacio pepe", "cacio e pepe"),
    ("carbonara", "carbonara"),
    ("amatriciana", "amatriciana"),
    ("risotto", "risotto"),
)


def normalize_recipe_query(text: str) -> str:
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    for wrong, right in _DISH_ALIASES:
        if wrong in t:
            t = t.replace(wrong, right)
    return t


def detect_curated_dish(text: str) -> str | None:
    t = normalize_recipe_query(text)
    for needle, key in _DISH_KEYS:
        if needle in t:
            return key
    return None


def curated_recipe_for(text: str) -> str | None:
    key = detect_curated_dish(text)
    if key is None:
        return None
    return CURATED_RECIPES.get(key)
