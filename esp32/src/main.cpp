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
#include "nvs_flash.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "driver/gpio.h"

#include "config.h"
#include "i2s_audio.h"
#include "wake_word.h"
#include "udp_transport.h"
#include "audio_board.h"

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
static TickType_t s_state_since = 0;
static uint32_t s_mic_fail_streak = 0;

#define WIFI_CONNECTED_BIT BIT0
static EventGroupHandle_t s_wifi_events;

static void karen_note_state(karen_state_t st)
{
    if (s_state != st) {
        s_state = st;
        s_state_since = xTaskGetTickCount();
    }
}

static uint32_t karen_state_elapsed_ms(void)
{
    return (uint32_t)((xTaskGetTickCount() - s_state_since) * portTICK_PERIOD_MS);
}

static void karen_force_idle(const char *reason)
{
    karen_state_t prev = s_state;
    ESP_LOGW(TAG, "Recovery → IDLE (%s)", reason);
    s_session_abort = true;
    if (prev == STATE_LISTENING || prev == STATE_RINGING)
        udp_send_end_of_audio();
    i2s_spk_end_playback();
    audio_board_alarm_stop();
    udp_response_reset();
    udp_response_disarm();
    audio_board_set_duplex_mic(false);
    if (s_ww_available) {
        wake_word_set_active(true);
        wake_word_reset();
    }
    audio_board_recover_input();
    karen_note_state(STATE_IDLE);
    s_mic_fail_streak = 0;
}

// ── Wi-Fi ────────────────────────────────────────────────────────────────────

static void wifi_event_handler(void *arg, esp_event_base_t base,
                                int32_t event_id, void *data)
{
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnesso, riprovo…");
        esp_wifi_connect();
        xEventGroupClearBits(s_wifi_events, WIFI_CONNECTED_BIT);
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&event->ip_info.ip));
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

// ── Task riproduzione risposta ───────────────────────────────────────────────

