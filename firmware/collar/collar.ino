/*
 * IMU-Based Assistance Dog Alert Verification and Emergency Escalation System
 * ---------------------------------------------------------------------------
 * Collar (sensing node) firmware for ESP32 + MPU6050.
 *
 * Detects the trained double-spin alert behaviour of a seizure-alert assistance
 * dog, verifies it across several consecutive windows to reject one-off motion,
 * and relays a confirmed alert to the owner's phone over BLE.  Everything after
 * that -- the acknowledgement window, the caregiver page, the emergency
 * escalation -- happens on the phone and the backend; see docs/02-architecture.md.
 *
 * Structure
 * ---------
 * The signal-processing core lives in src/ as plain C with no Arduino
 * dependency (ca_features, ca_forest, ca_verify, ca_ring), so it can be
 * compiled and tested on a host -- see firmware/test/.  This file is only the
 * hardware glue: sampling, BLE, indicators, logging.
 *
 * Core assignment
 * ---------------
 * Core 0 samples the IMU on a hardware-timer tick.  Core 1 runs classification,
 * BLE and SD.  Sampling must not jitter -- the frequency features assume a
 * uniform 51.2 Hz -- so it gets a core to itself and the expensive work (a
 * 133-point DFT per signal) is kept off it.
 *
 * Board:    ESP32-WROOM-32 DevKit
 * Toolchain: Arduino IDE 2.3.x with esp32 board support 2.0.x
 * Libraries: Wire, SPI, SD, ESP32 BLE Arduino (bundled with the core)
 *
 * Wiring is documented in docs/05-hardware.md.
 */

#include <Arduino.h>
#include <math.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <SD.h>
#include <SPI.h>
#include <Wire.h>
#include <string.h>

extern "C" {
#include "src/ca_features.h"
#include "src/ca_forest.h"
#include "src/ca_ring.h"
#include "src/ca_verify.h"
#include "src/model.h"
}

/* ------------------------------------------------------------------------ */
/* configuration                                                            */
/* ------------------------------------------------------------------------ */

#define FIRMWARE_VERSION "1.0.0-bench"

/* Bench integration only: allows a manual test alert over BLE. Set to 0 before any non-demo use. */
#define ENABLE_SERIAL_TEST_ALERTS 1
/* MicroSD is deferred. Do not initialise SPI while GPIO18/19 are used by the red LED and buzzer. */
#define ENABLE_SD_LOGGING 0

/* Identifies this collar, and therefore this dog, in every alert. */
#define DOG_ID "stuart"

/* --- pins (see docs/05-hardware.md) --- */
static const int PIN_SDA = 21;
static const int PIN_SCL = 22;
static const int PIN_LED_STATUS = 4;  /* green: armed (user bench wiring) */
static const int PIN_LED_ALERT = 18;  /* red: alert raised (user bench wiring) */
static const int PIN_BUZZER = 19;     /* buzzer (user bench wiring) */
static const int PIN_SD_CS = 5;
static const int PIN_BATTERY = 34; /* ADC1, input-only */

/* --- MPU6050 --- */
static const uint8_t MPU_ADDRESS = 0x68;
static const uint8_t MPU_PWR_MGMT_1 = 0x6B;
static const uint8_t MPU_CONFIG = 0x1A;
static const uint8_t MPU_GYRO_CONFIG = 0x1B;
static const uint8_t MPU_ACCEL_CONFIG = 0x1C;
static const uint8_t MPU_ACCEL_XOUT_H = 0x3B;
static const uint8_t MPU_WHO_AM_I = 0x75;

/* The training data was recorded on a Shimmer3 in m/s^2 and deg/s.  The model's
 * thresholds are in those units, so the raw MPU6050 counts must be converted --
 * not merely scaled to "some consistent unit".  A wrong constant here does not
 * crash anything; it quietly moves every feature off the model's operating
 * point, which is the hardest class of bug to notice in the field.
 *
 * Ranges are chosen to match the spin's dynamics: a trained spin peaks around
 * 500-600 deg/s, so +/-2000 deg/s leaves headroom without wasting resolution,
 * and +/-8 g covers the impulsive paw-strikes during a rapid turn. */
