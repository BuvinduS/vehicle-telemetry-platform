#include "calibration_manager.h"

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
                                        size_t yawMaxSamplesPerEvent)
    : data_(loaded),
      state_(initialStateFor(loaded)),
      gravityAverager_(requiredStationarySamples),
      yawEventDetector_(yawTriggerThreshold, yawEndThreshold, yawMinSamplesToAnalyze, yawMaxSamplesPerEvent),
      yawTracker_(requiredConsistentYawEvents) {}

bool CalibrationManager::update(Vector3 rawAccel, bool isStationary, float referenceAccel) {
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
                                                            referenceAccel, candidate);
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