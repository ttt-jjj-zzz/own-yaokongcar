import time
import sys
import signal

# 检查依赖
try:
    import serial
except ImportError:
    print("Error: PySerial module not found. Please install it using: sudo pip3 install pyserial")
    sys.exit(1)

from servo import Servo, CAMERA_SERVO_CHIP, CAMERA_SERVO_ID, CAM_MIN_US, CAM_MAX_US, CAM_MID_US
from motor import Motor, MOTOR_A_PWM_CHIP, MOTOR_A_PWM_ID, MOTOR_B_PWM_CHIP, MOTOR_B_PWM_ID
from sbus_receiver import SBUSReceiver
from camera_stream import CameraStream # 引入摄像头模块

# GPIO 配置
PIN_IN1 = 19
PIN_IN2 = 21
PIN_IN3 = 129
PIN_IN4 = 98

# SBUS 配置
# 请确保已在 /boot/uEnv/uEnv.txt 中开启了:
# dtoverlay=/dtb/overlay/rk3576-lubancat-uart3-m0-overlay.dtbo
# 对应的物理引脚是: Pin 3 (RX) 和 Pin 5 (TX)
# 注意：千万不要选 m1，因为 m1 对应的 Pin 36 已经被你的左后轮电机占了！
SBUS_PORT = "/dev/ttyS3" 
SBUS_BAUD = 100000

# 通道映射 (参考旧 STM32 代码 MC7RB.c)
# 你的旧代码逻辑：
# chbuf[1] -> 控制电机前进后退 (当时是坦克逻辑，这里保留为油门)
# chbuf[0] -> 当时是差速，这里映射为转向 (阿克曼转向)
# chbuf[2] -> 辅助舵机 (忽略或用于其他功能)

CH_STEERING = 3  # CH3: 转向
CH_THROTTLE = 1  # CH1: 油门
CH_CAMERA   = 9  # CH9: 摄像头

# 校准功能通道
CH_CALIB_SWITCH = 6 # CH6 or CH7: 开关通道，拉高 (>1500) 进入校准模式
CH_CALIB_KNOB   = 8 # CH8: 旋钮，用于调节中位

# 阈值设置 (参考旧代码 main.c)
# 中心点 ~992, 死区 ±100 (892 - 1092)
# LubanCat 上读取解析可能略有偏差，建议实测微调
SBUS_MID = 992
SBUS_DEADBAND = 100
SBUS_MIN = 200   # 估算值
SBUS_MAX = 1800  # 估算值

def map_sbus_to_pwm(value):
    """
    将 SBUS 值映射到 -1.0 到 1.0 (用于 set_speed 或 set_angle)
    """
    # 你的旧代码逻辑：
    # if val > 1092: 正转
    # if val < 892: 反转
    # else: 停止
    
    if abs(value - SBUS_MID) < SBUS_DEADBAND:
        return 0.0
    
    # 将 200~1800 映射到 -1.0~1.0
    # 为了手感更好，这里用了简单的线性变换
    # Norm = (Val - Mid) / (Max - Mid)
    # 假设 Max=1800, Mid=992 -> Range ~800
    norm = (value - SBUS_MID) / 800.0
    return max(-1.0, min(norm, 1.0))

