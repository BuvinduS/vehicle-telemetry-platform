#include "obd_poller.h"

using namespace obd;

void ObdPoller::update() {
    obd2_.update();

    switch (obd2_.state()) {
        case QueryState::IDLE: {
            uint8_t pid = CORE_PIDS[pidIndex_].pid;
            // If requestPID() fails here (e.g. transient transport TX
            // failure), we simply try again next update() call with the
            // same pidIndex_ -- no special handling needed since IDLE
            // means nothing is lost by retrying.
            obd2_.requestPID(pid);
            break;
        }

        case QueryState::READY: {
            float value;
            uint8_t pid = CORE_PIDS[pidIndex_].pid;
            if (obd2_.getResult(value)) {
                applyResult(pid, value);
            }
            pidIndex_ = (pidIndex_ + 1) % CORE_PID_COUNT;
            break;
        }

        case QueryState::TIMED_OUT: {
            uint8_t pid = CORE_PIDS[pidIndex_].pid;
            markInvalid(pid);
            obd2_.clearTimeout();
            pidIndex_ = (pidIndex_ + 1) % CORE_PID_COUNT;
            break;
        }

        case QueryState::WAITING:
        default:
            break; // nothing to do -- still waiting on the current request
    }
}

void ObdPoller::applyResult(uint8_t pid, float value) {
    switch (pid) {
        case PID_RPM:
            latest_.rpm = value;
            latest_.rpm_valid = true;
            break;
        case PID_SPEED:
            latest_.speed_kmh = value;
            latest_.speed_valid = true;
            break;
        case PID_THROTTLE:
            latest_.throttle_pct = value;
            latest_.throttle_valid = true;
            break;
        case PID_COOLANT_TEMP:
            latest_.coolant_temp_c = value;
            latest_.coolant_valid = true;
            break;
        case PID_ENGINE_LOAD:
            latest_.engine_load_pct = value;
            latest_.engine_load_valid = true;
            break;
    }
}

void ObdPoller::markInvalid(uint8_t pid) {
    switch (pid) {
        case PID_RPM:            latest_.rpm_valid = false; break;
        case PID_SPEED:          latest_.speed_valid = false; break;
        case PID_THROTTLE:       latest_.throttle_valid = false; break;
        case PID_COOLANT_TEMP:   latest_.coolant_valid = false; break;
        case PID_ENGINE_LOAD:    latest_.engine_load_valid = false; break;
    }
}