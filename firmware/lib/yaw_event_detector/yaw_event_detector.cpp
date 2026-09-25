#include "yaw_event_detector.h"
#include <math.h>

YawEventDetector::YawEventDetector(float triggerThreshold, float endThreshold,
                                    size_t minSamplesToAnalyze, size_t maxSamples)
    : state_(State::Idle),
      triggerThreshold_(triggerThreshold),
      endThreshold_(endThreshold),
      minSamplesToAnalyze_(minSamplesToAnalyze),
      maxSamples_(maxSamples < kMaxCapacity ? maxSamples : kMaxCapacity),
      count_(0) {}

void YawEventDetector::reset() {
    state_ = State::Idle;
    count_ = 0;
}

bool YawEventDetector::analyzeAndReset(YawCandidate& outCandidate) {
    bool produced = false;
    if (count_ >= minSamplesToAnalyze_) {
        EventCorrelation corr = correlateEvent(bufferX_, bufferY_, bufferRef_, count_);
        outCandidate = candidateFromCorrelation(corr);
        produced = true; // even an Undetermined result counts as a completed analysis
    }
    reset();
    return produced;
}

bool YawEventDetector::update(float tiltCorrectedX, float tiltCorrectedY, float referenceAccel,
                               YawCandidate& outCandidate) {
    float absRef = fabsf(referenceAccel);

    if (state_ == State::Idle) {
        if (absRef >= triggerThreshold_) {
            state_ = State::Buffering;
            count_ = 0;
            bufferX_[count_] = tiltCorrectedX;
            bufferY_[count_] = tiltCorrectedY;
            bufferRef_[count_] = referenceAccel;
            count_++;
        }
        return false;
    }

    // Buffering
    if (count_ < maxSamples_) {
        bufferX_[count_] = tiltCorrectedX;
        bufferY_[count_] = tiltCorrectedY;
        bufferRef_[count_] = referenceAccel;
        count_++;
    }

    bool bufferFull = (count_ >= maxSamples_);
    bool droppedBelowEnd = (absRef < endThreshold_);

    if (bufferFull || droppedBelowEnd) {
        return analyzeAndReset(outCandidate);
    }

    return false;
}

float differentiateSpeedStep(float prevSpeedKmh, float prevTimestampSec,
                              float currSpeedKmh, float currTimestampSec) {
    float dt = currTimestampSec - prevTimestampSec;
    if (dt < 1e-3f) return 0.0f; // no new sample / clock hasn't advanced
    float dv = (currSpeedKmh - prevSpeedKmh) / 3.6f;
    return dv / dt;
}