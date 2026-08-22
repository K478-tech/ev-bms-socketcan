# System Design Report — EV Battery Monitoring System
### SocketCAN Assignment — Option 5

## 1. Problem Description

An Electric Vehicle Battery Management System (BMS) must continuously
monitor pack health (cell voltage, temperature, current), estimate
State of Charge (SOC), and protect the pack by controlling the main
contactor (isolating the pack on fault) and cooling fan (preventing
thermal runaway). This project implements a distributed, 4-ECU
simulation of such a system communicating over SocketCAN, plus a
Diagnostic ECU that provides bus-level fault detection independent of
the other nodes.

## 2. Functional Block Diagram

```
 [Voltage Sensor]   [Temp Sensor]   [Current Sensor]
          \               |               /
           \              |              /
                    SENSOR ECU
                          |
                (0x100/0x101/0x102/0x1F0)
                          |
                    CONTROLLER ECU  --- computes SOC, decides mode
                       /       \
              (0x110)/         \(0x111)
                     /           \
             [Contactor]      [Cooling Fan]      <- via ACTUATOR ECU
                     
   All messages also observed by: DIAGNOSTIC ECU -> 0x1FF -> HMI
```

## 3. ECU Architecture

| ECU | Role | Inputs | Outputs |
|---|---|---|---|
| Sensor ECU | Simulated sensing + self-check | (simulated physical values) | 0x100, 0x101, 0x102, 0x1F0 |
| Controller ECU (BMS) | SOC estimation, mode decision, safety logic | 0x100, 0x101, 0x102, 0x1F0 | 0x110, 0x111, 0x120 |
| Actuator ECU | Executes contactor/fan commands | 0x110, 0x111 | (physical action, logged) |
| Diagnostic ECU | Bus-wide timeout & plausibility watchdog | all messages | 0x1FF |

Network topology: all 4 ECUs + the HMI attach to a single shared
`vcan0` bus (classic multi-drop CAN bus topology), each as an
independent OS process — analogous to independent physical ECUs on a
vehicle CAN bus.

## 4. CAN Matrix

| CAN ID | Name | Transmitter | Receiver(s) | Type | Rate/Trigger |
|---|---|---|---|---|---|
| 0x100 | Cell Voltage | Sensor | Controller, Diagnostic | Periodic | 100 ms |
| 0x101 | Cell Temperature | Sensor | Controller, Diagnostic | Periodic | 200 ms |
| 0x102 | Pack Current | Sensor | Controller, Diagnostic | Periodic | 100 ms |
| 0x120 | BMS Status (SOC+Mode) | Controller | Diagnostic, HMI | Periodic | 500 ms |
| 0x110 | Contactor Command | Controller | Actuator | Event | on state change |
| 0x111 | Fan Command | Controller | Actuator | Event | on ≥5% threshold change |
| 0x1F0 | Sensor Fault Flags | Sensor | Controller, Diagnostic | Event | on fault detected |
| 0x1FF | System Warning | Diagnostic | All (broadcast) | Event | on fault/timeout detected |

## 5. Signal Specification

| Signal | Message | Bytes | Type | Resolution | Range | Encode formula |
|---|---|---|---|---|---|---|
| Cell Voltage | 0x100 | 2 (uint16, LE) | unsigned | 0.001 V | 0–5 V | raw = V × 1000 |
| Cell Temperature | 0x101 | 1 (uint8) | unsigned+offset | 1 °C | −40–120 °C | raw = T + 40 |
| Pack Current | 0x102 | 2 (int16, LE) | signed | 0.1 A | −500–500 A | raw = I × 10 |
| SOC | 0x120 byte0 | 1 (uint8) | unsigned | 0.5 % | 0–100 % | raw = SOC × 2 |
| BMS Mode | 0x120 byte1 | 1 (uint8) | enum | — | 0=Idle,1=Charge,2=Discharge,3=Fault | — |
| Contactor Cmd | 0x110 | 1 (uint8) | enum | — | 0=Open,1=Closed | — |
| Fan Duty | 0x111 | 1 (uint8) | unsigned | 1 % | 0–100 % | direct |
| Fault Flags | 0x1F0 / 0x1FF | 1 (uint8, bitfield) | bitfield | — | bit0 OverV, bit1 UnderV, bit2 OverTemp, bit3 OverCurrent, bit4 Timeout | — |

Physical plausibility ranges used for validation (Sensor ECU
self-check and Diagnostic ECU cross-check):
- Cell voltage: 2.5–4.3 V (typical Li-ion safe operating window)
- Temperature: −20–60 °C
- Current: −300–300 A

## 6. Design Decisions

- **python-can + SocketCAN** was chosen over raw sockets for
  cross-platform readability, mature CAN-utils interoperability
  (`candump`/`cansend` can observe/inject alongside the Python nodes),
  and built-in `Notifier`/`Listener` abstractions that map cleanly onto
  "ECU reacts to bus events."
- **Coulomb counting** for SOC (rather than a full OCV/lookup-table
  model) was chosen for simplicity appropriate to a communication-
  network assignment — the SOC algorithm is a placeholder for BMS
  business logic, not the graded artifact; the CAN design is.
- **Dual-layer fault detection**: the Sensor ECU self-reports faults
  (0x1F0) for fast reaction by the Controller, while the Diagnostic
  ECU *independently* re-validates every received value. This means a
  malfunctioning Sensor ECU that stops self-checking (but keeps
  transmitting garbage) is still caught — a deliberate defense-in-depth
  choice reflecting how real automotive diagnostic layers work.
- **Event-triggered vs periodic split** follows real BMS practice:
  raw sensor telemetry is periodic (needed continuously for control
  loops), while actuator commands and faults are event-triggered
  (sent only when something changes, reducing bus load).
- **Timeout multiplier = 3×** period is a standard conservative
  choice — tolerant to a couple of dropped/delayed frames from
  scheduling jitter, but fast enough (≤0.6s worst case here) for a
  safety-relevant BMS.

## 7. Fault Handling Summary

| Trigger | Detection point | System response |
|---|---|---|
| Sensor value out of physical range | Sensor ECU self-check (fast) + Diagnostic ECU cross-check (independent) | 0x1F0 sent → Controller enters FAULT mode → contactor OPEN, fan 100% |
| Periodic message missing >3× period | Diagnostic ECU watchdog | 0x1FF broadcast + diagnostic.log WARNING entry |
| ECU process killed | Diagnostic ECU watchdog (via missing periodic messages) | Same as above; downstream nodes (e.g. Actuator) hold last known state |
| Fault condition clears / ECU restarts | Diagnostic ECU (message resumes) | "RESTORED" log entry; Controller mode returns to normal once fault_active clears |

## 8. Known Limitations / Future Work

- SOC model is simplistic coulomb counting with no temperature
  compensation or cell balancing — acceptable for this assignment's
  scope (CAN network design), not production-grade BMS logic.
- Single simulated cell rather than a full pack (e.g. 96 cells) to
  keep the CAN matrix and code readable; the same message pattern
  scales directly (e.g. per-cell voltage messages with a cell-index
  byte).
- No bus-off / error-frame handling implemented; SocketCAN's default
  error handling is relied upon.
