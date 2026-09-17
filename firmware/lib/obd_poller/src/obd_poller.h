#pragma once
#include "OBD2.h"
#include "OBDPids.h"

struct ObdData {
    float rpm            = 0.0f;
    float speed_kmh       = 0.0f;
    float throttle_pct    = 0.0f;
    float coolant_temp_c  = 0.0f;
    float engine_load_pct = 0.0f;

    bool rpm_valid            = false;
    bool speed_valid          = false;
    bool throttle_valid       = false;
    bool coolant_valid        = false;
    bool engine_load_valid    = false;
};

class ObdPoller {
public:
    explicit ObdPoller(obd::OBD2& obd2) : obd2_(obd2) {}

    // Call every loop() iteration, regardless of internal state
    // (mirrors OBD2::update()'s own "harmless no-op when idle" contract).
    void update();

    ObdData getLatest() const { return latest_; }

private:
    obd::OBD2& obd2_;
    ObdData    latest_;
    size_t     pidIndex_ = 0;

    void applyResult(uint8_t pid, float value);
    void markInvalid(uint8_t pid);
};