# Musica con Jarvis — setup Music Assistant + Navidrome

Jarvis **non riproduce musica sull'ESP32** (solo voce/TTS). I comandi vocali passano da TOPGRO → Home Assistant → **Music Assistant** → **Navidrome** → altoparlante configurato (PC, Chromecast, ecc.).

## Architettura

```
"Jarvis, riproduci Gli anni di Max Pezzali"
        │
        ▼
   ESP32 (mic/speaker TTS)
        │ UDP
        ▼
   TOPGRO — music_skill → HA REST media_player.play_media
        │
        ▼
   Home Assistant (192.168.1.67)
        │
        ▼
   Music Assistant — cerca in Navidrome
        │
        ▼
   media_player.* (PC, salotto, …)
```

## Prerequisiti (già presenti sul Mini PC)

- **Home Assistant** — container `homeassistant`
- **Navidrome** — container `navidrome` (libreria musicale locale)

Verifica Navidrome: apri `http://192.168.1.67:4533` e controlla che ci siano album/artisti indicizzati.

---

## Perché non vedi "Add-on" in Home Assistant

Hai **Home Assistant Container** (Docker), non Home Assistant OS:

| Installazione | Add-on Store |
|---------------|--------------|
| **HA OS** (Raspberry Pi, VM dedicata) | ✅ Sì |
| **HA Supervised** | ✅ Sì |
| **HA Container** (il tuo caso: `ghcr.io/home-assistant/home-assistant:stable`) | ❌ No |

Gli Add-on sono container gestiti solo da HA OS. Con Docker devi avviare **Music Assistant come container separato** (come Navidrome e Jellyfin) e collegarlo tramite **integrazione** in HA.

---

## 1. Installare Music Assistant (Docker — il tuo caso)

Sul Mini PC (`192.168.1.67`), nella struttura `barossi-home`:

```bash
mkdir -p ~/repos/barossi-home/media-music-assistant/data
```

Copia il compose da questo repo (`homeassistant/docker/music-assistant/docker-compose.yml`) oppure crea il file lì con:

```yaml
services:
  music-assistant-server:
    image: ghcr.io/music-assistant/server:latest
    container_name: music-assistant-server
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./data:/data
    cap_add:
      - SYS_ADMIN
      - DAC_READ_SEARCH
    security_opt:
      - apparmor:unconfined
    environment:
      - LOG_LEVEL=info
      - TZ=Europe/Rome
```

Avvia:

```bash
cd ~/repos/barossi-home/media-music-assistant
docker compose up -d
```

Verifica: apri **http://192.168.1.67:8095** — deve comparire l’interfaccia Music Assistant.

> `network_mode: host` è **obbligatorio** (discovery player e streaming). Stesso motivo per cui HA usa già `network_mode: host`.

### Collegare HA a Music Assistant

1. In HA: **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**
2. Cerca **Music Assistant**
3. URL server: **`http://127.0.0.1:8095`** (HA e MA sono sullo stesso host, entrambi in host network)
4. Completa la configurazione

Dopo l’integrazione compariranno entity `media_player.*` in HA.

### Opzione solo su HA OS (non il tuo caso)

Se un giorno migrassi a Home Assistant OS, potresti usare **Impostazioni → Add-on**. Con Container usa sempre il metodo Docker sopra.

---

## 2. Collegare Navidrome a Music Assistant

Navidrome **non compare con il suo nome** nell’elenco. Devi aggiungere:

### **OpenSubsonic Media Server Library**

(in italiano potrebbe restare in inglese; cerca **OpenSubsonic** o **Open Subsonic**)

1. **Impostazioni → Provider musicali** (o *Music sources*) → **Aggiungi un nuovo provider**
2. Nella lista cerca **OpenSubsonic Media Server Library**  
   - Descrizione tipica: *"Stream music from your OpenSubsonic compatible server"*
   - **Non** confonderlo con “Subsonic” generico: serve l’API **Open Subsonic** (Navidrome la supporta)
3. Parametri per il tuo Navidrome:

| Campo | Valore |
|-------|--------|
| Base URL | `http://127.0.0.1` |
| Port | `4533` |
| Server Path | *(lascia vuoto)* |
| Username | utente Navidrome |
| Password | password Navidrome |

4. **Salva** → attendi la sincronizzazione libreria

Verifica Navidrome: apri `http://192.168.1.67:4533` e controlla che ci siano album indicizzati.

