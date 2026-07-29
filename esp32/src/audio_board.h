#pragma once

#include "esp_err.h"
#include "config.h"
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Inizializza I2C, TCA9555 (amplificatore), I2S full-duplex,
 * codec ES8311 (speaker) e ES7210 (dual-mic).
 */
esp_err_t audio_board_init(void);

/** Abilita/disabilita l'amplificatore NS4150 via TCA9555. */
void audio_board_pa_enable(bool enable);

/** Imposta il volume speaker (0–100). */
esp_err_t audio_board_set_volume(int volume);

/**
 * Riconfigura l'uscita speaker a un nuovo sample rate (es. 22050 per Piper TTS).
 * Sospende il microfono sul bus I2S condiviso durante il cambio rate.
 */
esp_err_t audio_board_set_playback_rate(uint32_t sample_rate);

/** Prepara lo speaker per playback TTS. */
esp_err_t audio_board_begin_playback(void);

/** Ripristina stato normale dopo il playback. */
esp_err_t audio_board_end_playback(void);

/** true mentre il playback TTS è in corso. */
bool audio_board_is_playback_active(void);

/** Durante ring: microfono attivo anche con speaker (per dismiss senza wake word). */
void audio_board_set_duplex_mic(bool enable);

/** Ripristina microfono/I2S RX dopo errori o sessioni bloccate. */
esp_err_t audio_board_recover_input(void);

/** Breve tono di conferma wake word (~100 ms). */
esp_err_t audio_board_play_ack_tone(void);

/** Doppio bip breve al wake word (non blocca il task audio). */
void audio_board_wake_ack(void);

/** Avvia allarme sonoro locale (beeps alternati) fino a audio_board_alarm_stop(). */
esp_err_t audio_board_alarm_start(void);

/** Ferma l'allarme sonoro. */
void audio_board_alarm_stop(void);

bool audio_board_alarm_active(void);

/**
 * Legge campioni dal microfono ES7210 (TDM 4 canali).
 * @param tdm_out   buffer di uscita (4 × samples int16)
 * @param samples   campioni per canale
 * @return numero di campioni per canale letti, -1 su errore
 */
int audio_board_mic_read(int16_t *tdm_out, size_t samples);

/**
 * Scrive campioni PCM mono sullo speaker ES8311 (duplicati su stereo).
 * @return campioni mono scritti, -1 su errore
 */
int audio_board_spk_write(const int16_t *mono, size_t samples);

/** Flush buffer TX speaker. */
void audio_board_spk_flush(void);

#ifdef __cplusplus
}
#endif
