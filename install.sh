#!/usr/bin/env bash
# ============================================================================
# WMS 物料管理系统 —— 一键安装 / 更新 / 卸载脚本
#   https://github.com/dakerclaw/wms
#
# 用法：
#   sudo ./install.sh install  [--port 5000] [--app-dir /opt/wms]
#   sudo ./install.sh update
#   sudo ./install.sh uninstall [--purge]
#
# 也可一行命令远程执行：
#   curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install.sh | sudo bash -s -- install
#
# 说明：
#   - 使用 systemd 守护 gunicorn（部分机器若只有 supervisor，会提示改用 readme 手工步骤）。
#   - 安装参数记录在 /etc/wms/install.conf，update/uninstall 自动读取，无需重复传参。
#   - 更新时自动备份数据库（sqlite3 backup，WAL 模式下比 cp 安全）。
#   - 卸载默认保留数据库，除非加 --purge。
# ============================================================================
set -euo pipefail

REPO_URL="${WMS_REPO:-https://github.com/dakerclaw/wms.git}"
CONF_DIR="${WMS_CONF_DIR:-/etc/wms}"
CONF_FILE="${CONF_DIR}/install.conf"
SERVICE_NAME="${WMS_SERVICE:-wms}"
DEFAULT_PORT="5000"
DEFAULT_APP_DIR="${WMS_APP_DIR:-/opt/wms}"

# ---------- 输出辅助 ----------
c_reset='\033[0m'; c_red='\033[31m'; c_grn='\033[32m'; c_yel='\033[33m'; c_cyn='\033[36m'
info()  { printf "${c_cyn}[INFO]${c_reset} %s\n" "$*"; }
ok()    { printf "${c_grn}[ OK ]${c_reset} %s\n" "$*"; }
warn()  { printf "${c_yel}[WARN]${c_reset} %s\n" "$*"; }
die()   { printf "${c_red}[FAIL]${c_reset} %s\n" "$*" >&2; exit 1; }

# ---------- 前置检查 ----------
require_root() {
  [ "$(id -u)" -eq 0 ] || die "请用 root 执行（sudo ./install.sh $*）"
}

require_systemd() {
  command -v systemctl >/dev/null 2>&1 || die "未找到 systemctl，本脚本仅支持 systemd。请参照 readme 手工部署。"
  if [ ! -d /run/systemd/system ]; then
    die "systemd 未作为 init 运行（可能是容器/WSL）。请参照 readme 手工部署。"
  fi
}

# ---------- 参数解析 ----------
parse_args() {
  PORT="$DEFAULT_PORT"
  APP_DIR="$DEFAULT_APP_DIR"
  PURGE=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --port)    PORT="${2:?--port 需要值}"; shift 2 ;;
      --port=*)  PORT="${1#*=}"; shift ;;
      --app-dir) APP_DIR="${2:?--app-dir 需要值}"; shift 2 ;;
      --app-dir=*) APP_DIR="${1#*=}"; shift ;;
      --purge)   PURGE=1; shift ;;
      *) die "未知参数：$1" ;;
    esac
  done
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "--port 必须是数字"
}

# ---------- 依赖安装 ----------
install_deps() {
  info "检查系统依赖 ..."
  local need_apt=0
  command -v python3 >/dev/null 2>&1 || need_apt=1
  command -v git >/dev/null 2>&1 || need_apt=1
  python3 -c 'import venv' 2>/dev/null || need_apt=1

  if [ "$need_apt" -eq 1 ]; then
    command -v apt-get >/dev/null 2>&1 || die "缺少 python3/git，且当前系统非 apt 系，请手动安装后重试"
    info "安装系统包：python3 python3-venv python3-pip git curl"
    apt-get update -qq
    # Debian/Ubuntu 新版 venv 需要独立的 python3-venv 包（如 python3.13-venv）
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git curl \
      || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip git curl
  fi

  # 校验 venv 可用（Debian 上 pip 可能来自 ensurepip）
  python3 -c 'import venv' 2>/dev/null || die "python3 venv 模块不可用，请安装 python3-venv 后重试"
  ok "系统依赖就绪"
}

# ---------- 应用目录权重 ----------
ensure_app_dir() {
  if [ ! -d "$APP_DIR" ]; then
    mkdir -p "$(dirname "$APP_DIR")"
  fi
  chown root:root "$APP_DIR" 2>/dev/null || true
}

# ---------- pip 镜像（国内加速，失败回退官方源）----------
pip_install() {
  local py="$1"
  if "$py" -m pip install -q -i https://mirrors.aliyun.com/pypi/simple/ -r "$APP_DIR/requirements.txt"; then
    return 0
  fi
  warn "国内镜像安装失败，回退官方源重试 ..."
  "$py" -m pip install -q -r "$APP_DIR/requirements.txt"
}

