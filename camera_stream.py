import cv2
import threading
import time
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
try:
    from turbojpeg import TurboJPEG
    # 尝试初始化 TurboJPEG，失败则回退到 OpenCV
    jpeg = TurboJPEG()
    USE_TURBOJPEG = True
except:
    USE_TURBOJPEG = False

# 全局帧缓冲与同步条件变量
output_frame = None
frame_condition = threading.Condition()
frame_id = 0  # 帧计数器，用于丢帧检测

# ============ 极致低延迟模式配置 ============
# 清晰度：降低以换取更小的体积
FIXED_JPEG_QUALITY = 20      
# 帧率：提高帧率以减少输入延迟（30fps -> 33ms 间隔，而 10fps -> 100ms 间隔）
TARGET_FPS = 30              
FRAME_SKIP_THRESHOLD = 5     

# 简单的全屏 HTML 模板
# 将视频流作为背景全屏显示，padding:0, margin:0 
PAGE = """
<html>
<head>
<title>LubanCat FPV</title>
<style>
body { 
    margin: 0; 
    padding: 0; 
    background-color: #000; 
    display: flex; 
    justify-content: center; 
    align-items: center; 
    height: 100vh; 
    overflow: hidden;
}
img {
    height: 100%;
    width: auto;
    object-fit: contain;
}
</style>
</head>
<body>
<img src="/video_feed">
</body>
</html>
"""

class MJPEGStreamHandler(BaseHTTPRequestHandler):
    """处理 MJPEG 流的 HTTP 请求"""
    def log_message(self, format, *args):
        pass  # 禁用日志输出，减少CPU开销
    
    def do_GET(self):
        global output_frame, frame_id
        
        # 1. 如果访问根路径 /，返回 HTML 网页（大屏幕模式）
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(PAGE.encode('utf-8'))
            
        # 2. 如果访问 /video_feed，返回视频流
        elif self.path == '/video_feed':
            # 优化 Socket 发送缓冲区，防止网络卡顿时数据堆积产生延迟
            try:
                # 设置发送缓冲区为 16KB（更小以避免堆积）
                self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 16 * 1024)
                # 设置 TCP_NODELAY 减少延迟
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except:
                pass

            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            
            # 初始化为当前帧，确保连接建立后立刻开始传输（避免初始丢帧判断逻辑导致的跳过）
            last_sent_frame_id = frame_id - 1
            last_send_time = 0
            min_frame_interval = 1.0 / TARGET_FPS  # 限制帧率
            
            try:
                while True:
                    with frame_condition:
                        # 等待新帧，但设置超时避免死锁
                        frame_condition.wait(timeout=0.5)
                        if output_frame is None:
                            continue
                        
                        current_frame_id = frame_id
                        frame = output_frame
                    
                    # 如果没有新帧（超时唤醒），跳过
                    if current_frame_id <= last_sent_frame_id:
                        continue

                    # 丢帧检测：如果落后太多帧，只需要更新状态，不需要丢弃当前的最新帧
                    # 原来的逻辑是 continue，会导致当前已经获取到的好帧也被丢弃，可能导致“卡死”
                    # if current_frame_id - last_sent_frame_id > FRAME_SKIP_THRESHOLD:
                    #     pass 
                    
                    # 帧率限制
                    now = time.perf_counter()
                    if now - last_send_time < min_frame_interval:
                        continue
                    
                    # 3. 压缩 JPEG（使用 PyTurboJPEG 如果可用，速度快3倍）
                    if USE_TURBOJPEG:
                        # pixel_format=TJPF_BGR 是默认的 OpenCV 格式
                        encodedImage = jpeg.encode(frame, quality=FIXED_JPEG_QUALITY)
                    else:
                        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), FIXED_JPEG_QUALITY]
                        (flag, encodedImage) = cv2.imencode(".jpg", frame, encode_param)
                        if not flag:
                            continue
                    
                    try:
                        self.wfile.write(b'--frame\r\n')
                        self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                        if USE_TURBOJPEG:
                            self.wfile.write(encodedImage)
                        else:
                            self.wfile.write(bytearray(encodedImage))
                        self.wfile.write(b'\r\n')
                        self.wfile.flush()
                        
                        last_sent_frame_id = current_frame_id
                        last_send_time = now
                    except (BrokenPipeError, ConnectionResetError):
                        break  # 客户端断开，退出循环
                    
            except Exception:
                pass
        else:
            self.send_error(404)

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器"""
    pass

class CameraStream:
    # 极致性能模式配置：分辨率降至 320x240
    def __init__(self, port=8080, device='/dev/video0', width=320, height=240):
        self.port = port
        self.device = device
        self.width = width
        self.height = height
        self.running = False
        self.thread = None
        self.server = None
        self.cap = None

    def start(self):
        """启动摄像头采集和 HTTP 服务器"""
        global frame_id
        if self.running:
            return

        print(f"Opening Camera {self.device} ({self.width}x{self.height}) [Low Bandwidth Mode]...")
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)

        if not self.cap.isOpened():
            print(f"Warning: Could not open {self.device}. Trying /dev/video1...")
            self.device = '/dev/video1'
            self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
            if not self.cap.isOpened():
                print(f"Error: Could not open camera {self.device} either. Please unplug/replug camera.")
                # 这里我们即便摄像头失败，也返回，不启动 Server，否则用户会以为是网络问题
                return

        # 关键优化：设置缓冲区大小为1，只保留最新的一帧，丢弃陈旧帧，大幅降低延迟
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # 设置 MJPG 格式和分辨率
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        
        real_w = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        real_h = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"Camera opened: {real_w}x{real_h}")

        self.running = True
        
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

        try:
            self.server = ThreadedHTTPServer(('0.0.0.0', self.port), MJPEGStreamHandler)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            print(f"Camera Stream started at http://<IP>:{self.port}/ (Full Screen)")
        except OSError as e:
            print(f"Error starting HTTP server: {e}")

    def _capture_loop(self):
        global output_frame, frame_id
        frame_interval = 1.0 / TARGET_FPS
        last_capture_time = 0
        
        while self.running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                now = time.perf_counter()
                # 限制采集帧率
                if now - last_capture_time >= frame_interval:
                    with frame_condition:
                        output_frame = frame
                        frame_id += 1
                        frame_condition.notify_all()
                    last_capture_time = now
            else:
                time.sleep(0.01)
        
    def stop(self):
        """停止采集和服务"""
        self.running = False
        
        # 1. 优先释放摄像头资源
        if self.cap:
            try:
                self.cap.release()
            except:
                pass

        # 2. 尝试关闭 HTTP 服务器
        if self.server:
            try:
                # 仅关闭 socket，不调用 shutdown() 以避免死锁等待
                # 因为 server 线程是 daemon，主程序退出时会自动销毁
                self.server.server_close()
            except:
                pass
        
        # 3. 唤醒可能卡在 wait() 的线程以便它们能响应退出
        try:
            with frame_condition:
                frame_condition.notify_all()
        except:
            pass
