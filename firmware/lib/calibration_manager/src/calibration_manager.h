#pragma once

#include "calibration_serializer.h"
#include "gravity_averager.h"
#include "yaw_event_detector.h"
#include "yaw_calibration.h"

// Orchestrates the full runtime calibration lifecycle: seeded from
// whatever CalibrationNvs::load() returned (or a default all-invalid
// CalibrationData on first boot), it drives tilt averaging then yaw
// estimation (pooled continuous heading) until both are known, applying
// whichever correction is currently available to every accel reading
// along the way.
//
// Deliberately has NO Arduino/NVS dependency -- it doesn't call
// CalibrationNvs itself. The caller (main firmware loop) is
// responsible for calling CalibrationNvs::save(getCalibration()) when
// update() returns true (a transition just happened worth persisting).
// This keeps the state machine logic native-testable, same as
// everything else so far -- only the actual flash I/O lives outside it.

enum class CalibrationState { NeedsTilt, NeedsYaw, Ready };

class CalibrationManager {
public:
    explicit CalibrationManager(const CalibrationData& loaded,
                                 size_t requiredStationarySamples = 20,
                                 int minYawWindows = 5,
                                 float yawTriggerThreshold = 1.5f,
                                 float yawEndThreshold = 0.5f,
                                 size_t yawMinSamplesToAnalyze = 10,
                                 size_t yawMaxSamplesPerEvent = 60,
                                 float staleTiltThresholdDeg = 15.0f,
                                 float minPooledCorr = 0.4f,
                                 float headingToleranceDeg = 12.0f);

    CalibrationState state() const { return state_; }

    // Call once per sample tick.
    // - rawAccel: unmodified sensor reading.
    // - isStationary: external gate, e.g. OBD speed_kmh == 0. Only
    //   consulted while state() == NeedsTilt.
    // - referenceAccel: OBD-speed-derived reference acceleration (see
    //   differentiateSpeedStep). Only consulted while
    //   state() == NeedsYaw; pass 0 while stationary/irrelevant.
    // - isFreshReferenceSample: whether referenceAccel is a genuinely
    //   new OBD reading this tick, vs. a held/repeated value from the
    //   last one. Only matters while state() == NeedsYaw -- ignored
    //   entirely during NeedsTilt, since gravity averaging correctly
    //   uses every raw accel tick regardless of OBD freshness.
    // Returns true if a transition just happened that's worth
    // persisting (tilt just completed, or yaw just locked) -- caller
    // should save getCalibration() via CalibrationNvs when this is true.
    bool update(Vector3 rawAccel, bool isStationary, float referenceAccel, bool isFreshReferenceSample);

    // Tilt- and (once known) yaw-corrected acceleration, using
    // whatever correction is currently available. Before tilt is
    // known, returns rawAccel unmodified (identity). Once tilt is
    // known but yaw isn't yet, returns tilt-corrected values with no
    // yaw rotation applied. With yaw known: x = forward, y = lateral, z = up.
    Vector3 getCorrectedAccel(Vector3 rawAccel) const;

    const CalibrationData& getCalibration() const { return data_; }

    // Stale-tilt guard diagnostics. The guard runs whenever the vehicle is stationary and
    // state() != NeedsTilt: if corrected gravity is more than staleTiltThresholdDeg away
    // from vertical, the stored tilt no longer matches how the unit is mounted, so tilt is
    // recomputed from that stationary reading and yaw is cleared to be re-learned.
    int tiltAutoResets() const { return tiltAutoResets_; }
    float lastTiltErrorDeg() const { return lastTiltErrorDeg_; }

    // Read-only access for field-test diagnostics (per-window logging).
    const YawEventDetector& yawDetector() const { return yawEventDetector_; }
    const HeadingEstimate& headingEstimate() const { return headingTracker_.current(); }

private:
    CalibrationData data_;
    CalibrationState state_;
    bool recomputeTiltIfStale(Vector3 stationaryGravity);

    GravityAverager gravityAverager_;
    GravityAverager staleCheckAverager_;
    float staleTiltThresholdDeg_;
    int tiltAutoResets_ = 0;
    float lastTiltErrorDeg_ = 0.0f;
    YawEventDetector yawEventDetector_;
    HeadingTracker headingTracker_;
};