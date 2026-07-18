# Cablaggio Hardware – Waveshare ESP32-S3 AI Smart Speaker Board

## Scheda

**Prodotto:** Waveshare ESP32-S3-AUDIO-Board (ESP32-S3R8, 16 MB Flash, 8 MB PSRAM)

Componenti audio integrati:
- **ES7210** – ADC, array dual-mic con noise reduction
- **ES8311** – codec DAC per lo speaker
- **NS4150** – amplificatore Class-D 3 W (abilitato via TCA9555)
- **TCA9555** – expander I2C per GPIO esterni (PA, pulsanti)

> **Nota:** la scheda richiede una batteria Li-ion 3.7 V con connettore MX1.25 (non inclusa). Può essere alimentata anche via USB-C.

---

## Pinout audio (integrato, nessun cablaggio esterno)

| Segnale | GPIO | Dispositivo |
|---------|------|-------------|
| I2C SCL | 10 | ES8311, ES7210, TCA9555 |
| I2C SDA | 11 | ES8311, ES7210, TCA9555 |
| I2S MCLK | 12 | Bus audio condiviso |
| I2S BCLK | 13 | Bus audio condiviso |
| I2S LRCK | 14 | Bus audio condiviso |
| I2S DIN | 15 | ES7210 → ESP32 (microfono) |
| I2S DOUT | 16 | ESP32 → ES8311 (speaker) |
| BOOT | 0 | Pulsante trigger fallback |
| WS2812 RGB | 38 | 7 LED (non usati dal firmware Karen) |

### Indirizzi I2C

| Chip | Indirizzo | Funzione |
|------|-----------|----------|
| ES8311 | 0x18 | DAC speaker |
| ES7210 | 0x40 | ADC dual-mic |
| TCA9555 | 0x20 | IO expander (PA su EXIO8) |

---

## Schema audio

```
                    ┌─────────────────────────────┐
                    │  Waveshare ESP32-S3-AUDIO   │
                    │                             │
  Dual Mic Array ──►│  ES7210 (ADC)               │
                    │    I2S DIN ← GPIO15         │
                    │    I2C ← GPIO10/11          │
                    │                             │
                    │  ES8311 (DAC)               │
                    │    I2S DOUT → GPIO16        │
                    │    I2C ← GPIO10/11          │
                    │         │                   │
                    │  TCA9555 EXIO8 ──► NS4150   │
                    │         │                   │
                    │      Speaker integrato      │
                    └─────────────────────────────┘
                              │
                              │ UDP Wi-Fi
                              ▼
                    ┌─────────────────────────────┐
                    │     Jetson Orin Nano        │
                    │  Whisper → LLM → Piper TTS  │
                    └─────────────────────────────┘
```

---

## Configurazione in `config.h`

```cpp
// I2C
#define I2C_SCL_GPIO        GPIO_NUM_10
#define I2C_SDA_GPIO        GPIO_NUM_11

// I2S full-duplex
#define I2S_MCLK_GPIO       GPIO_NUM_12
#define I2S_BCLK_GPIO       GPIO_NUM_13
#define I2S_LRCK_GPIO       GPIO_NUM_14
#define I2S_DIN_GPIO        GPIO_NUM_15
#define I2S_DOUT_GPIO       GPIO_NUM_16

// Amplificatore via TCA9555
#define TCA9555_PA_PIN      IO_EXPANDER_PIN_NUM_8
```

---

## Setup precedente (rimosso)

Il vecchio cablaggio con **INMP441** + **MAX98357A** su DevKit ESP32-S3 non è più necessario. Tutto l'audio è integrato sulla Waveshare.
