#!/bin/bash

# 获取当前脚本所在目录的绝对路径
WORK_DIR=$(cd "$(dirname "$0")"; pwd)
SERVICE_NAME="faster_car.service"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

echo "=== 配置开机自启动服务 ==="
echo "工作目录: $WORK_DIR"
echo "服务文件: $SERVICE_PATH"

# 创建 systemd 服务文件
# 使用 sudo tee 写入文件
sudo tee $SERVICE_PATH > /dev/null <<EOF
[Unit]
Description=Faster Car Baby Control Service
# 只要网络协议栈准备好即可，不需要等待联网
After=network.target

[Service]
Type=simple
# 使用 root 权限运行，确保能访问 GPIO 和串口
User=root
WorkingDirectory=$WORK_DIR
# -u 参数表示不缓存输出，方便查看日志
ExecStart=/usr/bin/python3 -u $WORK_DIR/main.py
# 如果程序意外退出，总是尝试重启
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "正在重新加载 systemd daemon..."
sudo systemctl daemon-reload

echo "正在启用服务 (开机自启)..."
sudo systemctl enable $SERVICE_NAME

echo "正在启动服务..."
sudo systemctl restart $SERVICE_NAME

echo "=== 完成！ ==="
echo "现在你可以随时关闭 SSH，小车程序会在后台运行。"
echo "如果在没有 WiFi 的地方，只需要给小车上电，程序会自动启动。"
echo "查看日志命令: sudo journalctl -u $SERVICE_NAME -f"
echo "停止服务命令: sudo systemctl stop $SERVICE_NAME"