# ---------- 写入 systemd unit ----------
write_unit() {
  info "写入 systemd 服务 ${SERVICE_NAME}.service ..."
  local secret_key=""
  if [ -f "$APP_DIR/.secret_key" ]; then
    secret_key="$(cat "$APP_DIR/.secret_key")"
  fi

  cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=WMS 物料管理系统
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
Environment=WMS_BIND=0.0.0.0:${PORT}
Environment=WMS_WORKERS=2
Environment=WMS_HTTPS=0
${secret_key:+Environment=WMS_SECRET_KEY=${secret_key}}
ExecStart=${APP_DIR}/venv/bin/gunicorn -c ${APP_DIR}/gunicorn.conf.py app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
}

# ---------- 防火墙（有 ufw 才处理）----------
open_firewall() {
  if command -v ufw >/dev/null 2>&1; then
    ufw status 2>/dev/null | grep -qi active || { info "ufw 未启用，跳过防火墙配置"; return 0; }
    info "放行端口 ${PORT}/tcp ..."
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || warn "ufw 放行失败，请手动 ufw allow ${PORT}/tcp"
  fi
}

# ---------- 健康检查 ----------
health_check() {
  info "等待服务就绪 ..."
  local i url="http://127.0.0.1:${PORT}/api/me"
  for i in $(seq 1 20); do
    if curl -fsS -m 3 -o /dev/null "$url" 2>/dev/null || \
       [ "$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null)" = "401" ]; then
      ok "服务已响应（/api/me 返回 401 属正常的未登录响应）"
      return 0
    fi
    sleep 1
  done
  warn "健康检查超时，请查看日志：journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
  return 1
}

# ---------- 备份数据库 ----------
backup_db() {
  [ -f "$APP_DIR/wms.db" ] || return 0
  local bk="$APP_DIR/backup"
  mkdir -p "$bk"
  local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
  local out="$bk/wms_pre_upgrade_${stamp}.db"
  if "$APP_DIR/venv/bin/python" - "$APP_DIR/wms.db" "$out" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PY
  then
    ok "数据库已备份：$out"
  else
    warn "数据库备份失败（继续执行更新）"
  fi
}

# ---------- 命令：install ----------
cmd_install() {
  require_root
  require_systemd
  parse_args "$@"

  printf "\n=== WMS 安装 ===\n  仓库：%s\n  目录：%s\n  端口：%s\n\n" "$REPO_URL" "$APP_DIR" "$PORT"

  install_deps
  ensure_app_dir

  if [ -d "$APP_DIR/.git" ]; then
    info "检测到已有 git 仓库，改用更新流程 ..."
    cmd_update
    return 0
  fi

  if [ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]; then
    die "目录 $APP_DIR 非空且不是 WMS git 仓库。请先清理，或用 --app-dir 指定其他目录。"
  fi

  info "克隆源码 ..."
  if ! git clone --quiet --depth 1 "$REPO_URL" "$APP_DIR"; then
    die "git clone 失败，请检查网络或仓库地址"
  fi
  ok "源码已克隆"

  info "创建 Python 虚拟环境并安装依赖 ..."
  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install -q --upgrade pip
  pip_install "$APP_DIR/venv/bin/python"
  ok "Python 依赖已安装"

  # 生成会话密钥（固定下来，重启/重装都不会让用户登录态失效）
  if [ ! -f "$APP_DIR/.secret_key" ]; then
    "$APP_DIR/venv/bin/python" -c 'import secrets;print(secrets.token_hex(32))' > "$APP_DIR/.secret_key"
    chmod 600 "$APP_DIR/.secret_key"
    ok "已生成随机会话密钥 .secret_key"
  fi

  mkdir -p "$APP_DIR/logs" "$APP_DIR/backup"

  write_unit
  systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
  systemctl restart "$SERVICE_NAME"
  open_firewall

  # 记录安装参数供 update/uninstall 使用
  mkdir -p "$CONF_DIR"
  cat > "$CONF_FILE" <<CONF
APP_DIR=${APP_DIR}
PORT=${PORT}
SERVICE_NAME=${SERVICE_NAME}
REPO_URL=${REPO_URL}
CONF_DIR=${CONF_DIR}
INSTALLED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
CONF

  if health_check; then
    printf "\n${c_grn}=== 安装完成 ===${c_reset}\n"
    printf "  访问地址：http://<服务器IP>:%s\n" "$PORT"
    printf "  默认账号：admin / admin001 （请登录后立即修改）\n"
    printf "  服务管理：systemctl {start|stop|restart|status} %s\n" "$SERVICE_NAME"
    printf "  实时日志：journalctl -u %s -f\n\n" "$SERVICE_NAME"
  else
    die "服务未正常响应，安装未完成"
  fi
}

