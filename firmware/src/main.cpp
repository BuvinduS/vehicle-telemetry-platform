#include <Arduino.h>
#include <time.h>
#include "imu_sensor.h"
#include "mqtt_publisher.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <stdarg.h>
#include <SPI.h>
#include <transports/MCP2515Transport.h>
#include <OBD2.h>
#include "calibration_nvs.h"
#include "calibration_manager.h"
#include "secrets.h"

// Set to 1 (or build with -DENABLE_UDP_DEBUG=1) to mirror debug lines to the dev machine over UDP.
#ifndef ENABLE_UDP_DEBUG
#define ENABLE_UDP_DEBUG 0
#endif

// ---------------------------------------------------------------------------
// Configuration — update these for your environment
// ---------------------------------------------------------------------------
// static const char* WIFI_SSID     = "S23_FE";
// static const char* WIFI_PASSWORD = "clbu0004";
// static const char* BROKER_IP     = "10.76.197.48";  //Dev machine IP when on the WIFI_SSID network
static const uint16_t BROKER_PORT = 1883;

// MPU6050 pins — adjust for your ESP32 board
static const int SDA_PIN = 21;
static const int SCL_PIN = 20;

// --- MCP2515 / CAN pins (confirmed, OBD2Lib-reference.md §9) ---
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

// Reference acceleration is speed change between two accepted OBD readings. Speed is
// quantized to 1 km/h and its value changes at irregular instants, so:
//  - a baseline shorter than MIN gives artifacts (1 km/h in 0.1 s "=" 2.8 m/s^2);
//  - a baseline longer than MAX (e.g. the first change after a long plateau) is stale,
//    so it is discarded and the baseline is simply re-anchored.
static const float MIN_REFERENCE_INTERVAL_S = 1.0f;
static const float MAX_REFERENCE_INTERVAL_S = 3.0f;

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
// Raw accel accumulated since the last fresh OBD speed update. Each fresh
// reference value is the AVERAGE acceleration over that interval, so it gets
// paired with the average IMU reading over the same interval rather than one
// noisy instantaneous sample (engine/road vibration would swamp it).
static float accSumX = 0, accSumY = 0, accSumZ = 0;
static int   accCount = 0;
static int   lastPrintedWindows = 0; // for the per-window yaw diagnostic print
static int   lastPrintedResets = 0;  // for the stale-tilt auto-recalibration message

// --- Wireless debug log ------------------------------------------------------
// Mirrors selected diagnostic lines to the dev laptop (same machine as the MQTT
// broker) over UDP, so a USB cable isn't needed during a test drive. Entirely
// separate from MQTT: no topics, no dashboard/DB impact. Fire-and-forget.
// On the laptop:  see the receiver one-liner in the notes for this step.
#if ENABLE_UDP_DEBUG
static const uint16_t DEBUG_UDP_PORT = 5005;
static WiFiUDP   dbgUdp;
static IPAddress dbgTarget;
static bool      dbgTargetValid = false;
#endif

static void debugLog(const char* fmt, ...) {
    char buf[200];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    Serial.print(buf);
#if ENABLE_UDP_DEBUG
    if (dbgTargetValid && WiFi.status() == WL_CONNECTED) {
        dbgUdp.beginPacket(dbgTarget, DEBUG_UDP_PORT);
        dbgUdp.write(reinterpret_cast<const uint8_t*>(buf), strlen(buf));
        dbgUdp.endPacket();
    }
#endif
}
static unsigned long lastStatMs = 0;

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
        /*minYawWindows=*/6,            // pool at least this many windows before locking
        /*yawTriggerThreshold=*/0.15f,
        /*yawEndThreshold=*/0.05f,     // effectively unused: real updates never read this low
        /*yawMinSamplesToAnalyze=*/6,
        /*yawMaxSamplesPerEvent=*/8,   // fixed window of ~8 reference samples
        /*staleTiltThresholdDeg=*/15.0f,
        /*minPooledCorr=*/0.50f,       // sweep-validated: 200/200 locks, 0 false locks on pure noise
        /*headingToleranceDeg=*/10.0f  // last N pooled estimates must agree within this before locking
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

    #if ENABLE_UDP_DEBUG
        dbgTargetValid = dbgTarget.fromString(BROKER_IP);
        if (dbgTargetValid) debugLog("[DBG] wireless debug log -> %s:%u\n", BROKER_IP, DEBUG_UDP_PORT);
