#include <Arduino.h>
#include <time.h>
#include "imu_sensor.h"
#include "mqtt_publisher.h"
#include <WiFi.h>
#include <SPI.h>
#include <transports/MCP2515Transport.h>
#include <OBD2.h>
#include "calibration_nvs.h"
#include "calibration_manager.h"

// ---------------------------------------------------------------------------
// Configuration — update these for your environment
// ---------------------------------------------------------------------------
static const char* WIFI_SSID     = "S23_FE";
static const char* WIFI_PASSWORD = "clbu0004";
static const char* BROKER_IP     = "10.76.197.48";  //Dev machine IP when on the WIFI_SSID network
static const uint16_t BROKER_PORT = 1883;

// MPU6050 pins — adjust for your ESP32 board
static const int SDA_PIN = 21;
static const int SCL_PIN = 20;

// --- New: MCP2515 / CAN pins (confirmed, OBD2Lib-reference.md §9) ---
static const int CAN_SCK  = 12;
static const int CAN_MOSI = 4;
static const int CAN_MISO = 5;
static const int CAN_CS   = 13;
static const int CAN_INT  = 15;

// Publish interval in milliseconds (~10Hz to match OBD publisher)
static const unsigned long PUBLISH_INTERVAL_MS = 100;

// Below this, the vehicle is treated as stationary for tilt calibration
// purposes. Not exactly 0 since OBD speed can be noisy/rounded.
static const float STATIONARY_SPEED_THRESHOLD_KMH = 1.0f;

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
static IMUSensor     imu;
static MQTTPublisher mqtt;
static unsigned long lastPublish = 0;
static SPIClass canSPI(FSPI);
static obd::MCP2515Transport canTransport(CAN_CS, CAN_INT, canSPI, CAN_500KBPS, MCP_8MHZ);
static obd::OBD2 obd2(canTransport);
static ObdPoller obdPoller(obd2);

// --- New: IMU orientation calibration ---
// Heap-allocated because CalibrationManager needs the loaded
// CalibrationData at construction time, which only exists after
// calibNvs.load() runs in setup() -- can't be a plain global
// initialized before that. One allocation, once, at boot.
static CalibrationNvs calibNvs;
static CalibrationManager* calibManager = nullptr;
static float prevSpeedKmh = 0.0f;
static float prevTimestampSec = 0.0f;
static float lastReferenceAccel = 0.0f; // temporary, for debug print visibility while tuning

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println(F("\n[TELEMETRY] IMU Publisher starting..."));

    // Init IMU
    if (!imu.begin(SDA_PIN, SCL_PIN)) {
        Serial.println(F("[TELEMETRY] IMU init failed — halting."));
        while (true) delay(1000);
    }

    // --- New: Init IMU orientation calibration ---
    // Not fatal if NVS fails -- calibration still runs, just won't
    // survive a reboot. Telemetry itself doesn't depend on this.
    if (!calibNvs.begin()) {
        Serial.println(F("[CALIB] NVS begin() failed -- continuing with in-session-only calibration."));
    }
    CalibrationData loadedCalib; // defaults all-invalid if load() below fails/finds nothing
    bool hasStored = calibNvs.load(loadedCalib);
    Serial.printf("[CALIB] Stored calibration %s.\n", hasStored ? "found, resuming" : "not found -- starting fresh");
    // Thresholds dropped deliberately low right now -- purely to prove
    // the mechanism can transition at all before tuning back up to
    // something that won't false-trigger on ordinary driving noise.
    calibManager = new CalibrationManager(
        loadedCalib,
        /*requiredStationarySamples=*/20,
        /*requiredConsistentYawEvents=*/3,
        /*yawTriggerThreshold=*/0.15f,
        /*yawEndThreshold=*/0.05f,
        /*yawMinSamplesToAnalyze=*/10,
        /*yawMaxSamplesPerEvent=*/60
    );
    prevTimestampSec = millis() / 1000.0f;

    // --- New: Init CAN/OBD2 ---
    canSPI.begin(CAN_SCK, CAN_MISO, CAN_MOSI, CAN_CS);

    bool transportOk = canTransport.begin();
    Serial.println(transportOk ? F("[OBD2] transport.begin() OK") : F("[OBD2] transport.begin() FAILED"));

    bool obdOk = obd2.begin();
    Serial.println(obdOk ? F("[OBD2] obd2.begin() OK") : F("[OBD2] obd2.begin() FAILED"));

    // Init MQTT
    mqtt.configure(WIFI_SSID, WIFI_PASSWORD, BROKER_IP, BROKER_PORT);
    while (!mqtt.begin()) {
        Serial.println(F("[TELEMETRY] MQTT init failed — retrying in 5s..."));
        delay(5000);
    }

    configTime(0, 0, "pool.ntp.org");
    Serial.print(F("[TIME] Syncing NTP..."));
    struct tm timeinfo;
    while (!getLocalTime(&timeinfo)) {
        Serial.print(F("."));
        delay(500);
    }
    Serial.println(F(" done."));

    Serial.print(F("[NET] Pinging broker... "));
    // just try a raw TCP connect test
    WiFiClient testClient;
    if (testClient.connect(BROKER_IP, 1883)) {
        Serial.println(F("reachable."));
        testClient.stop();
    } else {
        Serial.println(F("UNREACHABLE."));
    }

    Serial.println(F("[TELEMETRY] Ready. Publishing at 10Hz."));
}

