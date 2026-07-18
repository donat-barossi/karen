#include "udp_transport.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "freertos/queue.h"
#include "lwip/sockets.h"
#include <string.h>
#include <arpa/inet.h>
#include <errno.h>

static const char *TAG = "udp_transport";

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t  type;
    uint8_t  reserved;
    uint16_t seq;
} karn_header_t;

#define MAX_RESPONSE_PKTS 512

typedef struct {
    int16_t  data[UDP_CHUNK_SAMPLES];
    uint16_t nsamples;
    bool     valid;
} response_slot_t;

static int              s_tx_sock  = -1;
static int              s_rx_sock  = -1;
static struct sockaddr_in s_jetson_addr;

static response_slot_t *s_response_slots = NULL;
static uint16_t         s_last_seq    = 0;
static bool             s_stream_done = false;
static volatile bool    s_armed       = false;
static volatile bool    s_ring_active  = false;
static volatile bool    s_ring_pending = false;
static volatile bool    s_ring_stop    = false;
static volatile bool    s_ring_listen  = false;
static SemaphoreHandle_t s_pkt_sem    = NULL;
static size_t           s_pkts_recv   = 0;

typedef struct {
    uint16_t seq;
    uint16_t nsamples;
    bool     is_end;
    int16_t *data;   // buffer in PSRAM, liberato dal task TX
} udp_tx_job_t;

static QueueHandle_t    s_tx_queue    = NULL;

static bool _send_packet(uint8_t type, uint16_t seq,
                          const void *payload, size_t payload_len)
{
    static uint8_t pkt[8 + UDP_CHUNK_BYTES];
    karn_header_t *hdr = (karn_header_t *)pkt;
    hdr->magic    = htonl(PACKET_MAGIC);
    hdr->type     = type;
    hdr->reserved = 0;
    hdr->seq      = htons(seq);

    size_t total = sizeof(karn_header_t);
    if (payload && payload_len > 0) {
        memcpy(pkt + total, payload, payload_len);
        total += payload_len;
    }

    ssize_t sent = sendto(s_tx_sock, pkt, total, 0,
                          (struct sockaddr *)&s_jetson_addr, sizeof(s_jetson_addr));
    return sent == (ssize_t)total;
}

static void udp_tx_task(void *arg)
{
    (void)arg;
    udp_tx_job_t job;

    ESP_LOGI(TAG, "Task TX UDP avviato (pace=%dms)", UDP_TX_PACE_MS);

    while (true) {
        if (xQueueReceive(s_tx_queue, &job, portMAX_DELAY) != pdTRUE)
            continue;

        if (job.is_end) {
            _send_packet(PKT_TYPE_END_AUDIO, 0, NULL, 0);
            ESP_LOGD(TAG, "TX END_AUDIO");
        } else if (job.data && job.nsamples > 0) {
            _send_packet(PKT_TYPE_AUDIO, job.seq, job.data,
                          job.nsamples * sizeof(int16_t));
            vTaskDelay(pdMS_TO_TICKS(UDP_TX_PACE_MS));
        }

        if (job.data)
            heap_caps_free(job.data);
    }
}

static void notify_packet(void)
{
    if (s_pkt_sem)
        xSemaphoreGive(s_pkt_sem);
}

static bool store_response_packet(uint8_t pkt_type, uint16_t seq,
                                  const void *payload, size_t payload_bytes)
{
    if (!s_armed && !s_ring_active) {
        ESP_LOGW(TAG, "Pacchetto risposta scartato (RX non armato) seq=%u", seq);
        return false;
    }

    if (seq >= MAX_RESPONSE_PKTS) {
        ESP_LOGW(TAG, "seq %u fuori range", seq);
        return false;
    }

    size_t samples = payload_bytes / sizeof(int16_t);
    if (samples > UDP_CHUNK_SAMPLES)
        samples = UDP_CHUNK_SAMPLES;

    response_slot_t *slot = &s_response_slots[seq];
    if (!slot->valid) {
        memcpy(slot->data, payload, samples * sizeof(int16_t));
        slot->nsamples = (uint16_t)samples;
        slot->valid    = true;
        notify_packet();
    }

    if (seq > s_last_seq)
        s_last_seq = seq;

    s_pkts_recv++;

    if (pkt_type == PKT_TYPE_END_RESPONSE) {
        s_stream_done = true;
        notify_packet();
    }

    return true;
}

