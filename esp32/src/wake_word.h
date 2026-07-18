#pragma once
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "config.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Inizializza il motore WakeNet (ESP-SR v2).
 * Carica i modelli dalla partizione SPIFFS "srmodel".
 * @return ESP_OK in caso di successo.
 */
esp_err_t wake_word_init(void);

/**
 * Alimenta l'AFE con un frame audio e controlla se il wake word è rilevato.
 * La dimensione del frame richiesta è quella restituita da get_feed_chunksize();
 * può essere interrogata dopo wake_word_init() tramite wake_word_get_chunksize().
 *
 * @param audio     campioni PCM 16-bit @ 16kHz
 * @param samples   numero di campioni (deve corrispondere al chunksize AFE)
 * @return true se "Ehi Karen" / wake word è stato rilevato
 */
bool wake_word_process(const int16_t *audio, size_t samples);

/**
 * Svuota il buffer AFE (chiamare all'inizio della registrazione).
 */
void wake_word_reset(void);

/**
 * Abilita/disabilita il fetch AFE (disattivare durante registrazione/playback).
 */
void wake_word_set_active(bool active);

/**
 * Restituisce il numero di campioni per frame richiesto dall'AFE.
 * Chiamare DOPO wake_word_init().
 */
int  wake_word_get_chunksize(void);

/**
 * Rilascia le risorse del motore wake word.
 */
void wake_word_deinit(void);

/**
 * Restituisce il nome del modello wake word in uso.
 */
const char *wake_word_get_model_name(void);

#ifdef __cplusplus
}
#endif
