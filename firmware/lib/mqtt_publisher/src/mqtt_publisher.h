#pragma once

#include <stdint.h>
#include "imu_sensor.h"

class MQTTPublisher {
public:
    void configure(const char* ssid,
                   const char* password,
                   const char* broker_ip,
                   uint16_t    broker_port);

    bool begin();
    void loop();
    bool publish(const AccelData& accel);
    bool isConnected() const;

private:
    const char* _ssid        = nullptr;
    const char* _password    = nullptr;
    const char* _broker_ip   = nullptr;
    uint16_t    _broker_port = 1883;

    char _topic[64] = "telemetry/vehicle/imu";

    bool _connectWifi();
    bool _connectBroker();
};