#include <unity.h>
#include "gravity_averager.h"
#include "calibration_manager.h"
#include <math.h>

void setUp(void) {}
void tearDown(void) {}

// --- GravityAverager -----------------------------------------------------

void test_averager_completes_after_required_samples(void) {
    GravityAverager avg(5);
    Vector3 result;
    bool done = false;
    for (int i = 0; i < 5; i++) {
        done = avg.update(true, {1.0f, 2.0f, 9.81f}, result);
    }
    TEST_ASSERT_TRUE(done);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 1.0f, result.x);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 2.0f, result.y);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, 9.81f, result.z);
}

void test_averager_resets_on_movement_before_completion(void) {
    GravityAverager avg(5);
    Vector3 result;

    avg.update(true, {0, 0, 9.81f}, result);
    avg.update(true, {0, 0, 9.81f}, result);
    bool interrupted = avg.update(false, {2.0f, 0, 5.0f}, result); // vehicle starts moving
    TEST_ASSERT_FALSE(interrupted);

    // Needs 5 FRESH stationary samples now, not just 3 more.
    bool done = false;
    for (int i = 0; i < 4; i++) {
        done = avg.update(true, {0, 0, 9.81f}, result);
    }
    TEST_ASSERT_FALSE(done); // only 4 of 5 fresh samples so far
    done = avg.update(true, {0, 0, 9.81f}, result);
    TEST_ASSERT_TRUE(done);
}

// --- CalibrationManager ----------------------------------------------------

// Loaded with both tilt+yaw already valid (from NVS) -> should start
// Ready immediately and never transition.
void test_manager_starts_ready_when_fully_loaded(void) {
    CalibrationData loaded;
    loaded.tiltValid = true;
    loaded.tiltCorrection = identityRotation();
    loaded.yawValid = true;
    loaded.yawAngleDeg = 0.0f;

    CalibrationManager mgr(loaded);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);

    bool transitioned = mgr.update({1, 2, 9.81f}, true, 0.0f, true);
    TEST_ASSERT_FALSE(transitioned);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);
}

// Loaded with tilt valid but yaw not -> should resume directly at
// NeedsYaw, not redo tilt from scratch.
void test_manager_resumes_at_needs_yaw_when_only_tilt_loaded(void) {
    CalibrationData loaded;
    loaded.tiltValid = true;
    loaded.tiltCorrection = identityRotation();
    loaded.yawValid = false;

    CalibrationManager mgr(loaded);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsYaw);
}

// Fresh (first boot, nothing valid) -> full lifecycle: stationary
// samples resolve tilt, then a clean sustained event resolves yaw,
// ending Ready with sane corrected output.
void test_manager_full_lifecycle_from_scratch(void) {
    CalibrationData empty; // all fields default-invalid
    CalibrationManager mgr(empty, /*requiredStationarySamples=*/5,
                            /*minYawWindows=*/2,
                            /*yawTriggerThreshold=*/1.5f, /*yawEndThreshold=*/0.5f,
                            /*yawMinSamplesToAnalyze=*/5, /*yawMaxSamplesPerEvent=*/20);

    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsTilt);

    // Tilted mount: gravity split across X and Z (~45 degrees)
    Vector3 tiltedGravity = {6.936f, 0.0f, 6.936f};
    bool tiltDone = false;
    for (int i = 0; i < 5; i++) {
        tiltDone = mgr.update(tiltedGravity, /*isStationary=*/true, 0.0f, /*isFreshReferenceSample=*/true);
    }
    TEST_ASSERT_TRUE(tiltDone);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsYaw);

    // Now driving: feed two consistent clean acceleration events.
    // Raw accel = tilted gravity + an injected event on the sensor's
    // untouched Y axis (which, after tilt correction, is where the
    // "true" forward signal will show up in this fabricated scenario).
    float refs[] = {1.6f, 2.0f, 2.5f, 3.0f, 2.5f, 2.0f, 1.6f, 0.2f};
    bool yawLocked = false;
    for (int eventNum = 0; eventNum < 6 && !yawLocked; eventNum++) {
        for (float r : refs) {
            Vector3 raw = { tiltedGravity.x, r, tiltedGravity.z }; // event rides on raw Y
            yawLocked = mgr.update(raw, /*isStationary=*/false, r, /*isFreshReferenceSample=*/true);
            if (yawLocked) break;
        }
    }

    TEST_ASSERT_TRUE(yawLocked);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);
    // The event rode on raw Y, which tilt correction leaves untouched -> forward is +Y (90 deg).
    TEST_ASSERT_FLOAT_WITHIN(5.0f, 90.0f, mgr.getCalibration().yawAngleDeg);

    // Final sanity: corrected output should now be tilt+yaw corrected.
    Vector3 corrected = mgr.getCorrectedAccel(tiltedGravity);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, corrected.x);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, corrected.y);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 9.81f, corrected.z);
}

