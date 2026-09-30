#pragma once

// Tilt-only orientation correction. Solves roll/pitch by rotating a
// measured gravity vector onto canonical "level" (0, 0, +9.81).
// Does NOT solve yaw — see the OBD-speed-correlation component for that.
// No dynamic allocation, no external deps — safe for ESP32 or native/Unity tests.

struct Vector3 {
    float x, y, z;
};

struct RotationMatrix {
    float m[3][3];
};

// Build a rotation that maps `measuredGravity` onto (0, 0, +9.81).
// `measuredGravity` should be an average of several stationary
// accelerometer readings (see note in .cpp on how many / how long).
RotationMatrix computeTiltCorrection(Vector3 measuredGravity);

// Apply a previously computed rotation to any subsequent raw reading.
Vector3 applyCorrection(const RotationMatrix& r, Vector3 raw);

// Identity matrix — safe default before any calibration has run.
RotationMatrix identityRotation();