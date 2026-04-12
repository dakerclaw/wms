# WMS 物料管理系统

> 仓库地址：`https://github.com/dakerclaw/wms`

根据你的服务器登录方式，选择对应版本：

- 👤 **[普通用户部署（推荐）](#版本一普通用户部署推荐)**
- 🔴 **[Root 用户部署](#版本二root-用户部署)**

---

# 版本一：普通用户部署（推荐）

> 以下步骤以**普通用户**（如 `mac`）登录服务器执行，仅在需要系统级操作时使用 `sudo`。

## 一、全新安装

### 1. 安装系统依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx supervisor
```

### 2. 克隆项目

```bash
sudo git clone https://github.com/dakerclaw/wms.git /opt/wms
sudo chown -R $USER:$USER /opt/wms
cd /opt/wms
```

> `chown` 将项目目录归属当前用户，后续操作无需 `sudo`。

### 3. 配置 Python 环境

```bash
cd /opt/wms
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 4. 测试运行

```bash
cd /opt/wms
source venv/bin/activate
python3 app.py
```

看到 `Running on http://0.0.0.0:5000` 说明正常。`Ctrl+C` 停止。

### 5. 创建目录和配置

```bash
mkdir -p /opt/wms/logs /opt/wms/backup

cat > /opt/wms/gunicorn.conf.py <<'EOF'
workers = 2
bind = "0.0.0.0:5000"
EOF
```

### 6. 配置 Supervisor（进程守护）

```bash
sudo tee /etc/supervisor/conf.d/wms.conf > /dev/null <<EOF
[program:wms]
directory=/opt/wms
command=/opt/wms/venv/bin/gunicorn -c gunicorn.conf.py app:app
autostart=true
autorestart=true
user=$USER
redirect_stderr=true
stdout_logfile=/opt/wms/logs/supervisor.log
EOF

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status wms
```

应显示 `RUNNING`或 `STARTING`。

> **注意**：`<<EOF`（不加引号）才能让 shell 替换 `$USER`。如果替换失败，请直接将 `user=$USER` 改为你的用户名（如 `user=mac`）。

### 7. 防火墙放行

```bash
sudo ufw allow OpenSSH
sudo ufw allow 5000/tcp
sudo ufw --force enable
```

### 8. 验证访问

浏览器打开 `http://服务器IP:5000`

默认管理员账号：**admin** / **admin001**

## 二、更新升级

```bash
cd /opt/wms && git pull
sudo supervisorctl restart wms
```

如涉及 Python 依赖变更（`requirements.txt` 有改动）：

```bash
cd /opt/wms
source venv/bin/activate
pip install -r requirements.txt
sudo supervisorctl restart wms
```

## 三、卸载清理

### 1. 停止并移除服务

```bash
sudo supervisorctl stop wms
sudo rm -f /etc/supervisor/conf.d/wms.conf
sudo supervisorctl reread
sudo supervisorctl update
```

### 2. 移除 Nginx 配置（如已配置）

```bash
sudo rm -f /etc/nginx/sites-enabled/wms
sudo rm -f /etc/nginx/sites-available/wms
sudo nginx -t && sudo systemctl reload nginx
```

### 3. 删除项目

```bash
sudo rm -rf /opt/wms
```

### 4. 释放防火墙端口（可选）

```bash
sudo ufw delete allow 5000/tcp
```

### 5. 卸载系统依赖（可选）

```bash
sudo apt remove -y nginx supervisor
sudo apt autoremove -y
```

> ⚠️ Python3、git、pip 等基础工具不建议卸载。

## 四、日常运维

| 操作 | 命令 |
|------|------|
| 启动 / 停止 / 重启 | `sudo supervisorctl start\|stop\|restart wms` |
| 查看状态 | `sudo supervisorctl status wms` |
| 实时日志 | `sudo supervisorctl tail -f wms` |
| 错误日志 | `tail -f /opt/wms/logs/supervisor.log` |
| 数据库备份 | 系统内置备份功能，或 `cp /opt/wms/wms.db /opt/wms/backup/` |

---

# 版本二：Root 用户部署

> 以下步骤以 **root** 用户直接登录服务器执行，全程无需 `sudo`。

## 一、全新安装

### 1. 安装系统依赖

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx supervisor
```

### 2. 克隆项目

```bash
cd /opt
git clone https://github.com/dakerclaw/wms.git
cd /opt/wms
```

### 3. 配置 Python 环境

```bash
cd /opt/wms
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### 4. 测试运行

```bash
cd /opt/wms
source venv/bin/activate
python3 app.py
```

看到 `Running on http://0.0.0.0:5000` 说明正常。`Ctrl+C` 停止。

### 5. 创建目录和配置

```bash
mkdir -p /opt/wms/logs /opt/wms/backup

cat > /opt/wms/gunicorn.conf.py <<'EOF'
workers = 2
bind = "0.0.0.0:5000"
EOF
```

### 6. 配置 Supervisor（进程守护）

```bash
cat > /etc/supervisor/conf.d/wms.conf <<'EOF'
[program:wms]
directory=/opt/wms
command=/opt/wms/venv/bin/gunicorn -c gunicorn.conf.py app:app
autostart=true
autorestart=true
user=root
redirect_stderr=true
stdout_logfile=/opt/wms/logs/supervisor.log
EOF

supervisorctl reread
supervisorctl update
supervisorctl status wms
```

应显示 `RUNNING`或 `STARTING`。

### 7. 防火墙放行

```bash
ufw allow OpenSSH
ufw allow 5000/tcp
ufw --force enable
```

### 8. 验证访问

浏览器打开 `http://服务器IP:5000`

默认管理员账号：**admin** / **admin001**

## 二、更新升级

```bash
cd /opt/wms && git pull
supervisorctl restart wms
```

如涉及 Python 依赖变更（`requirements.txt` 有改动）：

```bash
cd /opt/wms
source venv/bin/activate
pip install -r requirements.txt
supervisorctl restart wms
```

## 三、卸载清理

### 1. 停止并移除服务

```bash
supervisorctl stop wms
rm -f /etc/supervisor/conf.d/wms.conf
supervisorctl reread
supervisorctl update
```

### 2. 移除 Nginx 配置（如已配置）

```bash
rm -f /etc/nginx/sites-enabled/wms
rm -f /etc/nginx/sites-available/wms
nginx -t && systemctl reload nginx
```

### 3. 删除项目

```bash
rm -rf /opt/wms
```

### 4. 释放防火墙端口（可选）

```bash
ufw delete allow 5000/tcp
```

### 5. 卸载系统依赖（可选）

```bash
apt remove -y nginx supervisor
apt autoremove -y
```

> ⚠️ Python3、git、pip 等基础工具不建议卸载。

## 四、日常运维

| 操作 | 命令 |
|------|------|
| 启动 / 停止 / 重启 | `supervisorctl start\|stop\|restart wms` |
| 查看状态 | `supervisorctl status wms` |
| 实时日志 | `supervisorctl tail -f wms` |
| 错误日志 | `tail -f /opt/wms/logs/supervisor.log` |
| 数据库备份 | 系统内置备份功能，或 `cp /opt/wms/wms.db /opt/wms/backup/` |

---

# 附录（两个版本通用）

## Nginx 反向代理（可选）

> 以下命令假设以 root 执行；普通用户请在命令前加 `sudo`。

```bash
cat > /etc/nginx/sites-available/wms <<'EOF'
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

ln -sf /etc/nginx/sites-available/wms /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
systemctl enable nginx
```

配置后需将 `gunicorn.conf.py` 的 bind 改为 `127.0.0.1:5000` 并放行 80 端口：

```bash
sed -i 's/0.0.0.0:5000/127.0.0.1:5000/' /opt/wms/gunicorn.conf.py
ufw allow 80/tcp
supervisorctl restart wms
```

### HTTPS（需要域名）

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 你的域名
```

## 安全建议

1. **修改 secret_key**：编辑 `app.py`，将 `wms_secret_key_2026` 改为随机字符串
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. **修改默认密码**：首次登录后立即修改管理员密码
3. **定期更新系统**：`apt update && apt upgrade -y`（root）或 `sudo apt update && sudo apt upgrade -y`（普通用户）
4. **内网限制访问**：在 Nginx 配置中限制 IP 段
   ```nginx
   location / {
       allow 192.168.1.0/24;  # 改为你的内网段
       deny all;
       proxy_pass http://127.0.0.1:5000;
       ...
   }
   ```

## 文件结构

```
/opt/wms/
├── app.py              # Flask 主程序
├── requirements.txt    # Python 依赖
├── gunicorn.conf.py    # Gunicorn 配置（部署时创建，已加入 .gitignore）
├── wms.db              # SQLite 数据库（自动生成）
├── venv/               # Python 虚拟环境（部署时生成）
├── logs/               # 日志目录
├── backup/             # 数据库备份目录
├── static/
│   ├── css/style.css
│   └── js/app.js
└── templates/
    └── index.html
```