static const float ACCEL_LSB_PER_G = 4096.0f;   /* +/-8 g  */
static const float GYRO_LSB_PER_DPS = 16.4f;    /* +/-2000 deg/s */
static const float GRAVITY_M_S2 = 9.80665f;

/* Sampling period derived from the exported model, so retraining at a different
 * rate cannot leave the firmware sampling at the old one. */
static const uint32_t SAMPLE_PERIOD_US =
    (uint32_t)(1000000.0f / CA_SAMPLE_RATE_HZ + 0.5f);

/* --- BLE --- */
#define ALERT_SERVICE_UUID "6f1d0001-b5a3-f393-e0a9-e50e24dcca9e"
#define ALERT_CHAR_UUID "6f1d0002-b5a3-f393-e0a9-e50e24dcca9e"
#define STATUS_CHAR_UUID "6f1d0003-b5a3-f393-e0a9-e50e24dcca9e"

/* An alert is retransmitted until the phone acknowledges it, because a BLE
 * notification is fire-and-forget: the collar gets no indication that the
 * phone's app was foregrounded, or even that the packet was parsed.  The relay
 * de-duplicates on (dog_id, sequence, uptime), so repeats are harmless. */
static const uint32_t ALERT_RETRANSMIT_MS = 3000u;
static const uint8_t ALERT_MAX_RETRANSMITS = 10u;

/* ------------------------------------------------------------------------ */
/* state                                                                    */
/* ------------------------------------------------------------------------ */

static ca_ring g_ring;
static ca_verify_gate g_gate;
static ca_scratch g_scratch;                    /* ~12 kB; must not be on a stack */
static ca_real g_features[CA_FEATURE_COUNT];
static ca_real g_window[CA_WINDOW_SAMPLES * CA_N_CHANNELS];

static BLEServer *g_server = nullptr;
static BLECharacteristic *g_alert_characteristic = nullptr;
static BLECharacteristic *g_status_characteristic = nullptr;
static volatile bool g_phone_connected = false;

static uint32_t g_alert_sequence = 0u;
static bool g_alert_outstanding = false;
static uint32_t g_alert_last_sent_ms = 0u;
static uint8_t g_alert_send_count = 0u;
static char g_alert_payload[192];

static portMUX_TYPE g_timer_mux = portMUX_INITIALIZER_UNLOCKED;
static volatile bool g_sample_due = false;
static hw_timer_t *g_sample_timer = nullptr;

/* Explicit bench-only threshold mode. The 250 deg/s starting value is a
 * provisional demo setting, NOT a validated detector threshold. Calibrate it
 * from logged normal/target movement before making any performance claims. */
static volatile float g_latest_gyro_mag_dps = 0.0f;
static volatile uint32_t g_sample_counter = 0u;
static bool g_threshold_test_mode = false;
static bool g_next_alert_is_threshold_test = false;
static float g_test_gyro_threshold_dps = 250.0f;
static uint8_t g_test_consecutive_samples = 0u;
static uint32_t g_last_test_trigger_ms = 0u;
static uint32_t g_last_seen_sample_counter = 0u;
static uint32_t g_last_test_telemetry_ms = 0u;
static const uint8_t TEST_REQUIRED_CONSECUTIVE_SAMPLES = 3u;
static const uint32_t TEST_COOLDOWN_MS = 6000u;

static bool g_sd_available = false;

/* ------------------------------------------------------------------------ */
/* MPU6050                                                                  */
/* ------------------------------------------------------------------------ */

static void mpu_write(uint8_t reg, uint8_t value)
{
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(reg);
    Wire.write(value);
    Wire.endTransmission();
}

static uint8_t mpu_read(uint8_t reg)
{
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(reg);
    Wire.endTransmission(false);
    Wire.requestFrom((int)MPU_ADDRESS, 1);
    return Wire.available() ? Wire.read() : 0u;
}

