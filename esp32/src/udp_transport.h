#pragma once
#include "esp_err.h"
#include "config.h"
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

esp_err_t udp_transport_init(void);

bool udp_send_audio(const int16_t *audio_pcm16, size_t samples, uint16_t seq);
bool udp_send_end_of_audio(void);

/** Reset buffer per una nuova risposta audio dal Jetson. */
void udp_response_reset(void);

/** Abilita la ricezione risposta (chiamare prima di WAITING_RESPONSE). */
void udp_response_arm(void);

/** Disabilita la ricezione risposta. */
void udp_response_disarm(void);

bool udp_response_is_complete(void);
uint16_t udp_response_last_seq(void);
bool udp_response_slot_valid(uint16_t seq);
const int16_t *udp_response_slot_data(uint16_t seq, uint16_t *nsamples);
size_t udp_response_count_valid(void);
size_t udp_response_packets_received(void);

/** Attende un nuovo pacchetto (o END) dal task RX. */
bool udp_response_wait_event(uint32_t timeout_ms);

bool udp_ring_is_active(void);
bool udp_ring_listen_active(void);
void udp_ring_set_listen(bool enable);
bool udp_ring_pending(void);
bool udp_ring_stop_pending(void);
void udp_ring_clear_pending(void);
void udp_ring_clear_stop(void);

void udp_transport_deinit(void);

#ifdef __cplusplus
}
#endif
