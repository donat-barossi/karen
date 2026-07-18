#include "audio_board.h"

#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "driver/i2s_tdm.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_io_expander.h"
#include "esp_io_expander_tca95xx_16bit.h"

#include <string.h>
#include <math.h>

static const char *TAG = "audio_board";

static i2c_master_bus_handle_t  s_i2c_bus    = NULL;
static esp_io_expander_handle_t s_io_exp     = NULL;
static i2s_chan_handle_t        s_tx_handle  = NULL;
static i2s_chan_handle_t        s_rx_handle  = NULL;
static esp_codec_dev_handle_t   s_out_dev    = NULL;
static esp_codec_dev_handle_t   s_in_dev     = NULL;
static const audio_codec_data_if_t *s_data_if = NULL;
static uint32_t                   s_play_rate = AUDIO_SAMPLE_RATE;
static volatile bool              s_playback_active = false;
static volatile bool              s_duplex_mic      = false;

static esp_err_t open_out_codec(uint32_t sample_rate)
{
    if (!s_out_dev) return ESP_ERR_INVALID_STATE;

    esp_codec_dev_sample_info_t fs = {
        .bits_per_sample = AUDIO_BITS,
        .channel         = 2,
        .channel_mask    = 0,
        .sample_rate     = sample_rate,
        .mclk_multiple   = I2S_MCLK_MULTIPLE,
    };

    esp_err_t ret = esp_codec_dev_close(s_out_dev);
    if (ret != ESP_OK && ret != ESP_CODEC_DEV_WRONG_STATE) return ret;

    ret = esp_codec_dev_open(s_out_dev, &fs);
    if (ret == ESP_OK) {
        s_play_rate = sample_rate;
        ESP_LOGI(TAG, "ES8311 aperto @ %lu Hz (mclk x%d)",
                 (unsigned long)sample_rate, I2S_MCLK_MULTIPLE);
    }
    return ret;
}

// ── I2C ───────────────────────────────────────────────────────────────────────

static esp_err_t i2c_bus_init(void)
{
    const i2c_master_bus_config_t cfg = {
        .i2c_port   = I2C_PORT,
        .sda_io_num = I2C_SDA_GPIO,
        .scl_io_num = I2C_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    return i2c_new_master_bus(&cfg, &s_i2c_bus);
}

// ── TCA9555 – amplificatore NS4150 ───────────────────────────────────────────

static esp_err_t tca9555_init(void)
{
    esp_err_t ret = esp_io_expander_new_i2c_tca95xx_16bit(
        s_i2c_bus, TCA9555_I2C_ADDR, &s_io_exp);
    if (ret != ESP_OK) return ret;

    // EXIO8 = PA enable (output); pulsanti EXIO9-11 = input
    ret = esp_io_expander_set_dir(s_io_exp,
        TCA9555_PA_PIN, IO_EXPANDER_OUTPUT);
    if (ret != ESP_OK) return ret;

    ret = esp_io_expander_set_dir(s_io_exp,
        IO_EXPANDER_PIN_NUM_9 | IO_EXPANDER_PIN_NUM_10 | IO_EXPANDER_PIN_NUM_11,
        IO_EXPANDER_INPUT);
    return ret;
}

void audio_board_pa_enable(bool enable)
{
    if (!s_io_exp) return;
    esp_io_expander_set_level(s_io_exp, TCA9555_PA_PIN, enable ? 1 : 0);
}

// ── I2S full-duplex ─────────────────────────────────────────────────────────

static esp_err_t i2s_duplex_init(void)
{
    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_PORT, I2S_ROLE_MASTER);
    chan_cfg.auto_clear = true;
    ESP_RETURN_ON_ERROR(i2s_new_channel(&chan_cfg, &s_tx_handle, &s_rx_handle), TAG, "i2s_new_channel");

    // TX: I2S standard stereo (ES8311 DAC)
    i2s_std_config_t tx_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_MCLK_GPIO,
            .bclk = I2S_BCLK_GPIO,
            .ws   = I2S_LRCK_GPIO,
            .dout = I2S_DOUT_GPIO,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    ESP_RETURN_ON_ERROR(i2s_channel_init_std_mode(s_tx_handle, &tx_cfg), TAG, "tx std init");

    // RX: I2S TDM 4 slot (ES7210 ADC dual-mic)
    i2s_tdm_slot_mask_t slot_mask = I2S_TDM_SLOT0 | I2S_TDM_SLOT1 |
                                    I2S_TDM_SLOT2 | I2S_TDM_SLOT3;
    i2s_tdm_config_t rx_cfg = {
        .clk_cfg  = I2S_TDM_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_TDM_PHILIPS_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO, slot_mask),
        .gpio_cfg = {
            .mclk = I2S_MCLK_GPIO,
            .bclk = I2S_BCLK_GPIO,
            .ws   = I2S_LRCK_GPIO,
            .dout = I2S_GPIO_UNUSED,
            .din  = I2S_DIN_GPIO,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };
    rx_cfg.slot_cfg.total_slot = MIC_TDM_SLOTS;
    ESP_RETURN_ON_ERROR(i2s_channel_init_tdm_mode(s_rx_handle, &rx_cfg), TAG, "rx tdm init");

    // TX prima di RX (requisito esp_codec_dev full-duplex)
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_tx_handle), TAG, "tx enable");
    ESP_RETURN_ON_ERROR(i2s_channel_enable(s_rx_handle), TAG, "rx enable");

    return ESP_OK;
}

