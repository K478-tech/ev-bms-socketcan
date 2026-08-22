# EV Battery Monitoring System — SocketCAN Assignment

A 4-ECU distributed system communicating over a simulated CAN bus
(`vcan0`) using Linux SocketCAN + `python-can`.

## Architecture

                         Cell Voltage (0x100)
                         Cell Temperature (0x101)
                         Pack Current (0x102)
                         Sensor Fault (0x1F0)
        SENSOR ECU ────────────────────────────────►
                                                        │
                              ┌─────────────────────────┴─────────────────────────┐
                              │                    vcan0 (shared bus)              │
                              └─────────────────────────┬─────────────────────────┘
                                                        │
        CONTROLLER ECU ◄────────────────────────────────┘
             │   ▲
             │   │  BMS Status (0x120)
             │   └────────────────────────────► (Diagnostic ECU, HMI)
             │
             │  Contactor Cmd (0x110), Fan Cmd (0x111)
             ▼
        ACTUATOR ECU

        DIAGNOSTIC ECU  ── listens to ALL IDs on vcan0 ── broadcasts System Warning (0x1FF)
        HMI DASHBOARD   ── listens to ALL IDs on vcan0 (read-only)
All 4 ECUs + the HMI attach to the same `vcan0` bus as independent OS
processes — exactly like independent physical nodes on a real CAN bus.

## 1. Setup

```bash
# System packages
sudo apt update
sudo apt install can-utils

# Virtual CAN interface
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0

# Python dependencies
pip install -r requirements.txt
```

Verify the interface:
```bash
ip link show vcan0
```

## 2. Running the system

Open 6 terminals (or use `tmux`/`screen`):

```bash
# Terminal 1 — raw bus trace (optional but recommended for the demo)
candump vcan0

# Terminal 2
python3 ecus/sensor_ecu.py

# Terminal 3
python3 ecus/controller_ecu.py

# Terminal 4
python3 ecus/actuator_ecu.py

# Terminal 5
python3 ecus/diagnostic_ecu.py

# Terminal 6 — dashboard
python3 hmi/dashboard.py
```

Start them in roughly this order (Sensor → Controller → Actuator →
Diagnostic → HMI) so early messages aren't missed, though the system is
resilient to any start order.

## 3. Running the verification challenges

**Challenge 1 — Normal operation:** just let the system in the state
above run for a minute or two. Watch SOC drift, mode settle to
IDLE/CHARGE/DISCHARGE depending on simulated current.

**Challenge 2 — Missing message detection:**
```bash
# In the Sensor ECU terminal, press Ctrl+C
```
Within ~0.3–0.6s the Diagnostic ECU terminal should print a Timeout
WARNING block and it will be appended to `logs/diagnostic.log`.

**Challenge 3 — Sensor fault / invalid data handling:**
```bash
python3 ecus/sensor_ecu.py --inject-temp 200 --inject-after 5
```
After 5 seconds this Sensor ECU instance reports temperature=200°C,
triggering a 0x1F0 fault. Watch the Controller terminal switch to
FAULT mode and the Actuator terminal open the contactor.

Other injectable faults:
```bash
python3 ecus/sensor_ecu.py --inject-voltage 5.0 --inject-after 5
python3 ecus/sensor_ecu.py --inject-current 900 --inject-after 5
```

**Challenge 4 — Node failure handling:**
```bash
# In the Controller ECU terminal, press Ctrl+C
```
Actuator ECU holds its last commanded state (no new commands arrive).
Diagnostic ECU logs a Controller ECU Timeout warning.

**Challenge 5 — Recovery:**
```bash
# Restart whichever ECU you killed, e.g.:
python3 ecus/sensor_ecu.py
```
Diagnostic ECU detects messages resuming and logs a "...RESTORED"
event; the Controller naturally returns to normal mode once fault
conditions clear.

## 4. Logs

- `logs/diagnostic.log` — every WARNING event raised by the Diagnostic ECU
  (timeouts, invalid values, sensor faults, recoveries)
- `logs/actuator.log` — every contactor/fan state change

## 5. Project structure

```
ev-bms-socketcan/
├── common/can_ids.py        # CAN matrix, encode/decode, shared constants
├── ecus/
│   ├── sensor_ecu.py        # 0x100, 0x101, 0x102, 0x1F0 (fault injection via CLI)
│   ├── controller_ecu.py    # SOC calc, mode logic, 0x110/0x111/0x120
│   ├── actuator_ecu.py      # simulated contactor + fan
│   └── diagnostic_ecu.py    # timeout watchdog, value validation, 0x1FF
├── hmi/dashboard.py         # console live dashboard
├── tests/test_cases.md      # test case table for the test report
├── logs/                    # generated at runtime
├── docs/design_report.md    # system design report source
└── requirements.txt
```

## 6. CAN Matrix (summary)

| ID | Name | Direction | Type | Rate |
|---|---|---|---|---|
| 0x100 | Cell Voltage | Sensor → Controller/Diag | Periodic | 100ms |
| 0x101 | Cell Temperature | Sensor → Controller/Diag | Periodic | 200ms |
| 0x102 | Pack Current | Sensor → Controller/Diag | Periodic | 100ms |
| 0x120 | BMS Status (SOC+Mode) | Controller → Diag/HMI | Periodic | 500ms |
| 0x110 | Contactor Command | Controller → Actuator | Event | on change |
| 0x111 | Fan Command | Controller → Actuator | Event | on threshold |
| 0x1F0 | Sensor Fault Flags | Sensor → Controller/Diag | Event | on fault |
| 0x1FF | System Warning | Diagnostic → All | Event | on fault/timeout |

Full signal-level spec (byte layout, resolution, ranges) is in
`docs/design_report.md`.

## 7. Worked Example — Manually Decoding a candump Frame

Sample raw output from `candump vcan0` during normal operation:


Each line reads: **interface** `vcan0` — **CAN ID** (hex) — **DLC** (data length in bytes, in `[ ]`) — **payload bytes** (hex).

- `100` = 0x100 = Cell Voltage message, DLC 2
- `102` = 0x102 = Pack Current message, DLC 2

Both signals are little-endian (`struct.pack('<H', ...)` for voltage, `'<h'` for current — see `common/can_ids.py`), so the **first byte is the low byte**.

**Line 1 — `100 [2] 6D 0E`** (Cell Voltage)
Bytes `0x6D, 0x0E` → little-endian uint16 = `0x0E6D` = 3693
Voltage = 3693 / 1000 = **3.693 V**

**Line 2 — `102 [2] D7 FF`** (Pack Current)
Bytes `0xD7, 0xFF` → little-endian int16 = `0xFFD7` = −41 (two's complement)
Current = −41 / 10 = **−4.1 A** (negative = discharging)

**Line 3 — `100 [2] 64 0E`** (Cell Voltage)
`0x0E64` = 3684 → **3.684 V**

**Line 4 — `102 [2] D4 FF`** (Pack Current)
`0xFFD4` = −44 → **−4.4 A**

This confirms the Sensor ECU's simulated random-walk output (voltage ~3.68–3.69V, small discharge current) is being encoded and transmitted on the bus exactly as specified in the Signal Specification table above.
