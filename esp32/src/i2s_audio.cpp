#include "i2s_audio.h"
#include "audio_board.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "i2s_audio";

// Buffer TDM grezzo (4 canali × campioni)
static int16_t s_tdm_buf[AFE_CHUNK_SAMPLES * MIC_TDM_SLOTS];

esp_err_t i2s_audio_init(void)
{
    esp_err_t ret = audio_board_init();
    if (ret == ESP_OK)
        ESP_LOGI(TAG, "I2S audio inizializzato (Waveshare ES8311/ES7210)");
    return ret;
}

int i2s_mic_read_dual(int16_t *stereo_out, size_t samples)
{
    int n = audio_board_mic_read(s_tdm_buf, samples);
    if (n <= 0) return n;

    // Estrai MIC1 (slot 0) e MIC2 (slot 1) interleaved per AFE dual-mic
    for (int i = 0; i < n; i++) {
        stereo_out[i * 2]     = s_tdm_buf[i * MIC_TDM_SLOTS + 0];
        stereo_out[i * 2 + 1] = s_tdm_buf[i * MIC_TDM_SLOTS + 1];
    }
    return n;
}

int i2s_mic_read_mono(int16_t *mono_out, size_t samples)
{
    int n = audio_board_mic_read(s_tdm_buf, samples);
    if (n <= 0) return n;

    // MIC1 (slot 0) per streaming UDP
    for (int i = 0; i < n; i++)
        mono_out[i] = s_tdm_buf[i * MIC_TDM_SLOTS + 0];
    return n;
}

esp_err_t i2s_spk_begin_playback(void)
{
    return audio_board_begin_playback();
}

esp_err_t i2s_spk_end_playback(void)
{
    return audio_board_end_playback();
}

int i2s_spk_write(const int16_t *buf, size_t samples, uint32_t ms_wait)
{
    (void)ms_wait;
    return audio_board_spk_write(buf, samples);
}

void i2s_spk_flush(void)
{
    audio_board_spk_flush();
}

esp_err_t i2s_set_volume(int volume)
{
    return audio_board_set_volume(volume);
}
