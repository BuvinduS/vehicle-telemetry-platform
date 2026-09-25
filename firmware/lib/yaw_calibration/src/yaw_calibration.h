#pragma once

// Determines which tilt-corrected horizontal axis (X or Y) is
// "longitudinal" by correlating IMU acceleration against an
// independent reference signal derived from OBD-II speed, during real
// acceleration/braking events. Requires several consistent events
// before locking in, so a single noisy sample (a pothole, a bump)
// can't lock in the wrong axis.
//
// Simplification: this identifies a best-fit AXIS + SIGN, not a
// continuous rotation angle. Correct for a mount that's roughly
// axis-aligned (0/90/180/270 degrees) in the horizontal plane; an
// arbitrarily-angled mount will still show residual cross-axis mixing.
// Revisit with a continuous angle fit if the enclosure doesn't
// guarantee rough axis alignment.

#include <stddef.h>

enum class LongitudinalAxis { X, Y, Undetermined };

struct EventCorrelation {
    float corrWithX; // Pearson correlation, tilt-corrected accel X vs reference
    float corrWithY; // Pearson correlation, tilt-corrected accel Y vs reference
};

struct YawCandidate {
    LongitudinalAxis axis;
    float forwardSign; // +1 if a positive raw reading means forward accel, else -1
};

struct YawCalibrationResult {
    bool locked;
    YawCandidate candidate;
};

// Converts a buffered speed_kmh + timestamp series into an approximate
// longitudinal reference acceleration (m/s^2) via backward difference.
// OBD speed is coarse (often 1 km/h resolution) so this is intentionally
// a rough reference -- it only needs to be good enough to pick the
// right IMU axis, not to be a precision accelerometer substitute.
// outAccelMs2 must have space for n floats; outAccelMs2[0] is always 0
// (no prior sample to difference against).
void differentiateSpeedToAccel(const float* speedKmh, const float* timestampSec,
                                size_t n, float* outAccelMs2);

// Correlate one buffered event (tilt-corrected accel X/Y alongside the
// OBD-derived reference) over a braking/accelerating window. All three
// arrays must be the same length and time-aligned.
EventCorrelation correlateEvent(const float* tiltCorrectedAccelX,
                                 const float* tiltCorrectedAccelY,
                                 const float* referenceAccel,
                                 size_t sampleCount);

// Turn a correlation result into a candidate axis + sign, or
// Undetermined if neither axis correlates strongly enough, or the two
// axes are too close to call (ambiguous event -- not a clean accel/brake).
YawCandidate candidateFromCorrelation(const EventCorrelation& corr);

// Tracks candidates across multiple events; only locks in once several
// CONSECUTIVE events agree on both axis and sign.
class YawCalibrationTracker {
public:
    explicit YawCalibrationTracker(int requiredConsistentEvents = 3);

    // Feed one event's candidate. Undetermined candidates are ignored
    // (don't reset progress -- a single weak event shouldn't cost you
    // a streak of good ones). Returns current state; check .locked.
    YawCalibrationResult addEvent(const YawCandidate& candidate);

    void reset();

private:
    int requiredConsistentEvents_;
    int consistentCount_;
    YawCandidate lastCandidate_;
    bool hasLastCandidate_;
};