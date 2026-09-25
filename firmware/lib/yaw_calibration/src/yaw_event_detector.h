#pragma once

#include "yaw_calibration.h"
#include <stddef.h>

// Watches a continuous stream of tilt-corrected accel + OBD-derived
// reference accel, detects acceleration/braking events by threshold on
// the reference signal, buffers samples during an event, and produces
// a YawCandidate once the event ends -- ready to feed straight into
// YawCalibrationTracker::addEvent().
//
// Fixed-size buffer, no dynamic allocation -- safe for ESP32.

class YawEventDetector {
public:
    // triggerThreshold: |referenceAccel| above this starts an event.
    // endThreshold: |referenceAccel| below this (once triggered) ends
    //   it. Should be lower than triggerThreshold (hysteresis) so a
    //   signal hovering right at the trigger doesn't rapidly start/stop.
    // minSamplesToAnalyze: events shorter than this are discarded as
    //   too brief to correlate reliably (e.g. a single bump).
    // maxSamples: hard cap on buffered samples per event.
    YawEventDetector(float triggerThreshold = 1.5f,
                      float endThreshold = 0.5f,
                      size_t minSamplesToAnalyze = 10,
                      size_t maxSamples = 60);

    // Call once per sample tick with the latest tilt-corrected accel
    // and the latest reference accel (see differentiateSpeedStep
    // below). Returns true and fills outCandidate if an event just
    // completed and was analyzed (candidate may itself be
    // Undetermined -- that's still a completed analysis, distinct from
    // "event discarded as too short", which returns false). Returns
    // false while idle, mid-buffering, or after discarding a too-short
    // event.
    bool update(float tiltCorrectedX, float tiltCorrectedY, float referenceAccel,
                YawCandidate& outCandidate);

private:
    enum class State { Idle, Buffering };

    void reset();
    bool analyzeAndReset(YawCandidate& outCandidate);

    State state_;
    float triggerThreshold_;
    float endThreshold_;
    size_t minSamplesToAnalyze_;
    size_t maxSamples_;

    static constexpr size_t kMaxCapacity = 128; // hard upper bound for the static buffer
    float bufferX_[kMaxCapacity];
    float bufferY_[kMaxCapacity];
    float bufferRef_[kMaxCapacity];
    size_t count_;
};

// Single-step version of the OBD-speed-to-accel differentiation, for
// streaming use where samples arrive one at a time (e.g. whenever a
// new OBD speed reading lands) rather than in a pre-collected batch.
// Returns 0 if dt is too small to trust (e.g. no new OBD sample has
// arrived since the last call -- call this with the same "current"
// values repeated on ticks where speed hasn't updated).
float differentiateSpeedStep(float prevSpeedKmh, float prevTimestampSec,
                              float currSpeedKmh, float currTimestampSec);