static bool mpu_begin()
{
    Wire.begin(PIN_SDA, PIN_SCL, 400000);

    uint8_t who = mpu_read(MPU_WHO_AM_I);
    if (who != 0x68 && who != 0x70 && who != 0x71) {
        Serial.printf("MPU6050 WHO_AM_I returned 0x%02X; sensor not found\n", who);
        return false;
    }

    mpu_write(MPU_PWR_MGMT_1, 0x00); /* wake */
    delay(100);
    mpu_write(MPU_PWR_MGMT_1, 0x01); /* clock from the X gyro: more stable */

    /* DLPF at 21 Hz.  Sampling at 51.2 Hz puts Nyquist at 25.6 Hz, so anything
     * above that aliases straight into the band the spectral features read.
     * The spin's energy lives well below 10 Hz; the noise this removes is
     * collar rattle and paw impact ringing. */
    mpu_write(MPU_CONFIG, 0x04);

    mpu_write(MPU_ACCEL_CONFIG, 0x10); /* +/-8 g */
    mpu_write(MPU_GYRO_CONFIG, 0x18);  /* +/-2000 deg/s */
    delay(50);
    return true;
}

/* Read one sample into ax, ay, az (m/s^2), gx, gy, gz (deg/s). */
static bool mpu_read_sample(ca_real *out)
{
    Wire.beginTransmission(MPU_ADDRESS);
    Wire.write(MPU_ACCEL_XOUT_H);
    if (Wire.endTransmission(false) != 0) {
        return false;
    }
    /* 14 bytes: 6 accel, 2 temperature, 6 gyro. */
    if (Wire.requestFrom((int)MPU_ADDRESS, 14) != 14) {
        return false;
    }

    int16_t raw[7];
    for (int i = 0; i < 7; ++i) {
        raw[i] = (int16_t)((Wire.read() << 8) | Wire.read());
    }

    out[0] = ((ca_real)raw[0] / ACCEL_LSB_PER_G) * GRAVITY_M_S2;
    out[1] = ((ca_real)raw[1] / ACCEL_LSB_PER_G) * GRAVITY_M_S2;
    out[2] = ((ca_real)raw[2] / ACCEL_LSB_PER_G) * GRAVITY_M_S2;
    /* raw[3] is temperature, unused. */
    out[3] = (ca_real)raw[4] / GYRO_LSB_PER_DPS;
    out[4] = (ca_real)raw[5] / GYRO_LSB_PER_DPS;
    out[5] = (ca_real)raw[6] / GYRO_LSB_PER_DPS;
    return true;
}

/* ------------------------------------------------------------------------ */
/* BLE                                                                      */
/* ------------------------------------------------------------------------ */

class ConnectionCallbacks : public BLEServerCallbacks {
    void onConnect(BLEServer *server) override
    {
        (void)server;
        g_phone_connected = true;
        Serial.println("relay connected");
    }

    void onDisconnect(BLEServer *server) override
    {
        g_phone_connected = false;
        Serial.println("relay disconnected; re-advertising");
        /* Keep advertising: a collar that stops advertising after the phone
         * walks out of range is a collar that never reconnects. */
        server->startAdvertising();
    }
};

/* The phone writes the alert id back once it has taken responsibility for the
 * escalation.  Until then the collar keeps retransmitting. */
class AlertAckCallbacks : public BLECharacteristicCallbacks {
    void onWrite(BLECharacteristic *characteristic) override
    {
        String value = characteristic->getValue();
        if (value.startsWith("ACK:")) {
            Serial.printf("relay acknowledged: %s\n", value.c_str());
            g_alert_outstanding = false;
            digitalWrite(PIN_LED_ALERT, LOW);
        }
    }
};

