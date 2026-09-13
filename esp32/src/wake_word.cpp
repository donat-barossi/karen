#include "wake_word.h"
#include "esp_log.h"
#include <string.h>

#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_afe_config.h"
#include "model_path.h"

static const char *TAG = "wake_word";

/** Cambiare ad ogni fix AFE per verificare il flash via seriale. */
#define WAKE_WORD_BUILD_TAG "2026-09-13-gate1200-thr065"

static const esp_afe_sr_iface_t *s_afe_handle = NULL;
static esp_afe_sr_data_t        *s_afe_data   = NULL;
static srmodel_list_t           *s_models     = NULL;
static int                       s_chunksize  = 512;
static char                      s_model_name[64] = {0};

static volatile bool s_afe_active = false;
static volatile bool s_detected   = false;
static TaskHandle_t  s_fetch_task = NULL;

static void wake_fetch_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "Task fetch AFE avviato (%s)", WAKE_WORD_BUILD_TAG);

    while (true) {
        if (!s_afe_active || !s_afe_data || !s_afe_handle) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }

        /* fetch() blocca finché feed() fornisce dati (pattern ESP-SR ufficiale) */
        afe_fetch_result_t *result = s_afe_handle->fetch(s_afe_data);
        if (!s_afe_active)
            continue;
        if (!result || result->ret_value == ESP_FAIL)
            continue;

        if (result->wakeup_state == WAKENET_DETECTED) {
            s_detected = true;
            ESP_LOGI(TAG, "Wake word rilevato! (model=%d, word=%d)",
                     result->wakenet_model_index, result->wake_word_index);
        }
    }
}

static esp_err_t wake_word_create_afe(void)
{
    afe_config_t *afe_cfg = afe_config_init("MM", s_models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (!afe_cfg) {
        ESP_LOGE(TAG, "afe_config_init fallita");
        return ESP_FAIL;
    }

    afe_cfg->aec_init          = true;
    afe_cfg->se_init           = true;
    afe_cfg->ns_init           = true;
    afe_cfg->vad_init          = true;
    afe_cfg->vad_mode          = VAD_MODE_0;
    afe_cfg->agc_init          = true;
    afe_cfg->agc_mode          = AFE_AGC_MODE_WAKENET;
    afe_cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    afe_cfg->afe_perferred_core     = 0;
    afe_cfg->afe_perferred_priority = 5;
    afe_cfg->afe_ringbuf_size       = 150;
    afe_cfg->wakenet_init       = true;
    afe_cfg->wakenet_model_name = s_model_name;
    afe_cfg->wakenet_mode       = (det_mode_t)WAKENET_DET_MODE;

    afe_config_check(afe_cfg);

    s_afe_handle = esp_afe_handle_from_config(afe_cfg);
    if (!s_afe_handle) {
        afe_config_free(afe_cfg);
        return ESP_FAIL;
    }

    s_afe_data = s_afe_handle->create_from_config(afe_cfg);
    afe_config_free(afe_cfg);
    if (!s_afe_data) {
        ESP_LOGE(TAG, "AFE create_from_config fallita");
        s_afe_handle = NULL;
        return ESP_FAIL;
    }

    if (s_afe_handle->set_wakenet_threshold) {
        int thr0 = s_afe_handle->set_wakenet_threshold(
            s_afe_data, 0, WAKENET_THRESHOLD);
        int thr1 = s_afe_handle->set_wakenet_threshold(
            s_afe_data, 1, WAKENET_THRESHOLD);
        ESP_LOGI(TAG, "WakeNet threshold=%.2f mode=%d (ret0=%d ret1=%d)",
                 WAKENET_THRESHOLD, WAKENET_DET_MODE, thr0, thr1);
    }

    s_chunksize = s_afe_handle->get_feed_chunksize(s_afe_data);
    ESP_LOGI(TAG, "AFE dual-mic pronto – chunksize %d (~%d ms)",
             s_chunksize, s_chunksize * 1000 / AUDIO_SAMPLE_RATE);

    s_afe_handle->print_pipeline(s_afe_data);
    return ESP_OK;
}

esp_err_t wake_word_init(void)
{
    s_models = esp_srmodel_init("model");
    if (!s_models) {
        ESP_LOGW(TAG, "Partizione model non trovata – wake word disabilitato");
        return ESP_ERR_NOT_FOUND;
    }

    ESP_LOGI(TAG, "Modelli in flash: %d", s_models->num);
    for (int i = 0; i < s_models->num; i++)
        ESP_LOGI(TAG, "  [%d] %s", i, s_models->model_name[i]);

    const char *wn_name = esp_srmodel_filter(s_models, "wn", NULL);
    if (!wn_name && esp_srmodel_exists(s_models, (char *)WAKEWORD_MODEL_NAME) >= 0)
        wn_name = WAKEWORD_MODEL_NAME;

    if (!wn_name) {
        ESP_LOGW(TAG, "Nessun modello WakeNet in flash – wake word disabilitato");
        return ESP_ERR_NOT_FOUND;
    }

    strlcpy(s_model_name, wn_name, sizeof(s_model_name));
    ESP_LOGI(TAG, "WakeNet model: %s (%s)", s_model_name, WAKE_WORD_BUILD_TAG);

    esp_err_t err = wake_word_create_afe();
    if (err != ESP_OK)
        return err;

    if (!s_fetch_task) {
        xTaskCreatePinnedToCore(wake_fetch_task, "afe_fetch", 4096, NULL,
                                5, &s_fetch_task, 1);
    }

    return ESP_OK;
}

esp_err_t wake_word_reinit(void)
{
    if (!s_models || !s_model_name[0])
        return ESP_ERR_INVALID_STATE;

    bool was_active = s_afe_active;
    s_afe_active = false;
    s_detected = false;
    vTaskDelay(pdMS_TO_TICKS(80));

    if (s_afe_data && s_afe_handle) {
        s_afe_handle->destroy(s_afe_data);
        s_afe_data = NULL;
        s_afe_handle = NULL;
    }

    esp_err_t err = wake_word_create_afe();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "wake_word_reinit fallita");
        return err;
    }

    s_afe_active = was_active;
    return ESP_OK;
}

