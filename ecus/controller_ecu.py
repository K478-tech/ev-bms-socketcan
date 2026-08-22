"""
controller_ecu.py

The core BMS logic:
- Receives Cell Voltage (0x100), Cell Temperature (0x101), Pack Current (0x102),
  and Sensor Fault (0x1F0).
- Computes SOC via simple coulomb counting from a starting point.
- Decides operating Mode (IDLE / CHARGE / DISCHARGE / FAULT).
- Commands the Actuator ECU: Contactor (0x110, event) and Fan (0x111, event).
- Publishes BMS Status (0x120, periodic 500ms) for the Diagnostic ECU / HMI.

Safety logic: any sensor fault (0x1F0) -> Mode = FAULT -> contactor OPEN,
fan forced to 100% until fault clears.
"""

import threading
import time

import can

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from common import can_ids as C


class ControllerECU:
    def __init__(self, channel='vcan0'):
        self.bus = can.interface.Bus(channel=channel, interface='socketcan')

        self.voltage = None
        self.temperature = None
        self.current = None
        self.soc = 70.0          # starting SOC assumption
        self.mode = C.MODE_IDLE
        self.contactor_state = C.CONTACTOR_CLOSED
        self.fan_duty = 0

        self.fault_active = False
        self.last_fault_flags = 0

        self._stop = False
        self._lock = threading.Lock()
        self._last_soc_update = time.time()

        self.listener = _RxListener(self)
        self.notifier = can.Notifier(self.bus, [self.listener])

    def _send(self, arb_id, data):
        msg = can.Message(arbitration_id=arb_id, data=data, is_extended_id=False)
        self.bus.send(msg)

    # -------- called by the CAN listener whenever a message arrives -------
    def on_voltage(self, v):
        with self._lock:
            self.voltage = v

    def on_temperature(self, t):
        with self._lock:
            self.temperature = t

    def on_current(self, i):
        with self._lock:
            self.current = i
            self._update_soc(i)

    def on_sensor_fault(self, flags):
        with self._lock:
            self.fault_active = True
            self.last_fault_flags = flags

    def clear_fault(self):
        with self._lock:
            self.fault_active = False
            self.last_fault_flags = 0

    def _update_soc(self, current_a):
        now = time.time()
        dt_hours = (now - self._last_soc_update) / 3600.0
        self._last_soc_update = now
        # simplistic coulomb counting against an assumed 50Ah pack
        pack_ah = 50.0
        delta_pct = (current_a * dt_hours / pack_ah) * 100.0
        self.soc = max(0.0, min(100.0, self.soc + delta_pct))

    # -------------------------- decision loop ------------------------------
    def _decide_and_command(self):
        with self._lock:
            if self.fault_active:
                new_mode = C.MODE_FAULT
                new_contactor = C.CONTACTOR_OPEN
                new_fan = 100
            else:
                if self.current is None:
                    new_mode = C.MODE_IDLE
                elif self.current > 1:
                    new_mode = C.MODE_CHARGE
                elif self.current < -1:
                    new_mode = C.MODE_DISCHARGE
                else:
                    new_mode = C.MODE_IDLE
                new_contactor = C.CONTACTOR_CLOSED
                # simple thermal-driven fan curve
                if self.temperature is not None and self.temperature > 35:
                    new_fan = min(100, int((self.temperature - 25) * 5))
                else:
                    new_fan = 0

            mode_changed = new_mode != self.mode
            contactor_changed = new_contactor != self.contactor_state
            fan_changed = abs(new_fan - self.fan_duty) >= 5

            self.mode = new_mode
            self.contactor_state = new_contactor
            self.fan_duty = new_fan

        if contactor_changed:
            self._send(C.ID_CONTACTOR_CMD, C.encode_contactor_cmd(new_contactor))
            print(f"[Controller] Contactor -> {'CLOSED' if new_contactor else 'OPEN'} (0x110 sent)")
        if fan_changed:
            self._send(C.ID_FAN_CMD, C.encode_fan_cmd(new_fan))
            print(f"[Controller] Fan -> {new_fan}% (0x111 sent)")
        if mode_changed:
            print(f"[Controller] Mode -> {C.MODE_NAMES[new_mode]}")

    def _status_loop(self):
        while not self._stop:
            with self._lock:
                soc, mode = self.soc, self.mode
            self._send(C.ID_BMS_STATUS, C.encode_bms_status(soc, mode))
            time.sleep(C.PERIODIC_PERIOD_S[C.ID_BMS_STATUS])

    def _decision_loop(self):
        while not self._stop:
            self._decide_and_command()
            time.sleep(0.1)

    def run(self):
        print("[Controller] Starting BMS controller ECU.")
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._decision_loop, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Controller] Shutting down.")
            self._stop = True
            self.notifier.stop()


class _RxListener(can.Listener):
    def __init__(self, controller: ControllerECU):
        self.controller = controller

    def on_message_received(self, msg: can.Message):
        if msg.arbitration_id == C.ID_CELL_VOLTAGE:
            self.controller.on_voltage(C.decode_cell_voltage(msg.data))
        elif msg.arbitration_id == C.ID_CELL_TEMPERATURE:
            self.controller.on_temperature(C.decode_cell_temperature(msg.data))
        elif msg.arbitration_id == C.ID_PACK_CURRENT:
            self.controller.on_current(C.decode_pack_current(msg.data))
        elif msg.arbitration_id == C.ID_SENSOR_FAULT:
            flags = C.decode_fault_flags(msg.data)
            self.controller.on_sensor_fault(flags)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default='vcan0')
    args = parser.parse_args()
    ControllerECU(channel=args.channel).run()
