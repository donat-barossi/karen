# Karen – Timer, sveglie e calendario Outlook

## Cosa può fare Karen oggi

| Comando vocale | Intent | Dove |
|----------------|--------|------|
| "Timer di 5 minuti" | `timer` (start) | Scheduler locale (`host/data/schedules.json`) |
| "Annulla il timer" / "Annulla tutti i timer" | `timer` (cancel) | Scheduler locale |
| "Quali timer ho attivi?" | `timer` (list) | Scheduler locale |
| "Sveglia alle 7:30" | `alarm` (set) | Scheduler locale |
| "Sveglia alle 7 lunedì mercoledì venerdì" | `alarm` (set, days) | Scheduler locale |
| "Domani non suonare" | `alarm` (skip_tomorrow) | Salta una data senza cancellare la ricorrenza |
| "Quali sveglie ho?" | `alarm` (list) | Scheduler locale |
| "Cosa ho in calendario domani?" | `calendar_query` | Calendario Outlook via HA |
| "Ricordami domani alle 15 riunione con Marco" | `reminder` | Crea evento in calendario |
| "Aggiungi dentista venerdì alle 10" | `calendar_create` | Calendario Outlook |

---

## 1. Home Assistant – configurazione base

Copia il package:

```bash
cp homeassistant/packages/karen.yaml /path/to/ha/config/packages/
```

Riavvia HA o ricarica gli automations.

---

## 2. Collegare Outlook

In Home Assistant:

1. **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**
2. Cerca **Microsoft 365** o **Outlook Calendar**
3. Completa login Microsoft (OAuth)
4. Annota l'`entity_id` del calendario (es. `calendar.outlook`, `calendar.marco_outlook_com`)

In `host/config.local.yaml` sul TOPGRO:

```yaml
ha:
  token: "YOUR_HA_LONG_LIVED_TOKEN"
  calendar:
    entity_id: calendar.outlook   # il tuo entity_id reale
    reminder_minutes: 15
```

Aggiorna anche `homeassistant/packages/karen.yaml`:

- Sostituisci `calendar.outlook` nell'automazione `karen_calendar_reminder` con il tuo entity_id

---

## 3. Promemoria automatici (eventi Outlook)

L'automazione **Karen – Promemoria calendario** annuncia gli eventi **15 minuti prima** dell'inizio.

Per TTS vocale sullo speaker:

1. Configura un `media_player` o `tts` in HA
2. Decommenta la sezione TTS in `script.karen_announce`

---

## 4. Creare eventi vocalmente

Karen usa `calendar.create_event` di Home Assistant:

- Gli eventi creati vocalmente finiscono nel calendario Outlook sincronizzato (se HA ha permessi di scrittura)
- Per promemoria brevi usa intent `reminder` (evento 15 min)

Esempi:

- *"Hey Kira, ricordami domani alle 15 la riunione con Marco"*
- *"Aggiungi al calendario dentista venerdì alle 10"*

---

## 5. Sveglie e timer

Timer e sveglie sono gestiti **localmente sul host Karen** (file `host/data/schedules.json`), non più limitati a una sola entity HA.

### Timer multipli

- Puoi avviare più timer contemporaneamente (es. pasta + forno)
- Comandi: *"timer di 5 minuti"*, *"annulla timer"*, *"annulla tutti i timer"*, *"quali timer ho?"*
- Alla scadenza Karen annuncia via `script.karen_announce` in Home Assistant

### Allarme continuo e dismiss

- Timer e sveglia fanno suonare **beeps alternati** sull'ESP (immediati, senza TTS)
- Per fermare: *"stop"*, *"basta"*, *"si sono sveglio"* (senza wake word)
- Con wake word: *"Hey Kira, stop"*
- Notifica testuale anche su Home Assistant

### Sveglie ricorrenti

- Più sveglie con giorni diversi, es.:
  - *"Sveglia alle 7 lunedì mercoledì e venerdì"*
  - *"Sveglia alle 8 martedì e giovedì"*
- Giorni: 0=lunedì … 6=domenica (anche *feriali*, *weekend*, *tutti i giorni*)
- *"Domani non suonare"* / *"Salta la sveglia domani"* → salta solo domani, la ricorrenza resta
- *"Salta la prossima sveglia"* → salta la prossima occorrenza

### Annuncio in HA

- `script.karen_announce` (campo `message`) — notifica + opzionale TTS sul media player
- Le entity `timer.karen` / `input_datetime.karen_alarm` in HA restano opzionali per automazioni legacy

---

## 6. Test senza voce

```bash
cd ~/karen
KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "timer di tre minuti"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "sveglia alle sette lunedì mercoledì e venerdì"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "domani non suonare la sveglia"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "annulla tutti i timer"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "cosa ho in calendario domani"
```

---

## Roadmap (non ancora implementato)

- Sveglie one-shot con data specifica (senza ricorrenza)
- Scrittura bidirezionale avanzata Outlook (serie, invitati)
- Annuncio promemoria direttamente su ESP32 (oggi via HA)