bool wake_word_process(const int16_t *audio, size_t samples)
{
    if (!s_afe_data || !s_afe_handle || !s_afe_active)
        return false;

    s_afe_handle->feed(s_afe_data, audio);
    (void)samples;

    if (s_detected) {
        s_detected = false;
        return true;
    }
    return false;
}

void wake_word_reset(void)
{
    if (s_afe_data && s_afe_handle)
        s_afe_handle->reset_buffer(s_afe_data);
    s_detected = false;
}

void wake_word_set_active(bool active)
{
    if (!active && s_afe_active) {
        wake_word_reset();
        s_afe_active = false;
        return;
    }
    if (active && !s_afe_active) {
        s_detected = false;
        s_afe_active = true;
        return;
    }
    s_afe_active = active;
}

bool wake_word_is_active(void)
{
    return s_afe_active;
}

int wake_word_get_chunksize(void)
{
    return s_chunksize;
}

void wake_word_deinit(void)
{
    s_afe_active = false;
    if (s_fetch_task) {
        vTaskDelete(s_fetch_task);
        s_fetch_task = NULL;
    }
    if (s_afe_data && s_afe_handle) {
        s_afe_handle->destroy(s_afe_data);
        s_afe_data = NULL;
        s_afe_handle = NULL;
    }
    if (s_models) {
        esp_srmodel_deinit(s_models);
        s_models = NULL;
    }
}

const char *wake_word_get_model_name(void)
{
    return s_model_name[0] ? s_model_name : WAKEWORD_MODEL_NAME;
}

const char *wake_word_get_build_tag(void)
{
    return WAKE_WORD_BUILD_TAG;
}
