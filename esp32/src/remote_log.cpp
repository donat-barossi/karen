#include "remote_log.h"
#include "config.h"
#include "udp_transport.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "esp_system.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static const char *TAG = "remote_log";
static bool s_ready = false;

void remote_log_init(void)
{
    s_ready = true;
    remote_log_send("boot remote_log ready");
}

void remote_log_send(const char *line)
{
    if (!s_ready || !line || !line[0])
        return;
    if (!udp_send_log_line(line))
        ESP_LOGD(TAG, "log non inviato: %.40s…", line);
}

void remote_log_printf(const char *fmt, ...)
{
    char buf[REMOTE_LOG_MAX_LEN];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    remote_log_send(buf);
}

void remote_log_heartbeat(int state, bool wifi, bool ww_active,
                          uint32_t tx_fail, uint32_t mic_rms)
{
    remote_log_printf(
        "HB state=%d wifi=%d ww=%d heap=%lu uptime=%lus tx_fail=%lu mic_rms=%lu",
        state,
        wifi ? 1 : 0,
        ww_active ? 1 : 0,
        (unsigned long)esp_get_free_heap_size(),
        (unsigned long)(esp_timer_get_time() / 1000000ULL),
        (unsigned long)tx_fail,
        (unsigned long)mic_rms);
}
