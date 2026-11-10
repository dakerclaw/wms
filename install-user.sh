#!/usr/bin/env bash
# ============================================================================
# WMS 物料管理系统 —— 普通用户一键安装 / 更新 / 卸载脚本（无需 root 部署应用）
#   https://github.com/dakerclaw/wms
#
# 用法：
#   ./install-user.sh install  [--port 5000] [--app-dir ~/apps/wms]
#   ./install-user.sh update
#   ./install-user.sh uninstall [--purge]
#
# 也可一行命令远程执行：
#   curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- install
#
# 与 install.sh 的区别：
#   - 应用装在当前用户家目录（默认 ~/apps/wms），不需要 root 写 /opt。
#   - 服务用 systemd --user 守护（不写 /etc/systemd/system），用 systemctl --user 管理。
#   - 只有「安装系统依赖」这一步可能需要 sudo；若依赖已齐全，全程无需 root。
#   - 自动尝试 enable-linger，使服务在退出登录后仍运行、并可开机自启
#     （linger 需要 sudo；失败时降级为仅登录期间运行，并给出提示）。
# ============================================================================
set -euo pipefail

REPO_URL="${WMS_REPO:-https://github.com/dakerclaw/wms.git}"
SERVICE_NAME="${WMS_SERVICE:-wms}"
DEFAULT_PORT="5000"
DEFAULT_APP_DIR="${WMS_APP_DIR:-$HOME/apps/wms}"
CONF_FILE=""   # 解析 --app-dir 后确定为 <app-dir>/.install.conf

# ---------- 输出辅助 ----------
c_reset='\033[0m'; c_red='\033[31m'; c_grn='\033[32m'; c_yel='\033[33m'; c_cyn='\033[36m'
info()  { printf "${c_cyn}[INFO]${c_reset} %s\n" "$*"; }
ok()    { printf "${c_grn}[ OK ]${c_reset} %s\n" "$*"; }
warn()  { printf "${c_yel}[WARN]${c_reset} %s\n" "$*"; }
die()   { printf "${c_red}[FAIL]${c_reset} %s\n" "$*" >&2; exit 1; }

# ---------- 前置检查 ----------
require_non_root_note() {
  if [ "$(id -u)" -eq 0 ]; then
    warn "当前是 root 用户。普通用户脚本建议以普通用户执行；"
    warn "若你就是想用 root 跑，本脚本仍可用（服务跑在 root 的 user 实例下）。"
    warn "生产环境更推荐用 install.sh 走系统级 systemd。"
  fi
}

require_user_systemd() {
  command -v systemctl >/dev/null 2>&1 || die "未找到 systemctl，本脚本需要 systemd。请改用 readme 手工步骤。"
  if [ ! -d /run/systemd/system ]; then
    die "systemd 未作为 init 运行（容器/WSL）。请改用 readme 手工步骤。"
  fi
  # systemd --user 需要可用的 user bus
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    die "当前没有可用的 systemd --user 实例。
  常见原因：未通过登录会话（如直接用 root shell、被 ssh 直连且无 linger）。
  解决：先执行  sudo loginctl enable-linger $(id -un)  然后重新登录再试。"
  fi
}

# ---------- 参数解析 ----------
parse_args() {
  PORT="$DEFAULT_PORT"
  APP_DIR="$DEFAULT_APP_DIR"
  PURGE="${PURGE:-0}"   # 保留外部已设置的 --purge
  while [ $# -gt 0 ]; do
    case "$1" in
      --port)      PORT="${2:?--port 需要值}"; shift 2 ;;
      --port=*)    PORT="${1#*=}"; shift ;;
      --app-dir)   APP_DIR="${2:?--app-dir 需要值}"; shift 2 ;;
      --app-dir=*) APP_DIR="${1#*=}"; shift ;;
      --purge)     PURGE=1; shift ;;
      *) die "未知参数：$1" ;;
    esac
  done
  [[ "$PORT" =~ ^[0-9]+$ ]] || die "--port 必须是数字"
  # 展开 ~ 并转绝对路径
  case "$APP_DIR" in
    "~") APP_DIR="$HOME" ;;
    "~/"*) APP_DIR="$HOME/${APP_DIR#\~/}" ;;
  esac
  mkdir -p "$(dirname "$APP_DIR")" 2>/dev/null || true
  APP_DIR="$(cd "$(dirname "$APP_DIR")" && pwd)/$(basename "$APP_DIR")"
  CONF_FILE="${APP_DIR}/.install.conf"
}

