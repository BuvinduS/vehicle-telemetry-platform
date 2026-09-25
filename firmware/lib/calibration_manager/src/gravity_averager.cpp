#include "gravity_averager.h"

GravityAverager::GravityAverager(size_t requiredSamples)
    : requiredSamples_(requiredSamples), count_(0), sumX_(0), sumY_(0), sumZ_(0) {}

void GravityAverager::reset() {
    count_ = 0;
    sumX_ = sumY_ = sumZ_ = 0.0f;
}

bool GravityAverager::update(bool isStationary, Vector3 rawAccel, Vector3& outAverage) {
    if (!isStationary) {
        reset(); // moving again before finishing -- discard, don't average across the transition
        return false;
    }

    sumX_ += rawAccel.x;
    sumY_ += rawAccel.y;
    sumZ_ += rawAccel.z;
    count_++;

    if (count_ < requiredSamples_) return false;

    outAverage = { sumX_ / count_, sumY_ / count_, sumZ_ / count_ };
    reset();
    return true;
}