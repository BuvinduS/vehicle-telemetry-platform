#include "calibration_nvs.h"
#include <Preferences.h>

namespace {
Preferences s_prefs;
}

bool CalibrationNvs::begin() {
    return s_prefs.begin(kNamespace, /*readOnly=*/false);
}

bool CalibrationNvs::load(CalibrationData& outData) {
    uint8_t buffer[kCalibrationBlobSize];
    size_t got = s_prefs.getBytes(kKey, buffer, kCalibrationBlobSize);
    if (got != kCalibrationBlobSize) return false; // key doesn't exist yet -- first boot
    return deserializeCalibration(buffer, kCalibrationBlobSize, outData);
}

bool CalibrationNvs::save(const CalibrationData& data) {
    uint8_t buffer[kCalibrationBlobSize];
    size_t written = serializeCalibration(data, buffer, kCalibrationBlobSize);
    if (written != kCalibrationBlobSize) return false;
    size_t stored = s_prefs.putBytes(kKey, buffer, kCalibrationBlobSize);
    return stored == kCalibrationBlobSize;
}

bool CalibrationNvs::clear() {
    return s_prefs.remove(kKey);
}