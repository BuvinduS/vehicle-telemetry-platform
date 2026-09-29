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

    // Call once per sample tick with the latest tilt-corrected accel,
    // the latest reference accel, and whether this tick's reference
    // value is a GENUINELY fresh OBD reading (vs. a repeat of the last
    // one, because OBD speed updates far less often than the sample
    // rate this is called at). Stale ticks are a complete no-op --
    // not buffered at all -- because correlateEvent() needs the
    // buffered reference values to actually vary to mean anything;
    // buffering a held/repeated constant produces zero variance and
    // Pearson correlation is undefined for that, so it silently comes
    // back Undetermined regardless of the real magnitude. Returns true
    // and fills outCandidate if an event just completed and was
    // analyzed (candidate may itself be Undetermined -- that's still a
    // completed analysis, distinct from "event discarded as too
    // short"). Returns false while idle, mid-buffering, discarding a
    // too-short event, or on any stale (non-fresh) tick.
    bool update(float tiltCorrectedX, float tiltCorrectedY, float referenceAccel,
                bool isFreshSample, YawCandidate& outCandidate);

    // Discard any in-progress window (used when the tilt frame changes underneath it).
    // windowsCompleted() is intentionally NOT reset -- it stays monotonic for logging.
    void restart() { reset(); }

    // --- Diagnostics (read-only; used for field-test logging) ---
    size_t bufferedCount() const { return count_; }
    int windowsCompleted() const { return windowsCompleted_; }
    const EventCorrelation& lastCorrelation() const { return lastCorr_; }
    const HeadingFit& lastHeadingFit() const { return lastFit_; }
    const YawCandidate& lastCandidate() const { return lastCandidate_; }
    const WindowStats& lastWindowStats() const { return lastStats_; }

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

    int windowsCompleted_ = 0;
    EventCorrelation lastCorr_ = {0.0f, 0.0f};
    HeadingFit lastFit_ = {0.0f, 0.0f};
    YawCandidate lastCandidate_ = {LongitudinalAxis::Undetermined, 0.0f};
    WindowStats lastStats_ = {0, 0, 0, 0, 0, 0};
};

// Single-step version of the OBD-speed-to-accel differentiation, for
// streaming use where samples arrive one at a time (e.g. whenever a
// new OBD speed reading lands) rather than in a pre-collected batch.
// Returns 0 if dt is too small to trust (e.g. no new OBD sample has
// arrived since the last call -- call this with the same "current"
// values repeated on ticks where speed hasn't updated).
float differentiateSpeedStep(float prevSpeedKmh, float prevTimestampSec,
                              float currSpeedKmh, float currTimestampSec);