static void ble_begin()
{
    BLEDevice::init("AssistDogCollar-" DOG_ID);
    g_server = BLEDevice::createServer();
    g_server->setCallbacks(new ConnectionCallbacks());

    BLEService *service = g_server->createService(ALERT_SERVICE_UUID);

    g_alert_characteristic = service->createCharacteristic(
        ALERT_CHAR_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY |
            BLECharacteristic::PROPERTY_WRITE);
    g_alert_characteristic->addDescriptor(new BLE2902());
    g_alert_characteristic->setCallbacks(new AlertAckCallbacks());

    g_status_characteristic = service->createCharacteristic(
        STATUS_CHAR_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY);
    g_status_characteristic->addDescriptor(new BLE2902());

    service->start();

    BLEAdvertising *advertising = BLEDevice::getAdvertising();
    advertising->addServiceUUID(ALERT_SERVICE_UUID);
    advertising->setScanResponse(true);
    BLEDevice::startAdvertising();
    Serial.println("BLE advertising as AssistDogCollar-" DOG_ID);
}

static float battery_volts()
{
    /* 2:1 divider onto a 3.3 V, 12-bit ADC. */
    return (float)analogRead(PIN_BATTERY) * (3.3f / 4095.0f) * 2.0f;
}

static void publish_status()
{
    if (!g_phone_connected || g_status_characteristic == nullptr) {
        return;
    }
    char payload[128];
    snprintf(payload, sizeof(payload),
             "{\"dog_id\":\"%s\",\"uptime_ms\":%lu,\"battery_v\":%.2f,"
             "\"firmware\":\"%s\",\"sd\":%s}",
             DOG_ID, (unsigned long)millis(), battery_volts(), FIRMWARE_VERSION,
             g_sd_available ? "true" : "false");
    g_status_characteristic->setValue((uint8_t *)payload, strlen(payload));
    g_status_characteristic->notify();
}

/* ------------------------------------------------------------------------ */
/* alert emission                                                           */
/* ------------------------------------------------------------------------ */

static void log_line(const char *line)
{
    if (!g_sd_available) {
        return;
    }
    File file = SD.open("/alerts.log", FILE_APPEND);
    if (!file) {
        return;
    }
    file.println(line);
    file.close();
}

static void raise_alert(const ca_alert &alert)
{
    ++g_alert_sequence;

    /* The payload is exactly the DetectionEvent the relay expects; see
     * escalation/model.py.  uptime_ms is what makes the alert id stable across
     * retransmissions, so it must be the gate's firing time and not "now". */
    snprintf(g_alert_payload, sizeof(g_alert_payload),
             "{\"dog_id\":\"%s\",\"sequence\":%lu,\"device_uptime_ms\":%lu,"
             "\"confidence\":%.4f,\"votes\":%d,\"window_count\":%d,"
             "\"firmware_version\":\"%s\"}",
             DOG_ID, (unsigned long)g_alert_sequence,
             (unsigned long)alert.timestamp_ms, (double)alert.confidence,
             alert.votes, alert.window_count,
             g_next_alert_is_threshold_test ? "1.0.0-bench-threshold-test" : FIRMWARE_VERSION);
    g_next_alert_is_threshold_test = false;

    g_alert_outstanding = true;
    g_alert_send_count = 0u;
    g_alert_last_sent_ms = 0u; /* forces an immediate first transmission */

    digitalWrite(PIN_LED_ALERT, HIGH);
    digitalWrite(PIN_LED_STATUS,LOW);
    /* A short local chirp: if a person is nearby, the fastest escalation path is
     * the one that does not involve a phone at all. */
    tone(PIN_BUZZER, 2000, 300);
    delay(300);
    digitalWrite(PIN_LED_ALERT, LOW);
    digitalWrite(PIN_LED_STATUS,HIGH);
    Serial.printf("ALERT %s\n", g_alert_payload);
    log_line(g_alert_payload);
}

#if ENABLE_SERIAL_TEST_ALERTS
/*
 * Bench-only end-to-end test. Open Serial Monitor at 115200 baud, ensure the
 * Python BLE relay is already connected, then send TEST_ALERT. This deliberately
 * bypasses the classifier and tests only BLE -> relay -> backend -> dashboard.
 */
static char g_serial_command[32];
static size_t g_serial_command_len = 0;

