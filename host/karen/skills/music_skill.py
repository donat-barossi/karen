"""
Skill: riproduzione musicale via Home Assistant (Music Assistant / Jellyfin / media_player).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..asr_fix import fix_asr_transcript
from ..ha_client import HomeAssistantClient, ha_action_error
from ..stop import is_music_stop_phrase
from .base import BaseSkill

log = logging.getLogger(__name__)

_PLAY_PREFIXES = (
    "riproduci",
    "metti",
    "fammi sentire",
    "voglio sentire",
    "ascolta",
    "play",
    "fai partire",
    "passa a",
)

_MUSIC_HINTS = (
    "musica",
    "album",
    "brano",
    "canzone",
    "canzoni",
    "playlist",
    "artista",
    "cantante",
)

_GENRES = frozenset({
    "pop", "rock", "jazz", "blues", "classica", "classico", "dance",
    "techno", "house", "hip hop", "rap", "trap", "reggaeton", "latino",
    "metal", "punk", "indie", "soul", "funk", "disco", "electronic",
    "elettronica", "ambient", "folk", "country", "r&b", "rnb",
})

# ASR / pronuncia italiana → nome artista in libreria (Navidrome/MA)
_ARTIST_ALIASES: dict[str, str] = {
    "giovanotti": "Jovanotti",
    "giovannotti": "Jovanotti",
    "lorenzo giovanotti": "Jovanotti",
    "lorenzo giovannotti": "Jovanotti",
    "max pezzali": "Max Pezzali",
    "883": "883",
}


def _fix_asr_music(text: str) -> str:
    return fix_asr_transcript(text)


def _normalize_artist(name: str) -> str:
    key = _normalize(name)
    if key in _ARTIST_ALIASES:
        return _ARTIST_ALIASES[key]
    if "giovanott" in key:
        return "Jovanotti"
    return name.strip()


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = re.sub(r"[^\w\s']", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_music_intent(text: str) -> dict[str, Any] | None:
    """
    Estrae intent musica da testo utente (fast-path, senza LLM).

    Esempi:
      riproduci gli anni di max pezzali  → track
      riproduci musica degli 883          → artist
      riproduci musica pop                → genre
      riproduci l album hit mania ...     → album
    """
    t = _normalize(_fix_asr_music(text))
    if not t:
        return None

    if re.search(r"\b(?:svegl\w*|spegl\w*|timer|allarm\w*|promemoria)\b", t):
        return None

    if is_music_stop_phrase(text):
        return {"intent": "music", "parameters": {"action": "stop"}}

    if re.search(r"\b(?:pausa|metti in pausa)\b.*\bmusica\b", t):
        return {"intent": "music", "parameters": {"action": "pause"}}

    if re.search(r"\b(?:riprendi|continua)\b.*\bmusica\b", t):
        return {"intent": "music", "parameters": {"action": "play"}}

    body = t
    for prefix in _PLAY_PREFIXES:
        if body.startswith(prefix + " "):
            body = body[len(prefix) + 1 :].strip()
            break
        if body == prefix:
            return None
    else:
        if not any(h in t for h in _MUSIC_HINTS):
            return None

    body = re.sub(r"^(?:la|il|un|una|del|della|dei|degli)\s+", "", body).strip()

    if re.search(r"\b(?:svegl\w*|spegl\w*)\b", body) or re.search(r"\balle\s+\d", body):
        return None

    m = re.match(r"^(?:l )?album\s+(.+)$", body)
    if m:
        return {
            "intent": "music",
            "parameters": {
                "action": "play",
                "search_type": "album",
                "query": m.group(1).strip(),
            },
        }

    m = re.match(r"^musica\s+(?:dei|degli|delle|del|della|di)\s+(.+)$", body)
    if m:
        return {
            "intent": "music",
            "parameters": {
                "action": "play",
                "search_type": "artist",
                "query": m.group(1).strip(),
            },
        }

    m = re.match(r"^musica\s+(.+)$", body)
    if m:
        rest = m.group(1).strip()
        if rest in _GENRES or rest.startswith("anni "):
            return {
                "intent": "music",
                "parameters": {
                    "action": "play",
                    "search_type": "genre",
                    "query": rest,
                },
            }
        return {
            "intent": "music",
            "parameters": {
                "action": "play",
                "search_type": "artist",
                "query": rest,
            },
        }

    m = re.match(r"^(?:brano|canzone|canzoni)\s+(?:di\s+)?(.+)$", body)
    if m:
        return {
            "intent": "music",
            "parameters": {
                "action": "play",
                "search_type": "track",
                "query": m.group(1).strip(),
            },
        }

    m = re.match(r"^(.+?)\s+di\s+(.+)$", body)
    if m:
        track = m.group(1).strip()
        artist = _normalize_artist(m.group(2).strip())
        if track and artist and track.lower() not in _GENRES:
            return {
                "intent": "music",
                "parameters": {
                    "action": "play",
                    "search_type": "track",
                    "query": track,
                    "artist": artist,
                },
            }

    if body:
        return {
            "intent": "music",
            "parameters": {
                "action": "play",
                "search_type": "artist",
                "query": _format_artist_query(body),
            },
        }
    return None


def _format_artist_query(name: str) -> str:
    """Normalizza nome artista per ricerca MA/Navidrome."""
    cleaned = name.strip()
    normalized = _normalize_artist(cleaned)
    if normalized.lower() != _normalize(cleaned):
        return normalized
    return cleaned.title()


def _spoken_label(params: dict[str, Any]) -> str:
    query = str(params.get("query", "")).strip()
    artist = str(params.get("artist", "")).strip()
    search_type = str(params.get("search_type", "track")).lower()
    if search_type == "track" and artist:
        return f"{query} di {artist}"
    if search_type == "album":
        return f"l'album {query}"
    if search_type == "artist":
        return f"musica di {query}"
    if search_type == "genre":
        return f"musica {query}"
    return query


class MusicSkill(BaseSkill):

    @property
    def handled_intents(self) -> list[str]:
        return ["music"]

    async def execute(self, intent_data: dict[str, Any]) -> str:
        music_cfg = self._cfg.get("music", {})
        ha_cfg = self._cfg.get("ha", {})
        entity = (
            intent_data.get("parameters", {}).get("media_player")
            or music_cfg.get("media_player")
            or ha_cfg.get("entities", {}).get("media_player")
        )
        player_name = music_cfg.get("player_name", "player")

        ha = HomeAssistantClient(ha_cfg)
        params = intent_data.get("parameters", {})
        action = params.get("action", "play")

        if action == "stop":
            if not entity:
                return "Non ho un player musicale configurato."
            result = await ha.call_service("media_player.media_stop", entity_id=entity)
            return "Ok, musica fermata." if result.ok else ha_action_error("fermare la musica", result)

        if action == "pause":
            if not entity:
                return "Non ho un player musicale configurato."
            result = await ha.call_service("media_player.media_pause", entity_id=entity)
            return "Ok, musica in pausa." if result.ok else ha_action_error("mettere in pausa", result)

        if action == "play" and not params.get("query"):
            if not entity:
                return "Non ho un player musicale configurato."
            result = await ha.call_service("media_player.media_play", entity_id=entity)
            return "Ok, riprendo la musica." if result.ok else ha_action_error("riprendere la musica", result)

        if not entity:
            return (
                "Non ho un player musicale configurato in Home Assistant. "
                "Installa Music Assistant e imposta music.media_player in config."
            )

        query = str(params.get("query", "")).strip()
        if not query:
            return "Non ho capito cosa vuoi ascoltare."

        search_type = str(params.get("search_type", "track")).lower()
        artist = str(params.get("artist", "")).strip()
        if artist:
            artist = _normalize_artist(artist)
        elif search_type == "artist":
            query = _format_artist_query(query)
        label = _spoken_label({**params, "artist": artist, "query": query})

        if search_type in ("track", "artist", "album"):
            play_args: dict[str, Any] = {
                "entity_id": entity,
                "media_id": query,
                "media_type": search_type,
                "enqueue": "replace",
            }
            if search_type == "track" and artist:
                play_args["artist"] = artist
            result = await ha.call_service("music_assistant.play_media", **play_args)
            if (
                not result.ok
                and search_type == "track"
                and not artist
            ):
                result = await ha.call_service(
                    "music_assistant.play_media",
                    entity_id=entity,
                    media_id=_format_artist_query(query),
                    media_type="artist",
                    enqueue="replace",
                )
                if result.ok:
                    log.info(
                        "Musica fallback artista → %s su %s (track %r assente)",
                        query,
                        entity,
                        query,
                    )
                    return (
                        f"Non trovo il brano {query} in libreria. "
                        f"Metto musica di {query} su {player_name}."
                    )
            if (
                not result.ok
                and search_type == "track"
                and artist
            ):
                result = await ha.call_service(
                    "music_assistant.play_media",
                    entity_id=entity,
                    media_id=artist,
                    media_type="artist",
                    enqueue="replace",
                )
                if result.ok:
                    log.info(
                        "Musica fallback artista → %s su %s (track %r assente)",
                        artist,
                        entity,
                        query,
                    )
                    return (
                        f"Non trovo {query} di {artist} in libreria. "
                        f"Metto musica di {artist} su {player_name}."
                    )
        else:
            result = await ha.call_service(
                "media_player.play_media",
                entity_id=entity,
                media_content_id=query,
                media_content_type=music_cfg.get("content_type", "music"),
            )
        if result.ok:
            log.info("Musica → %s su %s (query=%r)", label, entity, query)
            return f"Ok, metto {label} su {player_name}."
        if result.error in ("unreachable", "timeout", "not_configured"):
            return ha_action_error(f"riprodurre {label}", result)
        return (
            f"Non riesco a riprodurre {label}. "
            "Il brano potrebbe non essere in Navidrome, oppure Music Assistant non è raggiungibile."
        )