### Se non trovi OpenSubsonic nella lista

- Usa la **barra di ricerca** nel dialogo “Aggiungi provider” e digita `open`
- Controlla i filtri in alto (tipo **Musica** / **Music**)
- In alternativa, provider **Filesystem** / **Cartella locale**: punta alla stessa cartella montata in Navidrome (`/mnt/external-media/music` sul Mini PC) — MA indicizza i file direttamente, senza passare da Navidrome

---

## 3. Configurare un player (dove suona la musica)

In **Impostazioni** (icona ingranaggio), l’interfaccia italiana usa questi nomi:

| Inglese (documentazione) | Italiano in Music Assistant |
|--------------------------|-----------------------------|
| Settings | **Impostazioni** |
| Music providers | **Provider musicali** |
| Player providers | **Lettore provider** ← spesso confuso con “Provider musicali” |
| Players | **Lettori** |
| Plugin providers | **Plugin providers** (di solito resta in inglese) |
| Add a new provider | **Aggiungi un nuovo provider** / **Aggiungi nuovo** |

Sotto **Impostazioni** dovresti vedere due sezioni distinte:
- *"Gestisci le tue fonti musicali, i servizi di streaming e le integrazioni"* → **Provider musicali** (Navidrome va qui)
- *"Configura e gestisci i tuoi dispositivi di output audio"* → **Lettori** / **Lettore provider**

Se non trovi “Player providers”, cerca **Lettore provider** oppure apri direttamente:
`http://192.168.1.67:8095/#/settings/playerproviders`

### Opzione A — Musica dalle casse del Mini PC

**Non cercarlo in “Aggiungi provider”.** Il provider si chiama **Local Audio Out** (nome in inglese anche con UI italiana), è **integrato di serie** e compare già in **Impostazioni → Lettore provider** nella lista provider, non nel dialogo “Aggiungi”.

1. **Docker:** il container deve vedere l’audio dell’host. Nel `docker-compose.yml` servono almeno:
   ```yaml
   devices:
     - /dev/snd:/dev/snd
   group_add:
     - "29"   # gid del gruppo audio (verifica con: getent group audio)
   ```
   Poi: `docker compose up -d` (ricrea il container).
2. In MA: **Impostazioni → Lettore provider → Local Audio Out** → **Ricarica** (icona refresh).
3. In **Lettori** dovrebbero comparire le uscite ALSA del Mini PC (una per scheda/canale).
4. Se i log dicono `No local audio output devices found`, il container non vede `/dev/snd` o la scheda è occupata da un altro processo.

**Alternativa immediata (già funzionante):** il player **Web (Sendspin)** — apri l’UI MA nel browser e riproduci da lì; l’audio esce dalle casse del PC che usa il browser, non dal server headless.

**Filtro “Stadio” nel dialogo Aggiungi provider:** provider sperimentali (es. AirPlay receiver) compaiono solo se nel filtro **Stadio** selezioni anche **Alpha** o **Beta**. Local Audio Out non è lì perché è già preinstallato.

**Nessun suono su ALC897 Analog?** Controlla il mixer ALSA dell’host: spesso **Master** è a 0% e **spento** (muto), anche se Headphone/Front sono al 100%. Il compose include un servizio `alsa-init` che all’avvio esegue:
```bash
amixer -c 1 sset Master 100% unmute
amixer -c 1 cset name='Auto-Mute Mode' Disabled
```
Verifica anche che le casse siano collegate al jack **Line Out** (verde) della scheda madre, non a HDMI.

**Volume basso?** Il jack analogico della scheda madre è un’uscita **line-level** (~2 V): va bene per cuffie o casse amplificate, ma non riempie una stanza con piccoli speaker passivi. Soluzioni:
- alza **Master** ALSA al 100% (lo fa `alsa-init` all’avvio);
- in MA, volume del lettore **ALC897 Analog** al massimo;
- usa **casse amplificate** (con alimentazione propria) o un piccolo amplificatore tra PC e speaker;
- in **Local Audio Out → Volume control mode** imposta **Disabled** se il controllo volume di MA non risponde (il container non ha `amixer`, quindi il volume hardware via UI può non aggiornare la scheda).

### Opzione B — Musica su dispositivi Home Assistant

Richiede **due passaggi** (prima il plugin, poi i player):