static void service_serial_test_command()
{
    while (Serial.available() > 0) {
        const char ch = (char)Serial.read();
        if (ch == '\r') {
            continue;
        }
        if (ch == '\n') {
            g_serial_command[g_serial_command_len] = '\0';
            if (strcmp(g_serial_command, "TEST_MODE ON") == 0) {
                g_threshold_test_mode = true;
                g_test_consecutive_samples = 0u;
                g_last_seen_sample_counter = g_sample_counter;
                Serial.printf("THRESHOLD TEST MODE ON; gyro magnitude threshold=%.1f deg/s; %u consecutive samples\n",
                              g_test_gyro_threshold_dps, TEST_REQUIRED_CONSECUTIVE_SAMPLES);
                Serial.println("TEST ONLY: threshold trigger bypasses the ML classifier; not a validated detector");
            } else if (strcmp(g_serial_command, "TEST_MODE OFF") == 0) {
                g_threshold_test_mode = false;
                g_test_consecutive_samples = 0u;
                Serial.println("THRESHOLD TEST MODE OFF; ML classification resumed");
            } else if (strncmp(g_serial_command, "THRESHOLD ", 10) == 0) {
                char *end = nullptr;
                float value = strtof(g_serial_command + 10, &end);
                if (end != g_serial_command + 10 && *end == '\0' && value >= 20.0f && value <= 2000.0f) {
                    g_test_gyro_threshold_dps = value;
                    g_test_consecutive_samples = 0u;
                    Serial.printf("Test gyro magnitude threshold set to %.1f deg/s\n", g_test_gyro_threshold_dps);
                } else {
                    Serial.println("Usage: THRESHOLD <20..2000> (deg/s)");
                }
            } else if (strcmp(g_serial_command, "TEST_STATUS") == 0) {
                Serial.printf("test_mode=%s threshold=%.1f deg/s latest_gyro_magnitude=%.1f deg/s\n",
                              g_threshold_test_mode ? "ON" : "OFF", g_test_gyro_threshold_dps,
                              (double)g_latest_gyro_mag_dps);
            } else if (strcmp(g_serial_command, "TEST_ALERT") == 0) {
                if (!g_alert_outstanding) {
                    ca_alert test = {};
                    test.timestamp_ms = millis();
                    test.window_index = -1;
                    test.confidence = 0.95f;
                    test.votes = CA_VERIFY_K;
                    test.window_count = CA_VERIFY_N;
                    Serial.println("BENCH TEST: injecting a synthetic alert (classifier bypassed)");
                    raise_alert(test);
                } else {
                    Serial.println("TEST_ALERT ignored: an alert is already outstanding");
                }
            } else if (g_serial_command_len > 0) {
                Serial.printf("Unknown serial command: %s\n", g_serial_command);
                Serial.println("Commands: TEST_ALERT | TEST_MODE ON | TEST_MODE OFF | THRESHOLD <deg/s> | TEST_STATUS");
            }
            g_serial_command_len = 0;
        } else if (g_serial_command_len < sizeof(g_serial_command) - 1) {
            g_serial_command[g_serial_command_len++] = ch;
        }
    }
}
#endif

static void service_outstanding_alert()
{
    if (!g_alert_outstanding) {
        return;
    }
    uint32_t now = millis();
    if (g_alert_last_sent_ms != 0u && (now - g_alert_last_sent_ms) < ALERT_RETRANSMIT_MS) {
        return;
    }
    if (g_alert_send_count >= ALERT_MAX_RETRANSMITS) {
        /* Give up transmitting, but keep the red LED on and the line on the SD
         * card: the alert happened whether or not the phone heard about it, and
         * the caregiver's log must show that the link failed. */
        Serial.println("alert retransmission exhausted; phone never acknowledged");
        log_line("{\"event\":\"relay_unreachable\"}");
        g_alert_outstanding = false;
        return;
    }

    if (g_phone_connected && g_alert_characteristic != nullptr) {
        g_alert_characteristic->setValue((uint8_t *)g_alert_payload,
                                         strlen(g_alert_payload));
        g_alert_characteristic->notify();
    }
    g_alert_last_sent_ms = now;
    ++g_alert_send_count;
}

