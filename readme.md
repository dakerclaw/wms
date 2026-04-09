# WMS 物料出入库管理系统

> 仓库地址：`https://github.com/dakerclaw/wms`

## 一、服务器环境准备

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装 Python 和 pip
sudo apt install -y python3 python3-pip python3-venv git

# 安装 Nginx（反向代理）
sudo apt install -y nginx

# 安装 supervisor（进程守护）
sudo apt install -y supervisor
```

## 二、克隆项目

```bash
# 克隆到 /opt/wms
cd /opt
sudo git clone https://github.com/dakerclaw/wms.git
cd /opt/wms
```

## 三、配置 Python 环境

```bash
cd /opt/wms

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖（含 gunicorn 生产服务器）
pip install -r requirements.txt
pip install gunicorn
```

> 用 `gunicorn` 替代 Flask 自带的开发服务器，性能更好且支持多进程。

## 四、测试运行

```bash
cd /opt/wms
source venv/bin/activate
python3 app.py
```

看到 `Running on http://0.0.0.0:5000` 说明正常。用 `Ctrl+C` 停止。

## 五、配置 Gunicorn

```bash
cat > /opt/wms/gunicorn.conf.py << 'EOF'
bind = "0.0.0.0:5000"
workers = 2
threads = 4
timeout = 120
accesslog = "/opt/wms/logs/access.log"
errorlog = "/opt/wms/logs/error.log"
loglevel = "info"
EOF

# 创建日志目录
mkdir -p /opt/wms/logs
```

## 六、配置 Supervisor（开机自启 + 崩溃重启）

```bash
sudo cat > /etc/supervisor/conf.d/wms.conf << 'EOF'
[program:wms]
directory=/opt/wms
command=/opt/wms/venv/bin/gunicorn -c gunicorn.conf.py app:app
autostart=true
autorestart=true
user=root
redirect_stderr=true
stdout_logfile=/opt/wms/logs/supervisor.log
EOF

# 重新加载 supervisor 配置
sudo supervisorctl reread
sudo supervisorctl update

# 查看状态（应显示 RUNNING）
sudo supervisorctl status wms
```

**常用 supervisor 命令：**

```bash
sudo supervisorctl start wms    # 启动
sudo supervisorctl stop wms     # 停止
sudo supervisorctl restart wms  # 重启
sudo supervisorctl tail -f wms  # 查看实时日志
```

## 七、防火墙设置

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 5000/tcp
sudo ufw --force enable
```

## 八、验证访问

浏览器打开 `http://服务器IP:5000`，应该能看到 WMS 登录页面。

默认管理员账号：**shangtai** / **st999777**

## 九、日常运维

| 操作 | 命令 |
|------|------|
| 重启 WMS | `sudo supervisorctl restart wms` |
| 查看实时日志 | `sudo supervisorctl tail -f wms` |
| 查看错误日志 | `tail -f /opt/wms/logs/error.log` |
| 更新代码 | `cd /opt/wms && git pull && sudo supervisorctl restart wms` |
| 备份数据库 | `cp /opt/wms/wms.db /opt/wms/backup/wms_$(date +%Y%m%d).db` |

## 十、自动备份数据库（可选）

```bash
# 创建备份目录
mkdir -p /opt/wms/backup

# 添加定时任务（每天凌晨3点备份，保留30天）
sudo crontab -e
# 添加以下行：
0 3 * * * cp /opt/wms/wms.db /opt/wms/backup/wms_$(date +\%Y\%m\%d).db && find /opt/wms/backup -name "wms_*.db" -mtime +30 -delete
```

## 十一、安全建议

1. **修改 secret_key**：编辑 `app.py`，把 `wms_secret_key_2026` 改为随机字符串
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. **修改默认密码**：首次登录后立即修改管理员密码
3. **定期更新**：`sudo apt update && sudo apt upgrade -y`

## 十二、Nginx 反向代理（可选）

如果需要域名、HTTPS 或 80 端口访问，可配置 Nginx 反向代理：

```bash
# 安装 Nginx
sudo apt install -y nginx
```

### 仅 HTTP

```bash
sudo cat > /etc/nginx/sites-available/wms << 'EOF'
server {
    listen 80;
    server_name 你的域名或IP;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/wms /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl enable nginx
```

> 配置 Nginx 后，需将 `gunicorn.conf.py` 的 bind 改回 `127.0.0.1:5000` 并放行 80 端口。

### HTTPS（需要域名）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

### 内网 IP 限制（可选）

```nginx
location / {
    allow 192.168.1.0/24;  # 改为你的内网段
    deny all;
    proxy_pass http://127.0.0.1:5000;
    ...
}
```

## 文件结构总览

```
/opt/wms/
├── app.py              # Flask 主程序
├── requirements.txt    # Python 依赖
├── gunicorn.conf.py    # Gunicorn 配置（部署时生成）
├── wms.db              # SQLite 数据库（自动生成）
├── venv/               # Python 虚拟环境（部署时生成）
├── logs/               # 日志目录（部署时生成）
├── backup/             # 数据库备份目录
├── static/
│   ├── css/style.css
│   └── js/app.js
└── templates/
    └── index.html
```
