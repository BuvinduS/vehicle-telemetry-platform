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

// NOTE: these integer values get persisted to flash (see
// calibration_serializer) -- don't reorder or renumber this enum
// without a version bump there.
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

// Diagnostic / continuous-angle estimate: the direction in the horizontal
// plane along which accel best tracks the reference. angleDeg is measured
// from +X toward +Y (range -180..180, so it also encodes forward vs
// backward). projectedCorr is the Pearson correlation of accel projected
// onto that direction against the reference -- how trustworthy the angle is.
struct HeadingFit {
    float angleDeg;
    float projectedCorr;
};
HeadingFit fitHeading(const float* accelX, const float* accelY,
                      const float* referenceAccel, size_t sampleCount);

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

// ---------------------------------------------------------------------------
// Pooled continuous-heading estimation (used by CalibrationManager).
//
// Per-window correlations are too noisy on their own: the OBD reference is coarse
// and vibration dominates weak events. Instead each completed window contributes its
// raw covariance sums, and one heading is estimated from ALL windows pooled together.
// Strong accel/brake events carry large covariance, so they dominate naturally; weak
// noise-only windows barely move the estimate. Yaw is a continuous angle, so a mount at
// any orientation works (no axis-aligned assumption).
// ---------------------------------------------------------------------------

// Mean-removed sums for one window: covariance of each accel axis with the reference,
// plus the variance sums needed to turn a pooled direction into a correlation.
struct WindowStats {
    float covXR, covYR;   // sum (x-mx)(r-mr), sum (y-my)(r-mr)
    float sxx, syy, sxy;  // sum (x-mx)^2, (y-my)^2, (x-mx)(y-my)
    float srr;            // sum (r-mr)^2
};
WindowStats computeWindowStats(const float* accelX, const float* accelY,
                               const float* referenceAccel, size_t sampleCount);

struct HeadingEstimate {
    float angleDeg = 0.0f;     // forward direction, degrees from +X toward +Y (-180..180)
    float pooledCorr = 0.0f;   // correlation of accel projected on that direction vs reference
    int   windows = 0;         // windows pooled so far
    bool  locked = false;
};

class HeadingTracker {
public:
    // minWindows: pool at least this many windows before locking.
    // minPooledCorr: required pooled correlation along the estimated direction.
    // stableToleranceDeg / stableCount: the last stableCount pooled estimates must all
    //   lie within stableToleranceDeg of the newest one (i.e. the answer has settled).
    HeadingTracker(int minWindows = 5, float minPooledCorr = 0.4f,
                   float stableToleranceDeg = 12.0f, int stableCount = 3);

    // Add one completed window. Once locked, further windows are ignored until reset().
    const HeadingEstimate& addWindow(const WindowStats& w);
    const HeadingEstimate& current() const { return est_; }
    void reset();

private:
    static constexpr int kMaxHistory = 8;

    int   minWindows_;
    float minPooledCorr_;
    float stableToleranceDeg_;
    int   stableCount_;

    WindowStats pooled_;
    HeadingEstimate est_;
    float history_[kMaxHistory];
    int   historyCount_;
};