1. **Impostazioni → Plugin providers → Aggiungi nuovo**
   - **Home Assistant** (plugin) → URL `http://127.0.0.1:8123` + token HA long-lived
2. **Impostazioni → Lettore provider → Aggiungi nuovo**
   - **Home Assistant Media Players** → seleziona i `media_player` da usare

Altri provider comuni (nomi spesso in inglese nel menu): **Snapcast**, **Google Cast**, **AirPlay**.

3. In **Lettori** verifica che il dispositivo sia **abilitato** e prova riproduzione manuale.

---

## 4. Trovare l’entity_id in Home Assistant

1. **Impostazioni → Dispositivi e servizi → Entità**
2. Filtra `media_player`
3. Copia l’ID del player Music Assistant, es.:
   - `media_player.hd_audio_generic_alc897_analog_hw_10` (Local Audio Out / Mini PC)
   - `media_player.music_assistant` (nome generico, se presente)

Test manuale in **Strumenti per sviluppatori → Servizi**:

```yaml
service: media_player.play_media
target:
  entity_id: media_player.hd_audio_generic_alc897_analog_hw_10
data:
  media_content_id: "Gli anni Max Pezzali"
  media_content_type: music
```

Se parte la musica, la catena HA → MA → Navidrome funziona.

---

## 5. Configurare Jarvis (TOPGRO)

In `host/config.local.yaml` (o merge con `base.yaml`):

```yaml
ha:
  entities:
    media_player: media_player.hd_audio_generic_alc897_analog_hw_10

music:
  media_player: media_player.hd_audio_generic_alc897_analog_hw_10
  player_name: "casa"          # nome usato in TTS ("su casa")
  content_type: music
```

Riavvia Jarvis (richiede servizio attivo; vedi [setup-guide.md](setup-guide.md) per linger):

```bash
systemctl --user restart karen-topgro
```

---

## 6. Comandi vocali supportati

| Esempio | Tipo ricerca |
|---------|----------------|
| *Riproduci Gli anni di Max Pezzali* | brano |
| *Riproduci musica degli 883* | artista |
| *Riproduci musica pop* | genere |
| *Riproduci l'album Hit Mania Dance Estate 2003* | album |
| *Ferma la musica* | stop |
| *Pausa la musica* | pausa |

Jarvis risponde con TTS sull’ESP32 (*"Ok, metto … su casa"*) e la musica esce dal **player HA**, non dal Waveshare.

---

## 7. Test senza ESP32

Sul TOPGRO:

```bash
cd ~/karen/host
source venv/bin/activate
python3 - << 'PY'
import asyncio
from karen.config_loader import load_config
from karen.skills.music_skill import parse_music_intent, MusicSkill

for phrase in [
    "riproduci gli anni di max pezzali",
    "riproduci musica degli 883",
    "riproduci musica pop",
    "riproduci l album hit mania dance estate 2003",
    "ferma la musica",
]:
    print(phrase, "→", parse_music_intent(phrase))

async def main():
    cfg = load_config()
    skill = MusicSkill(cfg)
    intent = parse_music_intent("riproduci musica pop")
    print(await skill.execute({**intent, "response_it": ""}))

asyncio.run(main())
PY
```

---

## Script HA opzionale

In `homeassistant/packages/karen.yaml` c’è `script.karen_play_music` per testare da HA o automazioni.

---

## Alternative: Jellyfin

Sul Mini PC c’è già **Jellyfin**. Puoi:

1. Integrare Jellyfin in HA (HACS / integrazione ufficiale)
2. Usare il `media_player` Jellyfin al posto di Music Assistant
3. Impostare lo stesso `music.media_player` in config Karen

Music Assistant + Navidrome resta la scelta migliore per ricerca vocale su libreria MP3/flac locale.

---

## Troubleshooting

| Problema | Verifica |
|----------|----------|
| *"Non ho un player musicale configurato"* | `music.media_player` in config + entity esiste in HA |
| Jarvis risponde OK ma silenzio | Test servizio `play_media` in HA; player online in MA |
| Brano sbagliato | Libreria Navidrome incompleta; rinomina file/tag ID3 |
| Nessun menu **Add-on** in HA | Normale con Container — usa Docker (sezione 1) |
| Nessun `media_player` in HA | MA non installato o integrazione HA non completata |

Log Jarvis: `~/karen/host/karen.log` — cerca `Musica →`.
