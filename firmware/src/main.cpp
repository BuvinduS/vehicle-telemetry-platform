#include <Arduino.h>
#include <time.h>
#include "imu_sensor.h"
#include "mqtt_publisher.h"
#include <WiFi.h>
#include <SPI.h>
#include <transports/MCP2515Transport.h>
#include <OBD2.h>

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

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
static IMUSensor     imu;
static MQTTPublisher mqtt;
static unsigned long lastPublish = 0;
static SPIClass canSPI(FSPI);
static obd::MCP2515Transport canTransport(CAN_CS, CAN_INT, canSPI, CAN_500KBPS, MCP_8MHZ);
static obd::OBD2 obd2(canTransport);
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
    if (now - lastPublish >= PUBLISH_INTERVAL_MS) {
        lastPublish = now;

        AccelData accel = imu.getRawAccel();
        if (accel.valid) {
            bool ok = mqtt.publish(accel);
            if (!ok) {
                Serial.println(F("[TELEMETRY] Publish failed."));
            }
        }
    }
    mqtt.loop();
}