#include "yaw_calibration.h"
#include <math.h>

namespace {
constexpr float kMinCorrelationToTrust = 0.5f; // below this, event too weak/noisy to use
constexpr float kMinCorrelationGap = 0.15f;    // require a clear winner, not a near-tie between axes

float pearson(const float* a, const float* b, size_t n) {
    if (n < 2) return 0.0f;

    float meanA = 0, meanB = 0;
    for (size_t i = 0; i < n; i++) { meanA += a[i]; meanB += b[i]; }
    meanA /= n; meanB /= n;

    float cov = 0, varA = 0, varB = 0;
    for (size_t i = 0; i < n; i++) {
        float da = a[i] - meanA;
        float db = b[i] - meanB;
        cov += da * db;
        varA += da * da;
        varB += db * db;
    }
    float denom = sqrtf(varA * varB);
    if (denom < 1e-6f) return 0.0f; // no variance in one signal -- can't correlate
    return cov / denom;
}

} // namespace

void differentiateSpeedToAccel(const float* speedKmh, const float* timestampSec,
                                size_t n, float* outAccelMs2) {
    if (n == 0) return;
    outAccelMs2[0] = 0.0f;
    for (size_t i = 1; i < n; i++) {
        float dv = (speedKmh[i] - speedKmh[i - 1]) / 3.6f; // km/h -> m/s
        float dt = timestampSec[i] - timestampSec[i - 1];
        outAccelMs2[i] = (dt > 1e-3f) ? (dv / dt) : 0.0f;
    }
}

EventCorrelation correlateEvent(const float* ax, const float* ay, const float* ref, size_t n) {
    return { pearson(ax, ref, n), pearson(ay, ref, n) };
}

YawCandidate candidateFromCorrelation(const EventCorrelation& corr) {
    float absX = fabsf(corr.corrWithX);
    float absY = fabsf(corr.corrWithY);

    float strongest = absX > absY ? absX : absY;
    float gap = fabsf(absX - absY);

    if (strongest < kMinCorrelationToTrust || gap < kMinCorrelationGap) {
        return { LongitudinalAxis::Undetermined, 0.0f };
    }

    if (absX > absY) {
        return { LongitudinalAxis::X, corr.corrWithX >= 0 ? 1.0f : -1.0f };
    }
    return { LongitudinalAxis::Y, corr.corrWithY >= 0 ? 1.0f : -1.0f };
}

YawCalibrationTracker::YawCalibrationTracker(int requiredConsistentEvents)
    : requiredConsistentEvents_(requiredConsistentEvents),
      consistentCount_(0),
      lastCandidate_{LongitudinalAxis::Undetermined, 0.0f},
      hasLastCandidate_(false) {}

YawCalibrationResult YawCalibrationTracker::addEvent(const YawCandidate& candidate) {
    if (candidate.axis == LongitudinalAxis::Undetermined) {
        // Weak/ambiguous event -- ignore it, don't burn an existing streak on noise.
        return { false, lastCandidate_ };
    }

    bool matches = hasLastCandidate_ &&
                   candidate.axis == lastCandidate_.axis &&
                   candidate.forwardSign == lastCandidate_.forwardSign;

    consistentCount_ = matches ? (consistentCount_ + 1) : 1; // mismatch starts a fresh streak

    lastCandidate_ = candidate;
    hasLastCandidate_ = true;

    bool locked = consistentCount_ >= requiredConsistentEvents_;
    return { locked, lastCandidate_ };
}

void YawCalibrationTracker::reset() {
    consistentCount_ = 0;
    hasLastCandidate_ = false;
    lastCandidate_ = { LongitudinalAxis::Undetermined, 0.0f };
}