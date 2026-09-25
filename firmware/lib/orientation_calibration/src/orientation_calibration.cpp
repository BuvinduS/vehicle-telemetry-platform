#include "orientation_calibration.h"
#include <math.h>

namespace {

Vector3 normalize(Vector3 v) {
    float len = sqrtf(v.x * v.x + v.y * v.y + v.z * v.z);
    if (len < 1e-6f) return {0, 0, 1}; // degenerate input, avoid div-by-zero
    return {v.x / len, v.y / len, v.z / len};
}

Vector3 cross(Vector3 a, Vector3 b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x
    };
}

float dot(Vector3 a, Vector3 b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

} // namespace

RotationMatrix identityRotation() {
    RotationMatrix r{};
    r.m[0][0] = 1; r.m[1][1] = 1; r.m[2][2] = 1;
    return r;
}

RotationMatrix computeTiltCorrection(Vector3 measuredGravity) {
    const Vector3 target = {0, 0, 1}; // canonical "level, gravity on +z"
    Vector3 a = normalize(measuredGravity);

    Vector3 v = cross(a, target);
    float s = sqrtf(v.x * v.x + v.y * v.y + v.z * v.z); // sin(angle)
    float c = dot(a, target);                            // cos(angle)

    // Already aligned (unit mounted dead level) — identity, skip the math.
    if (s < 1e-6f && c > 0) {
        return identityRotation();
    }

    // Anti-parallel case (gravity reads as pointing +z instead of the
    // sensor being upside down some other way) — 180 degree rotation
    // about any axis perpendicular to target. Pick X arbitrarily.
    if (s < 1e-6f && c < 0) {
        RotationMatrix r{};
        r.m[0][0] = 1; r.m[1][1] = -1; r.m[2][2] = -1;
        return r;
    }

    // Rodrigues' rotation formula: R = I + [v]_x + [v]_x^2 * (1-c)/s^2
    float vx[3][3] = {
        {0, -v.z, v.y},
        {v.z, 0, -v.x},
        {-v.y, v.x, 0}
    };

    float factor = (1.0f - c) / (s * s);

    RotationMatrix r = identityRotation();
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            float vx2 = 0;
            for (int k = 0; k < 3; k++) vx2 += vx[i][k] * vx[k][j];
            r.m[i][j] += vx[i][j] + vx2 * factor;
        }
    }
    return r;
}

Vector3 applyCorrection(const RotationMatrix& r, Vector3 raw) {
    return {
        r.m[0][0] * raw.x + r.m[0][1] * raw.y + r.m[0][2] * raw.z,
        r.m[1][0] * raw.x + r.m[1][1] * raw.y + r.m[1][2] * raw.z,
        r.m[2][0] * raw.x + r.m[2][1] * raw.y + r.m[2][2] * raw.z
    };
}