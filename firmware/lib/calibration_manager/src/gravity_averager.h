#pragma once

#include "orientation_calibration.h"
#include <stddef.h>

// Accumulates raw accel samples while the vehicle is stationary, and
// produces the single averaged gravity vector that
// computeTiltCorrection() expects. Discards progress if the vehicle
// starts moving before enough samples are collected -- a partial
// average spanning a stop-then-go transition would be garbage, not a
// slightly-noisy-but-usable one.

class GravityAverager {
public:
    explicit GravityAverager(size_t requiredSamples = 20);

    // Call once per sample tick. isStationary should reflect an
    // external gate (e.g. OBD speed == 0) -- this class doesn't decide
    // that itself. Returns true once requiredSamples have been
    // collected while continuously stationary; outAverage is filled
    // with the result in that case only.
    bool update(bool isStationary, Vector3 rawAccel, Vector3& outAverage);

    void reset();

private:
    size_t requiredSamples_;
    size_t count_;
    float sumX_, sumY_, sumZ_;
};