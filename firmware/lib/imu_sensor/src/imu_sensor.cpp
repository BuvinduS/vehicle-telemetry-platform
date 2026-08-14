#include "imu_sensor.h"

#include <Arduino.h>
#include <Wire.h>
#include "MPU6050.h"

static MPU6050 s_mpu;

// MPU6050 raw accel scale factor for ±2g range
// Raw value / 16384.0 = g, multiply by 9.81 for m/s²
static constexpr float ACCEL_SCALE = 9.81f / 16384.0f;

bool IMUSensor::begin(int sda_pin, int scl_pin) {
    Wire.begin(sda_pin, scl_pin);
    Wire.setClock(400000);

    Serial.println(F("[IMU] Initializing MPU6050..."));
    s_mpu.initialize();

    if (!s_mpu.testConnection()) {
        Serial.println(F("[IMU] Connection failed — check wiring."));
        return false;
    }

    Serial.println(F("[IMU] Connection successful."));

    // Set accel range to ±2g (default, most sensitive)
    s_mpu.setFullScaleAccelRange(MPU6050_ACCEL_FS_2);

    _ready = true;
    Serial.println(F("[IMU] Ready."));
    return true;
}

bool IMUSensor::isReady() const {
    return _ready;
}

AccelData IMUSensor::getRawAccel() {
    AccelData result = {0.0f, 0.0f, 0.0f, false};
    if (!_ready) return result;

    int16_t ax, ay, az;
    s_mpu.getAcceleration(&ax, &ay, &az);

    result.x     = ax * ACCEL_SCALE;
    result.y     = ay * ACCEL_SCALE;
    result.z     = az * ACCEL_SCALE;
    result.valid = true;

    return result;
}