#   endif

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

            // Accumulate raw accel every tick; it gets averaged and consumed
            // when the next genuinely new OBD speed value arrives.
            accSumX += rawVec.x; accSumY += rawVec.y; accSumZ += rawVec.z;
            accCount++;

            // OBD speed only refreshes about once a second and in whole km/h
            // steps, so most ticks just repeat the previous value. Only a tick
            // where the value actually CHANGED is a real data point: it advances
            // the differentiator's clock (so dt spans the real gap between two
            // distinct readings) and is the only kind of tick the yaw detector
            // is allowed to buffer.
            bool isFreshReferenceSample = false;
            if (obdData.speed_valid) {
                float nowSeconds = now / 1000.0f;
                if (obdData.speed_kmh != prevSpeedKmh) {
                    float dt = nowSeconds - prevTimestampSec;
                    if (dt >= MAX_REFERENCE_INTERVAL_S) {
                        // First change after a long plateau: dt is meaningless. Re-anchor only,
                        // and restart the accel average so it spans the same interval as the
                        // next reference value will.
                        prevSpeedKmh = obdData.speed_kmh;
                        prevTimestampSec = nowSeconds;
                        accSumX = accSumY = accSumZ = 0; accCount = 0;
                    } else if (dt >= MIN_REFERENCE_INTERVAL_S) {
                        lastReferenceAccel = differentiateSpeedStep(prevSpeedKmh, prevTimestampSec,
                                                                     obdData.speed_kmh, nowSeconds);
                        prevSpeedKmh = obdData.speed_kmh;
                        prevTimestampSec = nowSeconds;
                        isFreshReferenceSample = true;
                    }
                    // else: changed again too soon -- keep waiting; the baseline stays put so
                    // the eventual sample spans at least MIN_REFERENCE_INTERVAL_S.
                }
                // else: unchanged. lastReferenceAccel is kept only so the debug print stays
                // readable; the detector ignores these ticks.
            } else {
                lastReferenceAccel = 0.0f; // OBD itself invalid -- nothing to hold onto
            }

            // On a fresh tick, hand the yaw stage the AVERAGE accel over the same
            // interval the reference value describes. On stale ticks the yaw stage
            // ignores the sample anyway, and the tilt stage wants per-tick values.
            Vector3 accelForCalib = rawVec;
            if (isFreshReferenceSample && accCount > 0) {
                accelForCalib = { accSumX / accCount, accSumY / accCount, accSumZ / accCount };
                accSumX = accSumY = accSumZ = 0; accCount = 0;
            }

            // --- New: drive the calibration state machine ---
            if (calibManager->update(accelForCalib, isStationary, lastReferenceAccel, isFreshReferenceSample)) {
                // A real transition happened (tilt just completed, or
                // yaw just locked) -- worth persisting. This fires at
                // most twice per calibration lifecycle, never every
                // tick, so flash write endurance isn't a concern here.
                bool saved = calibNvs.save(calibManager->getCalibration());
                debugLog("[CALIB] state changed -> %d, save %s\n",
                              static_cast<int>(calibManager->state()), saved ? "OK" : "FAILED");
                if (calibManager->tiltAutoResets() != lastPrintedResets) {
                    lastPrintedResets = calibManager->tiltAutoResets();
                    debugLog("[CALIB] stored tilt was %.0f deg off while parked -> tilt recomputed, yaw will re-learn\n",
                             calibManager->lastTiltErrorDeg());
                }
            }

            // --- Diagnostic: one line each time a yaw window completes ---
            // corrX/corrY: correlation of each tilt-corrected horizontal axis with
            //   the OBD-derived reference. Need |max| >= 0.5 and a gap >= 0.15.
            // angle/proj: best-fit forward direction (deg from +X toward +Y) and how
            //   well accel projected on it tracks the reference (want > ~0.7).
            const YawEventDetector& yd = calibManager->yawDetector();
            if (yd.windowsCompleted() != lastPrintedWindows) {
                lastPrintedWindows = yd.windowsCompleted();
                const HeadingEstimate& he = calibManager->headingEstimate();
                debugLog("[YAW] window %d: this=%.0fdeg (proj %.2f) | POOLED angle=%.0fdeg corr=%.2f n=%d %s\n",
                         yd.windowsCompleted(),
                         yd.lastHeadingFit().angleDeg, yd.lastHeadingFit().projectedCorr,
                         he.angleDeg, he.pooledCorr, he.windows, he.locked ? "LOCKED" : "");
            }

            Vector3 correctedVec = calibManager->getCorrectedAccel(rawVec);
            AccelData correctedAccel = { correctedVec.x, correctedVec.y, correctedVec.z, true };

            // Compact 1 Hz status. acc = tilt(+yaw)-corrected accel: when parked and
            // level, z should be ~9.8 and x/y ~0 (quick check that stored tilt is valid).
            if (now - lastStatMs >= 1000) {
                lastStatMs = now;
                debugLog("[STAT] calib=%d buf=%u win=%d speed=%.0f ref=%.2f acc=(%.2f,%.2f,%.2f)\n",
                         static_cast<int>(calibManager->state()),
                         (unsigned)yd.bufferedCount(), yd.windowsCompleted(),
                         obdData.speed_kmh, lastReferenceAccel,
                         correctedVec.x, correctedVec.y, correctedVec.z);
            }

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
            "[OBD] rpm=%.1f(%d) speed=%.1f(%d) throttle=%.1f(%d) coolant=%.1f(%d) load=%.1f(%d) | calib=%d ref=%.2f buf=%u\n",
            obdData.rpm,            obdData.rpm_valid,
            obdData.speed_kmh,      obdData.speed_valid,
            obdData.throttle_pct,   obdData.throttle_valid,
            obdData.coolant_temp_c, obdData.coolant_valid,
            obdData.engine_load_pct, obdData.engine_load_valid,
            static_cast<int>(calibManager->state()),
            lastReferenceAccel,
            (unsigned)calibManager->yawDetector().bufferedCount()
        );

        if (!mqtt.publish(obdData)) {
            Serial.println(F("[TELEMETRY] OBD publish failed."));
        }
    }
    mqtt.loop();
}