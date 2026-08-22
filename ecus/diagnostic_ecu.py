"""
diagnostic_ecu.py

Passively monitors the entire bus:
- Tracks last-seen timestamp for every periodic message -> detects timeouts
  (Challenge 2: Missing Message Detection, Challenge 4: Node Failure).
- Validates decoded signal values against physical ranges -> detects invalid
  sensor values even if the Sensor ECU itself failed to self-report
  (defense in depth alongside Challenge 3).
- Listens for 0x1F0 (sensor-reported faults) and relays them.
- Broadcasts 0x1FF System Warning messages and writes a structured event log
  matching the assignment's required format.
- Detects recovery (Challenge 5): once a previously-timed-out message resumes,
  logs a "recovered" event.
"""

import os
import threading
import time

import can

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from common import can_ids as C

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'diagnostic.log')


def log_event(source: str, description: str, action: str):
    ts = C.now_ts()
    entry = (
        f"WARNING:\n{description}\n\nSource: {source}\nTimestamp: {ts}\nAction: {action}\n"
        + ("-" * 40)
    )
    print(entry)
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, 'a') as f:
        f.write(entry + '\n')


class DiagnosticECU(can.Listener):
    def __init__(self, channel='vcan0'):
        self.bus = can.interface.Bus(channel=channel, interface='socketcan')
        self.last_seen = {}          # can_id -> timestamp
        self.timed_out = {}          # can_id -> bool (already flagged?)
        self._stop = False
        self._lock = threading.Lock()
        self.notifier = can.Notifier(self.bus, [self])

    def _send(self, arb_id, data):
        msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
        self.bus.send(msg)

    def _broadcast_warning(self, flags):
        self._send(C.ID_SYSTEM_WARNING, C.encode_fault_flags(flags))

    # -------------------- message reception & value checks -----------------
    def on_message_received(self, msg: can.Message):
        can_id = msg.arbitration_id
        with self._lock:
            was_timed_out = self.timed_out.get(can_id, False)
            self.last_seen[can_id] = time.time()
            if was_timed_out and can_id in C.PERIODIC_PERIOD_S:
                self.timed_out[can_id] = False
                recovered = True
            else:
                recovered = False

        if recovered:
            log_event(source=self._name_for_id(can_id),
                      description=f"{self._name_for_id(can_id)} communication RESTORED",
                      action="System returning to normal operation")

        # ---- plausibility checks on received values ----
        if can_id == C.ID_CELL_VOLTAGE:
            v = C.decode_cell_voltage(msg.data)
            lo, hi = C.VOLTAGE_RANGE_V
            if v < lo or v > hi:
                log_event("Sensor ECU", f"Invalid Cell Voltage reading: {v:.3f} V",
                          "Controller notified / safe-mode expected")
        elif can_id == C.ID_CELL_TEMPERATURE:
            t = C.decode_cell_temperature(msg.data)
            lo, hi = C.TEMP_RANGE_C
            if t < lo or t > hi:
                log_event("Sensor ECU", f"Invalid Cell Temperature reading: {t:.1f} C",
                          "Controller notified / safe-mode expected")
        elif can_id == C.ID_PACK_CURRENT:
            i = C.decode_pack_current(msg.data)
            lo, hi = C.CURRENT_RANGE_A
            if i < lo or i > hi:
                log_event("Sensor ECU", f"Invalid Pack Current reading: {i:.1f} A",
                          "Controller notified / safe-mode expected")
        elif can_id == C.ID_SENSOR_FAULT:
            flags = C.decode_fault_flags(msg.data)
            names = C.fault_flags_to_names(flags)
            log_event("Sensor ECU", f"Sensor Fault reported: {names}",
                      "Controller switched to FAULT mode / contactor opened")
            self._broadcast_warning(flags)
        elif can_id == C.ID_BMS_STATUS:
            soc, mode = C.decode_bms_status(msg.data)
            if mode == C.MODE_FAULT:
                pass  # already logged via sensor fault path

    @staticmethod
    def _name_for_id(can_id):
        return {
            C.ID_CELL_VOLTAGE: "Sensor ECU (Voltage)",
            C.ID_CELL_TEMPERATURE: "Sensor ECU (Temperature)",
            C.ID_PACK_CURRENT: "Sensor ECU (Current)",
            C.ID_BMS_STATUS: "Controller ECU",
        }.get(can_id, hex(can_id))

    # ---------------------------- timeout watchdog --------------------------
    def _watchdog_loop(self):
        while not self._stop:
            now = time.time()
            with self._lock:
                for can_id, period in C.PERIODIC_PERIOD_S.items():
                    last = self.last_seen.get(can_id)
                    already_flagged = self.timed_out.get(can_id, False)
                    if last is None:
                        continue  # never seen yet, skip until first message
                    if (now - last) > period * C.TIMEOUT_MULTIPLIER and not already_flagged:
                        self.timed_out[can_id] = True
                        name = self._name_for_id(can_id)
                        threading.Thread(
                            target=log_event,
                            args=(name, f"{name} Timeout (no message for >{period*C.TIMEOUT_MULTIPLIER:.1f}s)",
                                  "Controller switched to safe mode" if "Controller" not in name
                                  else "System-wide fault mode assumed"),
                            daemon=True,
                        ).start()
                        self._broadcast_warning(C.FAULT_TIMEOUT)
            time.sleep(0.2)

    def run(self):
        print("[DiagnosticECU] Starting. Monitoring bus for timeouts and invalid values.")
        threading.Thread(target=self._watchdog_loop, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[DiagnosticECU] Shutting down.")
            self._stop = True
            self.notifier.stop()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default='vcan0')
    args = parser.parse_args()
    DiagnosticECU(channel=args.channel).run()
