#include <unity.h>
#include "orientation_calibration.h"
#include <math.h>

void setUp(void) {}
void tearDown(void) {}

// --- Helpers -----------------------------------------------------------

static void assertVectorNear(Vector3 expected, Vector3 actual, float tol) {
    TEST_ASSERT_FLOAT_WITHIN(tol, expected.x, actual.x);
    TEST_ASSERT_FLOAT_WITHIN(tol, expected.y, actual.y);
    TEST_ASSERT_FLOAT_WITHIN(tol, expected.z, actual.z);
}

// --- Tests ---------------------------------------------------------------

// Unit already mounted dead level: calibration should be a no-op.
void test_already_level_returns_identity(void) {
    Vector3 level = {0, 0, 9.81f};
    RotationMatrix r = computeTiltCorrection(level);
    Vector3 corrected = applyCorrection(r, level);
    assertVectorNear({0, 0, 9.81f}, corrected, 0.01f);
}

// Unit tilted ~45 degrees (gravity split across X and Z): after
// correction, gravity should land back on pure +Z.
void test_45_degree_tilt_corrects_to_level(void) {
    Vector3 tilted = {6.936f, 0.0f, 6.936f}; // |g| ~ 9.81, 45 deg off Z
    RotationMatrix r = computeTiltCorrection(tilted);
    Vector3 corrected = applyCorrection(r, tilted);
    assertVectorNear({0, 0, 9.81f}, corrected, 0.05f);
}

// Tilt correction must generalize to readings taken AFTER calibration,
// not just reproduce the calibration sample itself. A lateral event
// riding on top of the same tilt should isolate cleanly onto Y.
void test_tilt_correction_isolates_later_lateral_event(void) {
    Vector3 calibrationGravity = {6.936f, 0.0f, 6.936f};
    RotationMatrix r = computeTiltCorrection(calibrationGravity);

    // Same tilt, plus 3 m/s^2 injected on the sensor's untouched Y axis
    Vector3 duringTurn = {6.936f, 3.0f, 6.936f};
    Vector3 corrected = applyCorrection(r, duringTurn);

    TEST_ASSERT_FLOAT_WITHIN(0.05f, 0.0f, corrected.x);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 3.0f, corrected.y);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 9.81f, corrected.z);
}

// Rotation matrices must preserve vector magnitude — a cheap way to
// catch a broken/non-orthogonal matrix from a formula mistake.
void test_correction_preserves_magnitude(void) {
    Vector3 tilted = {4.0f, 5.0f, 7.0f};
    RotationMatrix r = computeTiltCorrection(tilted);
    Vector3 corrected = applyCorrection(r, tilted);

    float originalMag = sqrtf(tilted.x * tilted.x + tilted.y * tilted.y + tilted.z * tilted.z);
    float correctedMag = sqrtf(corrected.x * corrected.x + corrected.y * corrected.y + corrected.z * corrected.z);
    TEST_ASSERT_FLOAT_WITHIN(0.01f, originalMag, correctedMag);
}

// Degenerate input (e.g. a bad/zero-length IMU sample slipping through
// before averaging) must not divide-by-zero or produce NaN — it should
// fall back to identity rather than crash the calibration routine.
void test_zero_vector_input_falls_back_safely(void) {
    Vector3 zero = {0, 0, 0};
    RotationMatrix r = computeTiltCorrection(zero);
    Vector3 corrected = applyCorrection(r, {1.0f, 2.0f, 3.0f});

    TEST_ASSERT_FALSE(isnan(corrected.x));
    TEST_ASSERT_FALSE(isnan(corrected.y));
    TEST_ASSERT_FALSE(isnan(corrected.z));
}

// Gravity read as pointing the "wrong way" on Z (e.g. unit mounted
// upside down) is the s~0, c<0 edge case in the Rodrigues formula —
// must not divide-by-zero, and must still correct gravity onto +Z.
void test_antiparallel_gravity_handled(void) {
    Vector3 invertedGravity = {0, 0, -9.81f};
    RotationMatrix r = computeTiltCorrection(invertedGravity);
    Vector3 corrected = applyCorrection(r, invertedGravity);
    assertVectorNear({0, 0, 9.81f}, corrected, 0.05f);
}

// Identity helper should be a true no-op — a separate check from
// "already level returns identity" above, testing the helper directly.
void test_identity_rotation_is_noop(void) {
    RotationMatrix id = identityRotation();
    Vector3 v = {1.23f, -4.56f, 7.89f};
    Vector3 result = applyCorrection(id, v);
    assertVectorNear(v, result, 0.001f);
}

// --- Runner ----------------------------------------------------------

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_already_level_returns_identity);
    RUN_TEST(test_45_degree_tilt_corrects_to_level);
    RUN_TEST(test_tilt_correction_isolates_later_lateral_event);
    RUN_TEST(test_correction_preserves_magnitude);
    RUN_TEST(test_zero_vector_input_falls_back_safely);
    RUN_TEST(test_antiparallel_gravity_handled);
    RUN_TEST(test_identity_rotation_is_noop);
    return UNITY_END();
}