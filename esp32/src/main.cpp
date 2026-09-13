/**
 * Karen – ESP32-S3 Main
 * Waveshare ESP32-S3 AI Smart Speaker Board
 *
 * Macchina a stati:
 *   IDLE → LISTENING → WAITING_RESPONSE → SPEAKING → IDLE
 *   IDLE → (START_RING) → WAITING_RESPONSE → SPEAKING → RINGING → …
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_log.h"
#include "esp_event.h"
#include "esp_system.h"
#include "nvs_flash.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "driver/gpio.h"

#include "config.h"
#include "i2s_audio.h"
#include "wake_word.h"
#include "udp_transport.h"
#include "audio_board.h"
#include "status_led.h"
#include "remote_log.h"

static const char *TAG = "karen_main";

typedef enum {
    STATE_IDLE,
    STATE_LISTENING,
    STATE_WAITING_RESPONSE,
    STATE_SPEAKING,
    STATE_RINGING,
} karen_state_t;

static volatile karen_state_t s_state = STATE_IDLE;
static bool s_ww_available = false;
static volatile bool s_session_abort = false;
static volatile bool s_listen_reset = false;
static TickType_t s_state_since = 0;
static TickType_t s_wake_cooldown_until = 0;
static uint32_t s_mic_fail_streak = 0;

#define WIFI_CONNECTED_BIT BIT0
static EventGroupHandle_t s_wifi_events;
static bool s_udp_ready = false;
static bool s_remote_log_ready = false;
static volatile uint32_t s_idle_mic_rms = 0;

static bool karen_wifi_connected(void);

static const char *reset_reason_str(esp_reset_reason_t reason)
{
    switch (reason) {
    case ESP_RST_POWERON:   return "poweron";
    case ESP_RST_BROWNOUT:  return "brownout";
    case ESP_RST_SW:        return "software";
    case ESP_RST_PANIC:     return "panic";
    case ESP_RST_INT_WDT:   return "int_wdt";
    case ESP_RST_TASK_WDT:  return "task_wdt";
    case ESP_RST_WDT:       return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    default:                return "other";
    }
}

static esp_err_t karen_ensure_udp_ready(void)
{
    if (s_udp_ready)
        return ESP_OK;
    if (!karen_wifi_connected())
        return ESP_ERR_INVALID_STATE;

    esp_err_t err = udp_transport_init();
    if (err != ESP_OK)
        return err;

    s_udp_ready = true;
    if (!s_remote_log_ready) {
        remote_log_init();
        s_remote_log_ready = true;
    }
    return ESP_OK;
}

static bool karen_wait_for_wifi(uint32_t timeout_ms)
{
    if (karen_wifi_connected())
        return true;
    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_events, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE,
        pdMS_TO_TICKS(timeout_ms));
    return (bits & WIFI_CONNECTED_BIT) != 0;
}

static void karen_note_state(karen_state_t st)
{
    if (s_state != st) {
        karen_state_t prev = s_state;
        s_state = st;
        s_state_since = xTaskGetTickCount();
        remote_log_printf("state %d->%d", (int)prev, (int)st);
    }
}

static uint32_t karen_state_elapsed_ms(void)
{
    return (uint32_t)((xTaskGetTickCount() - s_state_since) * portTICK_PERIOD_MS);
}

static void karen_ring_phase_reset(void);
static void karen_force_idle(const char *reason);

static void karen_wake_start_cooldown(uint32_t ms)
{
    s_wake_cooldown_until = xTaskGetTickCount() + pdMS_TO_TICKS(ms);
}

static bool karen_wake_in_cooldown(void)
{
    return xTaskGetTickCount() < s_wake_cooldown_until;
}

static void karen_wake_word_enable(bool hard_reset)
{
    if (!s_ww_available)
        return;
    audio_board_set_duplex_mic(false);
    if (hard_reset) {
        audio_board_recover_input();
        if (wake_word_reinit() != ESP_OK)
            wake_word_reset();
    } else {
        wake_word_reset();
    }
    wake_word_set_active(true);
}

static void karen_wake_word_enable_after_session(void)
{
    if (!s_ww_available)
        return;
    audio_board_set_duplex_mic(false);
    audio_board_recover_input();
    vTaskDelay(pdMS_TO_TICKS(WAKE_POST_TTS_MS));
    wake_word_reset();
    wake_word_set_active(true);
}

static void karen_wake_word_disable(void)
{
    if (!s_ww_available)
        return;
    wake_word_set_active(false);
}

static void karen_ring_phase_reset(void)
{
    udp_ring_set_listen(false);
}

static void karen_stop_ring_soft(const char *reason)
{
    ESP_LOGI(TAG, "STOP_RING (%s)", reason);
    audio_board_alarm_stop();
    udp_listen_again_clear();
    udp_ring_set_listen(false);
    karen_ring_phase_reset();
    audio_board_set_duplex_mic(false);
    audio_board_recover_input();
    status_led_listening_off();
    if (s_state == STATE_RINGING || s_state == STATE_WAITING_RESPONSE ||
        s_state == STATE_SPEAKING) {
        if (s_state == STATE_WAITING_RESPONSE || s_state == STATE_SPEAKING)
            s_session_abort = true;
        karen_note_state(STATE_IDLE);
    }
    if (s_ww_available) {
        karen_wake_word_enable_after_session();
    }
}

static void karen_force_idle(const char *reason)
{
    karen_state_t prev = s_state;
    ESP_LOGW(TAG, "Recovery → IDLE (%s)", reason);
    remote_log_printf("recovery: %s", reason);
    s_session_abort = true;
    if (prev == STATE_LISTENING || prev == STATE_RINGING)
        udp_send_end_of_audio();
    i2s_spk_end_playback();
    audio_board_alarm_stop();
    udp_response_reset();
    udp_response_disarm();
    audio_board_set_duplex_mic(false);
    karen_ring_phase_reset();
    if (s_ww_available) {
        karen_wake_word_enable_after_session();
    }
    audio_board_recover_input();
    status_led_listening_off();
    karen_note_state(STATE_IDLE);
    s_mic_fail_streak = 0;
}

static void karen_abort_listen_idle(const char *reason)
{
    ESP_LOGI(TAG, "%s", reason);
    status_led_listening_off();
    udp_send_end_of_audio();
    udp_response_disarm();
    audio_board_set_duplex_mic(false);
    audio_board_recover_input();
    karen_note_state(STATE_IDLE);
    karen_wake_word_enable_after_session();
}

static void karen_begin_listening(void)
{
    status_led_listening_on();
    audio_board_set_duplex_mic(false);
    udp_response_arm();
    karen_note_state(STATE_LISTENING);
}

// ── Wi-Fi ────────────────────────────────────────────────────────────────────

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t event_id, void *data)
{
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnesso, riprovo…");
        remote_log_send("wifi disconnected");
        esp_wifi_connect();
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&event->ip_info.ip));
        remote_log_printf("wifi ip " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(s_wifi_events, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init(void)
{
    s_wifi_events = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_t inst_any_id, inst_got_ip;
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, &inst_any_id));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, &inst_got_ip));

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());

    EventBits_t bits = xEventGroupWaitBits(s_wifi_events,
                                           WIFI_CONNECTED_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(15000));
    if (bits & WIFI_CONNECTED_BIT) {
        ESP_LOGI(TAG, "Wi-Fi connesso");
        esp_wifi_set_ps(WIFI_PS_NONE);
        esp_wifi_set_max_tx_power(52);
    } else
        ESP_LOGE(TAG, "Wi-Fi: connessione fallita (riprova in background)");
}

// ── VAD basato su RMS ────────────────────────────────────────────────────────

static uint32_t compute_rms(const int16_t *buf, size_t len)
{
    int64_t sum = 0;
    for (size_t i = 0; i < len; i++) sum += (int64_t)buf[i] * buf[i];
    return (uint32_t)(sum / (int64_t)len);
}

static uint32_t compute_mic1_rms(const int16_t *dual, int samples)
{
    if (samples <= 0)
        return 0;
    int64_t sum = 0;
    for (int i = 0; i < samples; i++) {
        int32_t s = dual[i * 2];
        sum += (int64_t)s * s;
    }
    return (uint32_t)(sum / samples);
}

static void karen_ambient_rms_update(uint32_t *ema, uint32_t frame_rms)
{
    if (*ema > frame_rms * 8 && frame_rms <= WAKE_AMBIENT_TRACK_MAX) {
        *ema = frame_rms;
        return;
    }
    if (frame_rms <= WAKE_AMBIENT_TRACK_MAX) {
        *ema = (*ema * 15 + frame_rms) / 16;
        return;
    }
    if (frame_rms <= WAKE_AMBIENT_GATE_RMS)
        *ema = (*ema * 63 + frame_rms) / 64;
}

static bool karen_wifi_connected(void)
{
    if (!s_wifi_events)
        return false;
    return (xEventGroupGetBits(s_wifi_events) & WIFI_CONNECTED_BIT) != 0;
}

// ── Task riproduzione risposta ───────────────────────────────────────────────

static void supervisor_task(void *arg)
{
    (void)arg;
    uint32_t hb_ms = 0;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(SUPERVISOR_INTERVAL_MS));
        hb_ms += SUPERVISOR_INTERVAL_MS;

        if (!karen_wifi_connected() && !s_udp_ready) {
            karen_ensure_udp_ready();
        }

        if (!karen_wifi_connected() &&
            (s_state == STATE_LISTENING || s_state == STATE_WAITING_RESPONSE ||
             s_state == STATE_SPEAKING)) {
            karen_force_idle("Wi-Fi perso durante sessione");
        }

        if (hb_ms >= REMOTE_LOG_HEARTBEAT_MS) {
            hb_ms = 0;
            remote_log_heartbeat(
                (int)s_state,
                karen_wifi_connected(),
                s_ww_available && wake_word_is_active(),
                udp_get_tx_fail_count(),
                s_idle_mic_rms);
        }

        switch (s_state) {
        case STATE_LISTENING:
            if (karen_state_elapsed_ms() > STATE_LISTENING_MAX_MS)
                karen_force_idle("timeout LISTENING");
            break;
        case STATE_WAITING_RESPONSE:
            if (karen_state_elapsed_ms() > STATE_WAITING_MAX_MS)
                karen_force_idle("timeout WAITING_RESPONSE");
            break;
        case STATE_SPEAKING:
            if (karen_state_elapsed_ms() > STATE_SPEAKING_MAX_MS)
                karen_force_idle("timeout SPEAKING");
            break;
        case STATE_RINGING:
            if (!udp_ring_is_active())
                karen_force_idle("ring non attivo (host)");
            else if (karen_state_elapsed_ms() > STATE_RINGING_STUCK_MS)
                karen_force_idle("timeout RINGING (recovery wake word)");
            break;
        default:
            if (s_state == STATE_IDLE && s_ww_available && !wake_word_is_active())
                karen_wake_word_enable(false);
            break;
        }

        if (udp_ring_stop_pending()) {
            udp_ring_clear_stop();
            karen_stop_ring_soft("host");
        } else if (s_state != STATE_IDLE &&
                   gpio_get_level(WAKE_BUTTON_GPIO) == 0) {
            static uint32_t cancel_ms = 0;
            cancel_ms += SUPERVISOR_INTERVAL_MS;
            if (cancel_ms >= 500) {
                cancel_ms = 0;
                karen_force_idle("BOOT annulla sessione");
            }
        } else if (udp_ring_pending()) {
            if (s_state == STATE_IDLE) {
                udp_ring_clear_pending();
                audio_board_alarm_start();
                audio_board_set_duplex_mic(true);
                karen_ring_phase_reset();
                karen_note_state(STATE_RINGING);
                if (s_ww_available) {
                    wake_word_set_active(true);
                    wake_word_reset();
                }
                ESP_LOGI(TAG, "Ring: beep (jarvis o BOOT per fermare)");
            } else {
                udp_ring_clear_pending();
            }
        } else if (udp_push_play_pending() && s_state == STATE_IDLE) {
            udp_push_play_clear();
            karen_wake_word_disable();
            karen_note_state(STATE_WAITING_RESPONSE);
            ESP_LOGI(TAG, "Annuncio host: avvio playback…");
        }
    }
}

static bool playback_stream(volatile bool *abort)
{
    uint16_t next_seq = 0;
    bool spk_open = false;
    bool got_any = false;
    uint32_t idle_ms = 0;
    const uint32_t first_pkt_timeout_ms = RESPONSE_FIRST_TIMEOUT_MS;

    while (!(*abort)) {
        if (udp_playback_abort_pending())
            *abort = true;
        if (*abort)
            break;

        while (udp_response_slot_valid(next_seq)) {
            if (!spk_open) {
                if (i2s_spk_begin_playback() != ESP_OK)
                    return false;
                spk_open = true;
                got_any = true;
                idle_ms = 0;
                ESP_LOGI(TAG, "Stream avviato (seq=%u)", next_seq);
            }

            uint16_t ns = 0;
            const int16_t *data = udp_response_slot_data(next_seq, &ns);
            if (data && ns > 0) {
                int written = i2s_spk_write(data, ns, 0);
                if (written <= 0)
                    ESP_LOGW(TAG, "spk_write fallito seq=%u", next_seq);
            }
            next_seq++;
            idle_ms = 0;
        }

        if (udp_response_is_complete() && next_seq > udp_response_last_seq())
            break;

        uint32_t wait_ms = spk_open ? STREAM_GAP_TIMEOUT_MS : 50;
        if (!spk_open && idle_ms >= first_pkt_timeout_ms) {
            ESP_LOGW(TAG, "Timeout attesa prima risposta Jetson");
            remote_log_send("playback timeout no_response");
            break;
        }

        if (spk_open && udp_response_is_complete() &&
            next_seq <= udp_response_last_seq()) {
            if (idle_ms >= STREAM_GAP_TIMEOUT_MS) {
                ESP_LOGW(TAG, "Skip seq=%u (gap)", next_seq);
                next_seq++;
                idle_ms = 0;
                continue;
            }
        }

        if (udp_response_wait_event(wait_ms))
            idle_ms = 0;
        else
            idle_ms += wait_ms;
    }

    if (spk_open) {
        ESP_LOGI(TAG, "Stream finito: seq 0..%u, riprodotti=%u, validi=%u",
                 udp_response_last_seq(), next_seq,
                 (unsigned)udp_response_count_valid());
        i2s_spk_flush();
        vTaskDelay(pdMS_TO_TICKS(80));
        i2s_spk_end_playback();
    }

    return got_any;
}

static void playback_task(void *arg)
{
    while (true) {
        while (true) {
            if (s_state == STATE_WAITING_RESPONSE)
                break;
            vTaskDelay(pdMS_TO_TICKS(10));
        }

        s_session_abort = false;
        karen_note_state(STATE_SPEAKING);
        audio_board_set_duplex_mic(false);
        ESP_LOGI(TAG, "Riproduzione risposta (stream)…");

        bool got_data = playback_stream(&s_session_abort);
        udp_response_reset();

        if (s_session_abort) {
            ESP_LOGW(TAG, "Riproduzione interrotta (recovery)");
            udp_response_disarm();
            karen_note_state(STATE_IDLE);
            audio_board_set_duplex_mic(false);
            if (s_ww_available) {
                karen_wake_word_enable_after_session();
            }
            continue;
        }

        if (!got_data) {
            ESP_LOGW(TAG, "Nessun audio ricevuto dal Jetson");
            remote_log_send("playback no_audio");
            udp_listen_again_clear();
            udp_response_disarm();
            karen_note_state(STATE_IDLE);
            audio_board_set_duplex_mic(false);
            karen_wake_word_enable_after_session();
            continue;
        }

        ESP_LOGI(TAG, "Risposta terminata");

        if (udp_listen_again_pending()) {
            udp_listen_again_clear();
            audio_board_set_duplex_mic(false);
            s_listen_reset = true;
            karen_begin_listening();
            karen_wake_word_disable();
            ESP_LOGI(TAG, "Ascolto ripetizione (no wake word)…");
        } else {
            udp_response_disarm();
            karen_note_state(STATE_IDLE);
            audio_board_set_duplex_mic(false);
            audio_board_recover_input();
            s_session_abort = false;
            karen_wake_word_enable_after_session();
        }
    }
}

// ── Task principale audio ────────────────────────────────────────────────────

static void audio_main_task(void *arg)
{
    bool ww_available = (bool)(intptr_t)arg;

    const int read_samples = ww_available
        ? wake_word_get_chunksize()
        : UDP_CHUNK_SAMPLES;

    static int16_t mono_frame[AFE_CHUNK_SAMPLES];
    static int16_t dual_frame[AFE_CHUNK_SAMPLES * 2];

    uint16_t seq         = 0;
    uint32_t silence_ms  = 0;
    uint32_t record_ms   = 0;
    bool     had_speech  = false;
    uint32_t btn_held_ms = 0;
    const uint32_t frame_ms = ((uint32_t)read_samples * 1000) / AUDIO_SAMPLE_RATE;
    int n = 0;

    ESP_LOGI(TAG, "audio_main_task avviato (wake_word=%s)",
             ww_available ? "ON" : "OFF→GPIO0");

    while (true) {
        if (s_state == STATE_WAITING_RESPONSE && ww_available) {
            n = i2s_mic_read_dual(dual_frame, (size_t)read_samples);
            if (n > 0 && wake_word_process(dual_frame, (size_t)n)) {
                ESP_LOGI(TAG, "Wake durante attesa Jetson → nuovo ascolto");
                remote_log_send("wake during wait");
                udp_response_disarm();
                seq         = 0;
                silence_ms  = 0;
                record_ms   = 0;
                had_speech  = false;
                karen_begin_listening();
                karen_wake_word_disable();
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        if (s_state == STATE_WAITING_RESPONSE) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        if (s_state == STATE_SPEAKING && ww_available) {
            n = i2s_mic_read_dual(dual_frame, (size_t)read_samples);
            if (n > 0 && wake_word_process(dual_frame, (size_t)n)) {
                ESP_LOGI(TAG, "Wake durante risposta → ascolto comando");
                remote_log_send("wake barge-in");
                s_session_abort = true;
                i2s_spk_end_playback();
                udp_response_reset();
                udp_response_disarm();
                seq         = 0;
                silence_ms  = 0;
                record_ms   = 0;
                had_speech  = false;
                karen_begin_listening();
                karen_wake_word_disable();
                break;
            }
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        if (s_state == STATE_SPEAKING) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        if (ww_available) {
            n = i2s_mic_read_dual(dual_frame, (size_t)read_samples);
        } else {
            n = i2s_mic_read_mono(mono_frame, (size_t)read_samples);
        }
        if (n <= 0) {
            if (s_state == STATE_IDLE || s_state == STATE_LISTENING || s_state == STATE_RINGING) {
                if (++s_mic_fail_streak >= MIC_FAIL_RECOVER_COUNT) {
                    ESP_LOGW(TAG, "Mic fallito %lu volte, recovery…",
                             (unsigned long)s_mic_fail_streak);
                    audio_board_recover_input();
                    s_mic_fail_streak = 0;
                }
            }
            vTaskDelay(1);
            continue;
        }
        s_mic_fail_streak = 0;

        switch (s_state) {

        case STATE_IDLE: {
            bool triggered = false;
            static uint32_t s_ambient_rms_ema = 0;

            uint32_t frame_rms = ww_available
                ? compute_mic1_rms(dual_frame, n)
                : compute_rms(mono_frame, (size_t)n);
            s_idle_mic_rms = frame_rms;
            uint32_t ambient_before = s_ambient_rms_ema;

            static uint32_t idle_frames = 0;
            if (++idle_frames % (AUDIO_SAMPLE_RATE / read_samples * 10) == 0) {
                ESP_LOGD(TAG, "[MIC] RMS=%lu ema=%lu cool=%d",
                         frame_rms, s_ambient_rms_ema,
                         karen_wake_in_cooldown() ? 1 : 0);
            }

            bool ww_detected = false;
            if (ww_available)
                ww_detected = wake_word_process(dual_frame, (size_t)n);

            if (ww_detected) {
                if (karen_wake_in_cooldown()) {
                    ESP_LOGD(TAG, "Wake ignorato: cooldown");
                    remote_log_send("wake rejected cooldown");
                } else if (WAKE_AMBIENT_GATE_RMS > 0 &&
                           ambient_before > WAKE_AMBIENT_GATE_RMS) {
                    ESP_LOGI(TAG,
                             "Wake ignorato: rumore ambiente (rms=%lu ambient=%lu)",
                             (unsigned long)frame_rms,
                             (unsigned long)ambient_before);
                    remote_log_printf("wake rejected ambient rms=%lu ambient=%lu",
                                      (unsigned long)frame_rms,
                                      (unsigned long)ambient_before);
                    karen_wake_start_cooldown(WAKE_REJECT_COOLDOWN_MS);
                } else {
                    triggered = true;
                }
            } else {
                karen_ambient_rms_update(&s_ambient_rms_ema, frame_rms);
            }

            if (!triggered) {
                if (gpio_get_level(WAKE_BUTTON_GPIO) == 0) {
                    btn_held_ms += frame_ms;
                    if (btn_held_ms >= 500) {
                        triggered = true;
                        btn_held_ms = 0;
                        ESP_LOGI(TAG, "Trigger da pulsante BOOT");
                    }
                } else {
                    btn_held_ms = 0;
                }
            }

            if (triggered) {
                seq         = 0;
                silence_ms  = 0;
                record_ms   = 0;
                had_speech  = false;
                if (!karen_wifi_connected()) {
                    if (!karen_wait_for_wifi(5000)) {
                        ESP_LOGW(TAG, "Wake word OK ma Wi-Fi assente – impossibile inviare audio");
                        remote_log_send("wake wifi_down");
                        karen_wake_word_enable(false);
                        break;
                    }
                }
                if (karen_ensure_udp_ready() != ESP_OK) {
                    ESP_LOGW(TAG, "Wake word OK ma transport UDP non pronto");
                    remote_log_send("wake udp_down");
                    karen_wake_word_enable(false);
                    break;
                }
                remote_log_send("wake detected");
                karen_begin_listening();
                ESP_LOGI(TAG, ">>> Jarvis! Ascolto…");
                karen_wake_word_disable();
            }
            break;
        }

        case STATE_LISTENING: {
            if (s_listen_reset) {
                seq         = 0;
                silence_ms  = 0;
                record_ms   = 0;
                had_speech  = false;
                s_listen_reset = false;
            }
            // Streaming mono (MIC1) al Jetson – invia in chunk UDP da 512
            if (ww_available) {
                for (int i = 0; i < n; i++)
                    mono_frame[i] = dual_frame[i * 2];
            }

            record_ms += frame_ms;
            bool in_warmup = record_ms <= LISTEN_WARMUP_MS;
            uint32_t post_warmup_ms = record_ms > LISTEN_WARMUP_MS
                ? record_ms - LISTEN_WARMUP_MS : 0;

            static uint32_t listen_frames = 0;
            if (++listen_frames % (AUDIO_SAMPLE_RATE / read_samples) == 0) {
                ESP_LOGD(TAG, "[REC] RMS=%lu seq=%u warm=%d",
                         compute_rms(mono_frame, (size_t)n), seq, in_warmup);
            }

            for (int off = 0; off < n; off += UDP_CHUNK_SAMPLES) {
                int chunk = n - off;
                if (chunk > UDP_CHUNK_SAMPLES) chunk = UDP_CHUNK_SAMPLES;
                udp_send_audio(mono_frame + off, (size_t)chunk, seq++);
            }

            uint32_t rms = compute_rms(mono_frame, (size_t)n);
            if (!in_warmup && rms >= VAD_SPEECH_THRESHOLD)
                had_speech = true;

            if (had_speech && rms < VAD_SILENCE_THRESHOLD)
                silence_ms += frame_ms;
            else
                silence_ms = 0;

            bool min_speech_ok = post_warmup_ms >= VAD_MIN_SPEECH_MS;
            bool end_on_silence = had_speech && min_speech_ok &&
                                  silence_ms >= VAD_SILENCE_MS;
            bool end_on_max = record_ms >= VAD_MAX_RECORD_MS;
            bool end_on_host = had_speech && min_speech_ok &&
                                udp_response_packets_received() > 0;
            bool end_no_speech = !had_speech &&
                                 record_ms >= LISTEN_NO_SPEECH_IDLE_MS &&
                                 !end_on_host;

            if (end_no_speech) {
                karen_abort_listen_idle("Ascolto: silenzio, ritorno IDLE");
                seq        = 0;
                silence_ms = 0;
                record_ms  = 0;
                had_speech = false;
                break;
            }

            if (end_on_silence || end_on_max || end_on_host) {
                status_led_listening_off();
                udp_send_end_of_audio();
                remote_log_printf("listen end speech=%d rec_ms=%lu tx_seq=%u",
                                  had_speech, record_ms, (unsigned)seq);
                if (end_on_host) {
                    ESP_LOGI(TAG,
                             "Fine registrazione (host ha risposto, tot=%lums)",
                             record_ms);
                } else {
                    ESP_LOGI(TAG,
                             "Fine registrazione (speech=%d sil=%lums tot=%lums)",
                             had_speech, silence_ms, record_ms);
                }
                karen_note_state(STATE_WAITING_RESPONSE);
            }
            break;
        }

        case STATE_RINGING: {
            static uint32_t ring_btn_ms = 0;

            if (gpio_get_level(WAKE_BUTTON_GPIO) == 0) {
                ring_btn_ms += frame_ms;
                if (ring_btn_ms >= 500) {
                    ring_btn_ms = 0;
                    ESP_LOGI(TAG, "Ring: dismiss pulsante BOOT");
                    audio_board_alarm_stop();
                    karen_ring_phase_reset();
                    udp_send_ring_dismiss();
                }
            } else {
                ring_btn_ms = 0;
            }

            if (ww_available && wake_word_process(dual_frame, (size_t)n)) {
                ESP_LOGI(TAG, "Ring: wake word → dismiss immediato");
                audio_board_alarm_stop();
                audio_board_set_duplex_mic(false);
                karen_ring_phase_reset();
                udp_send_ring_dismiss();
                karen_note_state(STATE_IDLE);
                karen_wake_word_enable(false);
            }
            break;
        }

        case STATE_WAITING_RESPONSE:
        case STATE_SPEAKING:
            break;
        }
    }
}

// ── Entry point ──────────────────────────────────────────────────────────────

extern "C" void app_main(void)
{
    ESP_LOGI(TAG, "=== Karen ESP32-S3 (Waveshare Audio Board) ===");

    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);

    esp_reset_reason_t reset_reason = esp_reset_reason();
    ESP_LOGI(TAG, "Reset reason: %s", reset_reason_str(reset_reason));

    wifi_init();

    ESP_ERROR_CHECK(i2s_audio_init());
    status_led_init();

    gpio_config_t btn_cfg = {
        .pin_bit_mask = (1ULL << WAKE_BUTTON_GPIO),
        .mode         = GPIO_MODE_INPUT,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&btn_cfg);

    esp_err_t ww_ret = wake_word_init();
    s_ww_available = (ww_ret == ESP_OK);
    bool ww_available = s_ww_available;
    if (ww_available)
        ESP_LOGI(TAG, "Wake word: %s", wake_word_get_model_name());
    else
        ESP_LOGW(TAG, "Wake word disabilitato – premi BOOT per attivare");

    if (karen_wifi_connected())
        karen_ensure_udp_ready();
    if (s_remote_log_ready)
        remote_log_printf("boot reset=%s", reset_reason_str(reset_reason));

    xTaskCreatePinnedToCore(audio_main_task, "audio_main", 12288,
                            (void *)(intptr_t)ww_available, 5, NULL, 0);
    xTaskCreatePinnedToCore(playback_task, "playback", 8192,
                            NULL, 4, NULL, 1);
    xTaskCreatePinnedToCore(supervisor_task, "supervisor", 4096,
                            NULL, 3, NULL, 1);

    if (s_remote_log_ready)
        remote_log_printf("ready ww=%s build=%s thr=%.2f",
                          ww_available ? wake_word_get_model_name() : "off",
                          ww_available ? wake_word_get_build_tag() : "n/a",
                          (double)WAKENET_THRESHOLD);

    karen_note_state(STATE_IDLE);
    if (s_ww_available)
        karen_wake_word_enable(false);
    ESP_LOGI(TAG, "Karen pronta (VAD max=%dms, sil=%dms, speech=%d, ww_thr=%.2f).",
             VAD_MAX_RECORD_MS, VAD_SILENCE_MS, VAD_SPEECH_THRESHOLD,
             (double)WAKENET_THRESHOLD);
}