static void udp_recv_task(void *arg)
{
    (void)arg;
    static uint8_t pkt[8 + UDP_CHUNK_BYTES + 4];

    struct timeval tv = { .tv_sec = 0, .tv_usec = 200000 };
    setsockopt(s_rx_sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    ESP_LOGI(TAG, "Task RX UDP avviato");

    while (true) {
        struct sockaddr_in src;
        socklen_t src_len = sizeof(src);
        ssize_t len = recvfrom(s_rx_sock, pkt, sizeof(pkt), 0,
                               (struct sockaddr *)&src, &src_len);
        if (len < (ssize_t)sizeof(karn_header_t))
            continue;

        karn_header_t hdr;
        memcpy(&hdr, pkt, sizeof(hdr));
        if (ntohl(hdr.magic) != PACKET_MAGIC)
            continue;

        uint8_t pkt_type = hdr.type;
        uint16_t seq     = ntohs(hdr.seq);

        if (pkt_type == PKT_TYPE_START_RING) {
            s_ring_active  = true;
            s_ring_pending = true;
            s_ring_stop    = false;
            udp_response_arm();
            ESP_LOGI(TAG, "RX START_RING → ring attivo");
            continue;
        }
        if (pkt_type == PKT_TYPE_STOP_RING) {
            s_ring_active  = false;
            s_ring_listen  = false;
            s_ring_stop    = true;
            udp_response_disarm();
            ESP_LOGI(TAG, "RX STOP_RING → ring fermato");
            continue;
        }

        if (pkt_type != PKT_TYPE_RESPONSE && pkt_type != PKT_TYPE_END_RESPONSE)
            continue;

        size_t payload_bytes = (size_t)len - sizeof(karn_header_t);
        if (store_response_packet(pkt_type, seq,
                                  pkt + sizeof(karn_header_t), payload_bytes)) {
            ESP_LOGD(TAG, "RX seq=%u type=0x%02x bytes=%u (tot=%u)",
                     seq, pkt_type, (unsigned)payload_bytes, (unsigned)s_pkts_recv);
        }
    }
}

esp_err_t udp_transport_init(void)
{
    s_tx_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_tx_sock < 0) {
        ESP_LOGE(TAG, "socket TX fallito");
        return ESP_FAIL;
    }

    memset(&s_jetson_addr, 0, sizeof(s_jetson_addr));
    s_jetson_addr.sin_family = AF_INET;
    s_jetson_addr.sin_port   = htons(AUDIO_TX_PORT);
    inet_aton(JETSON_IP, &s_jetson_addr.sin_addr);

    s_rx_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s_rx_sock < 0) {
        ESP_LOGE(TAG, "socket RX fallito");
        return ESP_FAIL;
    }

    int reuse = 1;
    setsockopt(s_rx_sock, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    struct sockaddr_in rx_addr = {
        .sin_family = AF_INET,
        .sin_port   = htons(AUDIO_RX_PORT),
        .sin_addr   = { .s_addr = htonl(INADDR_ANY) },
    };
    if (bind(s_rx_sock, (struct sockaddr *)&rx_addr, sizeof(rx_addr)) < 0) {
        ESP_LOGE(TAG, "bind RX :%d fallito errno=%d", AUDIO_RX_PORT, errno);
        return ESP_FAIL;
    }

    int rcvbuf = 131072;
    setsockopt(s_rx_sock, SOL_SOCKET, SO_RCVBUF, &rcvbuf, sizeof(rcvbuf));

    if (!s_response_slots) {
        s_response_slots = (response_slot_t *)heap_caps_calloc(
            MAX_RESPONSE_PKTS, sizeof(response_slot_t), MALLOC_CAP_SPIRAM);
        if (!s_response_slots) {
            ESP_LOGE(TAG, "alloc buffer risposta fallita");
            return ESP_ERR_NO_MEM;
        }
    }

    if (!s_pkt_sem)
        s_pkt_sem = xSemaphoreCreateCounting(64, 0);

    if (!s_tx_queue) {
        s_tx_queue = xQueueCreate(UDP_TX_QUEUE_DEPTH, sizeof(udp_tx_job_t));
        if (!s_tx_queue) {
            ESP_LOGE(TAG, "alloc coda TX fallita");
            return ESP_ERR_NO_MEM;
        }
        ESP_LOGI(TAG, "Coda TX: %d slot × %u byte (metadati)",
                 UDP_TX_QUEUE_DEPTH, (unsigned)sizeof(udp_tx_job_t));
    }

    xTaskCreatePinnedToCore(udp_tx_task, "udp_tx", 4096, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(udp_recv_task, "udp_rx", 4096, NULL, 6, NULL, 1);

    ESP_LOGI(TAG, "UDP pronto → Jetson %s:%d | ascolto :%d",
             JETSON_IP, AUDIO_TX_PORT, AUDIO_RX_PORT);
    return ESP_OK;
}

static bool _tx_enqueue(udp_tx_job_t *job)
{
    if (!s_tx_queue || !job)
        return false;
    if (xQueueSend(s_tx_queue, job, pdMS_TO_TICKS(100)) != pdTRUE) {
        if (job->data) {
            heap_caps_free(job->data);
            job->data = NULL;
        }
        ESP_LOGW(TAG, "Coda TX piena, pacchetto scartato");
        return false;
    }
    return true;
}

bool udp_send_audio(const int16_t *audio_pcm16, size_t samples, uint16_t seq)
{
    if (samples > UDP_CHUNK_SAMPLES)
        samples = UDP_CHUNK_SAMPLES;
    if (!audio_pcm16 || samples == 0)
        return false;

    size_t bytes = samples * sizeof(int16_t);
    int16_t *copy = (int16_t *)heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM);
    if (!copy) {
        ESP_LOGE(TAG, "alloc TX buffer fallita (%u byte)", (unsigned)bytes);
        return false;
    }
    memcpy(copy, audio_pcm16, bytes);

    udp_tx_job_t job = {
        .seq      = seq,
        .nsamples = (uint16_t)samples,
        .is_end   = false,
        .data     = copy,
    };
    return _tx_enqueue(&job);
}

