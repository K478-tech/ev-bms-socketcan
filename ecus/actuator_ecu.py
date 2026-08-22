"""
actuator_ecu.py

Simulates the physical actuators:
- Main contactor (relay) -- receives 0x110
- Cooling fan            -- receives 0x111

Just logs the "physical" state changes to console + a log file, standing in
for real GPIO/relay driving hardware.
"""

import time
import can

import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from common import can_ids as C

LOG_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'actuator.log')


def log(line):
    ts = C.now_ts()
    full = f"[{ts}] {line}"
    print(full)
    with open(LOG_PATH, 'a') as f:
        f.write(full + '\n')


class ActuatorECU(can.Listener):
    def __init__(self, channel='vcan0'):
        self.bus = can.interface.Bus(channel=channel, interface='socketcan')
        self.contactor_state = C.CONTACTOR_CLOSED
        self.fan_duty = 0
        self.notifier = can.Notifier(self.bus, [self])

    def on_message_received(self, msg: can.Message):
        if msg.arbitration_id == C.ID_CONTACTOR_CMD:
            state = C.decode_contactor_cmd(msg.data)
            self.contactor_state = state
            log(f"[ActuatorECU] Contactor RELAY -> {'CLOSED (power connected)' if state else 'OPEN (power disconnected)'}")
        elif msg.arbitration_id == C.ID_FAN_CMD:
            duty = C.decode_fan_cmd(msg.data)
            self.fan_duty = duty
            log(f"[ActuatorECU] Cooling Fan PWM -> {duty}%")

    def run(self):
        print("[ActuatorECU] Starting. Waiting for contactor/fan commands...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[ActuatorECU] Shutting down.")
            self.notifier.stop()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', default='vcan0')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    ActuatorECU(channel=args.channel).run()
