#pragma once

#include "calibration_serializer.h"

// Thin ESP32 NVS (flash) wrapper around calibration_serializer. Not
// native-testable -- depends on Arduino's Preferences library, so this
// stays in its own lib directory, separate from the pure serialization
// logic, precisely so `pio test -e native` never has to compile it.
// The byte-level correctness is already covered by
// test_calibration_serializer; this class is just "move those exact
// bytes to/from a named NVS blob."
//
// IMPORTANT: save() writes to flash. Flash has limited write-cycle
// endurance -- call save() only on real state transitions (tilt
// completes, yaw locks in), NEVER on every loop tick or every sample.

class CalibrationNvs {
public:
    // Call once in setup(), after Serial/Wire init and before any
    // load()/save() calls.
    bool begin();

    // Fills outData and returns true if a valid stored calibration
    // exists. Returns false on first-ever boot (nothing stored) or if
    // stored data is corrupt/from an incompatible version -- treat
    // both cases identically: no trusted calibration, run fresh.
    bool load(CalibrationData& outData);

    // Persists the given calibration, overwriting whatever was there.
    // Safe to call with a partial state (tiltValid=true, yawValid=false)
    // right after tilt completes, then call again once yaw locks in.
    bool save(const CalibrationData& data);

    // Wipes stored calibration. Wire this to a manual "recalibrate"
    // trigger only -- never call this automatically.
    bool clear();

private:
    static constexpr const char* kNamespace = "imu_calib";
    static constexpr const char* kKey = "blob";
};