# ---------- 命令：update ----------
cmd_update() {
  require_root
  require_systemd
  [ -f "$CONF_FILE" ] || die "未找到 ${CONF_FILE}，请先执行 install"
  # shellcheck disable=SC1090
  . "$CONF_FILE"

  printf "\n=== WMS 更新 ===\n  目录：%s\n  端口：%s\n\n" "$APP_DIR" "$PORT"
  [ -d "$APP_DIR/.git" ] || die "$APP_DIR 不是 git 仓库，无法自动更新"

  backup_db

  info "拉取最新代码 ..."
  local before after
  before="$(git -C "$APP_DIR" rev-parse HEAD)"
  if ! git -C "$APP_DIR" pull --ff-only --quiet; then
    warn "git pull 失败（可能存在本地改动）。尝试保留本地改动后继续 ..."
    git -C "$APP_DIR" stash push -u -m "auto-stash-$(date +%s)" --quiet || true
    git -C "$APP_DIR" pull --ff-only --quiet || die "拉取失败，请手工处理 $APP_DIR 的 git 状态"
  fi
  after="$(git -C "$APP_DIR" rev-parse HEAD)"

  if [ "$before" = "$after" ]; then
    ok "已是最新版本（${after:0:8}），无需重启"
    return 0
  fi

  info "更新依赖 ..."
  pip_install "$APP_DIR/venv/bin/python"

  # 重新生成 unit（端口/密钥可能变化）
  write_unit
  systemctl restart "$SERVICE_NAME"

  if health_check; then
    printf "\n${c_grn}=== 更新完成 ===${c_reset}\n  ${before:0:8} -> ${after:0:8}\n\n"
  else
    warn "更新后服务未正常响应，请查看：journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
    exit 1
  fi
}

# ---------- 命令：uninstall ----------
cmd_uninstall() {
  require_root
  require_systemd
  parse_args "$@"

  if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
  else
    warn "未找到 ${CONF_FILE}，使用默认目录 $DEFAULT_APP_DIR"
  fi

  printf "\n=== WMS 卸载 ===\n  目录：%s\n  端口：%s\n\n" "$APP_DIR" "$PORT"

  if [ "$PURGE" -eq 0 ] && [ -f "$APP_DIR/wms.db" ]; then
    local stamp; stamp="$(date +%Y%m%d_%H%M%S)"
    local keep="/root/wms_data_${stamp}"
    mkdir -p "$keep"
    if "$APP_DIR/venv/bin/python" - "$APP_DIR/wms.db" "$keep/wms.db" 2>/dev/null <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as s, sqlite3.connect(sys.argv[2]) as d:
    s.backup(d)
PY
    then
      ok "数据库已保存到：$keep/wms.db（如需彻底删除请加 --purge）"
    else
      warn "数据库备份失败；若删除目录将丢失数据"
      read -r -p "仍要继续吗？[y/N] " ans
      [[ "$ans" =~ ^[Yy]$ ]] || { info "已取消"; exit 1; }
    fi
  elif [ "$PURGE" -eq 1 ]; then
    warn "--purge 已指定：数据库和备份将被彻底删除"
  fi

  info "停止并禁用服务 ..."
  systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload

  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true
  fi

  if [ -d "$APP_DIR" ]; then
    info "删除应用目录 $APP_DIR ..."
    rm -rf "$APP_DIR"
  fi
  rm -f "$CONF_FILE"
  rmdir "$CONF_DIR" 2>/dev/null || true

  printf "\n${c_grn}=== 卸载完成 ===${c_reset}\n"
  if [ "$PURGE" -eq 0 ]; then
    printf "  数据库已备份保留在 /root/wms_data_*/（加 --purge 可彻底删除）\n"
  else
    printf "  --purge 模式：数据库与应用目录已彻底删除，不可恢复\n"
  fi
  printf "  注意：python3 / git 等系统包未卸载\n\n"
}

# ---------- 命令：help ----------
cmd_help() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

# ---------- 入口 ----------
main() {
  local cmd="${1:-}"
  [ $# -gt 0 ] && shift || true
  case "$cmd" in
    install)   cmd_install "$@" ;;
    update)    cmd_update "$@" ;;
    uninstall) cmd_uninstall "$@" ;;
    ""|-h|--help|help) cmd_help ;;
    *) die "未知命令：$cmd（可用：install | update | uninstall）" ;;
  esac
}

main "$@"