// ---------------------------------------------------------------------------
// Loop
// ---------------------------------------------------------------------------
void loop() {
    unsigned long now = millis();

    obdPoller.update();

    if (now - lastPublish >= PUBLISH_INTERVAL_MS) {
        lastPublish = now;

        // Fetched before the accel block now -- calibration needs
        // speed_kmh/speed_valid alongside the IMU reading this cycle.
        ObdData obdData = obdPoller.getLatest();

        // Note: lastReferenceAccel is intentionally NOT reset here --
        // it needs to persist (hold) across ticks where no new OBD
        // speed sample has arrived. See the holding logic below.

        AccelData accel = imu.getRawAccel();
        if (accel.valid) {
            Vector3 rawVec = { accel.x, accel.y, accel.z };

            bool isStationary = obdData.speed_valid && obdData.speed_kmh < STATIONARY_SPEED_THRESHOLD_KMH;

            // Only advance the differentiator's clock -- and only
            // recompute a new reference value -- on a tick where the
            // OBD speed value has genuinely changed. Doing this on
            // every valid-but-unchanged tick (as before) reset dt to
            // ~100ms even though the ECU only refreshes speed roughly
            // once a second, inflating every computed value by ~10x
            // AND causing every event to immediately truncate to 1
            // sample the moment a repeat tick computed a correct 0.
            // Holding the last real value across repeat ticks instead
            // of snapping to 0 gives the event detector a sustained
            // signal to actually buffer past minSamplesToAnalyze.
            bool isFreshReferenceSample = false;
            if (obdData.speed_valid) {
                if (obdData.speed_kmh != prevSpeedKmh) {
                    float nowSeconds = now / 1000.0f;
                    lastReferenceAccel = differentiateSpeedStep(prevSpeedKmh, prevTimestampSec,
                                                                 obdData.speed_kmh, nowSeconds);
                    prevSpeedKmh = obdData.speed_kmh;
                    prevTimestampSec = nowSeconds;
                    isFreshReferenceSample = true;
                }
                // else: stale repeat -- hold lastReferenceAccel for the
                // debug print (below), but isFreshReferenceSample stays
                // false so CalibrationManager's yaw event detector
                // ignores this tick entirely rather than buffering a
                // held/repeated value with no real variance.
            } else {
                lastReferenceAccel = 0.0f; // OBD itself invalid -- nothing to hold onto
            }

            // --- New: drive the calibration state machine ---
            if (calibManager->update(rawVec, isStationary, lastReferenceAccel, isFreshReferenceSample)) {
                // A real transition happened (tilt just completed, or
                // yaw just locked) -- worth persisting. This fires at
                // most twice per calibration lifecycle, never every
                // tick, so flash write endurance isn't a concern here.
                bool saved = calibNvs.save(calibManager->getCalibration());
                Serial.printf("[CALIB] state changed -> %d, save %s\n",
                              static_cast<int>(calibManager->state()), saved ? "OK" : "FAILED");
            }

            Vector3 correctedVec = calibManager->getCorrectedAccel(rawVec);
            AccelData correctedAccel = { correctedVec.x, correctedVec.y, correctedVec.z, true };

            if (!mqtt.publish(correctedAccel)) {
                Serial.println(F("[TELEMETRY] IMU publish failed."));
            }
        }

        // --- Debug print, field-test only ---
        // referenceAccel added temporarily to diagnose why yaw isn't
        // locking -- watch for it dropping to 0 mid-acceleration
        // (stale/unchanged OBD speed reading), not just whether it
        // crosses the trigger threshold at all.
        Serial.printf(
            "[OBD] rpm=%.1f(%d) speed=%.1f(%d) throttle=%.1f(%d) coolant=%.1f(%d) load=%.1f(%d) | calib=%d ref=%.2f\n",
            obdData.rpm,            obdData.rpm_valid,
            obdData.speed_kmh,      obdData.speed_valid,
            obdData.throttle_pct,   obdData.throttle_valid,
            obdData.coolant_temp_c, obdData.coolant_valid,
            obdData.engine_load_pct, obdData.engine_load_valid,
            static_cast<int>(calibManager->state()),
            lastReferenceAccel
        );

        if (!mqtt.publish(obdData)) {
            Serial.println(F("[TELEMETRY] OBD publish failed."));
        }
    }
    mqtt.loop();
}