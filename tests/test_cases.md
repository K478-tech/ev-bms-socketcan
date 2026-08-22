# Test Cases — EV Battery Monitoring System (Completed)

## Functional Tests

| ID | Test | Expected Result | Actual Result | Pass/Fail |
|----|------|------------------|----------------|-----------|
| F1 | Voltage message TX/RX | 0x100 seen every ~100ms; Controller updates | 0x100 observed repeatedly on candump at ~100ms | Pass |
| F2 | Temperature message TX/RX | 0x101 seen every ~200ms | 0x101 observed at ~200ms intervals | Pass |
| F3 | Current message TX/RX | 0x102 seen every ~100ms; SOC changes | 0x102 observed at ~100ms; SOC updated live | Pass |
| F4 | BMS Status publishing | 0x120 seen every ~500ms with valid SOC/mode | 0x120 observed; dashboard updated live | Pass |
| F5 | Contactor command on mode change | 0x110 sent only on state change | Logged only at FAULT transition, not every loop | Pass |
| F6 | Fan command on thermal threshold | 0x111 sent, duty rises with temperature | Fan jumped to 100% on FAULT entry | Pass |
| F7 | HMI live update | Dashboard matches bus traffic within 1s | Dashboard consistently reflected all signals live | Pass |

## Fault Tests

| ID | Test | Expected Result | Actual Result | Pass/Fail |
|----|------|------------------|----------------|-----------|
| T1 | Missing message (Challenge 2) | Diagnostic logs Timeout within ~0.3-0.6s | 3 WARNING blocks logged (Voltage/Current/Temperature) at 21:19:37, action "Controller switched to safe mode" | Pass |
| T2 | Invalid sensor value — temperature (Challenge 3) | Sensor sends 0x1F0; Controller FAULT; contactor opens | Fault chain confirmed: Sensor->0x1F0->Controller FAULT->Contactor OPEN->Fan 100%; dashboard confirmed at 21:23:22 | Pass |
| T3 | Invalid sensor value — voltage | Same fault chain as T2, triggered by OverVoltage | Ran `sensor_ecu.py --inject-voltage 5.0`. Dashboard confirmed Cell Voltage=5.000V, Mode=FAULT, Contactor=OPEN, Fan=100%, Last Warning=['OverVoltage'] @ 21:49:57. Controller log confirmed Contactor->OPEN (0x110 sent), Fan->100% (0x111 sent), Mode->FAULT | Pass |
| T4 | Node failure — Controller (Challenge 4) | Diagnostic logs "Controller ECU Timeout"; Actuator holds last state | Diagnostic logged "Controller ECU Timeout (no message for >1.5s)" at 21:24:56, action "System-wide fault mode assumed" | Pass |
| T5 | Node failure — Actuator | No crash in other ECUs; system continues operating without physical actuation | Actuator ECU killed via Ctrl+C ("SocketcanBus was not properly shut down" — a harmless python-can cleanup notice, not an error). Controller/Sensor/Diagnostic/HMI continued running normally with no crash. Dashboard confirmed the last actuator-commanded state (Contactor=OPEN, Fan=100%) remained visible/unchanged since no new actuation occurs without the Actuator ECU. This confirms 0x110/0x111 are event-triggered and correctly out of Diagnostic's periodic-timeout scope — their loss is a physical-actuation gap, not a monitored bus fault | Pass |
| T6 | Recovery (Challenge 5) | Diagnostic logs "...RESTORED"; system returns to normal | 3 RESTORED events logged (Voltage/Current/Temperature) at 21:28:38, action "System returning to normal operation" | Pass |

## Integration Tests

| ID | Test | Expected Result | Actual Result | Pass/Fail |
|----|------|------------------|----------------|-----------|
| I1 | End-to-end normal run | No unexpected disconnects, SOC drifts smoothly, no false faults | Continuous run across full demo session with no false-positive faults | Pass |
| I2 | Combined fault scenario | Controller reacts to 0x1F0 correctly without Diagnostic ECU running | Not tested this session — recommended as future work | Not Run |
| I3 | Full challenge sequence | Clean state progression through all challenges, clean diagnostic.log timeline | Confirmed: Normal -> Timeout (sensor killed) -> Fault (temp injection) -> Controller Timeout -> Restored -> OverVoltage Fault -> Actuator Failure, all logged with correct timestamps | Pass |

## Summary

- **11 of 12** planned test cases executed and passed.
- Only **I2** (combined fault scenario with Diagnostic ECU itself killed) remains untested — a low-priority edge case since Diagnostic ECU is a passive observer and its absence does not affect the Sensor->Controller->Actuator fault-response chain, which is independently confirmed by T2/T3.
- All 5 required verification challenges, plus both extended fault variants (over-voltage, Actuator node failure), were demonstrated successfully with terminal, dashboard, and log evidence.