bool udp_send_end_of_audio(void)
{
    udp_tx_job_t job = {
        .seq      = 0,
        .nsamples = 0,
        .is_end   = true,
        .data     = NULL,
    };
    return _tx_enqueue(&job);
}

void udp_response_reset(void)
{
    if (s_response_slots)
        memset(s_response_slots, 0, MAX_RESPONSE_PKTS * sizeof(response_slot_t));
    s_last_seq    = 0;
    s_stream_done = false;
    s_pkts_recv   = 0;
    if (s_pkt_sem)
        xSemaphoreTake(s_pkt_sem, 0);
}

void udp_response_arm(void)
{
    udp_response_reset();
    s_armed = true;
    ESP_LOGI(TAG, "RX risposta armato");
}

void udp_response_disarm(void)
{
    s_armed = false;
}

bool udp_response_is_complete(void)
{
    return s_stream_done;
}

uint16_t udp_response_last_seq(void)
{
    return s_last_seq;
}

bool udp_response_slot_valid(uint16_t seq)
{
    return seq < MAX_RESPONSE_PKTS && s_response_slots[seq].valid;
}

const int16_t *udp_response_slot_data(uint16_t seq, uint16_t *nsamples)
{
    if (!udp_response_slot_valid(seq))
        return NULL;
    if (nsamples)
        *nsamples = s_response_slots[seq].nsamples;
    return s_response_slots[seq].data;
}

size_t udp_response_count_valid(void)
{
    size_t n = 0;
    for (uint16_t i = 0; i <= s_last_seq && i < MAX_RESPONSE_PKTS; i++)
        if (s_response_slots[i].valid) n++;
    return n;
}

size_t udp_response_packets_received(void)
{
    return s_pkts_recv;
}

bool udp_response_wait_event(uint32_t timeout_ms)
{
    if (!s_pkt_sem)
        return false;
    return xSemaphoreTake(s_pkt_sem, pdMS_TO_TICKS(timeout_ms)) == pdTRUE;
}

bool udp_ring_is_active(void)
{
    return s_ring_active;
}

bool udp_ring_listen_active(void)
{
    return s_ring_listen;
}

void udp_ring_set_listen(bool enable)
{
    s_ring_listen = enable;
}

bool udp_ring_pending(void)
{
    return s_ring_pending;
}

bool udp_ring_stop_pending(void)
{
    return s_ring_stop;
}

void udp_ring_clear_pending(void)
{
    s_ring_pending = false;
}

void udp_ring_clear_stop(void)
{
    s_ring_stop = false;
}

void udp_transport_deinit(void)
{
    if (s_tx_sock >= 0) { close(s_tx_sock); s_tx_sock = -1; }
    if (s_rx_sock >= 0) { close(s_rx_sock); s_rx_sock = -1; }
}