static void supervisor_task(void *arg)
{
    (void)arg;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(SUPERVISOR_INTERVAL_MS));

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
            if (karen_state_elapsed_ms() > STATE_RINGING_MAX_MS)
                karen_force_idle("timeout RINGING");
            break;
        default:
            break;
        }

        if (udp_ring_stop_pending()) {
            udp_ring_clear_stop();
            karen_force_idle("STOP_RING host");
        } else if (udp_ring_pending()) {
            if (s_state == STATE_IDLE) {
                udp_ring_clear_pending();
                if (s_ww_available) {
                    wake_word_set_active(false);
                    wake_word_reset();
                }
                audio_board_alarm_start();
                audio_board_set_duplex_mic(true);
                udp_response_arm();
                karen_note_state(STATE_RINGING);
                udp_ring_set_listen(true);
                ESP_LOGI(TAG, "Ring: allarme sonoro + ascolto dismiss");
            } else {
                udp_ring_clear_pending();
            }
        } else if (udp_push_play_pending() && s_state == STATE_IDLE) {
            udp_push_play_clear();
            if (s_ww_available) {
                wake_word_set_active(false);
                wake_word_reset();
            }
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
            if (udp_ring_is_active() && s_state == STATE_RINGING &&
                udp_response_packets_received() > 0)
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
            if (!udp_ring_is_active()) {
                udp_response_disarm();
                karen_note_state(STATE_IDLE);
                if (s_ww_available) wake_word_set_active(true);
            }
            continue;
        }

        if (!got_data) {
            ESP_LOGW(TAG, "Nessun audio ricevuto dal Jetson");
            if (udp_ring_is_active()) {
                udp_response_arm();
                karen_note_state(STATE_RINGING);
                udp_ring_set_listen(true);
            } else {
                udp_response_disarm();
                karen_note_state(STATE_IDLE);
                if (s_ww_available) wake_word_set_active(true);
            }
            continue;
        }

        ESP_LOGI(TAG, "Risposta terminata");

        if (udp_ring_is_active()) {
            audio_board_set_duplex_mic(true);
            udp_response_arm();
            karen_note_state(STATE_RINGING);
            udp_ring_set_listen(true);
            ESP_LOGI(TAG, "Ring: ascolto dismiss (no wake word)…");
        } else {
            udp_response_disarm();
            karen_note_state(STATE_IDLE);
            s_session_abort = false;
            if (s_ww_available) wake_word_set_active(true);
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

    ESP_LOGI(TAG, "audio_main_task avviato (wake_word=%s)",
             ww_available ? "ON" : "OFF→GPIO0");

    while (true) {
        int n;
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

            static uint32_t idle_frames = 0;
            if (++idle_frames % (AUDIO_SAMPLE_RATE / read_samples * 10) == 0) {
                const int16_t *rms_src = ww_available ? dual_frame : mono_frame;
                size_t rms_len = ww_available ? (size_t)n * 2 : (size_t)n;
                ESP_LOGD(TAG, "[MIC] RMS=%lu", compute_rms(rms_src, rms_len));
            }

            if (ww_available)
                triggered = wake_word_process(dual_frame, (size_t)n);

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
                ESP_LOGI(TAG, ">>> Karen! Ascolto…");
                if (ww_available) {
                    wake_word_set_active(false);
                    wake_word_reset();
                }
#if WAKE_ACK_BEEP
                audio_board_play_ack_tone();
#endif
                udp_response_arm();
                karen_note_state(STATE_LISTENING);
                seq         = 0;
                silence_ms  = 0;
                record_ms   = 0;
                had_speech  = false;
            }
            break;
        }

        case STATE_LISTENING: {
            // Streaming mono (MIC1) al Jetson – invia in chunk UDP da 512
            if (ww_available) {
                for (int i = 0; i < n; i++)
                    mono_frame[i] = dual_frame[i * 2];
            }

            static uint32_t listen_frames = 0;
            if (++listen_frames % (AUDIO_SAMPLE_RATE / read_samples) == 0) {
                ESP_LOGD(TAG, "[REC] RMS=%lu seq=%u", compute_rms(mono_frame, (size_t)n), seq);
            }

            for (int off = 0; off < n; off += UDP_CHUNK_SAMPLES) {
                int chunk = n - off;
                if (chunk > UDP_CHUNK_SAMPLES) chunk = UDP_CHUNK_SAMPLES;
                udp_send_audio(mono_frame + off, (size_t)chunk, seq++);
            }
            record_ms += frame_ms;

            uint32_t rms = compute_rms(mono_frame, (size_t)n);
            if (rms >= VAD_SPEECH_THRESHOLD)
                had_speech = true;

            if (had_speech && rms < VAD_SILENCE_THRESHOLD)
                silence_ms += frame_ms;
            else
                silence_ms = 0;

            bool min_speech_ok = record_ms >= VAD_MIN_SPEECH_MS;
            bool end_on_silence = had_speech && min_speech_ok &&
                                  silence_ms >= VAD_SILENCE_MS;
            bool end_on_max = record_ms >= VAD_MAX_RECORD_MS;
            bool end_on_host = udp_response_packets_received() > 0;

            if (end_on_silence || end_on_max || end_on_host) {
                udp_send_end_of_audio();
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
            if (!udp_ring_listen_active()) {
                vTaskDelay(pdMS_TO_TICKS(10));
                break;
            }

            static bool ring_listen_reset = true;
            if (ring_listen_reset) {
                seq         = 0;
                record_ms   = 0;
                silence_ms  = 0;
                had_speech  = false;
                ring_listen_reset = false;
            }

            if (ww_available) {
                for (int i = 0; i < n; i++)
                    mono_frame[i] = dual_frame[i * 2];
            }

            for (int off = 0; off < n; off += UDP_CHUNK_SAMPLES) {
                int chunk = n - off;
                if (chunk > UDP_CHUNK_SAMPLES) chunk = UDP_CHUNK_SAMPLES;
                udp_send_audio(mono_frame + off, (size_t)chunk, seq++);
            }
            record_ms += frame_ms;

            uint32_t rms = compute_rms(mono_frame, (size_t)n);
            if (rms >= VAD_SPEECH_THRESHOLD)
                had_speech = true;

            if (had_speech && rms < VAD_SILENCE_THRESHOLD)
                silence_ms += frame_ms;
            else if (rms >= VAD_SPEECH_THRESHOLD)
                silence_ms = 0;

            bool end_listen = record_ms >= RING_LISTEN_MS;
            bool end_speech = had_speech && silence_ms >= 800;

            if (end_listen || end_speech) {
                udp_send_end_of_audio();
                ring_listen_reset = true;
                ESP_LOGI(TAG, "Ring: fine ascolto dismiss (tot=%lums speech=%d)",
                         record_ms, had_speech);
                record_ms  = 0;
                silence_ms = 0;
                had_speech = false;
                seq        = 0;
                if (udp_ring_is_active()) {
                    vTaskDelay(pdMS_TO_TICKS(400));
                    udp_ring_set_listen(true);
                }
            }
            break;
        }

        case STATE_WAITING_RESPONSE:
        case STATE_SPEAKING:
            vTaskDelay(pdMS_TO_TICKS(10));
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

    wifi_init();

    ESP_ERROR_CHECK(i2s_audio_init());

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

    xEventGroupWaitBits(s_wifi_events, WIFI_CONNECTED_BIT,
                        pdFALSE, pdTRUE, portMAX_DELAY);
    ESP_ERROR_CHECK(udp_transport_init());

    xTaskCreatePinnedToCore(audio_main_task, "audio_main", 12288,
                            (void *)(intptr_t)ww_available, 5, NULL, 0);
    xTaskCreatePinnedToCore(playback_task, "playback", 8192,
                            NULL, 4, NULL, 1);
    xTaskCreatePinnedToCore(supervisor_task, "supervisor", 4096,
                            NULL, 3, NULL, 1);

    karen_note_state(STATE_IDLE);
    ESP_LOGI(TAG, "Karen pronta (VAD max=%dms, sil=%dms, speech=%d).",
             VAD_MAX_RECORD_MS, VAD_SILENCE_MS, VAD_SPEECH_THRESHOLD);
}
