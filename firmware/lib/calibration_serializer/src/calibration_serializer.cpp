#include "calibration_serializer.h"
#include <string.h>

namespace {

constexpr uint8_t kMagic[4] = {'C', 'A', 'L', '1'};
constexpr uint8_t kVersion = 1;

void writeFloat(uint8_t* buf, size_t& offset, float value) {
    memcpy(buf + offset, &value, sizeof(float));
    offset += sizeof(float);
}

float readFloat(const uint8_t* buf, size_t& offset) {
    float value;
    memcpy(&value, buf + offset, sizeof(float));
    offset += sizeof(float);
    return value;
}

uint8_t computeChecksum(const uint8_t* buf, size_t len) {
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) sum = static_cast<uint8_t>(sum + buf[i]);
    return sum;
}

} // namespace

size_t serializeCalibration(const CalibrationData& data, uint8_t* buffer, size_t bufferSize) {
    if (bufferSize < kCalibrationBlobSize) return 0;

    size_t offset = 0;
    memcpy(buffer + offset, kMagic, 4);
    offset += 4;
    buffer[offset++] = kVersion;
    buffer[offset++] = data.tiltValid ? 1 : 0;

    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            writeFloat(buffer, offset, data.tiltCorrection.m[i][j]);

    buffer[offset++] = data.yawValid ? 1 : 0;
    buffer[offset++] = static_cast<uint8_t>(data.yawAxis);
    writeFloat(buffer, offset, data.yawForwardSign);

    uint8_t checksum = computeChecksum(buffer, offset);
    buffer[offset++] = checksum;

    return offset; // == kCalibrationBlobSize
}

bool deserializeCalibration(const uint8_t* buffer, size_t bufferSize, CalibrationData& outData) {
    if (bufferSize < kCalibrationBlobSize) return false;
    if (memcmp(buffer, kMagic, 4) != 0) return false; // blank/erased flash or garbage

    size_t offset = 4;
    uint8_t version = buffer[offset++];
    if (version != kVersion) return false; // future: add migration here if format ever changes

    size_t checksumOffset = kCalibrationBlobSize - 1;
    uint8_t expectedChecksum = computeChecksum(buffer, checksumOffset);
    if (buffer[checksumOffset] != expectedChecksum) return false; // corrupt

    outData.tiltValid = buffer[offset++] != 0;

    for (int i = 0; i < 3; i++)
        for (int j = 0; j < 3; j++)
            outData.tiltCorrection.m[i][j] = readFloat(buffer, offset);

    outData.yawValid = buffer[offset++] != 0;
    outData.yawAxis = static_cast<LongitudinalAxis>(buffer[offset++]);
    outData.yawForwardSign = readFloat(buffer, offset);

    return true;
}