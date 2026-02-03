import os
import time

class PWM:
    def __init__(self, chip, pwm_id, period_ns=20000000):
        self.chip = chip
        self.pwm_id = pwm_id
        self.base_path = f"/sys/class/pwm/pwmchip{chip}"
        self.pwm_path = f"{self.base_path}/pwm{pwm_id}"
        self.period_ns = period_ns
        
        if not os.path.exists(self.base_path):
            raise RuntimeError(f"PWM chip {chip} not found")
            
        self.export()
        
        # 检查当前 period，如果是 0 (重启后默认状态)，必须先设置 period 才能进行其他操作
        try:
            with open(f"{self.pwm_path}/period", 'r') as f:
                current_period = int(f.read().strip())
        except (IOError, ValueError):
            current_period = 0

        if current_period == 0:
            # 初始状态：先设置周期，再清零占空比
            self.set_period(period_ns)
            self.set_duty_cycle(0)
        else:
            # 非初始状态：先清零占空比，避免 duty > new_period 错误
            self.set_duty_cycle(0)
            self.set_period(period_ns)
        
        # 现在状态合法了，可以安全地 disable 并设置极性
        self.disable()
        self.set_polarity("normal") 
        self.enable()

    def export(self):
        if not os.path.exists(self.pwm_path):
            try:
                with open(f"{self.base_path}/export", 'w') as f:
                    f.write(str(self.pwm_id))
                time.sleep(0.1)
            except IOError:
                pass # 可能已经导出

    def unexport(self):
        try:
            with open(f"{self.base_path}/unexport", 'w') as f:
                f.write(str(self.pwm_id))
        except IOError:
            pass

    def set_period(self, ns):
        with open(f"{self.pwm_path}/period", 'w') as f:
            f.write(str(ns))

    def set_duty_cycle(self, ns):
        # 确保占空比不超过周期
        ns = min(ns, self.period_ns)
        with open(f"{self.pwm_path}/duty_cycle", 'w') as f:
            f.write(str(ns))

    def set_polarity(self, polarity):
        # 只有在 disable 状态下才能修改极性
        self.disable()
        try:
            with open(f"{self.pwm_path}/polarity", 'w') as f:
                f.write(polarity)
        except IOError:
            pass
        self.enable()

    def enable(self):
        with open(f"{self.pwm_path}/enable", 'w') as f:
            f.write("1")

    def disable(self):
        with open(f"{self.pwm_path}/enable", 'w') as f:
            f.write("0")