/* ------------------------------------------------------------------------ */
/* sampling task (core 0)                                                   */
/* ------------------------------------------------------------------------ */

static void IRAM_ATTR on_sample_timer()
{
    portENTER_CRITICAL_ISR(&g_timer_mux);
    g_sample_due = true;
    portEXIT_CRITICAL_ISR(&g_timer_mux);
}

static void sampling_task(void *parameter)
{
    (void)parameter;
    ca_real sample[CA_N_CHANNELS];
    uint32_t missed = 0u;

    for (;;) {
        bool due;
        portENTER_CRITICAL(&g_timer_mux);
        due = g_sample_due;
        g_sample_due = false;
        portEXIT_CRITICAL(&g_timer_mux);

        if (!due) {
            /* Yield at the tick granularity; the timer will set the flag again
             * long before the next window is needed. */
            vTaskDelay(1);
            continue;
        }

        if (mpu_read_sample(sample)) {
            ca_ring_push(&g_ring, sample);
            const float gx = (float)sample[3];
            const float gy = (float)sample[4];
            const float gz = (float)sample[5];
            g_latest_gyro_mag_dps = sqrtf(gx * gx + gy * gy + gz * gz);
            ++g_sample_counter;
        } else if (++missed % 50u == 1u) {
            /* An I2C read can fail transiently; a *sustained* failure means the
             * sensor has come loose, which is worth saying out loud rather than
             * silently classifying stale data. */
            Serial.printf("IMU read failed (%lu total)\n", (unsigned long)missed);
        }
    }
}

/* ------------------------------------------------------------------------ */
/* setup / loop (core 1)                                                    */
/* ------------------------------------------------------------------------ */

void setup()
{
    Serial.begin(115200);
    delay(200);
    Serial.println();
    Serial.println("Assistance-dog alert collar " FIRMWARE_VERSION);
    Serial.printf("model: %d trees, %d nodes, %d features\n", CA_N_TREES, CA_N_NODES,
                  CA_N_FEATURES);
    Serial.printf("gate: %d-of-%d at p>=%.2f, refractory %lu ms\n", CA_VERIFY_K,
                  CA_VERIFY_N, (double)CA_VOTE_THRESHOLD,
                  (unsigned long)CA_REFRACTORY_MS);
    Serial.printf("window: %d samples @ %.2f Hz, stride %d\n", CA_WINDOW_SAMPLES,
                  (double)CA_SAMPLE_RATE_HZ, CA_STRIDE_SAMPLES);

    pinMode(PIN_LED_STATUS, OUTPUT);
    pinMode(PIN_LED_ALERT, OUTPUT);
    pinMode(PIN_BUZZER, OUTPUT);
    digitalWrite(PIN_LED_STATUS, LOW);
    digitalWrite(PIN_LED_ALERT, LOW);

    ca_ring_init(&g_ring);
    ca_verify_init(&g_gate);

    if (!mpu_begin()) {
        /* Without an IMU there is nothing to detect.  Blink the alert LED
         * forever rather than advertising a collar that cannot do its job. */
        for (;;) {
            digitalWrite(PIN_LED_ALERT, !digitalRead(PIN_LED_ALERT));
            delay(200);
        }
    }

#if ENABLE_SD_LOGGING
    g_sd_available = SD.begin(PIN_SD_CS);
    Serial.println(g_sd_available ? "SD card ready" : "SD card absent; not logging");
#else
    g_sd_available = false;
    Serial.println("SD logging disabled for this bench pin mapping (GPIO18/19 are used by LED/buzzer)");
#endif

    ble_begin();

    /* Core 0 does nothing but sample, so the 133-point DFTs on core 1 cannot
     * stretch the sampling interval and distort the spectral features. */
    /* Arduino-ESP32 core 3.x timer API: configure a 1 MHz timer (1 us/tick). */
    g_sample_timer = timerBegin(1000000);
    timerAttachInterrupt(g_sample_timer, &on_sample_timer);
    timerAlarm(g_sample_timer, SAMPLE_PERIOD_US, true, 0);

    xTaskCreatePinnedToCore(sampling_task, "imu", 4096, nullptr,
                            configMAX_PRIORITIES - 1, nullptr, 0);

    digitalWrite(PIN_LED_STATUS, HIGH);
    Serial.println("armed");
}