static esp_err_t reconfig_tx_rate(uint32_t rate, i2s_slot_mode_t mode)
{
    if (!s_tx_handle) return ESP_ERR_INVALID_STATE;

    i2s_std_config_t tx_cfg = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(rate),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
                        I2S_DATA_BIT_WIDTH_16BIT, mode),
        .gpio_cfg = {
            .mclk = I2S_MCLK_GPIO,
            .bclk = I2S_BCLK_GPIO,
            .ws   = I2S_LRCK_GPIO,
            .dout = I2S_DOUT_GPIO,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = { .mclk_inv = false, .bclk_inv = false, .ws_inv = false },
        },
    };

    esp_err_t ret = i2s_channel_disable(s_tx_handle);
    if (ret != ESP_OK) return ret;
    ret = i2s_channel_reconfig_std_clock(s_tx_handle, &tx_cfg.clk_cfg);
    if (ret != ESP_OK) return ret;
    ret = i2s_channel_reconfig_std_slot(s_tx_handle, &tx_cfg.slot_cfg);
    if (ret != ESP_OK) return ret;
    return i2s_channel_enable(s_tx_handle);
}

// ── Codec ES8311 (output) + ES7210 (input) ─────────────────────────────────

static esp_err_t codecs_init(void)
{
    audio_codec_i2s_cfg_t i2s_cfg = {
        .port      = I2S_PORT,
        .rx_handle = s_rx_handle,
        .tx_handle = s_tx_handle,
    };
    s_data_if = audio_codec_new_i2s_data(&i2s_cfg);
    if (!s_data_if) return ESP_FAIL;

    // ES8311 – DAC speaker
    audio_codec_i2c_cfg_t i2c_cfg = {
        .port       = I2C_PORT,
        .bus_handle = s_i2c_bus,
        .addr       = ES8311_CODEC_DEFAULT_ADDR,
    };
    const audio_codec_ctrl_if_t *out_ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    if (!out_ctrl) return ESP_FAIL;

    const audio_codec_gpio_if_t *gpio_if = audio_codec_new_gpio();
    if (!gpio_if) return ESP_FAIL;

    es8311_codec_cfg_t es8311_cfg = {
        .codec_mode = ESP_CODEC_DEV_WORK_MODE_DAC,
        .ctrl_if    = out_ctrl,
        .gpio_if    = gpio_if,
        .pa_pin     = -1,          // PA gestito via TCA9555
        .use_mclk   = true,
    };
    es8311_cfg.hw_gain.pa_voltage        = 5.0;
    es8311_cfg.hw_gain.codec_dac_voltage = 3.3;

    const audio_codec_if_t *out_codec = es8311_codec_new(&es8311_cfg);
    if (!out_codec) return ESP_FAIL;

    esp_codec_dev_cfg_t out_dev_cfg = {
        .codec_if = out_codec,
        .data_if  = s_data_if,
        .dev_type = ESP_CODEC_DEV_TYPE_OUT,
    };
    s_out_dev = esp_codec_dev_new(&out_dev_cfg);
    if (!s_out_dev) return ESP_FAIL;

    esp_codec_dev_sample_info_t out_fs = {
        .sample_rate     = AUDIO_SAMPLE_RATE,
        .channel         = 2,
        .bits_per_sample = AUDIO_BITS,
        .mclk_multiple   = I2S_MCLK_MULTIPLE,
    };
    ESP_RETURN_ON_ERROR(esp_codec_dev_open(s_out_dev, &out_fs), TAG, "es8311 open");

    // ES7210 – ADC dual-mic
    i2c_cfg.addr = ES7210_CODEC_DEFAULT_ADDR;
    const audio_codec_ctrl_if_t *in_ctrl = audio_codec_new_i2c_ctrl(&i2c_cfg);
    if (!in_ctrl) return ESP_FAIL;

    es7210_codec_cfg_t es7210_cfg = {
        .ctrl_if      = in_ctrl,
        .mic_selected = ES7210_SEL_MIC1 | ES7210_SEL_MIC2 | ES7210_SEL_MIC3,
    };
    const audio_codec_if_t *in_codec = es7210_codec_new(&es7210_cfg);
    if (!in_codec) return ESP_FAIL;

    esp_codec_dev_cfg_t in_dev_cfg = {
        .codec_if = in_codec,
        .data_if  = s_data_if,
        .dev_type = ESP_CODEC_DEV_TYPE_IN,
    };
    s_in_dev = esp_codec_dev_new(&in_dev_cfg);
    if (!s_in_dev) return ESP_FAIL;

    esp_codec_dev_sample_info_t in_fs = {
        .sample_rate     = AUDIO_SAMPLE_RATE,
        .channel         = MIC_TDM_SLOTS,
        .bits_per_sample = AUDIO_BITS,
    };
    ESP_RETURN_ON_ERROR(esp_codec_dev_open(s_in_dev, &in_fs), TAG, "es7210 open");
    ESP_RETURN_ON_ERROR(esp_codec_dev_set_in_gain(s_in_dev, 36.0), TAG, "es7210 gain");

    return ESP_OK;
}

