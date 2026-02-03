import serial
import time
import struct

class SBUSReceiver:
    def __init__(self, serial_port='/dev/ttyS3', baudrate=100000):
        try:
            self.ser = serial.Serial(
                port=serial_port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_TWO,
                timeout=0.02 # 1 frame is ~3ms, spacing 7ms
            )
            print(f"SBUS connected on {serial_port}")
        except Exception as e:
            print(f"Error opening serial port {serial_port}: {e}")
            self.ser = None

        self.channels = [1024] * 16 # Center
        self.last_frame_time = 0
        self.connected = False

    def update(self):
        if not self.ser:
            return

        # 尝试读取尽可能多的数据，直到找到有效帧
        # SBUS 帧长 25 字节
        # 0x0F <22 bytes data> <flags> 0x00
        
        while self.ser.in_waiting >= 25:
            # 读取可能的帧头
            header = self.ser.read(1)
            if header == b'\x0f':
                # 读取剩余24字节
                packet = self.ser.read(24)
                if len(packet) == 24 and packet[23] == 0x00:
                    self._parse_frame(packet)
                    self.last_frame_time = time.time()
                    self.connected = True
            else:
                # 不是帧头，跳过继续找
                pass
                
        # 超时检测 (SBUS通常每14ms-7ms发一次)
        if time.time() - self.last_frame_time > 0.5:
            self.connected = False

    def _parse_frame(self, data):
        # Bit manipulation for 11-bit channels
        # data[0-21] contains 16 channels
        
        channels = [0] * 16
        
        # Python handles bytes as ints automatically when indexing
        channels[0]  = ((data[0]    | data[1]<<8)                          & 0x07FF)
        channels[1]  = ((data[1]>>3 | data[2]<<5)                          & 0x07FF)
        channels[2]  = ((data[2]>>6 | data[3]<<2 | data[4]<<10)           & 0x07FF)
        channels[3]  = ((data[4]>>1 | data[5]<<7)                          & 0x07FF)
        channels[4]  = ((data[5]>>4 | data[6]<<4)                          & 0x07FF)
        channels[5]  = ((data[6]>>7 | data[7]<<1 | data[8]<<9)            & 0x07FF)
        channels[6]  = ((data[8]>>2 | data[9]<<6)                          & 0x07FF)
        channels[7]  = ((data[9]>>5 | data[10]<<3)                         & 0x07FF)
        channels[8]  = ((data[11]   | data[12]<<8)                         & 0x07FF)
        channels[9]  = ((data[12]>>3| data[13]<<5)                         & 0x07FF)
        channels[10] = ((data[13]>>6| data[14]<<2 | data[15]<<10)         & 0x07FF)
        channels[11] = ((data[15]>>1| data[16]<<7)                        & 0x07FF)
        channels[12] = ((data[16]>>4| data[17]<<4)                        & 0x07FF)
        channels[13] = ((data[17]>>7| data[18]<<1 | data[19]<<9)          & 0x07FF)
        channels[14] = ((data[19]>>2| data[20]<<6)                        & 0x07FF)
        channels[15] = ((data[20]>>5| data[21]<<3)                        & 0x07FF)

        self.channels = channels

    def get_channel(self, index):
        if 0 <= index < 16:
            return self.channels[index]
        return 1024

    def get_channel_normalized(self, index):
        # SBUS range usually ~200 to ~1800
        # Futaba/FrSky ~172 to 1811
        # Center ~992
        val = self.get_channel(index)
        
        # Map 172..1811 to -1.0..1.0
        min_val = 172
        max_val = 1811
        
        norm = (val - min_val) / (max_val - min_val) * 2.0 - 1.0
        
        # Deadband
        if abs(norm) < 0.05:
            norm = 0.0
            
        return max(-1.0, min(norm, 1.0))
