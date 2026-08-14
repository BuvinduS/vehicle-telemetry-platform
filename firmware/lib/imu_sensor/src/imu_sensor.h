#pragma once

struct AccelData {
    float x;      // m/s²
    float y;      // m/s²
    float z;      // m/s²
    bool  valid;
};

class IMUSensor {
public:
    bool      begin(int sda_pin, int scl_pin);
    bool      isReady() const;
    AccelData getRawAccel();

private:
    bool _ready = false;
};