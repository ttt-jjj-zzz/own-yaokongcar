import json
import os
from pwm import PWM

# PWM 配置
SERVO_PWM_CHIP = 4  # 转向舵机 (原 Chip 3 -> 现 Chip 4)
SERVO_PWM_ID = 0

CAMERA_SERVO_CHIP = 1 # 摄像头舵机 (新增，位于 Chip 1)
CAMERA_SERVO_ID = 0

# 转向舵机默认值 (如果配置文件不存在)
DEFAULT_STEERING_MID = 1471
DEFAULT_STEERING_RANGE = 150 # 单边幅度

# 摄像头舵机校准范围 (假设是 180度舵机 SG90/MG90S)
# 通常脉宽范围 500-2500us 对应 0-180度
# 这里保守设置 1000-2000，按需调整
CAM_MIN_US = 800
CAM_MAX_US = 2200
CAM_MID_US = 1500

CONFIG_FILE = "servo_config.json"

class Servo:
    def __init__(self, chip=SERVO_PWM_CHIP, channel=SERVO_PWM_ID, 
                 min_us=None, max_us=None, mid_us=None, is_steering=False):
        self.pwm = PWM(chip, channel)
        self.is_steering = is_steering
        
        # 如果是转向舵机，尝试从文件加载配置
        if self.is_steering:
            self.load_config()
        else:
            # 普通舵机直接使用传入参数
            self.min_us = min_us
            self.max_us = max_us
            self.mid_us = mid_us
            
        self.set_us(self.mid_us)

    def load_config(self):
        """从 JSON 加载校准值"""
        cfg_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
        try:
            with open(cfg_path, 'r') as f:
                data = json.load(f)
                self.mid_us = data.get("steering_mid", DEFAULT_STEERING_MID)
                self.min_us = data.get("steering_min", self.mid_us - DEFAULT_STEERING_RANGE)
                self.max_us = data.get("steering_max", self.mid_us + DEFAULT_STEERING_RANGE)
                print(f"Loaded steering config: Mid={self.mid_us}, Range=[{self.min_us}, {self.max_us}]")
        except FileNotFoundError:
            print("Config file not found, using defaults.")
            self.mid_us = DEFAULT_STEERING_MID
            self.min_us = self.mid_us - DEFAULT_STEERING_RANGE
            self.max_us = self.mid_us + DEFAULT_STEERING_RANGE

    def save_calibration(self, new_mid):
        """保存新的中位值，并更新范围"""
        # 你的逻辑：向左向右幅度固定为 150
        range_val = DEFAULT_STEERING_RANGE 
        
        self.mid_us = int(new_mid)
        self.min_us = self.mid_us - range_val
        self.max_us = self.mid_us + range_val
        
        data = {
            "steering_mid": self.mid_us,
            "steering_min": self.min_us,
            "steering_max": self.max_us
        }
        
        cfg_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
        try:
            with open(cfg_path, 'w') as f:
                json.dump(data, f, indent=4)
            print(f"Saved new steering calibration: Mid={self.mid_us}")
        except Exception as e:
            print(f"Failed to save config: {e}")

    def set_us(self, us):
        us = max(self.min_us, min(us, self.max_us))
        self.pwm.set_duty_cycle(us * 1000)

    def set_angle(self, angle):
        """
        angle: -1.0 到 1.0
        """
        # Map -1.0 (Left/Down) to 1.0 (Right/Up)
        angle = max(-1.0, min(angle, 1.0))
        
        # 默认假设 -1.0 对应 Max_US (像车轮那样反向)
        # 如果摄像头方向反了，可以修改这里的计算逻辑
        # 简单线性插值：Mid + angle * (Range/2)
        # 注意：这里仅仅是示例，具体方向需实测
        # 假设 -1 -> Min, 1 -> Max (正向)
        
        # 让我们把原本 Servo 类的反向逻辑保留给车轮
        # 但为了通用性，最好有个 reversed 参数。
        # 这里为了兼容旧代码，保持旧逻辑：
        # 旧逻辑：us = mid + (angle * -1) * (max - mid)
        # 即 -1.0 输入 -> 1 * delta -> 加到 Mid -> 变大 -> Max_US (左?)
        
        us = self.mid_us + (angle * -1) * (self.max_us - self.mid_us)
        self.set_us(int(us))

    def stop(self):
        self.pwm.disable()

