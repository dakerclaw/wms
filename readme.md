# WMS 物料管理系统

> 仓库地址：`https://github.com/dakerclaw/wms`

## 快速导航

| 操作 | 说明 |
|------|------|
| [全新安装](#一全新安装) | 从零部署到 Debian 服务器 |
| [更新升级](#二更新升级) | 拉取最新代码并重启 |
| [卸载清理](#三卸载清理) | 完整移除 WMS 及相关配置 |

---

## 一、全新安装

### 1. 安装系统依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx supervisor
```

### 2. 克隆项目

```bash
cd /opt
sudo git clone https://github.com/dakerclaw/wms.git
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

### 5. 创建必要目录

```bash
mkdir -p /opt/wms/logs /opt/wms/backup
```

### 6. 配置 Supervisor（进程守护）

```bash
sudo tee /etc/supervisor/conf.d/wms.conf > /dev/null <<'EOF'
[program:wms]
directory=/opt/wms
command=/opt/wms/venv/bin/gunicorn -c gunicorn.conf.py app:app
autostart=true
autorestart=true
user=root
redirect_stderr=true
stdout_logfile=/opt/wms/logs/supervisor.log
EOF

sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status wms
```

应显示 `RUNNING`。

### 7. 防火墙放行

```bash
sudo ufw allow OpenSSH
sudo ufw allow 5000/tcp
sudo ufw --force enable
```

### 8. 验证访问

浏览器打开 `http://服务器IP:5000`

默认管理员账号：**shangtai** / **st999777**

---

## 二、更新升级

每次从 Git 拉取代码后，重启服务即可生效：

```bash
cd /opt/wms && git pull
sudo supervisorctl restart wms
```

验证更新成功：

```bash
sudo supervisorctl status wms
# 应显示 RUNNING
```

> **注意**：如果更新涉及 Python 依赖变更（`requirements.txt` 改动），还需执行：
> ```bash
> cd /opt/wms
> source venv/bin/activate
> pip install -r requirements.txt
> sudo supervisorctl restart wms
> ```

---

## 三、卸载清理

### 1. 停止并移除 Supervisor 服务

```bash
sudo supervisorctl stop wms
sudo rm /etc/supervisor/conf.d/wms.conf
sudo supervisorctl reread
sudo supervisorctl update
```

### 2. 移除 Nginx 配置（如已配置）

```bash
sudo rm -f /etc/nginx/sites-enabled/wms
sudo rm -f /etc/nginx/sites-available/wms
sudo nginx -t && sudo systemctl reload nginx
```

### 3. 删除项目文件

```bash
sudo rm -rf /opt/wms
```

### 4. 释放防火墙端口（可选）

```bash
sudo ufw delete allow 5000/tcp
```

### 5. 卸载系统依赖（可选）

如果这些包没有其他服务在使用，可以卸载：

```bash
sudo apt remove -y nginx supervisor
sudo apt autoremove -y
```

> ⚠️ **Python3、git、pip 等基础工具不建议卸载。**

---

## 四、日常运维

| 操作 | 命令 |
|------|------|
| 启动服务 | `sudo supervisorctl start wms` |
| 停止服务 | `sudo supervisorctl stop wms` |
| 重启服务 | `sudo supervisorctl restart wms` |
| 查看状态 | `sudo supervisorctl status wms` |
| 实时日志 | `sudo supervisorctl tail -f wms` |
| 错误日志 | `tail -f /opt/wms/logs/error.log` |
| 数据库备份 | 系统内置备份功能，或手动 `cp /opt/wms/wms.db /opt/wms/backup/` |

---

## 五、Nginx 反向代理（可选）

使用域名或 80 端口访问时配置：

```bash
sudo tee /etc/nginx/sites-available/wms > /dev/null <<'EOF'
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

配置 Nginx 后，将 `gunicorn.conf.py` 的 bind 改为 `127.0.0.1:5000`，并放行 80 端口：

```bash
sudo ufw allow 80/tcp
```

### HTTPS（需要域名）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
```

---

## 六、安全建议

1. **修改 secret_key**：编辑 `app.py`，将 `wms_secret_key_2026` 改为随机字符串
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
2. **修改默认密码**：首次登录后立即修改管理员密码
3. **定期更新系统**：`sudo apt update && sudo apt upgrade -y`
4. **内网限制访问**：在 Nginx 配置中限制 IP 段
   ```nginx
   location / {
       allow 192.168.1.0/24;  # 改为你的内网段
       deny all;
       proxy_pass http://127.0.0.1:5000;
       ...
   }
   ```

---

## 文件结构

```
/opt/wms/
├── app.py              # Flask 主程序
├── requirements.txt    # Python 依赖
├── gunicorn.conf.py    # Gunicorn 配置
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
