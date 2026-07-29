"""
Karen – LLM Engine
Usa llama-cpp-python con Phi-3 Mini Q4.
Input:  testo in italiano (trascrizione Whisper)
Output: JSON strutturato con intent, parametri e risposta in italiano.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Sei Karen, assistente vocale per la casa. L'utente parla SEMPRE in italiano.

Devi rispondere SOLO con un oggetto JSON valido, senza markdown e senza testo extra.
Campi obbligatori:
- "intent": uno tra ["timer", "alarm", "calendar_query", "calendar_create", "reminder",
                      "ha_action", "weather", "time", "date", "recipe", "general", "unknown"]
- "parameters": oggetto con i parametri rilevanti ({} se vuoto)
- "response_it": risposta breve IN ITALIANO (max 2 frasi, MAI in inglese)
- "ha_service": stringa o null
- "ha_entity": stringa o null

Regole:
- response_it deve essere sempre in italiano
- per time/date/meteo usa response_it: "[SKILL_WILL_FILL]"
- non spiegare che sei un'AI, rispondi in modo naturale e conciso

Esempi:

Utente: che ore sono
{"intent":"time","parameters":{},"response_it":"[SKILL_WILL_FILL]","ha_service":null,"ha_entity":null}

Utente: imposta un timer di cinque minuti
{"intent":"timer","parameters":{"action":"start","duration_s":300},"response_it":"Timer di 5 minuti avviato!","ha_service":null,"ha_entity":null}

Utente: annulla tutti i timer
{"intent":"timer","parameters":{"action":"cancel","all":true},"response_it":"Timer annullati.","ha_service":null,"ha_entity":null}

Utente: sveglia alle sette e mezza
{"intent":"alarm","parameters":{"action":"set","hour":7,"minute":30,"days":[0,1,2,3,4,5,6]},"response_it":"Sveglia impostata per le 07:30!","ha_service":null,"ha_entity":null}

Utente: sveglia alle sette lunedì mercoledì e venerdì
{"intent":"alarm","parameters":{"action":"set","hour":7,"minute":0,"days":[0,2,4],"name":"lun-mer-ven"},"response_it":"Sveglia lun-mer-ven alle 07:00.","ha_service":null,"ha_entity":null}

Utente: domani non suonare la sveglia
{"intent":"alarm","parameters":{"action":"skip_tomorrow"},"response_it":"Ok, domani non suonerà.","ha_service":null,"ha_entity":null}

Utente: annulla tutte le sveglie
{"intent":"alarm","parameters":{"action":"cancel","all":true},"response_it":"Sveglie disattivate.","ha_service":null,"ha_entity":null}

Utente: cosa ho in calendario domani
{"intent":"calendar_query","parameters":{"when":"tomorrow"},"response_it":"[SKILL_WILL_FILL]","ha_service":null,"ha_entity":null}

Utente: ricordami domani alle 15 la riunione con Marco
{"intent":"reminder","parameters":{"title":"Riunione con Marco","when":"tomorrow","hour":15,"minute":0},"response_it":"[SKILL_WILL_FILL]","ha_service":null,"ha_entity":null}

Utente: aggiungi al calendario dentista venerdì alle 10
{"intent":"calendar_create","parameters":{"title":"Dentista","when":"friday","hour":10,"minute":0},"response_it":"[SKILL_WILL_FILL]","ha_service":null,"ha_entity":null}

Utente: accendi le luci del salotto
{"intent":"ha_action","parameters":{"action":"turn_on"},"response_it":"Accendo le luci del salotto!","ha_service":"light.turn_on","ha_entity":"light.salotto"}

Utente: ciao come stai
{"intent":"general","parameters":{},"response_it":"Ciao! Sono Karen, come posso aiutarti?","ha_service":null,"ha_entity":null}

Utente: qual è la ricetta della pasta alla carbonara
{"intent":"recipe","parameters":{"dish":"carbonara"},"response_it":"Per la carbonara servono guanciale, uova, pecorino e pepe. Cuoci la pasta, rosola il guanciale, mescola uova e pecorino, poi amalgama fuori dal fuoco.","ha_service":null,"ha_entity":null}

Regole ricette:
- intent recipe, response_it in italiano, massimo 4 frasi (risposta vocale breve)
- NON usare altri campi come ricetta, title, ingredients: solo il formato JSON sopra
"""

