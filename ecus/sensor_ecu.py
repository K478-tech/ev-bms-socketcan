"""
sensor_ecu.py

Simulates the battery pack's sensing hardware:
- Cell voltage   (0x100, periodic 100ms)
- Cell temperature (0x101, periodic 200ms)
- Pack current   (0x102, periodic 100ms)

Also performs a local self-check: if a value goes out of physical range,
it immediately sends a Sensor Fault message (0x1F0, event-triggered).

Fault injection (for Challenge 3) via CLI:
    python sensor_ecu.py --inject-temp 200
    python sensor_ecu.py --inject-voltage 5.0
    python sensor_ecu.py --inject-current 900
"""

import argparse
import random
import threading
import time

import can

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from common import can_ids as C


class SensorECU:
    def __init__(self, channel='vcan0', inject_temp=None, inject_voltage=None,
                 inject_current=None, inject_after=8.0):
        self.bus = can.interface.Bus(channel=channel, interface='socketcan')
        self.voltage = 3.7
        self.temperature = 25.0
        self.current = 0.0
        self.start_time = time.time()

        self.inject_temp = inject_temp
        self.inject_voltage = inject_voltage
        self.inject_current = inject_current
        self.inject_after = inject_after
        self._injected = False

        self._stop = False

    # ---- simulated physical readings (random walk around a setpoint) ----
    def _update_readings(self):
        elapsed = time.time() - self.start_time
        if not self._injected and elapsed >= self.inject_after:
            if self.inject_temp is not None:
                self.temperature = self.inject_temp
                print(f"[SensorECU] >>> INJECTING FAULT: temperature = {self.inject_temp}C")
            if self.inject_voltage is not None:
                self.voltage = self.inject_voltage
                print(f"[SensorECU] >>> INJECTING FAULT: voltage = {self.inject_voltage}V")
            if self.inject_current is not None:
                self.current = self.inject_current
                print(f"[SensorECU] >>> INJECTING FAULT: current = {self.inject_current}A")
            self._injected = True
        elif not (self._injected and (self.inject_temp is not None or
                                       self.inject_voltage is not None or
                                       self.inject_current is not None)):
            self.voltage = max(3.0, min(4.2, self.voltage + random.uniform(-0.01, 0.01)))
            self.temperature = max(15, min(45, self.temperature + random.uniform(-0.3, 0.3)))
            self.current = max(-50, min(50, self.current + random.uniform(-2, 2)))

    def _send(self, arb_id, data):
        msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
        self.bus.send(msg)

    def _check_and_report_faults(self):
        flags = 0
        vlo, vhi = C.VOLTAGE_RANGE_V
        tlo, thi = C.TEMP_RANGE_C
        clo, chi = C.CURRENT_RANGE_A

        if self.voltage > vhi:
            flags |= C.FAULT_OVER_VOLTAGE
        elif self.voltage < vlo:
            flags |= C.FAULT_UNDER_VOLTAGE
        if self.temperature > thi or self.temperature < tlo:
            flags |= C.FAULT_OVER_TEMP
        if self.current > chi or self.current < clo:
            flags |= C.FAULT_OVER_CURRENT

        if flags:
            self._send(C.ID_SENSOR_FAULT, C.encode_fault_flags(flags))
            names = C.fault_flags_to_names(flags)
            print(f"[SensorECU] FAULT DETECTED: {names} -> sent 0x1F0")
        return flags

    def _voltage_loop(self):
        while not self._stop:
            self._send(C.ID_CELL_VOLTAGE, C.encode_cell_voltage(self.voltage))
            time.sleep(C.PERIODIC_PERIOD_S[C.ID_CELL_VOLTAGE])

    def _temp_loop(self):
        while not self._stop:
            self._send(C.ID_CELL_TEMPERATURE, C.encode_cell_temperature(self.temperature))
            time.sleep(C.PERIODIC_PERIOD_S[C.ID_CELL_TEMPERATURE])

    def _current_loop(self):
        while not self._stop:
            self._send(C.ID_PACK_CURRENT, C.encode_pack_current(self.current))
            time.sleep(C.PERIODIC_PERIOD_S[C.ID_PACK_CURRENT])

    def _update_and_check_loop(self):
        while not self._stop:
            self._update_readings()
            self._check_and_report_faults()
            time.sleep(0.1)

    def run(self):
        print("[SensorECU] Starting. Sending Voltage(100ms)/Temp(200ms)/Current(100ms).")
        threads = [
            threading.Thread(target=self._voltage_loop, daemon=True),
            threading.Thread(target=self._temp_loop, daemon=True),
            threading.Thread(target=self._current_loop, daemon=True),
            threading.Thread(target=self._update_and_check_loop, daemon=True),
        ]
        for t in threads:
            t.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[SensorECU] Shutting down.")
            self._stop = True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default='vcan0')
    parser.add_argument('--inject-temp', type=float, default=None,
                         help='Inject an out-of-range temperature value (e.g. 200)')
    parser.add_argument('--inject-voltage', type=float, default=None,
                         help='Inject an out-of-range voltage value (e.g. 5.0)')
    parser.add_argument('--inject-current', type=float, default=None,
                         help='Inject an out-of-range current value (e.g. 900)')
    parser.add_argument('--inject-after', type=float, default=8.0,
                         help='Seconds to wait before injecting the fault (default 8s)')
    args = parser.parse_args()

    ecu = SensorECU(channel=args.channel, inject_temp=args.inject_temp,
                     inject_voltage=args.inject_voltage,
                     inject_current=args.inject_current,
                     inject_after=args.inject_after)
    ecu.run()
