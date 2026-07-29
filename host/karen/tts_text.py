"""Normalizzazione testo per sintesi vocale italiana (Piper)."""

from __future__ import annotations

import re

MAX_RECIPE_SPOKEN_CHARS = 520

_UNIT_RE = (
    (re.compile(r"(\d+)\s*kg\b", re.I), r"\1 chilogrammi"),
    (re.compile(r"(\d+)\s*g\b", re.I), r"\1 grammi"),
    (re.compile(r"(\d+)\s*ml\b", re.I), r"\1 millilitri"),
    (re.compile(r"(\d+)\s*cl\b", re.I), r"\1 centilitri"),
    (re.compile(r"(\d+)\s*l\b", re.I), r"\1 litri"),
    (re.compile(r"(\d+)\s*cucchiai?\b", re.I), r"\1 cucchiai"),
)

_BULLET_LINE_RE = re.compile(r"^[\s]*[-*•–—]\s+", re.M)
_NUMBERED_LINE_RE = re.compile(r"^[\s]*\d+[.)]\s+", re.M)
_INLINE_BULLET_RE = re.compile(r"\s[-–—]\s+(?=\d)")

_FRACTION_RE = (
    (re.compile(r"\b1/2\b"), "mezzo"),
    (re.compile(r"\b1/4\b"), "un quarto"),
    (re.compile(r"\b3/4\b"), "tre quarti"),
)

_FLUFF_SENTENCE_RE = re.compile(
    r"^(?:"
    r"preparare .+ (?:è|e') un'?operazione .+|"
    r"ecco (?:i passaggi|come preparare|la ricetta)|"
    r"segui questi passaggi"
    r")",
    re.I,
)

_RUNON_SPLIT_RE = re.compile(
    r"(?<=\))\s+(?=(?:Lessa|Cuoci|Rosola|Scola|Unisci|Mescola|Sbatti|"
    r"Aggiungi|Porta|In una|Nella|Friggi|Amalgama|Fuori)\b)",
    re.I,
)


def prepare_text_for_tts(text: str) -> str:
    """Rende il testo più naturale per Piper (niente elenchi/markdown)."""
    if not text:
        return text

    t = text.strip()
    t = _BULLET_LINE_RE.sub("", t)
    t = _NUMBERED_LINE_RE.sub("", t)
    t = _INLINE_BULLET_RE.sub(", ", t)
    t = t.replace("\n", " ")

    for pattern, repl in _FRACTION_RE:
        t = pattern.sub(repl, t)
    for pattern, repl in _UNIT_RE:
        t = pattern.sub(repl, t)

    t = re.sub(r"(\d+)\s*-\s*(\d+)\s*grammi", r"circa \1 grammi", t, flags=re.I)
    t = re.sub(r"\s{2,}", " ", t)
    return t.strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]
    return [p for p in parts if p and p[-1] in ".!?"]


def recipe_quality_ok(text: str, *, dish: str | None = None) -> bool:
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return False
    if any(len(s) > 240 for s in sentences):
        return False
    low = text.lower()
    if any(x in low for x in ("ecco i passaggi", "segui questi passaggi", "operazione semplice")):
        return False
    if dish == "carbonara" and any(x in low for x in ("pangrattato", "panna", "panna da cucina", "burro")):
        return False
    cooking = (
        "cuoci", "lessa", "rosola", "scola", "mescola", "unisci",
        "sbatti", "amalgama", "condisci", "friggi", "bollore",
    )
    return any(v in low for v in cooking)


def _split_runon_sentence(sentence: str) -> list[str]:
    chunks = [c.strip() for c in _RUNON_SPLIT_RE.split(sentence) if c.strip()]
    out: list[str] = []
    for chunk in chunks:
        if chunk[-1] not in ".!?":
            chunk = chunk.rstrip(",;:") + "."
        out.append(chunk)
    return out or [sentence]


def _cleanup_recipe_prose(text: str) -> str:
    t = text
    t = re.sub(
        r"\b(?:ingredienti|preparazione|procedimento|passaggi)\s*:\s*",
        "",
        t,
        flags=re.I,
    )
    t = re.sub(r"\b(?:ecco i passaggi|segui questi passaggi)\b\.?\s*", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    # Ripristina una sola introduzione ingredienti.
    t = re.sub(
        r"^(\d+\s+grammi)",
        r"Servono \1",
        t,
        flags=re.I,
    )
    if t and not t.lower().startswith("servono") and not t.lower().startswith("per "):
        if re.match(r"^\d+\s+grammi", t, re.I):
            t = "Servono " + t
    t = re.sub(r"\bServono\b", "Servono", t)
    t = re.sub(r"(Servono\s+)+", "Servono ", t, flags=re.I)
    return t.strip()


def format_recipe_for_speech(raw: str, *, max_sentences: int = 3) -> str:
    """Tre frasi in prosa: ingredienti, cottura, finitura."""
    t = _cleanup_recipe_prose(prepare_text_for_tts(raw))
    sentences = split_sentences(t)

    while sentences and _FLUFF_SENTENCE_RE.match(sentences[0]):
        sentences.pop(0)

    if len(sentences) == 1 and len(sentences[0]) > 160:
        sentences = _split_runon_sentence(sentences[0])

    if not sentences:
        return _cap_spoken_length(t, MAX_RECIPE_SPOKEN_CHARS)

    picked = sentences[:max_sentences]
    result = " ".join(picked)
    return _cap_spoken_length(result, MAX_RECIPE_SPOKEN_CHARS)


def _cap_spoken_length(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    sentences = split_sentences(text)
    out: list[str] = []
    total = 0
    for s in sentences:
        if total + len(s) + (1 if out else 0) > max_chars:
            break
        out.append(s)
        total += len(s) + (1 if out else 0)
    if out:
        return " ".join(out)
    cut = text.rfind(" ", 0, max_chars)
    out_text = (text[:cut] if cut > 80 else text[:max_chars]).rstrip(",;:")
    if out_text and out_text[-1] not in ".!?":
        out_text += "."
    return out_text
