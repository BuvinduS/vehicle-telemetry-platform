#include <unity.h>
#include "yaw_calibration.h"
#include <math.h>

void setUp(void) {}
void tearDown(void) {}

// --- differentiateSpeedToAccel -----------------------------------------

// Constant speed increase over even timesteps should yield a constant
// (nonzero) reference acceleration, skipping the first (undefined) sample.
void test_differentiate_constant_acceleration(void) {
    // Speed rising 5 km/h every 0.5s -> ~2.78 m/s^2 constant accel
    float speed[] = {20, 25, 30, 35, 40};
    float ts[]    = {0.0f, 0.5f, 1.0f, 1.5f, 2.0f};
    float outAccel[5];

    differentiateSpeedToAccel(speed, ts, 5, outAccel);

    TEST_ASSERT_FLOAT_WITHIN(0.01f, 0.0f, outAccel[0]); // no prior sample
    for (int i = 1; i < 5; i++) {
        TEST_ASSERT_FLOAT_WITHIN(0.05f, 2.777f, outAccel[i]);
    }
}

// Braking (decreasing speed) should yield negative reference accel.
void test_differentiate_deceleration_is_negative(void) {
    float speed[] = {40, 30, 20};
    float ts[]    = {0.0f, 1.0f, 2.0f};
    float outAccel[3];

    differentiateSpeedToAccel(speed, ts, 3, outAccel);

    TEST_ASSERT_TRUE(outAccel[1] < 0);
    TEST_ASSERT_TRUE(outAccel[2] < 0);
}

// --- correlateEvent / candidateFromCorrelation --------------------------

// IMU X axis tracks the reference closely, Y is flat noise -> X wins,
// positive sign (accelerating reads positive on X, matching reference).
void test_clean_event_identifies_x_as_longitudinal(void) {
    float ref[]  = {0.0f, 1.0f, 2.0f, 3.0f, 4.0f};
    float ax[]   = {0.1f, 1.1f, 1.9f, 3.2f, 3.9f}; // tracks ref closely
    float ay[]   = {0.05f, -0.02f, 0.03f, -0.01f, 0.04f}; // flat noise

    EventCorrelation corr = correlateEvent(ax, ay, ref, 5);
    YawCandidate candidate = candidateFromCorrelation(corr);

    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::X);
    TEST_ASSERT_TRUE(candidate.forwardSign > 0);
}

// Same shape, but the axis reads inverted relative to reference
// (unit mounted so "forward" on that axis is physically negative) ->
// should still identify X, but with a negative sign.
void test_inverted_axis_gets_negative_sign(void) {
    float ref[] = {0.0f, 1.0f, 2.0f, 3.0f, 4.0f};
    float ax[]  = {-0.1f, -1.1f, -1.9f, -3.2f, -3.9f}; // inverted
    float ay[]  = {0.05f, -0.02f, 0.03f, -0.01f, 0.04f};

    EventCorrelation corr = correlateEvent(ax, ay, ref, 5);
    YawCandidate candidate = candidateFromCorrelation(corr);

    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::X);
    TEST_ASSERT_TRUE(candidate.forwardSign < 0);
}

// Y axis tracks reference instead of X -> Y should win this time.
void test_clean_event_identifies_y_as_longitudinal(void) {
    float ref[] = {0.0f, -1.0f, -2.0f, -3.0f}; // braking event
    float ax[]  = {0.02f, 0.05f, -0.03f, 0.01f}; // flat noise
    float ay[]  = {0.0f, -0.9f, -2.1f, -2.9f};   // tracks ref

    EventCorrelation corr = correlateEvent(ax, ay, ref, 4);
    YawCandidate candidate = candidateFromCorrelation(corr);

    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::Y);
    // ay decreases right alongside ref (both go negative together) --
    // that's a POSITIVE correlation, meaning this axis already reads
    // braking as negative/accel as positive with no inversion needed.
    TEST_ASSERT_TRUE(candidate.forwardSign > 0);
}

// Weak/noisy event -- neither axis correlates well (e.g. a pothole
// bump, not a real accel/brake) -- must come back Undetermined rather
// than guessing.
void test_weak_event_is_undetermined(void) {
    float ref[] = {0.0f, 0.1f, -0.05f, 0.08f};
    float ax[]  = {0.3f, -0.2f, 0.4f, -0.1f};
    float ay[]  = {-0.2f, 0.3f, -0.1f, 0.2f};

    EventCorrelation corr = correlateEvent(ax, ay, ref, 4);
    YawCandidate candidate = candidateFromCorrelation(corr);

    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::Undetermined);
}

