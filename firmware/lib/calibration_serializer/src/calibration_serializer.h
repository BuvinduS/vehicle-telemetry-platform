#pragma once

#include "orientation_calibration.h"
#include "yaw_calibration.h"
#include <stdint.h>
#include <stddef.h>

// Pure struct + byte packing/unpacking for persisting calibration
// across boots. No Arduino/NVS dependency here on purpose -- fully
// native-testable. See calibration_nvs (a separate lib) for the actual
// flash read/write, which just moves these exact bytes in and out.

struct CalibrationData {
    bool tiltValid = false;
    RotationMatrix tiltCorrection = identityRotation();
    bool yawValid = false;
    float yawAngleDeg = 0.0f; // forward direction in the tilt-corrected plane, deg from +X toward +Y
};

// Fixed blob size (format v2): 4 (magic) + 1 (version) + 1 (tiltValid) + 36 (9
// floats) + 1 (yawValid) + 4 (yawAngleDeg) + 1 (checksum) = 48 bytes.
// v1 stored a discrete axis + sign and was 49 bytes; old blobs are simply rejected
// (treated as "nothing stored") and re-learned.
constexpr size_t kCalibrationBlobSize = 48;

// Serializes into buffer (must be >= kCalibrationBlobSize). Returns
// kCalibrationBlobSize on success, 0 if buffer is too small.
size_t serializeCalibration(const CalibrationData& data, uint8_t* buffer, size_t bufferSize);

// Deserializes from buffer. Returns false if the buffer is too small,
// magic/version don't match, or the checksum fails -- all three cases
// mean the same thing to a caller: "no trustworthy stored calibration,
// treat this like first boot." This deliberately covers blank/erased
// flash (reads as 0xFF bytes -- magic mismatch) as well as genuine
// corruption.
bool deserializeCalibration(const uint8_t* buffer, size_t bufferSize, CalibrationData& outData);