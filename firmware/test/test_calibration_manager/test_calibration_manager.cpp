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
    loaded.yawAxis = LongitudinalAxis::X;
    loaded.yawForwardSign = 1.0f;

    CalibrationManager mgr(loaded);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);

    bool transitioned = mgr.update({1, 2, 9.81f}, true, 0.0f);
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
                            /*requiredConsistentYawEvents=*/2,
                            /*yawTriggerThreshold=*/1.5f, /*yawEndThreshold=*/0.5f,
                            /*yawMinSamplesToAnalyze=*/5, /*yawMaxSamplesPerEvent=*/20);

    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsTilt);

    // Tilted mount: gravity split across X and Z (~45 degrees)
    Vector3 tiltedGravity = {6.936f, 0.0f, 6.936f};
    bool tiltDone = false;
    for (int i = 0; i < 5; i++) {
        tiltDone = mgr.update(tiltedGravity, /*isStationary=*/true, 0.0f);
    }
    TEST_ASSERT_TRUE(tiltDone);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::NeedsYaw);

    // Now driving: feed two consistent clean acceleration events.
    // Raw accel = tilted gravity + an injected event on the sensor's
    // untouched Y axis (which, after tilt correction, is where the
    // "true" forward signal will show up in this fabricated scenario).
    float refs[] = {1.6f, 2.0f, 2.5f, 3.0f, 2.5f, 2.0f, 1.6f, 0.2f};
    bool yawLocked = false;
    for (int eventNum = 0; eventNum < 2 && !yawLocked; eventNum++) {
        for (float r : refs) {
            Vector3 raw = { tiltedGravity.x, r, tiltedGravity.z }; // event rides on raw Y
            yawLocked = mgr.update(raw, /*isStationary=*/false, r);
            if (yawLocked) break;
        }
    }

    TEST_ASSERT_TRUE(yawLocked);
    TEST_ASSERT_TRUE(mgr.state() == CalibrationState::Ready);

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

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_averager_completes_after_required_samples);
    RUN_TEST(test_averager_resets_on_movement_before_completion);
    RUN_TEST(test_manager_starts_ready_when_fully_loaded);
    RUN_TEST(test_manager_resumes_at_needs_yaw_when_only_tilt_loaded);
    RUN_TEST(test_manager_full_lifecycle_from_scratch);
    RUN_TEST(test_get_corrected_accel_is_identity_before_tilt_known);
    return UNITY_END();
}