RECIPE_PROMPT = """\
Sei Karen, assistente vocale italiano.

Rispondi con ESATTAMENTE 3 frasi, ognuna chiusa da un punto. Massimo 65 parole totali.
- Frase 1: ingredienti principali in prosa (es. "Per la carbonara servono spaghetti, guanciale, uova, pecorino e pepe.").
- Frase 2: cottura (pasta, padella, uova sbattute, ecc.).
- Frase 3: unione finale fuori dal fuoco e servizio.

VIETATO: elenchi, trattini, numerazione, "ecco i passaggi", intro generiche, inglese.

Esempio:
Per la carbonara servono spaghetti, guanciale, uova, pecorino e pepe. Cuoci la pasta, rosola il guanciale e sbatti uova con formaggio. Scola, unisci tutto fuori dal fuoco e condisci con pepe.
"""

RECIPE_USER_SUFFIX = (
    "\n\nRispondi con esattamente 3 frasi brevi in prosa, senza elenchi né introduzioni generiche."
)


class LLMEngine:
    def __init__(self, cfg: dict, models_dir: Path) -> None:
        self._cfg = cfg
        model_path = cfg["model_path"]
        if not Path(model_path).is_absolute():
            self._model_path = str(models_dir / model_path)
        else:
            self._model_path = model_path
        self._llm: Any = None

    def load(self) -> None:
        from llama_cpp import Llama

        self._llm = Llama(
            model_path=self._model_path,
            n_gpu_layers=self._cfg.get("n_gpu_layers", -1),
            n_ctx=self._cfg.get("context_length", 2048),
            verbose=False,
        )
        log.debug("LLM caricato da %s", self._model_path)

    def generate(self, user_text: str) -> str:
        """Genera la risposta JSON dato il comando vocale in italiano."""
        if self._llm is None:
            raise RuntimeError("LLM non caricato. Chiama load() prima.")

        kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": self._cfg.get("max_tokens", 128),
            "temperature": self._cfg.get("temperature", 0.1),
            "top_p": self._cfg.get("top_p", 0.9),
            "stop": ["<|end|>", "<|endoftext|>", "\n\nUtente:"],
        }

        try:
            kwargs["response_format"] = {"type": "json_object"}
            response = self._llm.create_chat_completion(**kwargs)
        except TypeError:
            kwargs.pop("response_format", None)
            response = self._llm.create_chat_completion(**kwargs)

        content = response["choices"][0]["message"]["content"].strip()
        return self._repair_json(content)

    def generate_recipe(self, user_text: str) -> str:
        """Risposta ricetta in italiano (testo libero, breve per TTS)."""
        if self._llm is None:
            raise RuntimeError("LLM non caricato. Chiama load() prima.")

        from .recipes import detect_curated_dish
        from .tts_text import format_recipe_for_speech, recipe_quality_ok

        user_msg = user_text.strip() + RECIPE_USER_SUFFIX
        dish = detect_curated_dish(user_text)
        raw = self._recipe_completion(user_msg)
        formatted = format_recipe_for_speech(raw)
        if recipe_quality_ok(formatted, dish=dish):
            return formatted

        log.warning("Ricetta LLM debole, secondo tentativo: %r", formatted[:100])
        retry_msg = (
            f"{user_text.strip()}\n\n"
            "Solo 3 frasi corte: (1) ingredienti in prosa, (2) cottura, (3) finitura. "
            "Niente elenchi, niente 'ecco i passaggi'."
        )
        raw_retry = self._recipe_completion(retry_msg)
        formatted_retry = format_recipe_for_speech(raw_retry)
        if recipe_quality_ok(formatted_retry, dish=dish):
            return formatted_retry
        if dish:
            from .recipes import CURATED_RECIPES

            fallback = CURATED_RECIPES.get(dish)
            if fallback:
                log.warning("Ricetta LLM scartata, uso curata per %s", dish)
                return format_recipe_for_speech(fallback)
        return formatted_retry if formatted_retry.strip() else formatted

    def _recipe_completion(self, user_msg: str) -> str:
        response = self._llm.create_chat_completion(
            messages=[
                {"role": "system", "content": RECIPE_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=self._cfg.get("recipe_max_tokens", 180),
            temperature=self._cfg.get("recipe_temperature", 0.05),
            top_p=self._cfg.get("top_p", 0.9),
            stop=["<|end|>", "<|endoftext|>", "\n\nUtente:", "\n\n"],
        )
        return response["choices"][0]["message"]["content"].strip()

    @staticmethod
    def _repair_json(raw: str) -> str:
        raw = raw.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        start = raw.find("{")
        if start == -1:
            return raw

        end = raw.rfind("}")
        if end != -1:
            return raw[start : end + 1]

        return raw[start:] + "}"
