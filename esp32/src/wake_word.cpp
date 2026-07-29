#include "wake_word.h"
#include "esp_log.h"
#include <string.h>

#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_afe_config.h"
#include "model_path.h"

static const char *TAG = "wake_word";

static const esp_afe_sr_iface_t *s_afe_handle = NULL;
static esp_afe_sr_data_t        *s_afe_data   = NULL;
static srmodel_list_t           *s_models     = NULL;
static int                       s_chunksize  = 512;
static char                      s_model_name[64] = {0};

static volatile bool s_wake_detected = false;
static volatile bool s_fetch_running = false;
static volatile bool s_afe_active    = true;
static TaskHandle_t  s_fetch_task    = NULL;

static void wake_word_fetch_task(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "fetch task avviato (core %d)", xPortGetCoreID());

    while (s_fetch_running) {
        if (!s_afe_active || !s_afe_data || !s_afe_handle) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        afe_fetch_result_t *result = s_afe_handle->fetch_with_delay(
            s_afe_data, pdMS_TO_TICKS(100));
        if (!result || result->ret_value == ESP_FAIL)
            continue;

        if (result->wakeup_state == WAKENET_DETECTED) {
            s_wake_detected = true;
            ESP_LOGI(TAG, "Wake word rilevato! (model=%d, word=%d)",
                     result->wakenet_model_index, result->wake_word_index);
        }
    }

    s_fetch_task = NULL;
    vTaskDelete(NULL);
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
    ESP_LOGI(TAG, "WakeNet model: %s", s_model_name);

    // "MM" = dual-mic (array ES7210 sulla Waveshare)
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
        return ESP_FAIL;
    }

    if (s_afe_handle->set_wakenet_threshold) {
        int thr_ret = s_afe_handle->set_wakenet_threshold(
            s_afe_data, 1, WAKENET_THRESHOLD);
        ESP_LOGI(TAG, "WakeNet threshold=%.2f mode=%d (ret=%d)",
                 WAKENET_THRESHOLD, WAKENET_DET_MODE, thr_ret);
    }

    s_chunksize = s_afe_handle->get_feed_chunksize(s_afe_data);
    ESP_LOGI(TAG, "AFE dual-mic pronto – chunksize %d (~%d ms)",
             s_chunksize, s_chunksize * 1000 / AUDIO_SAMPLE_RATE);

    s_afe_handle->print_pipeline(s_afe_data);

    s_fetch_running = true;
    xTaskCreatePinnedToCore(wake_word_fetch_task, "afe_fetch", 4096,
                            NULL, 5, &s_fetch_task, 1);

    return ESP_OK;
}

bool wake_word_process(const int16_t *audio, size_t samples)
{
    if (!s_afe_data || !s_afe_handle) return false;

    s_afe_handle->feed(s_afe_data, audio);
    (void)samples;

    if (s_wake_detected) {
        s_wake_detected = false;
        return true;
    }
    return false;
}

void wake_word_reset(void)
{
    if (s_afe_data && s_afe_handle)
        s_afe_handle->reset_buffer(s_afe_data);
    s_wake_detected = false;
}

void wake_word_set_active(bool active)
{
    s_afe_active = active;
}

int wake_word_get_chunksize(void)
{
    return s_chunksize;
}

void wake_word_deinit(void)
{
    s_fetch_running = false;
    while (s_fetch_task != NULL)
        vTaskDelay(pdMS_TO_TICKS(10));

    if (s_afe_data && s_afe_handle) {
        s_afe_handle->destroy(s_afe_data);
        s_afe_data = NULL;
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