def main():
    print("Initializing Car Control System...")
    
    # 初始化硬件
    # 你的车结构：前舵机 + 后双电机
    try:
        # 转向舵机 (启用 is_steering=True 以支持读写配置)
        servo = Servo(is_steering=True) 
        
        # 摄像头舵机 (使用 Chip 1 - PWM1_CH1 Pin 19)
        cam_servo = Servo(chip=CAMERA_SERVO_CHIP, channel=CAMERA_SERVO_ID,
                          min_us=CAM_MIN_US, max_us=CAM_MAX_US, mid_us=CAM_MID_US)
                          
        # 注意：右轮电机(Motor A)需要 IN2>IN1 才能正转
        motor_a = Motor(MOTOR_A_PWM_CHIP, MOTOR_A_PWM_ID, PIN_IN2, PIN_IN1)
        motor_b = Motor(MOTOR_B_PWM_CHIP, MOTOR_B_PWM_ID, PIN_IN3, PIN_IN4)
    except Exception as e:
        print(f"Hardware initialization failed: {e}")
        # 如果电机初始化失败，可能是PWM overlay没开，但这里先不做硬性退出
        print("Continuing anyway (may crash if PWM missing)...")

    # 初始化 SBUS
    print(f"Connecting to SBUS on {SBUS_PORT}...")
    try:
        sbus = SBUSReceiver(SBUS_PORT, SBUS_BAUD)
    except:
        print(f"Error: Could not open {SBUS_PORT}. Did you enable the overlay in /boot/uEnv/uEnv.txt?")
        return

    # 初始化摄像头流
    camera = CameraStream(port=8080)
    try:
        camera.start()
    except Exception as e:
        print(f"Camera warning: {e}")

    # 控制主循环的标志
    running = True

    def stop_all():
        print("Stopping hardware...")
        try:
            servo.stop()
            cam_servo.stop()
            motor_a.stop()
            motor_b.stop()
            camera.stop() # 停止摄像头
        except:
            pass
        print("Car Stopped.")

    # 捕获 Ctrl+C
    def signal_handler(sig, frame):
        nonlocal running
        print("\nExit signal received. Stopping...")
        running = False
        # 不在这里直接 exit，而是让主循环自然结束
    
    signal.signal(signal.SIGINT, signal_handler)

    print("\n--- Remote Control Ready ---")
    print("Waiting for RC signal...")

    # 校准模式状态标记
    in_calibration_mode = False

    try:
        while running:
            # 读取遥控器数据
            sbus.update()

            if sbus.connected:
                # 获取公共数据 (无论什么模式，油门和摄像头都应该能动)
                throttle_raw = sbus.get_channel(CH_THROTTLE)
                camera_raw   = sbus.get_channel(CH_CAMERA)
                
                throttle_val = map_sbus_to_pwm(throttle_raw)
                camera_val   = map_sbus_to_pwm(camera_raw)

                # -----------------------
                # 1. 检查校准模式 (新增功能)
                # -----------------------
                calib_switch_val = sbus.get_channel(CH_CALIB_SWITCH)
                
                # 阈值判断：大于 1500 视为开启校准
                if calib_switch_val > 1500:
                    in_calibration_mode = True
                    
                    # 获取 CH8 旋钮值 (假设范围 200~1800)
                    knob_raw = sbus.get_channel(CH_CALIB_KNOB)
                    
                    # 映射中位 (精细调节模式)
                    # 将旋钮全程映射到 1350us ~ 1650us (±150us)
                    # 方向反转：(1800 - knob_raw) 
                    # 假设 knob_raw 范围 200~1800
                    # 1800 - 200 = 1600 (Max span)
                    
                    target_mid = int(1350 + (1800 - knob_raw) / 1600.0 * 300)
                    target_mid = max(1350, min(target_mid, 1650))
                    
                    # 实时驱动转向舵机回中 (此时不响应方向摇杆)
                    servo.set_us(target_mid)
                    
                    # print(f"CALIBRATING... Knob: {knob_raw} -> US: {target_mid}", end='\r')
                    
                else:
                    # 如果之前在校准模式，现在切回来了 -> 保存！
                    if in_calibration_mode:
                        print(f"\nExiting calibration. Saving new MID...")
                        # 读取最后一次的 CH8 值计算中位 (同样应用反转逻辑)
                        knob_raw = sbus.get_channel(CH_CALIB_KNOB)
                        final_mid = int(1350 + (1800 - knob_raw) / 1600.0 * 300)
                        final_mid = max(1350, min(final_mid, 1650))
                        
                        servo.save_calibration(final_mid)
                        in_calibration_mode = False
                        print(f"Saved! New Steering Mid: {final_mid}")

                    # -----------------------
                    # 2. 正常转向控制模式
                    # -----------------------
                    steering_raw = sbus.get_channel(CH_STEERING)
                    steering_val = map_sbus_to_pwm(steering_raw)
                    servo.set_angle(steering_val)


                # -----------------------
                # 3. 执行油门、摄像头控制 (全局生效)
                # -----------------------
                cam_servo.set_angle(camera_val)
                motor_a.set_speed(throttle_val)
                motor_b.set_speed(throttle_val)
                
            else:
                # 信号丢失保护
                motor_a.set_speed(0)
                motor_b.set_speed(0)
                servo.set_angle(0)
                cam_servo.set_angle(0)

            time.sleep(0.01) # 100Hz loop

    except Exception as e:
        print(f"\nRuntime Error: {e}")
    finally:
        stop_all()

if __name__ == "__main__":
    main()