// ── API pubblica ────────────────────────────────────────────────────────────

esp_err_t audio_board_init(void)
{
    ESP_LOGI(TAG, "Inizializzazione Waveshare ESP32-S3-AUDIO-Board…");

    ESP_RETURN_ON_ERROR(i2c_bus_init(), TAG, "I2C init");
    ESP_RETURN_ON_ERROR(tca9555_init(), TAG, "TCA9555 init");
    ESP_RETURN_ON_ERROR(i2s_duplex_init(), TAG, "I2S init");
    ESP_RETURN_ON_ERROR(codecs_init(), TAG, "codec init");

    audio_board_pa_enable(true);
    audio_board_set_volume(SPEAKER_VOLUME);

    ESP_LOGI(TAG, "Audio board pronta (ES8311 + ES7210, %d Hz)", AUDIO_SAMPLE_RATE);
    return ESP_OK;
}

esp_err_t audio_board_set_volume(int volume)
{
    if (!s_out_dev) return ESP_ERR_INVALID_STATE;
    if (volume < 0) volume = 0;
    if (volume > 100) volume = 100;
    return esp_codec_dev_set_out_vol(s_out_dev, volume);
}

esp_err_t audio_board_set_playback_rate(uint32_t sample_rate)
{
    if (!s_out_dev || !s_tx_handle) return ESP_ERR_INVALID_STATE;
    if (sample_rate == s_play_rate) return ESP_OK;

    esp_err_t ret = reconfig_tx_rate(sample_rate, I2S_SLOT_MODE_STEREO);
    if (ret != ESP_OK) return ret;

    return open_out_codec(sample_rate);
}

esp_err_t audio_board_begin_playback(void)
{
    audio_board_pa_enable(true);
    s_playback_active = true;
    return ESP_OK;
}

esp_err_t audio_board_end_playback(void)
{
    audio_board_spk_flush();
    vTaskDelay(pdMS_TO_TICKS(50));
    s_playback_active = false;
    return ESP_OK;
}

bool audio_board_is_playback_active(void)
{
    return s_playback_active;
}

