#include "status_led.h"

#include "config.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"

static const char *TAG = "status_led";

static led_strip_handle_t s_strip = NULL;
static TaskHandle_t       s_anim_task = NULL;
static bool               s_ready = false;
static volatile bool      s_anim_run = false;

/*
 * L'anello Waveshare usa WS2812 in ordine RGB sul filo, mentre led_strip RMT
 * invia sempre byte GRB. Per ottenere verde sul hardware: set_pixel(R,0,0).
 */
static inline void led_set_green(uint32_t index, uint8_t level)
{
    led_strip_set_pixel(s_strip, index, level, 0, 0);
}

static void draw_chase_frame(int head)
{
    led_strip_clear(s_strip);

    for (int i = 0; i < WAKE_LED_COUNT; i++) {
        int dist = (head - i + WAKE_LED_COUNT) % WAKE_LED_COUNT;
        if (dist >= WAKE_LED_CHASE_TAIL)
            continue;

        uint8_t level = (uint8_t)(WAKE_LED_BRIGHTNESS -
                                  (dist * WAKE_LED_BRIGHTNESS / WAKE_LED_CHASE_TAIL));
        if (level > 0)
            led_set_green(i, level);
    }

    led_strip_refresh(s_strip);
}

static void chase_task(void *arg)
{
    (void)arg;
    int head = 0;

    while (s_anim_run) {
        draw_chase_frame(head);
        head = (head + 1) % WAKE_LED_COUNT;
        vTaskDelay(pdMS_TO_TICKS(WAKE_LED_CHASE_MS));
    }

    led_strip_clear(s_strip);
    led_strip_refresh(s_strip);
    s_anim_task = NULL;
    vTaskDelete(NULL);
}

esp_err_t status_led_init(void)
{
#if !WAKE_ACK_LED
    return ESP_OK;
#endif

    led_strip_config_t strip_cfg = {
        .strip_gpio_num   = WAKE_LED_GPIO,
        .max_leds         = WAKE_LED_COUNT,
        .led_pixel_format = LED_PIXEL_FORMAT_GRB,
        .led_model        = LED_MODEL_WS2812,
        .flags = { .invert_out = false },
    };

    led_strip_rmt_config_t rmt_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000,
        .mem_block_symbols = 64,
        .flags = { .with_dma = false },
    };

    esp_err_t ret = led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip);
    if (ret != ESP_OK) {
        ESP_LOGW(TAG, "Anello RGB non disponibile: %s", esp_err_to_name(ret));
        return ret;
    }

    led_strip_clear(s_strip);
    s_ready = true;
    ESP_LOGI(TAG, "Anello RGB pronto (%d LED @ GPIO%d)", WAKE_LED_COUNT, WAKE_LED_GPIO);
    return ESP_OK;
}

bool status_led_available(void)
{
    return s_ready;
}

void status_led_listening_on(void)
{
#if !WAKE_ACK_LED
    return;
#endif
    if (!s_ready || !s_strip || s_anim_run)
        return;

    s_anim_run = true;
    xTaskCreatePinnedToCore(chase_task, "led_chase", 3072, NULL, 3, &s_anim_task, 1);
}

void status_led_listening_off(void)
{
#if !WAKE_ACK_LED
    return;
#endif
    if (!s_ready || !s_strip)
        return;

    s_anim_run = false;
    if (s_anim_task) {
        vTaskDelay(pdMS_TO_TICKS(WAKE_LED_CHASE_MS + 30));
    } else {
        led_strip_clear(s_strip);
        led_strip_refresh(s_strip);
    }
}