// Before tilt is known, getCorrectedAccel should just pass raw through
// unmodified (identity) rather than applying some default guess.
void test_get_corrected_accel_is_identity_before_tilt_known(void) {
    CalibrationData empty;
    CalibrationManager mgr(empty);

    Vector3 raw = {3.0f, -1.0f, 8.5f};
    Vector3 corrected = mgr.getCorrectedAccel(raw);

    TEST_ASSERT_FLOAT_WITHIN(0.001f, raw.x, corrected.x);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, raw.y, corrected.y);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, raw.z, corrected.z);
}

// Stale reference ticks (isFreshReferenceSample=false) during NeedsYaw
// must not be able to trigger or complete a yaw event on their own --
// only genuinely fresh samples should count. Mirrors the real bug
// found during vehicle testing: held/repeated reference values have no
// variance for correlateEvent() to work with.
void test_stale_reference_ticks_dont_advance_yaw(void) {
    CalibrationData loaded;
    loaded.tiltValid = true;
    loaded.tiltCorrection = identityRotation();
    loaded.yawValid = false;

    CalibrationManager mgr(loaded, 20, /*minYawWindows=*/2,
                            1.5f, 0.5f, /*minSamples=*/3, /*maxSamples=*/20);

    // 30 stale ticks holding an easily-triggering value -- none of
    // these should move the state machine at all.
    bool anyTransition = false;
    for (int i = 0; i < 30; i++) {
        anyTransition = mgr.update({0, 2.0f, 0}, false, 2.0f, /*isFreshReferenceSample=*/false)
                         || anyTransition;
    }
    TEST_ASSERT_FALSE(anyTransition);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsYaw);
}


// --- Stale-tilt guard ---------------------------------------------------------

static CalibrationData fullyCalibratedIdentity() {
    CalibrationData d;
    d.tiltValid = true;
    d.tiltCorrection = identityRotation();
    d.yawValid = true;
    d.yawAngleDeg = 0.0f;
    return d;
}

// The real field reading: unit parked and level, but stored tilt says "already
// upright" while gravity is actually ~55 deg off (mostly on -X). The guard must notice,
// recompute tilt from that stationary reading, and drop yaw so it is re-learned.
void test_stale_tilt_detected_and_recomputed(void) {
    CalibrationManager mgr(fullyCalibratedIdentity(), 20);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);

    Vector3 parked = {-7.9f, 0.4f, 5.4f}; // from the vehicle log
    bool transitioned = false;
    for (int i = 0; i < 20; i++) {
        transitioned = mgr.update(parked, /*isStationary=*/true, 0.0f, false) || transitioned;
    }

    TEST_ASSERT_TRUE(transitioned);
    TEST_ASSERT_EQUAL(1, mgr.tiltAutoResets());
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsYaw);
    TEST_ASSERT_TRUE(mgr.getCalibration().tiltValid);
    TEST_ASSERT_FALSE(mgr.getCalibration().yawValid);

    // With the recomputed tilt, that same parked reading must now read as level gravity.
    Vector3 corrected = mgr.getCorrectedAccel(parked);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, corrected.x);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, corrected.y);
    TEST_ASSERT_FLOAT_WITHIN(0.1f, 9.63f, corrected.z);

    // ...and it must NOT keep re-triggering once fixed.
    bool again = false;
    for (int i = 0; i < 60; i++) again = mgr.update(parked, true, 0.0f, false) || again;
    TEST_ASSERT_FALSE(again);
    TEST_ASSERT_EQUAL(1, mgr.tiltAutoResets());
}

// A few degrees of error (road camber, small settling) must be tolerated, not
// treated as a moved unit -- otherwise every gentle slope would wipe yaw.
void test_small_tilt_error_is_tolerated(void) {
    CalibrationManager mgr(fullyCalibratedIdentity(), 20);
    Vector3 slightlyOff = {0.85f, 0.0f, 9.77f}; // ~5 degrees
    bool transitioned = false;
    for (int i = 0; i < 60; i++) transitioned = mgr.update(slightlyOff, true, 0.0f, false) || transitioned;
    TEST_ASSERT_FALSE(transitioned);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);
    TEST_ASSERT_EQUAL(0, mgr.tiltAutoResets());
}

