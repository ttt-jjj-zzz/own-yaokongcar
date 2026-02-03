import os
from pwm import PWM

MOTOR_A_PWM_CHIP = 2
MOTOR_A_PWM_ID = 0
MOTOR_B_PWM_CHIP = 0
MOTOR_B_PWM_ID = 0

class Motor:
    def __init__(self, pwm_chip, pwm_id, pin_in1, pin_in2):
        self.pwm = PWM(pwm_chip, pwm_id, period_ns=1000000) # 1kHz for motor
        self.pin_in1 = pin_in1
        self.pin_in2 = pin_in2
        self._setup_gpio(pin_in1)
        self._setup_gpio(pin_in2)

    def _setup_gpio(self, pin):
        base = "/sys/class/gpio"
        path = f"{base}/gpio{pin}"
        if not os.path.exists(path):
            with open(f"{base}/export", 'w') as f:
                f.write(str(pin))
        with open(f"{path}/direction", 'w') as f:
            f.write("out")

    def _write_gpio(self, pin, value):
        with open(f"/sys/class/gpio/gpio{pin}/value", 'w') as f:
            f.write(str(value))

    def set_speed(self, speed):
        # speed: -1.0 to 1.0
        speed = max(-1.0, min(speed, 1.0))
        
        duty = int(abs(speed) * 1000000) # Map to 0-100% of 1ms period
        self.pwm.set_duty_cycle(duty)

        if speed > 0:
            self._write_gpio(self.pin_in1, 1)
            self._write_gpio(self.pin_in2, 0)
        elif speed < 0:
            self._write_gpio(self.pin_in1, 0)
            self._write_gpio(self.pin_in2, 1)
        else:
            self._write_gpio(self.pin_in1, 0)
            self._write_gpio(self.pin_in2, 0)

    def stop(self):
        self.set_speed(0)
        self.pwm.disable()