# ---------- 依赖检查/安装 ----------
check_deps() {
  info "检查依赖 ..."
  local missing=()
  command -v python3 >/dev/null 2>&1 || missing+=("python3")
  command -v git     >/dev/null 2>&1 || missing+=("git")
  command -v curl    >/dev/null 2>&1 || missing+=("curl")
  python3 -c 'import venv' 2>/dev/null || missing+=("python3-venv")

  if [ ${#missing[@]} -eq 0 ]; then
    ok "依赖齐全（python3 / git / curl / venv）"
    return 0
  fi

  warn "缺少：${missing[*]}"
  command -v apt-get >/dev/null 2>&1 || die "缺少 ${missing[*]}，且当前不是 apt 系系统，请手动安装后重试"
  info "需要管理员权限安装系统包，下面会提示输入 sudo 密码 ..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3 python3-venv python3-pip git curl \
    || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-pip git curl
  python3 -c 'import venv' 2>/dev/null || die "python3 venv 仍不可用，请手动安装 python3-venv"
  ok "依赖已安装"
}

# ---------- pip 安装（国内镜像优先）----------
pip_install() {
  local py="$1"
  if "$py" -m pip install -q -i https://mirrors.aliyun.com/pypi/simple/ -r "$APP_DIR/requirements.txt"; then
    return 0
  fi
  warn "国内镜像失败，回退官方源 ..."
  "$py" -m pip install -q -r "$APP_DIR/requirements.txt"
}

# ---------- user unit ----------
USER_UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

write_user_unit() {
  info "写入 systemd --user 服务 ${SERVICE_NAME}.service ..."
  mkdir -p "$USER_UNIT_DIR"

  local secret_key=""
  [ -f "$APP_DIR/.secret_key" ] && secret_key="$(cat "$APP_DIR/.secret_key")"

  cat > "${USER_UNIT_DIR}/${SERVICE_NAME}.service" <<UNIT
[Unit]
Description=WMS 物料管理系统（用户级）
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=WMS_BIND=0.0.0.0:${PORT}
Environment=WMS_WORKERS=2
Environment=WMS_HTTPS=0
${secret_key:+Environment=WMS_SECRET_KEY=${secret_key}}
ExecStart=${APP_DIR}/venv/bin/gunicorn -c ${APP_DIR}/gunicorn.conf.py app:app
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
}

# ---------- linger（退出登录后仍运行）----------
try_enable_linger() {
  local user; user="$(id -un)"
  if loginctl show-user "$user" --property=Linger 2>/dev/null | grep -q 'Linger=yes'; then
    ok "linger 已启用：服务退出登录后仍运行，且可开机自启"
    return 0
  fi
  info "尝试启用 linger（需 sudo），使服务在退出登录后继续运行 ..."
  if sudo -n loginctl enable-linger "$user" 2>/dev/null || sudo loginctl enable-linger "$user" 2>/dev/null; then
    ok "linger 已启用"
    return 0
  fi
  warn "未能启用 linger。服务只在当前登录会话期间运行。"
  warn "如需长期运行，请手动执行：sudo loginctl enable-linger $user"
}

# ---------- 防火墙 ----------
open_firewall() {
  command -v ufw >/dev/null 2>&1 || return 0
  ufw status 2>/dev/null | grep -qi active || return 0
  info "检测到 ufw 已启用，尝试放行 ${PORT}/tcp（需 sudo）..."
  sudo -n ufw allow "${PORT}/tcp" >/dev/null 2>&1 || sudo ufw allow "${PORT}/tcp" >/dev/null 2>&1 \
    || warn "ufw 放行失败，请手动执行：sudo ufw allow ${PORT}/tcp"
}

# ---------- 健康检查 ----------
health_check() {
  info "等待服务就绪 ..."
  local i url="http://127.0.0.1:${PORT}/api/me"
  for i in $(seq 1 20); do
    local code
    code="$(curl -s -m 3 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
    if [ "$code" = "401" ] || [ "$code" = "200" ]; then
      ok "服务已响应（HTTP $code，401 属正常的未登录响应）"
      return 0
    fi
    sleep 1
  done
  warn "健康检查超时。查看日志：systemctl --user status ${SERVICE_NAME}"
  warn "或：journalctl --user -u ${SERVICE_NAME} -n 50 --no-pager"
  return 1
}

# ---------- 数据库备份 ----------
backup_db() {
  [ -f "$APP_DIR/wms.db" ] || return 0
  mkdir -p "$APP_DIR/backup"
  local stamp out
  stamp="$(date +%Y%m%d_%H%M%S)"
  out="$APP_DIR/backup/wms_pre_upgrade_${stamp}.db"
  if "$APP_DIR/venv/bin/python" - "$APP_DIR/wms.db" "$out" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as s, sqlite3.connect(sys.argv[2]) as d:
    s.backup(d)
PY
  then
    ok "数据库已备份：$out"
  else
    warn "数据库备份失败（继续更新）"
  fi
}

# ---------- install ----------
cmd_install() {
  parse_args "$@"          # 先校验参数，参数错误比环境问题更应该立刻提示
  require_non_root_note
  require_user_systemd

  printf "\n=== WMS 安装（普通用户 / systemd --user）===\n  用户：%s\n  目录：%s\n  端口：%s\n\n" \
    "$(id -un)" "$APP_DIR" "$PORT"

  check_deps

  if [ -d "$APP_DIR/.git" ]; then
    info "检测到已有安装，改用更新流程 ..."
    cmd_update
    return 0
  fi

  if [ -n "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]; then
    die "目录 $APP_DIR 非空且不是 WMS git 仓库。请清理或换 --app-dir。"
  fi

  info "克隆源码 ..."
  git clone --quiet --depth 1 "$REPO_URL" "$APP_DIR" || die "git clone 失败，请检查网络"
  ok "源码已克隆"

  info "创建虚拟环境并安装依赖 ..."
  python3 -m venv "$APP_DIR/venv"
  "$APP_DIR/venv/bin/pip" install -q --upgrade pip
  pip_install "$APP_DIR/venv/bin/python"
  ok "依赖安装完成"

  if [ ! -f "$APP_DIR/.secret_key" ]; then
    "$APP_DIR/venv/bin/python" -c 'import secrets;print(secrets.token_hex(32))' > "$APP_DIR/.secret_key"
    chmod 600 "$APP_DIR/.secret_key"
    ok "已生成随机会话密钥"
  fi

  mkdir -p "$APP_DIR/logs" "$APP_DIR/backup"

  write_user_unit
  systemctl --user enable "$SERVICE_NAME" >/dev/null 2>&1 || warn "enable 失败（不影响本次启动）"
  systemctl --user restart "$SERVICE_NAME"
  try_enable_linger
  open_firewall

  cat > "$CONF_FILE" <<CONF
APP_DIR=${APP_DIR}
PORT=${PORT}
SERVICE_NAME=${SERVICE_NAME}
REPO_URL=${REPO_URL}
INSTALLED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
CONF

  if health_check; then
    printf "\n${c_grn}=== 安装完成 ===${c_reset}\n"
    printf "  访问地址：http://<服务器IP>:%s\n" "$PORT"
    printf "  默认账号：admin / admin001 （请登录后立即修改）\n"
    printf "  服务管理：systemctl --user {start|stop|restart|status} %s\n" "$SERVICE_NAME"
    printf "  实时日志：journalctl --user -u %s -f\n\n" "$SERVICE_NAME"
  else
    die "服务未正常响应，安装未完成"
  fi
}

# ---------- update ----------
cmd_update() {
  # 若未解析过参数，先确定 APP_DIR 以定位配置
  if [ -z "$CONF_FILE" ] || [ ! -f "$CONF_FILE" ]; then
    parse_args "$@"
  fi
  [ -f "$CONF_FILE" ] || die "未找到 ${CONF_FILE}，请先执行 install"
  # shellcheck disable=SC1090
  . "$CONF_FILE"
  CONF_FILE="${APP_DIR}/.install.conf"
  require_user_systemd

  printf "\n=== WMS 更新 ===\n  目录：%s\n  端口：%s\n\n" "$APP_DIR" "$PORT"
  [ -d "$APP_DIR/.git" ] || die "$APP_DIR 不是 git 仓库"

  backup_db

  info "拉取最新代码 ..."
  local before after
  before="$(git -C "$APP_DIR" rev-parse HEAD)"
  if ! git -C "$APP_DIR" pull --ff-only --quiet; then
    warn "git pull 失败（可能有本地改动），尝试 stash 后重试 ..."
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

  write_user_unit
  systemctl --user restart "$SERVICE_NAME"

  if health_check; then
    printf "\n${c_grn}=== 更新完成 ===${c_reset}\n  ${before:0:8} -> ${after:0:8}\n\n"
  else
    warn "更新后服务未响应，查看：journalctl --user -u ${SERVICE_NAME} -n 50 --no-pager"
    exit 1
  fi
}

# ---------- uninstall ----------
cmd_uninstall() {
  if [ -z "$CONF_FILE" ] || [ ! -f "$CONF_FILE" ]; then
    parse_args "$@"
  fi
  if [ -f "$CONF_FILE" ]; then
    # shellcheck disable=SC1090
    . "$CONF_FILE"
    CONF_FILE="${APP_DIR}/.install.conf"
  else
    warn "未找到安装配置，使用默认目录 $APP_DIR"
  fi
  require_user_systemd

  printf "\n=== WMS 卸载 ===\n  目录：%s\n  端口：%s\n\n" "$APP_DIR" "$PORT"

  if [ "$PURGE" -eq 0 ] && [ -f "$APP_DIR/wms.db" ]; then
    local stamp keep
    stamp="$(date +%Y%m%d_%H%M%S)"
    keep="$HOME/wms_data_${stamp}"
    mkdir -p "$keep"
    if "$APP_DIR/venv/bin/python" - "$APP_DIR/wms.db" "$keep/wms.db" 2>/dev/null <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as s, sqlite3.connect(sys.argv[2]) as d:
    s.backup(d)
PY
    then
      ok "数据库已保存到：$keep/wms.db"
    else
      warn "数据库备份失败；删除目录会丢失数据"
      read -r -p "仍要继续吗？[y/N] " ans
      [[ "$ans" =~ ^[Yy]$ ]] || { info "已取消"; exit 1; }
    fi
  elif [ "$PURGE" -eq 1 ]; then
    warn "--purge：数据库与备份将彻底删除"
  fi

  info "停止并禁用服务 ..."
  systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
  systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
  rm -f "${USER_UNIT_DIR}/${SERVICE_NAME}.service"
  systemctl --user daemon-reload

  command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active \
    && { sudo -n ufw delete allow "${PORT}/tcp" >/dev/null 2>&1 || true; }

  [ -d "$APP_DIR" ] && { info "删除目录 $APP_DIR ..."; rm -rf "$APP_DIR"; }

  printf "\n${c_grn}=== 卸载完成 ===${c_reset}\n"
  if [ "$PURGE" -eq 0 ]; then
    printf "  数据库已备份保留在 %s/\n" "$HOME/wms_data_*"
  else
    printf "  --purge 模式：数据已彻底删除，不可恢复\n"
  fi
  printf "  注意：系统包（python3/git 等）未卸载；linger 若已开启会保留\n\n"
}

# ---------- help ----------
cmd_help() {
  cat <<'USAGE'
WMS 物料管理系统 —— 普通用户一键安装 / 更新 / 卸载
  https://github.com/dakerclaw/wms

用法：
  ./install-user.sh install  [--port 5000] [--app-dir ~/apps/wms]
  ./install-user.sh update
  ./install-user.sh uninstall [--purge]

命令：
  install     全新安装（已存在安装则自动转为 update）
  update      拉取最新代码并重启（自动备份数据库）
  uninstall   卸载服务与应用目录
              --purge  同时彻底删除数据库与备份（默认保留到 ~/wms_data_<时间戳>/）

参数：
  --port N      监听端口，默认 5000
  --app-dir P   应用目录，默认 ~/apps/wms

一行命令安装：
  curl -fsSL https://raw.githubusercontent.com/dakerclaw/wms/main/install-user.sh | bash -s -- install

特点：
  - 应用装在当前用户家目录，不需要 root 写 /opt
  - 服务用 systemd --user 守护：systemctl --user {start,stop,restart,status} wms
  - 日志：journalctl --user -u wms -f
  - 仅「安装系统依赖」与「启用 linger」可能需要 sudo 密码
  - 建议执行一次  sudo loginctl enable-linger $USER  以便退出登录后继续运行、开机自启

要求：systemd + apt 系发行版（Debian/Ubuntu）
USAGE
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