void audio_board_set_duplex_mic(bool enable)
{
    s_duplex_mic = enable;
}

esp_err_t audio_board_recover_input(void)
{
    s_playback_active = false;

    if (s_rx_handle)
        i2s_channel_enable(s_rx_handle);

    if (!s_in_dev)
        return ESP_ERR_INVALID_STATE;

    esp_codec_dev_sample_info_t in_fs = {
        .sample_rate     = AUDIO_SAMPLE_RATE,
        .channel         = MIC_TDM_SLOTS,
        .bits_per_sample = AUDIO_BITS,
    };

    esp_err_t ret = esp_codec_dev_close(s_in_dev);
    if (ret != ESP_OK && ret != ESP_CODEC_DEV_WRONG_STATE)
        ESP_LOGW(TAG, "recover: close in_dev %s", esp_err_to_name(ret));

    ret = esp_codec_dev_open(s_in_dev, &in_fs);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "recover: reopen in_dev fallito");
        return ret;
    }

    int16_t probe[MIC_TDM_SLOTS * 64];
    size_t bytes = sizeof(probe);
    if (esp_codec_dev_read(s_in_dev, probe, (int)bytes) != ESP_CODEC_DEV_OK) {
        ESP_LOGE(TAG, "recover: lettura test fallita");
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Input audio ripristinato");
    return ESP_OK;
}

esp_err_t audio_board_play_ack_tone(void)
{
    if (!s_out_dev) return ESP_ERR_INVALID_STATE;

    const int freq_hz = 880;
    const int ms      = 150;
    const int n       = (AUDIO_SAMPLE_RATE * ms) / 1000;
    static int16_t stereo[512];

    if (n * 2 > (int)(sizeof(stereo) / sizeof(stereo[0])))
        return ESP_ERR_INVALID_SIZE;

    audio_board_pa_enable(true);
    bool was_active = s_playback_active;
    s_playback_active = true;

    for (int i = 0; i < n; i++) {
        int16_t s = (int16_t)(12000.0f * sinf(2.0f * (float)M_PI * freq_hz * i / AUDIO_SAMPLE_RATE));
        stereo[i * 2]     = s;
        stereo[i * 2 + 1] = s;
    }

    esp_codec_dev_write(s_out_dev, stereo, n * 2 * (int)sizeof(int16_t));
    vTaskDelay(pdMS_TO_TICKS(ms + 30));
    s_playback_active = was_active;
    return ESP_OK;
}

int audio_board_mic_read(int16_t *tdm_out, size_t samples)
{
    if (!s_in_dev || !tdm_out) return -1;

    if (s_playback_active && !s_duplex_mic) {
        memset(tdm_out, 0, samples * MIC_TDM_SLOTS * sizeof(int16_t));
        return (int)samples;
    }

    size_t bytes = samples * MIC_TDM_SLOTS * sizeof(int16_t);
    int ret = esp_codec_dev_read(s_in_dev, tdm_out, (int)bytes);
    if (ret != ESP_CODEC_DEV_OK) {
        ESP_LOGW(TAG, "mic_read fallita (%d), tentativo recovery RX", ret);
        if (s_rx_handle)
            i2s_channel_enable(s_rx_handle);
        return -1;
    }
    return (int)samples;
}

int audio_board_spk_write(const int16_t *mono, size_t samples)
{
    if (!s_out_dev || !mono) return -1;

    static int16_t stereo_buf[UDP_CHUNK_SAMPLES * 2];
    if (samples > UDP_CHUNK_SAMPLES) samples = UDP_CHUNK_SAMPLES;

    for (size_t i = 0; i < samples; i++) {
        stereo_buf[i * 2]     = mono[i];
        stereo_buf[i * 2 + 1] = mono[i];
    }

    size_t bytes = samples * 2 * sizeof(int16_t);
    int ret = esp_codec_dev_write(s_out_dev, stereo_buf, (int)bytes);
    if (ret != ESP_CODEC_DEV_OK) return -1;
    return (int)samples;
}

void audio_board_spk_flush(void)
{
    if (!s_out_dev) return;
    static const int16_t silence[128] = {0};
    esp_codec_dev_write(s_out_dev, (void *)silence, sizeof(silence));
}
