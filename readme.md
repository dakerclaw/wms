# WMS 物料管理系统

> 轻量级仓库物料收发管理系统 —— Flask + SQLite + 原生 JS，单文件后端、零前端构建、一条命令部署。

一个面向**中小型仓库 / 车间物料流转**场景的收发存管理系统。无需 Docker、无需 Node 构建，
后端只有 `app.py` 一个文件，前端是原生 JS，数据库是零依赖的 SQLite——克隆下来就能跑。

---

## 目录

- [项目介绍](#项目介绍)
- [项目功能](#项目功能)
  - [核心业务流程](#核心业务流程)
  - [功能清单](#功能清单)
  - [技术特性](#技术特性)
- [Linux 服务器部署](#linux-服务器部署)
  - [方式一：Root 一键脚本](#方式一root-一键脚本)
  - [方式二：普通用户一键脚本](#方式二普通用户一键脚本)
  - [升级](#升级)
  - [卸载](#卸载)
  - [两种方式对比](#两种方式对比)
  - [部署后配置](#部署后配置)
- [数据备份与恢复](#数据备份与恢复)
- [目录结构](#目录结构)
- [私有版权](#私有版权)

---

## 项目介绍

WMS（Warehouse Management System）物料管理系统用于管理仓库物料的**入库、出库、库存与查询**全流程。

系统围绕「物料批号 + 设备 + 包号」这一组唯一标识设计：每一次入库生成一条唯一的清单包号
（`批号-设备-包号`），出库时以此校验库存是否存在，避免重复出库与账实不符。

设计取向是**简单、可控、可自托管**：

- 单文件后端 `app.py`，无 ORM、无迁移框架、无前端构建链
- SQLite + WAL 模式，单机零运维，备份就是复制一个文件
- 权限只有两级（管理员 / 普通用户），够用且不易出错
- 所有操作留审计日志，事后可追溯
- 部署只需一条 `curl` 命令

适用场景：中小型仓库、车间物料周转、临时收发存台账、内网小规模团队协作。

---

## 项目功能

### 核心业务流程

```
        ┌──────────┐         ┌──────────┐         ┌──────────┐
        │   入库   │  ────▶  │   库存   │  ────▶  │   出库   │
        └──────────┘         └──────────┘         └──────────┘
        生成清单包号         可查可改可导出        校验库存后扣减
        (批号-设备-包号)                                │
                                                        ▼
                                                  ┌──────────┐
                                                  │ 审计日志 │
                                                  └──────────┘
```

### 功能清单

#### 📥 入库管理

- 选择仓库、设备、包装形式（标包 / 非标包）录入物料明细
- 支持一次录入多条明细（批号、设备、包号、重量）
- 每条明细自动生成唯一**清单包号**（`批号-设备-包号`）
- 入库前弹出确认预览，显示分组汇总（包数 / 总重量）
- 生成唯一入库单号，记录操作员与时间

#### 📤 出库管理

- 按批号 / 设备 / 包号录入出库明细，或直接选择库存
- 出库前自动**校验库存**，不存在的物料会明确列出
- 提交时再次原子校验，**并发下也不会重复出库**（唯一索引 + 事务保证）
- 生成唯一出库单号，记录车次、操作员与时间
- 支持出库明细查看与导出

#### 📦 库存查询

- 实时查询当前在库物料
- 支持按仓库、批号、设备等条件过滤
- 可编辑单条库存明细（批号 / 设备 / 包号 / 重量 / 仓库）
- 修改包号时自动同步更新清单包号，冲突时明确报错

#### 🔍 数据查询

- **入库查询**：按时间范围、仓库、设备、批号组合查询
- **出库查询**：按时间范围、仓库、车次、批号组合查询
- 查询结果支持一键导出为 Excel（`.xlsx`）

#### 📊 数据概览

- 昨日入库汇总、今日出库汇总
- 按仓库 / 车次分组的出入库统计
- 首页仪表盘一眼看清当前库存与近期流转

#### 👥 账号管理（管理员）

- 新增 / 修改 / 删除系统账号
- 两级权限：管理员（可管理仓库、账号、清理数据、备份）与普通用户（仅收发存操作）
- 支持批量导入账号
- 密码使用 werkzeug 加盐哈希存储，旧 MD5 密码在登录时自动透明升级

#### 🏭 仓库管理（管理员）

- 新增 / 修改 / 删除仓库
- 所有页面的仓库选项从接口动态加载，全局缓存、改动即时生效
- 默认初始化两个仓库：`仓库1`、`仓库2`

#### 🗑️ 数据清理（管理员）

- 删除指定日期之前的入库 / 出库记录
- 删除前支持**预览**将被删除的记录数量
- 操作记入审计日志

#### 💾 数据库备份（管理员）

- 手动创建数据库备份（`sqlite3.backup()`，WAL 模式下安全一致）
- 查看备份列表、删除旧备份
- 升级前自动备份

#### 📋 审计日志

- 记录登录、账号增删改、仓库增删改、入库、出库、库存修改、数据清理、备份等操作
- 包含操作人、时间、操作类型、详情

### 技术特性

#### 数据安全

| 特性 | 说明 |
|---|---|
| **原子出库** | `BEGIN IMMEDIATE` + `INSERT..SELECT WHERE NOT EXISTS`，配合 `list_no` 唯一索引，并发也不会重复出库 |
| **会话密钥** | 首次启动自动生成随机 `.secret_key`，绝不硬编码；支持环境变量注入 |
| **密码存储** | werkzeug scrypt 加盐哈希，旧 MD5 密码登录时自动升级 |
| **WAL 模式** | 读写并发友好，备份使用 `sqlite3.backup()` 保证一致性 |
| **外键约束** | 数据库层面保证关联数据完整性 |
| **审计留痕** | 所有关键操作落库，可追溯 |
| **统一时区** | 全部时间使用北京时间（UTC+8） |
| **XSS 防护** | 前端使用 `data-action` + 事件委托，杜绝字符串拼接注入 |
| **登录限速** | 同一来源 5 分钟内连续失败 5 次即锁定，返回 429，防暴力破解 |

#### 性能与运维

- 全部高频查询列已建索引，库存校验使用 `NOT EXISTS` 批量判断（避免 N+1）
- 静态资源走 ETag 协商缓存（内容未变返回 304）
- gunicorn 多 worker，模块加载时自动建表迁移，多进程安全（文件锁）
- 服务崩溃自动重启（systemd `Restart=always`）

#### 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / Flask 3.x |
| 数据库 | SQLite 3（WAL 模式） |
| WSGI | gunicorn |
| 前端 | 原生 HTML / CSS / JavaScript（无构建） |
| 部署 | systemd（系统级或用户级）/ 可选 nginx 反代 |
| 依赖 | 仅 3 个：`Flask`、`flask-cors`、`gunicorn` |

---

## Linux 服务器部署

提供两个一键脚本，按**你想要的运行身份**选择：

| 脚本 | 适用场景 |
|---|---|
| `install.sh` | 有 root 权限，装到 `/opt/wms`，系统级 systemd，**推荐用于生产** |
| `install-user.sh` | 没有 root 或不想动系统目录，装到 `~/apps/wms`，systemd --user |

两个脚本都支持 **安装 / 升级 / 卸载**，且：

- 自动安装系统依赖（python3 / venv / git / curl）
- 自动克隆源码、创建虚拟环境、安装 Python 依赖（优先国内镜像）
- 自动生成随机会话密钥并固化，重启不失效
- 升级前自动备份数据库
- 重复执行 `install` 会自动转为升级流程（幂等）
- 目标目录非空且不是本项目时**拒绝执行**，避免误覆盖

**前置要求**：Linux（Debian / Ubuntu 等 apt 系）+ systemd。

---

### 方式一：Root 一键脚本

装到 `/opt/wms`，服务名 `wms`，系统级 systemd 管理。

#### 安装

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- install
```

自定义端口和目录：

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- install --port 8080 --app-dir /opt/wms
```

也可以先下载再执行：

```bash
curl -fsSLO https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh
chmod +x install.sh
sudo ./install.sh install
```

安装完成后访问 `http://<服务器IP>:5000`，默认管理员 **admin / admin001**（请立即修改）。

#### 常用参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `--port N` | 监听端口 | `5000` |
| `--app-dir P` | 应用目录 | `/opt/wms` |

#### 服务管理

```bash
sudo systemctl start wms        # 启动
sudo systemctl stop wms         # 停止
sudo systemctl restart wms      # 重启
sudo systemctl status wms       # 状态
journalctl -u wms -f            # 实时日志
```

---

### 方式二：普通用户一键脚本

装到 `~/apps/wms`，服务用 **systemd --user** 守护，不写 `/etc`。除安装系统依赖外无需 root。

#### 安装

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- install
```

自定义端口和目录：

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- install --port 8080 --app-dir ~/apps/wms
```

#### 服务管理

```bash
systemctl --user start wms      # 启动
systemctl --user stop wms       # 停止
systemctl --user restart wms    # 重启
systemctl --user status wms     # 状态
journalctl --user -u wms -f     # 实时日志
```

#### ⚠️ 必须了解：关于 linger

普通用户的 `systemd --user` 实例**默认只在登录会话期间存在**——SSH 断开后服务会停止。

希望服务在退出登录后继续运行、并能开机自启，需要启用 linger：

```bash
sudo loginctl enable-linger $USER
```

脚本会自动尝试启用（失败时只告警不中断）。若脚本报错
「当前没有可用的 systemd --user 实例」，按下面处理：

1. 执行 `sudo loginctl enable-linger $USER`
2. **重新登录**服务器
3. 再次运行安装命令

> 长期运行的生产环境，建议直接用 root 版 `install.sh`——系统级 systemd 没有这个限制。

---

### 升级

升级会自动：**备份数据库** → 拉取最新代码 → 更新依赖 → 重启服务 → 健康检查。
若已是最新版本则直接跳过，不做无谓重启。

**Root 方式：**

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- update
```

**普通用户方式：**

```bash
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- update
```

若本地有未提交改动，脚本会自动 `git stash` 后继续，不会因冲突卡住。

### 卸载

默认**保留数据库**（导出到独立目录后删除应用），避免误删生产数据。

**Root 方式：**

```bash
# 保留数据库（备份到 /root/wms_data_<时间戳>/）
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- uninstall

# 彻底删除（含数据库与备份，不可恢复）
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- uninstall --purge
```

**普通用户方式：**

```bash
# 保留数据库（备份到 ~/wms_data_<时间戳>/）
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- uninstall

# 彻底删除
curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- uninstall --purge
```

### 两种方式对比

| 项目 | Root 脚本 `install.sh` | 普通用户脚本 `install-user.sh` |
|---|---|---|
| 安装目录 | `/opt/wms` | `~/apps/wms` |
| 服务类型 | 系统级 systemd | systemd --user |
| 服务名 | `wms.service` | `wms.service`（用户级） |
| 管理命令 | `systemctl ... wms` | `systemctl --user ... wms` |
| 日志 | `journalctl -u wms -f` | `journalctl --user -u wms -f` |
| 需要 root | 全程 | 仅装系统依赖时 |
| 退出登录后运行 | ✅ 默认 | ⚠️ 需 enable-linger |
| 开机自启 | ✅ 默认 | ⚠️ 需 enable-linger |
| 安装配置 | `/etc/wms/install.conf` | `<app-dir>/.install.conf` |
| 推荐场景 | 生产环境 | 个人测试 / 无 root 环境 |

### 部署后配置

#### 修改默认密码

首次登录后立即修改 `admin / admin001`。密码使用强哈希存储，管理员可在「账号管理」中重置。

#### 反向代理（可选）

如需用 80/443 端口或绑定域名，用 nginx 反代到应用端口。全部流量挂在根路径时：

```nginx
server {
    listen 80;
    server_name wms.example.com;
    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

#### 挂载到子路径（如 example.com/wms/）

若域名根路径已被其他站点占用，可把 WMS 挂到子路径下。应用内置子路径支持，
只需在 nginx 去掉前缀，并设置 `WMS_BASE_PATH`：

**nginx 配置：**

```nginx
location = /wms { return 301 /wms/; }

location /wms/ {
    rewrite ^/wms/(.*)$ /$1 break;      # 去掉 /wms 前缀再转发
    proxy_pass http://127.0.0.1:5000;
    proxy_http_version 1.1;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 20m;
    proxy_read_timeout   300s;
}
```

**应用设置**（让页面生成的静态资源与 API 地址带上 `/wms/` 前缀）：

```bash
# Root 方式
sudo systemctl edit wms
# 添加：
[Service]
Environment=WMS_BASE_PATH=/wms/

sudo systemctl daemon-reload && sudo systemctl restart wms

# 普通用户方式
systemctl --user edit wms   # 同样加 Environment=WMS_BASE_PATH=/wms/
systemctl --user daemon-reload && systemctl --user restart wms
```

配置后访问 `https://example.com/wms/` 即可。`WMS_BASE_PATH` 不设置时默认 `/`，即根路径部署。

#### 启用 HTTPS

部署 HTTPS 后，让会话 Cookie 带上 `Secure` 标记，编辑服务文件添加环境变量：

```bash
# Root 方式
sudo systemctl edit wms
# 添加：
[Service]
Environment=WMS_HTTPS=1

# 普通用户方式
systemctl --user edit wms
```

#### 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WMS_BIND` | 监听地址 | `0.0.0.0:5000` |
| `WMS_WORKERS` | gunicorn 进程数 | `2` |
| `WMS_SECRET_KEY` | 会话密钥（不设则自动生成） | 自动生成 |
| `WMS_HTTPS` | 设为 `1` 时 Cookie 带 Secure | `0` |
| `WMS_DB_PATH` | 数据库路径 | `<app-dir>/wms.db` |
| `WMS_BACKUP_DIR` | 备份目录 | `<app-dir>/backup` |
| `WMS_BASE_PATH` | 子路径部署时的挂载前缀，如 `/wms/` | `/` |
| `WMS_CORS_ORIGINS` | 跨域白名单（同源部署无需设置） | 空 |

---

## 数据备份与恢复

### 备份

两种方式：

1. **系统内手点**：管理员登录 →「数据库备份」→ 创建备份
2. **升级自动**：每次 `update` 前自动备份到 `backup/wms_pre_upgrade_<时间戳>.db`

> ⚠️ 不要直接用 `cp` 复制 `wms.db`——WAL 模式下可能有未落盘数据。
> 系统使用 `sqlite3.backup()`，能保证快照一致性。

### 恢复

```bash
# 1. 停止服务
sudo systemctl stop wms          # 或 systemctl --user stop wms

# 2. 备份当前库（以防万一）
mv /opt/wms/wms.db /opt/wms/wms.db.bak

# 3. 拷入备份文件
cp /opt/wms/backup/wms_20260101_120000.db /opt/wms/wms.db

# 4. 启动服务
sudo systemctl start wms
```

---

## 目录结构

```
/opt/wms/                     # 或 ~/apps/wms
├── app.py                    # 后端主程序（含建表与迁移）
├── requirements.txt          # Python 依赖
├── gunicorn.conf.py          # gunicorn 配置
├── install.sh                # Root 一键脚本
├── install-user.sh           # 普通用户一键脚本
├── .secret_key               # 自动生成的会话密钥（勿提交）
├── wms.db                    # SQLite 数据库（自动生成）
├── wms.db-wal / -shm         # WAL 临时文件
├── venv/                     # Python 虚拟环境
├── logs/                     # gunicorn 日志
├── backup/                   # 数据库备份
├── static/
│   ├── css/style.css
│   └── js/app.js
└── templates/
    └── index.html
```

---

## 私有版权

本项目为**私有软件**，保留所有权利。

- **著作权**：Copyright © 2026 dakerclaw. All rights reserved.
- **授权范围**：仅限著作权人明确授权的内部使用。未经书面许可，不得复制、分发、
  修改、公开发布、商业使用，或用于任何衍生作品。
- **无担保声明**：本软件按「现状」提供，不附带任何明示或暗示的担保，包括但不限于
  适销性、特定用途适用性与非侵权担保。在任何情况下，著作权人均不对因使用本软件
 而产生的任何索赔、损害或其他责任负责。
- **数据责任**：使用者应自行建立并维护数据备份机制。仓储数据属于关键业务数据，
  建议至少保留每日备份。
- **第三方组件**：本项目依赖 Flask（BSD-3-Clause）、flask-cors（MIT）、
  gunicorn（MIT），其授权条款各自适用。

如需商业授权或定制开发，请联系著作权人。

---

<div align="right">
<sub>WMS 物料管理系统 · 私有软件</sub>
</div>
