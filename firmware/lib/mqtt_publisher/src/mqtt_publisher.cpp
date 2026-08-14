#include "mqtt_publisher.h"

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

static WiFiClient   s_wifiClient;
static PubSubClient s_mqttClient(s_wifiClient);

void MQTTPublisher::configure(const char* ssid,
                               const char* password,
                               const char* broker_ip,
                               uint16_t    broker_port) {
    _ssid        = ssid;
    _password    = password;
    _broker_ip   = broker_ip;
    _broker_port = broker_port;
}

bool MQTTPublisher::begin() {
    if (!_connectWifi())   return false;
    s_mqttClient.setKeepAlive(10);     // send keepalive every 10 seconds
    s_mqttClient.setSocketTimeout(5); // TCP timeout
    s_wifiClient.setTimeout(5000);
    s_mqttClient.setServer(_broker_ip, _broker_port);
    if (!_connectBroker()) return false;
    return true;
}

void MQTTPublisher::loop() {
    // Check WiFi first
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("[MQTT] WiFi lost. Reconnecting..."));
        WiFi.reconnect();
        delay(2000);
        return;
    }

    if (!s_mqttClient.connected()) {
        Serial.println(F("[MQTT] Connection lost. Reconnecting..."));
        _connectBroker();
    }
    s_mqttClient.loop();
}

bool MQTTPublisher::publish(const AccelData& accel) {
    if (!accel.valid || !s_mqttClient.connected()) return false;

    char payload[128];
    time_t now = time(nullptr);
    snprintf(payload, sizeof(payload),
        "{\"ts\":%ld,"
        "\"accel_x\":%.3f,\"accel_y\":%.3f,\"accel_z\":%.3f}",
        now, accel.x, accel.y, accel.z);

        return s_mqttClient.publish(_topic, payload);
    }

bool MQTTPublisher::isConnected() const {
    return s_mqttClient.connected();
}

bool MQTTPublisher::_connectWifi() {
    Serial.print(F("[MQTT] Connecting to WiFi"));
    WiFi.begin(_ssid, _password);

    uint8_t retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 20) {
        delay(500);
        Serial.print(F("."));
        retries++;
    }

    if (WiFi.status() != WL_CONNECTED) {
        Serial.println(F("\n[MQTT] WiFi connection failed."));
        return false;
    }

    Serial.print(F("\n[MQTT] WiFi connected. IP: "));
    Serial.println(WiFi.localIP());
    return true;
}

bool MQTTPublisher::_connectBroker() {
    char clientId[32];
    snprintf(clientId, sizeof(clientId), "telemetry-imu-%04X",
             (uint16_t)(ESP.getEfuseMac() & 0xFFFF));

    uint8_t retries = 0;
    while (!s_mqttClient.connected()) {
        Serial.print(F("[MQTT] Connecting to broker..."));
        if (s_mqttClient.connect(clientId)) {
            Serial.println(F(" connected."));
            return true;
        }
        Serial.print(F(" failed, rc="));
        Serial.print(s_mqttClient.state());
        Serial.println(F(". Retrying in 2s..."));
        delay(2000);
    }

    Serial.println(F("[MQTT] Broker connection failed."));
    return false;
}