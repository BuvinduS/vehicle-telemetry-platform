// Bench-test sketch: verifies CalibrationNvs actually survives a power
// cycle. Completely separate flash from the main firmware -- does not
// touch main.cpp or any other production file.
//
// HOW TO USE:
// 1. Flash this. On first boot (nothing stored yet), it writes a known
//    sample calibration and prints "SAVED".
// 2. Reset the board (button, or power-cycle it) WITHOUT reflashing.
// 3. On the second boot, load() should now succeed and print the same
//    values back -- that's the actual proof persistence works, not
//    just that the code compiles.
// 4. To reset and try again from scratch, use the serial command
//    below to clear stored calibration.

#include <Arduino.h>
#include "calibration_nvs.h"
#include "orientation_calibration.h"

static CalibrationNvs nvs;

static void printCalibration(const char* label, const CalibrationData& data) {
    Serial.printf("--- %s ---\n", label);
    Serial.printf("tiltValid=%d yawValid=%d yawAxis=%d yawForwardSign=%.2f\n",
                  data.tiltValid, data.yawValid,
                  static_cast<int>(data.yawAxis), data.yawForwardSign);
    Serial.println("tiltCorrection matrix:");
    for (int i = 0; i < 3; i++) {
        Serial.printf("  %.4f %.4f %.4f\n",
                      data.tiltCorrection.m[i][0],
                      data.tiltCorrection.m[i][1],
                      data.tiltCorrection.m[i][2]);
    }
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    Serial.println(F("[bench] Calibration NVS persistence check starting..."));

    if (!nvs.begin()) {
        Serial.println(F("[bench] NVS begin() failed -- halting."));
        while (true) { delay(1000); }
    }

    CalibrationData loaded;
    if (nvs.load(loaded)) {
        Serial.println(F("[bench] Found EXISTING stored calibration (this is a reboot, not first boot):"));
        printCalibration("LOADED", loaded);
        Serial.println(F("[bench] If these values match what you saved last boot, persistence works."));
    } else {
        Serial.println(F("[bench] No valid stored calibration found (first boot, or previously cleared)."));

        // Write a known sample so the NEXT boot has something real to load back.
        CalibrationData sample;
        sample.tiltValid = true;
        sample.tiltCorrection = computeTiltCorrection({6.9f, 0.3f, 6.9f}); // arbitrary non-trivial tilt
        sample.yawValid = true;
        sample.yawAxis = LongitudinalAxis::Y;
        sample.yawForwardSign = -1.0f;

        bool saved = nvs.save(sample);
        Serial.printf("[bench] Save result: %s\n", saved ? "SAVED" : "FAILED");
        printCalibration("SAVED (verify this matches after reboot)", sample);
    }

    Serial.println(F("[bench] Send 'c' over serial to clear stored calibration and start over."));
}

void loop() {
    if (Serial.available()) {
        char c = Serial.read();
        if (c == 'c') {
            bool cleared = nvs.clear();
            Serial.printf("[bench] Clear result: %s -- reset the board to test first-boot behavior again.\n",
                          cleared ? "CLEARED" : "FAILED");
        }
    }
    delay(50);
}