// Ambiguous event -- both axes correlate similarly well (e.g. a
// diagonal-ish 45-degree-mounted bump) -- too close to call, must not
// pick one arbitrarily.
void test_ambiguous_event_is_undetermined(void) {
    float ref[] = {0.0f, 1.0f, 2.0f, 3.0f};
    float ax[]  = {0.0f, 0.9f, 2.1f, 2.9f};  // strong correlation
    float ay[]  = {0.0f, 0.95f, 1.9f, 3.1f}; // also strong, nearly tied

    EventCorrelation corr = correlateEvent(ax, ay, ref, 4);
    YawCandidate candidate = candidateFromCorrelation(corr);

    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::Undetermined);
}

// --- YawCalibrationTracker ----------------------------------------------

// Three consistent events in a row should lock in.
void test_tracker_locks_after_required_consistent_events(void) {
    YawCalibrationTracker tracker(3);
    YawCandidate c{ LongitudinalAxis::X, 1.0f };

    YawCalibrationResult r1 = tracker.addEvent(c);
    TEST_ASSERT_FALSE(r1.locked);
    YawCalibrationResult r2 = tracker.addEvent(c);
    TEST_ASSERT_FALSE(r2.locked);
    YawCalibrationResult r3 = tracker.addEvent(c);
    TEST_ASSERT_TRUE(r3.locked);
    TEST_ASSERT_TRUE(r3.candidate.axis == LongitudinalAxis::X);
}

// A conflicting event should restart the streak, not lock in early.
void test_tracker_restarts_streak_on_conflicting_event(void) {
    YawCalibrationTracker tracker(3);
    YawCandidate x{ LongitudinalAxis::X, 1.0f };
    YawCandidate y{ LongitudinalAxis::Y, 1.0f };

    tracker.addEvent(x);
    tracker.addEvent(x);
    YawCalibrationResult conflict = tracker.addEvent(y); // breaks the streak
    TEST_ASSERT_FALSE(conflict.locked);

    // Needs 3 fresh consistent Y events from here, not just 1 more.
    YawCalibrationResult r2 = tracker.addEvent(y);
    TEST_ASSERT_FALSE(r2.locked);
    YawCalibrationResult r3 = tracker.addEvent(y);
    TEST_ASSERT_TRUE(r3.locked);
    TEST_ASSERT_TRUE(r3.candidate.axis == LongitudinalAxis::Y);
}

// An Undetermined (weak/noisy) event shouldn't cost progress on an
// existing good streak.
void test_tracker_ignores_undetermined_events(void) {
    YawCalibrationTracker tracker(3);
    YawCandidate x{ LongitudinalAxis::X, 1.0f };
    YawCandidate weak{ LongitudinalAxis::Undetermined, 0.0f };

    tracker.addEvent(x);                                     // streak = 1
    YawCalibrationResult afterWeak = tracker.addEvent(weak);  // ignored, streak stays 1
    TEST_ASSERT_FALSE(afterWeak.locked);
    tracker.addEvent(x);                                      // streak = 2
    YawCalibrationResult r = tracker.addEvent(x);              // streak = 3 -> locked
    TEST_ASSERT_TRUE(r.locked); // 3 real consistent events, 1 ignored weak one in between
}

// --- Runner --------------------------------------------------------------

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_differentiate_constant_acceleration);
    RUN_TEST(test_differentiate_deceleration_is_negative);
    RUN_TEST(test_clean_event_identifies_x_as_longitudinal);
    RUN_TEST(test_inverted_axis_gets_negative_sign);
    RUN_TEST(test_clean_event_identifies_y_as_longitudinal);
    RUN_TEST(test_weak_event_is_undetermined);
    RUN_TEST(test_ambiguous_event_is_undetermined);
    RUN_TEST(test_tracker_locks_after_required_consistent_events);
    RUN_TEST(test_tracker_restarts_streak_on_conflicting_event);
    RUN_TEST(test_tracker_ignores_undetermined_events);
    return UNITY_END();
}