// The guard must only ever look at stationary readings.
void test_stale_guard_ignores_moving_vehicle(void) {
    CalibrationManager mgr(fullyCalibratedIdentity(), 20);
    Vector3 tilted = {-7.9f, 0.4f, 5.4f};
    bool transitioned = false;
    for (int i = 0; i < 100; i++) transitioned = mgr.update(tilted, /*isStationary=*/false, 0.0f, false) || transitioned;
    TEST_ASSERT_FALSE(transitioned);
    TEST_ASSERT_EQUAL(0, mgr.tiltAutoResets());
}

// A reading whose magnitude is nowhere near 1 g is a glitch (or not really at rest);
// it must not be used to overwrite a stored tilt.
void test_stale_guard_ignores_implausible_magnitude(void) {
    CalibrationManager mgr(fullyCalibratedIdentity(), 20);
    Vector3 glitch = {0.0f, 0.0f, 3.0f};
    bool transitioned = false;
    for (int i = 0; i < 60; i++) transitioned = mgr.update(glitch, true, 0.0f, false) || transitioned;
    TEST_ASSERT_FALSE(transitioned);
    TEST_ASSERT_EQUAL(0, mgr.tiltAutoResets());
}

// Forward direction at an arbitrary, non-axis-aligned angle (165 deg), realistic vibration
// noise, and a mix of strong and weak windows. The old discrete axis picker could not
// represent this; the pooled heading must recover it and rotate accel accordingly.
static float lcgNoise(unsigned& state, float amp) {
    state = state * 1664525u + 1013904223u;
    return amp * ((state >> 8) / 8388608.0f - 1.0f); // ~uniform in [-amp, amp]
}

void test_pooled_heading_recovers_arbitrary_angle_with_noise(void) {
    CalibrationData loaded;
    loaded.tiltValid = true;
    loaded.tiltCorrection = identityRotation();
    CalibrationManager mgr(loaded, 20, /*minYawWindows=*/5, 0.15f, 0.05f, 6, 8);

    const float trueDeg = 165.0f;
    const float c = cosf(trueDeg * 0.0174533f), s = sinf(trueDeg * 0.0174533f);
    // Mix of strong braking/acceleration and weak wiggles, like the real drive.
    float refs[] = {1.4f, 0.6f, 1.0f, -0.5f, -0.9f, -2.8f, 0.5f, 0.2f,
                    0.4f, -0.3f, 0.3f, 0.2f, -0.2f, 0.4f, -0.3f, 0.2f,
                    2.8f, 1.1f, -1.4f, -5.5f, -0.8f, -0.4f, 0.8f, 0.2f};
    unsigned rng = 12345u;
    bool locked = false;
    for (int pass = 0; pass < 4 && !locked; pass++) {
        for (float r : refs) {
            float nf = lcgNoise(rng, 0.5f), nl = lcgNoise(rng, 0.5f);
            Vector3 v = { c * r - s * 0 + (c * nf - s * nl), s * r + (s * nf + c * nl), 9.81f };
            locked = mgr.update(v, false, r, true) || locked;
            if (locked) break;
        }
    }
    TEST_ASSERT_TRUE(locked);
    float err = fabsf(fmodf(mgr.getCalibration().yawAngleDeg - trueDeg + 540.0f, 360.0f) - 180.0f);
    TEST_ASSERT_TRUE(err < 15.0f);

    // A pure forward push must now come out (mostly) on the corrected +x axis.
    Vector3 push = { c * 2.0f, s * 2.0f, 9.81f };
    Vector3 out = mgr.getCorrectedAccel(push);
    TEST_ASSERT_TRUE(out.x > 1.8f);
    TEST_ASSERT_TRUE(fabsf(out.y) < 0.6f);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_averager_completes_after_required_samples);
    RUN_TEST(test_averager_resets_on_movement_before_completion);
    RUN_TEST(test_manager_starts_ready_when_fully_loaded);
    RUN_TEST(test_manager_resumes_at_needs_yaw_when_only_tilt_loaded);
    RUN_TEST(test_manager_full_lifecycle_from_scratch);
    RUN_TEST(test_get_corrected_accel_is_identity_before_tilt_known);
    RUN_TEST(test_stale_reference_ticks_dont_advance_yaw);
    RUN_TEST(test_stale_tilt_detected_and_recomputed);
    RUN_TEST(test_small_tilt_error_is_tolerated);
    RUN_TEST(test_stale_guard_ignores_moving_vehicle);
    RUN_TEST(test_stale_guard_ignores_implausible_magnitude);
    RUN_TEST(test_pooled_heading_recovers_arbitrary_angle_with_noise);
    return UNITY_END();
}