"""
common/can_ids.py

Single source of truth for the EV Battery Monitoring System CAN matrix.
Every ECU imports this module so encode/decode logic never drifts apart.
"""

import struct

# --------------------------------------------------------------------------
# CAN Message IDs
# --------------------------------------------------------------------------
ID_CELL_VOLTAGE     = 0x100   # Sensor -> Controller, Diagnostic   (periodic 100ms)
ID_CELL_TEMPERATURE = 0x101   # Sensor -> Controller, Diagnostic   (periodic 200ms)
ID_PACK_CURRENT     = 0x102   # Sensor -> Controller, Diagnostic   (periodic 100ms)
ID_BMS_STATUS       = 0x120   # Controller -> Diagnostic, HMI      (periodic 500ms)
ID_CONTACTOR_CMD    = 0x110   # Controller -> Actuator             (event)
ID_FAN_CMD          = 0x111   # Controller -> Actuator             (event)
ID_SENSOR_FAULT     = 0x1F0   # Sensor -> Controller, Diagnostic   (event)
ID_SYSTEM_WARNING   = 0x1FF   # Diagnostic -> All (broadcast)      (event)

# Expected period (seconds) for periodic messages -> used by Diagnostic ECU
# for timeout detection. Event-triggered messages are not watched for timeout.
PERIODIC_PERIOD_S = {
    ID_CELL_VOLTAGE: 0.1,
    ID_CELL_TEMPERATURE: 0.2,
    ID_PACK_CURRENT: 0.1,
    ID_BMS_STATUS: 0.5,
}
TIMEOUT_MULTIPLIER = 3  # flag a timeout if no message seen for 3x its period

# --------------------------------------------------------------------------
# BMS Mode enum
# --------------------------------------------------------------------------
MODE_IDLE = 0
MODE_CHARGE = 1
MODE_DISCHARGE = 2
MODE_FAULT = 3
MODE_NAMES = {MODE_IDLE: "IDLE", MODE_CHARGE: "CHARGE",
              MODE_DISCHARGE: "DISCHARGE", MODE_FAULT: "FAULT"}

CONTACTOR_OPEN = 0
CONTACTOR_CLOSED = 1

# --------------------------------------------------------------------------
# Fault flag bits (used in ID_SENSOR_FAULT and internal fault tracking)
# --------------------------------------------------------------------------
FAULT_OVER_VOLTAGE  = 1 << 0
FAULT_UNDER_VOLTAGE = 1 << 1
FAULT_OVER_TEMP     = 1 << 2
FAULT_OVER_CURRENT  = 1 << 3
FAULT_TIMEOUT       = 1 << 4

# Valid physical ranges (used by Sensor ECU self-check and Diagnostic ECU
# plausibility checks)
VOLTAGE_RANGE_V     = (2.5, 4.3)     # healthy single-cell Li-ion range
TEMP_RANGE_C        = (-20, 60)      # healthy operating temperature
CURRENT_RANGE_A     = (-300, 300)    # healthy charge/discharge current

# ==========================================================================
# Encode / Decode helpers
# Each signal uses struct with explicit little-endian format.
# ==========================================================================

def encode_cell_voltage(voltage_v: float) -> bytes:
    """uint16, resolution 0.001V -> raw = V * 1000"""
    raw = int(round(voltage_v * 1000))
    raw = max(0, min(raw, 65535))
    return struct.pack('<H', raw)


def decode_cell_voltage(data: bytes) -> float:
    raw = struct.unpack('<H', data[:2])[0]
    return raw / 1000.0


def encode_cell_temperature(temp_c: float) -> bytes:
    """uint8, resolution 1C, offset -40 -> raw = T + 40"""
    raw = int(round(temp_c)) + 40
    raw = max(0, min(raw, 255))
    return struct.pack('<B', raw)


def decode_cell_temperature(data: bytes) -> float:
    raw = struct.unpack('<B', data[:1])[0]
    return raw - 40


def encode_pack_current(current_a: float) -> bytes:
    """int16, resolution 0.1A -> raw = I * 10"""
    raw = int(round(current_a * 10))
    raw = max(-32768, min(raw, 32767))
    return struct.pack('<h', raw)


def decode_pack_current(data: bytes) -> float:
    raw = struct.unpack('<h', data[:2])[0]
    return raw / 10.0


def encode_bms_status(soc_pct: float, mode: int) -> bytes:
    """byte0: SOC uint8 (res 0.5%) raw = SOC*2 ; byte1: mode enum"""
    raw_soc = int(round(soc_pct * 2))
    raw_soc = max(0, min(raw_soc, 255))
    return struct.pack('<BB', raw_soc, mode)


def decode_bms_status(data: bytes):
    raw_soc, mode = struct.unpack('<BB', data[:2])
    return raw_soc / 2.0, mode


def encode_contactor_cmd(state: int) -> bytes:
    return struct.pack('<B', state)


def decode_contactor_cmd(data: bytes) -> int:
    return struct.unpack('<B', data[:1])[0]


def encode_fan_cmd(duty_pct: int) -> bytes:
    duty_pct = max(0, min(int(duty_pct), 100))
    return struct.pack('<B', duty_pct)


def decode_fan_cmd(data: bytes) -> int:
    return struct.unpack('<B', data[:1])[0]


def encode_fault_flags(flags: int) -> bytes:
    return struct.pack('<B', flags & 0xFF)


def decode_fault_flags(data: bytes) -> int:
    return struct.unpack('<B', data[:1])[0]


def fault_flags_to_names(flags: int):
    names = []
    if flags & FAULT_OVER_VOLTAGE:  names.append("OverVoltage")
    if flags & FAULT_UNDER_VOLTAGE: names.append("UnderVoltage")
    if flags & FAULT_OVER_TEMP:     names.append("OverTemperature")
    if flags & FAULT_OVER_CURRENT:  names.append("OverCurrent")
    if flags & FAULT_TIMEOUT:       names.append("Timeout")
    return names


def now_ts() -> str:
    import datetime
    return datetime.datetime.now().strftime("%H:%M:%S")