void loop()
{
#if ENABLE_SERIAL_TEST_ALERTS
    service_serial_test_command();
#endif
    static uint32_t last_classification_ms = 0u;
    static uint32_t last_status_ms = 0u;

    /* One classification per stride.  Working in milliseconds against millis()
     * rather than counting samples keeps the cadence right even if the sampler
     * drops a reading. */
    const uint32_t stride_ms =
        (uint32_t)(1000.0f * CA_STRIDE_SAMPLES / CA_SAMPLE_RATE_HZ);

    uint32_t now = millis();
    if (!g_threshold_test_mode && (now - last_classification_ms) >= stride_ms && ca_ring_ready(&g_ring)) {
        last_classification_ms = now;

        if (ca_ring_copy_window(&g_ring, g_window)) {
            ca_real selected[CA_N_FEATURES];
            if (ca_extract(g_window, CA_WINDOW_SAMPLES, CA_SAMPLE_RATE_HZ, &g_scratch,
                           g_features) == 0) {
                ca_prepare_features(g_features, selected);
                ca_real probability = ca_forest_predict(selected);

                ca_alert alert;
                if (ca_verify_push(&g_gate, probability, now, &alert)) {
                    raise_alert(alert);
                }
            }
        }
        /* A torn window is simply skipped -- the next stride brings another. */
    }

    /* Threshold test mode consumes real IMU samples but deliberately bypasses
     * the ML classifier. Telemetry helps tune the provisional threshold. */
    const uint32_t samples_now = g_sample_counter;
    if (g_threshold_test_mode && samples_now != g_last_seen_sample_counter) {
        g_last_seen_sample_counter = samples_now;
        const float gyro_mag = g_latest_gyro_mag_dps;
        if (gyro_mag >= g_test_gyro_threshold_dps) {
            if (g_test_consecutive_samples < 255u) ++g_test_consecutive_samples;
        } else {
            g_test_consecutive_samples = 0u;
        }

        if ((now - g_last_test_telemetry_ms) >= 500u) {
            g_last_test_telemetry_ms = now;
            Serial.printf("TEST IMU: gyro_mag=%.1f deg/s threshold=%.1f deg/s consecutive=%u/%u\n",
                          (double)gyro_mag, (double)g_test_gyro_threshold_dps,
                          g_test_consecutive_samples, TEST_REQUIRED_CONSECUTIVE_SAMPLES);
        }

        if (g_test_consecutive_samples >= TEST_REQUIRED_CONSECUTIVE_SAMPLES &&
            !g_alert_outstanding && (now - g_last_test_trigger_ms) >= TEST_COOLDOWN_MS) {
            ca_alert test = {};
            test.timestamp_ms = now;
            test.window_index = -1;
            /* Relay currently enforces a minimum confidence. This value is a
             * compatibility placeholder, NOT an ML probability. Firmware version
             * marks this as threshold-test mode in the alert payload. */
            test.confidence = 0.95f;
            test.votes = TEST_REQUIRED_CONSECUTIVE_SAMPLES;
            test.window_count = TEST_REQUIRED_CONSECUTIVE_SAMPLES;
            g_next_alert_is_threshold_test = true;
            g_last_test_trigger_ms = now;
            g_test_consecutive_samples = 0u;
            Serial.println("THRESHOLD TEST TRIGGER: real IMU threshold crossed; ML bypassed");
            raise_alert(test);
        }
    }

    service_outstanding_alert();

    if ((now - last_status_ms) >= 15000u) {
        last_status_ms = now;
        publish_status();
    }

    delay(5);
}
