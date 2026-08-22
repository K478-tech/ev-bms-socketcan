"""
hmi/dashboard.py

Console-based Human Machine Interface. Subscribes to all bus traffic and
redraws a live status table. Also shows the most recent diagnostic warning.
"""

import os
import time
import threading

import can

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from common import can_ids as C


class Dashboard(can.Listener):
    def __init__(self, channel='vcan0'):
        self.bus = can.interface.Bus(channel=channel, interface='socketcan')
        self.voltage = None
        self.temperature = None
        self.current = None
        self.soc = None
        self.mode = None
        self.contactor = None
        self.fan = None
        self.last_warning = "None"
        self._lock = threading.Lock()
        self.notifier = can.Notifier(self.bus, [self])

    def on_message_received(self, msg: can.Message):
        with self._lock:
            if msg.arbitration_id == C.ID_CELL_VOLTAGE:
                self.voltage = C.decode_cell_voltage(msg.data)
            elif msg.arbitration_id == C.ID_CELL_TEMPERATURE:
                self.temperature = C.decode_cell_temperature(msg.data)
            elif msg.arbitration_id == C.ID_PACK_CURRENT:
                self.current = C.decode_pack_current(msg.data)
            elif msg.arbitration_id == C.ID_BMS_STATUS:
                self.soc, self.mode = C.decode_bms_status(msg.data)
            elif msg.arbitration_id == C.ID_CONTACTOR_CMD:
                self.contactor = C.decode_contactor_cmd(msg.data)
            elif msg.arbitration_id == C.ID_FAN_CMD:
                self.fan = C.decode_fan_cmd(msg.data)
            elif msg.arbitration_id == C.ID_SYSTEM_WARNING:
                flags = C.decode_fault_flags(msg.data)
                names = C.fault_flags_to_names(flags)
                self.last_warning = f"{names} @ {C.now_ts()}"

    def _fmt(self, v, unit="", nd=2):
        if v is None:
            return "—"
        return f"{v:.{nd}f}{unit}"

    def render_loop(self):
        try:
            while True:
                with self._lock:
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print("=" * 52)
                    print("   EV BATTERY MONITORING SYSTEM — LIVE DASHBOARD")
                    print("=" * 52)
                    print(f"  Cell Voltage     : {self._fmt(self.voltage, ' V', 3)}")
                    print(f"  Cell Temperature : {self._fmt(self.temperature, ' C', 1)}")
                    print(f"  Pack Current     : {self._fmt(self.current, ' A', 1)}")
                    print(f"  SOC              : {self._fmt(self.soc, ' %', 1)}")
                    mode_str = C.MODE_NAMES.get(self.mode, "—") if self.mode is not None else "—"
                    print(f"  Mode             : {mode_str}")
                    contactor_str = ("CLOSED" if self.contactor == C.CONTACTOR_CLOSED
                                      else "OPEN" if self.contactor is not None else "—")
                    print(f"  Contactor        : {contactor_str}")
                    print(f"  Fan              : {self._fmt(self.fan, ' %', 0)}")
                    print("-" * 52)
                    print(f"  Last Warning     : {self.last_warning}")
                    print("=" * 52)
                    print("  (Ctrl+C to exit)")
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n[HMI] Shutting down.")
            self.notifier.stop()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default='vcan0')
    args = parser.parse_args()
    Dashboard(channel=args.channel).render_loop()
