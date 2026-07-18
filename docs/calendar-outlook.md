# Karen – Timer, sveglie e calendario Outlook

## Cosa può fare Karen oggi

| Comando vocale | Intent | Dove |
|----------------|--------|------|
| "Timer di 5 minuti" | `timer` | HA `timer.karen` |
| "Annulla il timer" | `timer` (cancel) | HA |
| "Sveglia alle 7:30" | `alarm` | HA `input_datetime.karen_alarm` |
| "A che ora suona la sveglia?" | `alarm` (status) | HA |
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

### Timer

- Entity: `timer.karen`
- Formato durata corretto: `HH:MM:SS` (fix applicato nel codice)

### Sveglia

- Entity: `input_datetime.karen_alarm` (ora giornaliera)
- Karen attiva automaticamente `input_boolean.karen_active` quando imposti una sveglia
- Automazione giornaliera → `script.karen_announce`

Limiti attuali:

- **Una sveglia** alla volta (stesso orario ogni giorno)
- Per sveglie multiple o date specifiche → usa eventi calendario

---

## 6. Test senza voce

```bash
cd ~/karen
KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "timer di tre minuti"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "sveglia alle sette e mezza"

KAREN_PROFILE=topgro host/venv/bin/python scripts/test_pipeline.py \
  --profile topgro --text "cosa ho in calendario domani"
```

---

## Roadmap (non ancora implementato)

- Sveglie one-shot con data specifica
- Timer multipli
- Scrittura bidirezionale avanzata Outlook (serie, invitati)
- Annuncio promemoria direttamente su ESP32 (oggi via HA)
