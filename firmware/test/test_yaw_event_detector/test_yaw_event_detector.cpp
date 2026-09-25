#include <unity.h>
#include "yaw_event_detector.h"
#include <math.h>

void setUp(void) {}
void tearDown(void) {}

// --- differentiateSpeedStep ---------------------------------------------

void test_speed_step_acceleration(void) {
    float accel = differentiateSpeedStep(20.0f, 0.0f, 25.0f, 0.5f);
    TEST_ASSERT_FLOAT_WITHIN(0.05f, 2.777f, accel);
}

void test_speed_step_zero_dt_returns_zero(void) {
    float accel = differentiateSpeedStep(20.0f, 1.0f, 20.0f, 1.0f); // same timestamp, no new sample
    TEST_ASSERT_FLOAT_WITHIN(0.001f, 0.0f, accel);
}

// --- YawEventDetector ------------------------------------------------------

// Below trigger threshold the whole time -- should never fire.
void test_stays_idle_below_trigger_threshold(void) {
    YawEventDetector detector(1.5f, 0.5f, 5, 20);
    YawCandidate candidate;
    for (int i = 0; i < 30; i++) {
        bool produced = detector.update(0.1f, 0.05f, 0.2f, candidate);
        TEST_ASSERT_FALSE(produced);
    }
}

// A clean, sustained event above trigger, well past minSamplesToAnalyze,
// then drops below endThreshold -- should produce an analyzed candidate
// with a determinable axis (X here, since ax tracks ref).
void test_clean_sustained_event_produces_candidate(void) {
    YawEventDetector detector(1.5f, 0.5f, /*minSamples=*/5, /*maxSamples=*/60);
    YawCandidate candidate;
    bool produced = false;

    // Ramp up through trigger, hold above it for a while (ax tracks ref, ay is flat noise)
    float refs[] = {1.6f, 2.0f, 2.5f, 3.0f, 3.2f, 3.0f, 2.5f, 2.0f, 1.6f, 0.2f};
    for (float r : refs) {
        produced = detector.update(r * 0.95f, 0.02f, r, candidate);
        if (produced) break;
    }

    TEST_ASSERT_TRUE(produced);
    TEST_ASSERT_TRUE(candidate.axis == LongitudinalAxis::X);
    TEST_ASSERT_TRUE(candidate.forwardSign > 0);
}

// A brief blip that crosses the trigger for only a couple samples
// (e.g. a pothole) then immediately drops below end threshold -- too
// short to analyze, should be silently discarded (no candidate,
// detector back to idle for the next real event).
void test_brief_blip_is_discarded(void) {
    YawEventDetector detector(1.5f, 0.5f, /*minSamples=*/10, /*maxSamples=*/60);
    YawCandidate candidate;

    bool produced1 = detector.update(1.6f, 0.0f, 1.6f, candidate); // triggers, 1 sample
    TEST_ASSERT_FALSE(produced1);
    bool produced2 = detector.update(0.1f, 0.0f, 0.1f, candidate); // drops below end -- ends event
    TEST_ASSERT_FALSE(produced2); // only 2 samples, below minSamplesToAnalyze=10 -> discarded

    // Detector should be back to idle and ready for a fresh event.
    bool producedNext = detector.update(0.1f, 0.0f, 0.2f, candidate);
    TEST_ASSERT_FALSE(producedNext);
}

// An event that never drops below endThreshold before the buffer fills
// (e.g. sustained highway acceleration) should still get analyzed once
// maxSamples is hit, rather than buffering forever.
void test_buffer_full_forces_analysis(void) {
    YawEventDetector detector(1.5f, 0.5f, /*minSamples=*/5, /*maxSamples=*/10);
    YawCandidate candidate;
    bool produced = false;

    for (int i = 0; i < 20; i++) {
        // Sustained acceleration, never drops below endThreshold
        produced = detector.update(2.0f, 0.01f, 2.0f, candidate);
        if (produced) break;
    }

    TEST_ASSERT_TRUE(produced); // should have fired at sample 10 (maxSamples), not run forever
}

// --- Runner ----------------------------------------------------------

int main(int argc, char **argv) {
    UNITY_BEGIN();
    RUN_TEST(test_speed_step_acceleration);
    RUN_TEST(test_speed_step_zero_dt_returns_zero);
    RUN_TEST(test_stays_idle_below_trigger_threshold);
    RUN_TEST(test_clean_sustained_event_produces_candidate);
    RUN_TEST(test_brief_blip_is_discarded);
    RUN_TEST(test_buffer_full_forces_analysis);
    return UNITY_END();
}