#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Inizializza il logger remoto (dopo udp_transport_init). */
void remote_log_init(void);

/** Invia una riga di log al host (UDP PKT_TYPE_LOG). Ignorato se Wi-Fi assente. */
void remote_log_send(const char *line);

/** Formatta e invia (max REMOTE_LOG_MAX_LEN caratteri). */
void remote_log_printf(const char *fmt, ...);

/** Heartbeat periodico: stato, Wi-Fi, heap, uptime, errori TX. */
void remote_log_heartbeat(int state, bool wifi, bool ww_active,
                          uint32_t tx_fail, uint32_t mic_rms);

#ifdef __cplusplus
}
#endif
