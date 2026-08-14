#include <Arduino.h>
#include <time.h>
#include "imu_sensor.h"
#include "mqtt_publisher.h"
#include <WiFi.h>

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

// Publish interval in milliseconds (~10Hz to match OBD publisher)
static const unsigned long PUBLISH_INTERVAL_MS = 100;

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
static IMUSensor     imu;
static MQTTPublisher mqtt;
static unsigned long lastPublish = 0;

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