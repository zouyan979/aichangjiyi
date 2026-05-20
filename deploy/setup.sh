#!/bin/bash
# Memoria 宝塔一键部署脚本
# 使用方法：进入项目目录，运行 bash deploy/setup.sh

set -e

# 自动检测项目目录（脚本所在目录的上一级）
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="www"

echo "=========================================="
echo "  Memoria 宝塔部署脚本"
echo "=========================================="
echo ""

# 检查目录
if [ ! -d "$APP_DIR" ]; then
    echo "[错误] 项目目录不存在: $APP_DIR"
    echo "请先将项目上传到 $APP_DIR"
    exit 1
fi

cd "$APP_DIR"

# 1. 创建虚拟环境
echo "[1/5] 创建 Python 虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 2. 安装依赖
echo "[2/5] 安装依赖..."
pip install -r backend/requirements.txt gunicorn --quiet

# 3. 创建数据目录
echo "[3/5] 初始化数据目录..."
mkdir -p backend/data
chown -R $APP_USER:$APP_USER backend/data

# 4. 安装 systemd 服务
echo "[4/5] 安装系统服务..."
cp deploy/memoria.service /etc/systemd/system/
# 修正 WorkingDirectory
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$APP_DIR|" /etc/systemd/system/memoria.service
# 修正 ExecStart
sed -i "s|ExecStart=.*|ExecStart=$APP_DIR/venv/bin/gunicorn -c deploy/gunicorn.conf.py backend.main:app|" /etc/systemd/system/memoria.service
systemctl daemon-reload
systemctl enable memoria
systemctl start memoria

# 5. 完成
echo "[5/5] 部署完成！"
echo ""
echo "服务状态:"
systemctl status memoria --no-pager -l
echo ""
echo "=========================================="
echo "  后续步骤:"
echo "  1. 宝塔面板 → 网站 → 添加站点"
echo "  2. 域名填你的域名，根目录选 $APP_DIR"
echo "  3. 网站设置 → 配置文件，参考 deploy/nginx.conf"
echo "  4. 或直接用 IP:8765 访问（不推荐生产环境）"
echo ""
echo "  常用命令:"
echo "  systemctl start memoria    # 启动"
echo "  systemctl stop memoria     # 停止"
echo "  systemctl restart memoria  # 重启"
echo "  systemctl status memoria   # 查看状态"
echo "  journalctl -u memoria -f   # 查看日志"
echo "=========================================="
