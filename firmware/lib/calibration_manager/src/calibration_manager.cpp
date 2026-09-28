#include "calibration_manager.h"
#include <math.h>

namespace {
CalibrationState initialStateFor(const CalibrationData& data) {
    if (data.tiltValid && data.yawValid) return CalibrationState::Ready;
    if (data.tiltValid) return CalibrationState::NeedsYaw; // tilt loaded, yaw wasn't locked yet
    return CalibrationState::NeedsTilt;
}
} // namespace

CalibrationManager::CalibrationManager(const CalibrationData& loaded,
                                        size_t requiredStationarySamples,
                                        int requiredConsistentYawEvents,
                                        float yawTriggerThreshold,
                                        float yawEndThreshold,
                                        size_t yawMinSamplesToAnalyze,
                                        size_t yawMaxSamplesPerEvent,
                                        float staleTiltThresholdDeg)
    : data_(loaded),
      state_(initialStateFor(loaded)),
      gravityAverager_(requiredStationarySamples),
      staleCheckAverager_(requiredStationarySamples),
      staleTiltThresholdDeg_(staleTiltThresholdDeg),
      yawEventDetector_(yawTriggerThreshold, yawEndThreshold, yawMinSamplesToAnalyze, yawMaxSamplesPerEvent),
      yawTracker_(requiredConsistentYawEvents) {}

bool CalibrationManager::recomputeTiltIfStale(Vector3 g) {
    // Ignore implausible readings (sensor glitch, or not really stationary): gravity
    // magnitude is rotation-invariant, so it can be sanity-checked before trusting it.
    float rawMag = sqrtf(g.x * g.x + g.y * g.y + g.z * g.z);
    if (fabsf(rawMag - 9.81f) > 1.5f) return false;

    Vector3 corrected = applyCorrection(data_.tiltCorrection, g);
    float cosA = corrected.z / rawMag;
    if (cosA > 1.0f) cosA = 1.0f;
    if (cosA < -1.0f) cosA = -1.0f;
    lastTiltErrorDeg_ = acosf(cosA) * 57.2957795f;
    if (lastTiltErrorDeg_ <= staleTiltThresholdDeg_) return false;

    // Stored tilt no longer matches the mount. Recompute from this stationary reading;
    // the yaw stage worked in the old (wrong) horizontal plane, so it must be re-learned.
    data_.tiltCorrection = computeTiltCorrection(g);
    data_.tiltValid = true;
    data_.yawValid = false;
    data_.yawAxis = LongitudinalAxis::Undetermined;
    data_.yawForwardSign = 1.0f;
    yawTracker_.reset();
    yawEventDetector_.restart();
    state_ = CalibrationState::NeedsYaw;
    tiltAutoResets_++;
    return true;
}

bool CalibrationManager::update(Vector3 rawAccel, bool isStationary, float referenceAccel,
                                 bool isFreshReferenceSample) {
    // Stale-tilt guard: once a tilt exists, keep verifying it whenever stationary.
    if (state_ != CalibrationState::NeedsTilt) {
        Vector3 stationaryGravity;
        if (staleCheckAverager_.update(isStationary, rawAccel, stationaryGravity)) {
            if (recomputeTiltIfStale(stationaryGravity)) return true; // worth persisting
        }
    }

    switch (state_) {
        case CalibrationState::NeedsTilt: {
            Vector3 avgGravity;
            if (!gravityAverager_.update(isStationary, rawAccel, avgGravity)) return false;

            data_.tiltCorrection = computeTiltCorrection(avgGravity);
            data_.tiltValid = true;
            state_ = CalibrationState::NeedsYaw;
            return true; // worth persisting: tilt just completed
        }

        case CalibrationState::NeedsYaw: {
            Vector3 tiltCorrected = applyCorrection(data_.tiltCorrection, rawAccel);

            YawCandidate candidate;
            bool eventCompleted = yawEventDetector_.update(tiltCorrected.x, tiltCorrected.y,
                                                            referenceAccel, isFreshReferenceSample,
                                                            candidate);
            if (!eventCompleted) return false;

            YawCalibrationResult result = yawTracker_.addEvent(candidate);
            if (!result.locked) return false;

            data_.yawAxis = result.candidate.axis;
            data_.yawForwardSign = result.candidate.forwardSign;
            data_.yawValid = true;
            state_ = CalibrationState::Ready;
            return true; // worth persisting: yaw just locked
        }

        case CalibrationState::Ready:
        default:
            return false; // nothing to do -- already fully calibrated
    }
}

Vector3 CalibrationManager::getCorrectedAccel(Vector3 rawAccel) const {
    if (!data_.tiltValid) return rawAccel; // identity until tilt is known

    Vector3 tiltCorrected = applyCorrection(data_.tiltCorrection, rawAccel);
    if (!data_.yawValid) return tiltCorrected; // tilt-only until yaw locks in

    float longitudinal = (data_.yawAxis == LongitudinalAxis::Y ? tiltCorrected.y : tiltCorrected.x)
                          * data_.yawForwardSign;
    float lateral = (data_.yawAxis == LongitudinalAxis::Y ? tiltCorrected.x : tiltCorrected.y);

    return { longitudinal, lateral, tiltCorrected.z };
}