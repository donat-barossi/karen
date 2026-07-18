#pragma once

#include "esp_err.h"
#include "config.h"
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Inizializza I2C, I2S, codec ES8311/ES7210 e amplificatore. */
esp_err_t i2s_audio_init(void);

/**
 * Legge campioni dual-mic interleaved (MIC1, MIC2) per ESP-SR AFE.
 * @return campioni per canale, -1 su errore
 */
int i2s_mic_read_dual(int16_t *stereo_out, size_t samples);

/**
 * Legge campioni mono (MIC1) per streaming UDP.
 * @return campioni mono, -1 su errore
 */
int i2s_mic_read_mono(int16_t *mono_out, size_t samples);

/** Riconfigura speaker a SPK_SAMPLE_RATE (22050 Hz) prima della riproduzione. */
esp_err_t i2s_spk_begin_playback(void);

/** Ripristina sample rate a 16 kHz dopo la riproduzione. */
esp_err_t i2s_spk_end_playback(void);

/** Scrive campioni mono 16-bit sullo speaker. */
int i2s_spk_write(const int16_t *buf, size_t samples, uint32_t ms_wait);

/** Flush buffer TX speaker. */
void i2s_spk_flush(void);

/** Imposta volume speaker (0–100). */
esp_err_t i2s_set_volume(int volume);

#ifdef __cplusplus
}
#endif
