#pragma once

#include "esp_err.h"
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t status_led_init(void);

/** Anello verde acceso per tutta la fase di ascolto comando. */
void status_led_listening_on(void);

/** Spegne l'anello a fine ascolto / ritorno idle. */
void status_led_listening_off(void);

bool status_led_available(void);

#ifdef __cplusplus
}
#endif
