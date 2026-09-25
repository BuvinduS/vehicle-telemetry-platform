#include <unity.h>
#include "calibration_serializer.h"
#include <string.h>

void setUp(void) {}
void tearDown(void) {}

// A full round trip with realistic, non-trivial data should come back identical.
void test_roundtrip_full_calibration(void) {
    CalibrationData original;
    original.tiltValid = true;
    original.tiltCorrection = computeTiltCorrection({6.9f, 0.0f, 6.9f});
    original.yawValid = true;
    original.yawAxis = LongitudinalAxis::Y;
    original.yawForwardSign = -1.0f;

    uint8_t buffer[kCalibrationBlobSize];
    size_t written = serializeCalibration(original, buffer, kCalibrationBlobSize);
    TEST_ASSERT_EQUAL(kCalibrationBlobSize, written);

    CalibrationData restored;
    bool ok = deserializeCalibration(buffer, kCalibrationBlobSize, restored);
    TEST_ASSERT_TRUE(ok);

    TEST_ASSERT_TRUE(restored.tiltValid);
    TEST_ASSERT_TRUE(restored.yawValid);
    TEST_ASSERT_TRUE(restored.yawAxis == LongitudinalAxis::Y);
    TEST_ASSERT_FLOAT_WITHIN(0.001f, -1.0f, restored.yawForwardSign);
    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            TEST_ASSERT_FLOAT_WITHIN(0.0001f, original.tiltCorrection.m[i][j], restored.tiltCorrection.m[i][j]);
}

// Partial state (tilt done, yaw not yet locked) must round-trip too --
// this is the state saved right after tilt calibration, before any
// acceleration event has happened yet.
void test_roundtrip_tilt_only_partial_state(void) {
    CalibrationData original;
    original.tiltValid = true;
    original.tiltCorrection = identityRotation();
    original.yawValid = false; // not locked yet

    uint8_t buffer[kCalibrationBlobSize];
    serializeCalibration(original, buffer, kCalibrationBlobSize);

    CalibrationData restored;
    bool ok = deserializeCalibration(buffer, kCalibrationBlobSize, restored);
    TEST_ASSERT_TRUE(ok);
    TEST_ASSERT_TRUE(restored.tiltValid);
    TEST_ASSERT_FALSE(restored.yawValid);
}

// Blank/erased NVS flash reads as all 0xFF -- this must be rejected
// (magic won't match), not misread as some bizarre "valid" calibration.
void test_erased_flash_pattern_is_rejected(void) {
    uint8_t buffer[kCalibrationBlobSize];
    memset(buffer, 0xFF, kCalibrationBlobSize);

    CalibrationData restored;
    bool ok = deserializeCalibration(buffer, kCalibrationBlobSize, restored);
    TEST_ASSERT_FALSE(ok);
}

// A single flipped bit anywhere in a valid blob should fail the
// checksum and be rejected as corrupt, not silently accepted.
void test_corrupted_byte_fails_checksum(void) {
    CalibrationData original;
    original.tiltValid = true;
    original.tiltCorrection = computeTiltCorrection({0, 0, 9.81f});
    original.yawValid = true;
    original.yawAxis = LongitudinalAxis::X;
    original.yawForwardSign = 1.0f;

    uint8_t buffer[kCalibrationBlobSize];
    serializeCalibration(original, buffer, kCalibrationBlobSize);
    buffer[20] ^= 0xFF; // flip a byte in the middle of the tilt matrix data

    CalibrationData restored;
    bool ok = deserializeCalibration(buffer, kCalibrationBlobSize, restored);
    TEST_ASSERT_FALSE(ok);
}

// A future/unknown version byte should be rejected rather than
// misinterpreted with the current layout.
void test_wrong_version_is_rejected(void) {
    CalibrationData original;
    uint8_t buffer[kCalibrationBlobSize];
    serializeCalibration(original, buffer, kCalibrationBlobSize);
    buffer[4] = 99; // corrupt the version byte (offset 4, right after 4-byte magic)

    CalibrationData restored;
    bool ok = deserializeCalibration(buffer, kCalibrationBlobSize, restored);
    TEST_ASSERT_FALSE(ok);
}

// Buffers smaller than the fixed blob size must fail cleanly, not
// overrun.
void test_buffer_too_small_fails_cleanly(void) {
    CalibrationData original;
    uint8_t smallBuffer[10];
    size_t written = serializeCalibration(original, smallBuffer, sizeof(smallBuffer));
    TEST_ASSERT_EQUAL(0, written);

    uint8_t validBuffer[kCalibrationBlobSize] = {0};
    CalibrationData restored;
    bool ok = deserializeCalibration(validBuffer, 10, restored);
    TEST_ASSERT_FALSE(ok);
}

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_roundtrip_full_calibration);
    RUN_TEST(test_roundtrip_tilt_only_partial_state);
    RUN_TEST(test_erased_flash_pattern_is_rejected);
    RUN_TEST(test_corrupted_byte_fails_checksum);
    RUN_TEST(test_wrong_version_is_rejected);
    RUN_TEST(test_buffer_too_small_fails_cleanly);
    return UNITY_END();
}