"""WMS 物料管理系统 - Flask 后端。

时间统一使用北京时间(UTC+8)：created_at 显式写入，避免依赖服务器本地时区。
"""
from flask import Flask, request, jsonify, session, send_from_directory, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
from functools import wraps
from urllib.parse import urlparse
import sqlite3
import os
import hashlib
import datetime
import secrets
import csv
import io
import glob
import time
import logging
import threading
import contextlib

# ===================== 常量与基础工具 =====================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.environ.get('WMS_BACKUP_DIR') or os.path.join(BASE_DIR, 'backup')
DB_PATH = os.environ.get('WMS_DB_PATH') or os.path.join(BASE_DIR, 'wms.db')
BJ_TZ = datetime.timezone(datetime.timedelta(hours=8))


def now_bj():
    return datetime.datetime.now(BJ_TZ)


def now_bj_str():
    """统一的时间字符串，用于 created_at 与前端比较。"""
    return now_bj().strftime('%Y-%m-%d %H:%M:%S')


def _get_secret_key():
    """优先环境变量；否则持久化一个随机 key 到文件，保证多 worker 共享。

    绝不硬编码默认值：Flask session 是客户端签名 cookie，弱 key = 可伪造管理员。
    """
    env = os.environ.get('WMS_SECRET_KEY')
    if env:
        return env
    path = os.path.join(BASE_DIR, '.secret_key')
    if not os.path.exists(path):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(secrets.token_hex(32))
        except FileExistsError:
            pass  # 另一个 worker 已创建，下面直接读取
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


@contextlib.contextmanager
def _process_lock():
    """跨进程互斥：init_db 的建表/迁移只能有一个 worker 执行。

    POSIX 用 fcntl.flock，Windows 用 msvcrt.locking（本机开发用）。
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)
    path = os.path.join(BACKUP_DIR, '.init.lock')
    fh = open(path, 'a+')
    try:
        try:
            import fcntl
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            # Windows 的 locking 要求文件至少 1 字节
            fh.write('\0')
            fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    finally:
        fh.close()


# ---------- 密码：新哈希 + 兼容旧 MD5（登录时透明升级） ----------

def hash_pwd(pwd):
    """生成带盐哈希。Werkzeug 默认 scrypt/pbkdf2，check_password_hash 自动识别。"""
    return generate_password_hash(pwd)


def _is_legacy_hash(stored):
    return not (stored or '').startswith(('scrypt:', 'pbkdf2:'))


def verify_pwd(stored, pwd):
    """兼容历史 MD5 密码；新密码走 werkzeug。"""
    if _is_legacy_hash(stored):
        return secrets.compare_digest(stored or '', hashlib.md5(pwd.encode()).hexdigest())
    try:
        return check_password_hash(stored, pwd)
    except (ValueError, TypeError):
        return False


# ===================== App 配置 =====================

app = Flask(__name__)
app.secret_key = _get_secret_key()
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('WMS_HTTPS') == '1'
# 静态文件走协商缓存(no-cache + ETAg/Last-Modified)，既即时更新又允许 304 省流量
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# CORS 仅在显式配置时开启；同源部署无需通配放行（通配 + cookie 反而更易被利用）
_cors_origins = os.environ.get('WMS_CORS_ORIGINS')
if _cors_origins:
    CORS(app, resources={r'/api/*': {'origins': [o.strip() for o in _cors_origins.split(',')]}},
         supports_credentials=True)

logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)


@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/'):
        # no-cache 表示每次向服务器校验，内容未变时返回 304，不重复下载
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.before_request
def csrf_protect():
    """来源校验（仅跨域部署时启用）。

    仅在显式配置了 WMS_CORS_ORIGINS（可信前端域名）时才校验 Origin/Referer 是否在白名单；
    未配置时（同源 / IP:端口直连 / nginx 反代等）一律放行，避免误伤正常访问。

    说明：Host 比对式 CSRF 防护在反代或 IP 访问场景下会误伤，且本身不能真正防御 CSRF
    （应配合 SameSite=Lax Cookie，本项目已设置）；因此改为白名单式，默认宽松。
    """
    if not _cors_origins:
        return
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return
    origin = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if not origin:
        return
    netloc = urlparse(origin).netloc
    allowed = {urlparse(o).netloc for o in _cors_origins.split(',') if o.strip()}
    if netloc and netloc not in allowed:
        return jsonify({'code': 403, 'msg': '非法请求来源'}), 403


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception('Unhandled error on %s', request.path)
    return jsonify({'code': 500, 'msg': '服务器内部错误，请稍后重试'}), 500


# ===================== 数据库 =====================

def get_db():
    """每请求一个连接，缓存在 flask.g，由 teardown 统一关闭。"""
    if 'db' not in g:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 30000')
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def _conn_raw():
    """不经 flask.g 的独立连接（供模块级 init_db 使用）。"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout = 30000')
    return conn


def init_db():
    """幂等建表/迁移。模块加载时调用，生产 gunicorn 也会执行。"""
    with _process_lock():
        conn = _conn_raw()
        try:
            conn.execute('PRAGMA journal_mode = WAL')
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                created_at TEXT DEFAULT (datetime('now','+8 hours'))
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS factories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','+8 hours'))
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS inbound_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE NOT NULL,
                factory TEXT NOT NULL,
                equipment TEXT NOT NULL,
                package_type TEXT NOT NULL DEFAULT '标包',
                operator TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','+8 hours'))
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS inbound_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL,
                seq INTEGER NOT NULL,
                batch_no TEXT NOT NULL,
                equipment TEXT NOT NULL,
                package_no TEXT NOT NULL,
                list_no TEXT NOT NULL,
                weight REAL NOT NULL,
                FOREIGN KEY(order_no) REFERENCES inbound_orders(order_no) ON DELETE CASCADE
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS outbound_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT UNIQUE NOT NULL,
                factory TEXT NOT NULL,
                trip TEXT NOT NULL,
                operator TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now','+8 hours'))
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS outbound_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_no TEXT NOT NULL,
                seq INTEGER NOT NULL,
                batch_no TEXT NOT NULL,
                equipment TEXT NOT NULL,
                package_no TEXT NOT NULL,
                list_no TEXT NOT NULL,
                weight REAL NOT NULL,
                FOREIGN KEY(order_no) REFERENCES outbound_orders(order_no) ON DELETE CASCADE
            )''')
            c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                username TEXT,
                role TEXT,
                action TEXT NOT NULL,
                target TEXT,
                detail TEXT,
                ip TEXT
            )''')

            # --- 兼容旧库迁移 ---
            for table in ['inbound_orders', 'inbound_items', 'outbound_items']:
                cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()]
                if 'production_line' in cols and 'equipment' not in cols:
                    conn.execute(f'ALTER TABLE {table} RENAME COLUMN production_line TO equipment')
            cols = [r[1] for r in conn.execute('PRAGMA table_info(inbound_orders)').fetchall()]
            if 'package_type' not in cols:
                conn.execute("ALTER TABLE inbound_orders ADD COLUMN package_type TEXT NOT NULL DEFAULT '标包'")

            # --- 索引（JOIN/过滤列 + 出库去重唯一约束） ---
            c.execute('CREATE INDEX IF NOT EXISTS idx_ib_items_order ON inbound_items(order_no)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_ib_items_list ON inbound_items(list_no)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_ib_orders_created ON inbound_orders(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_ob_items_order ON outbound_items(order_no)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_ob_orders_created ON outbound_orders(created_at)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_outbound_items_list ON outbound_items(list_no)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts)')
            try:
                # 防重复出库：同一 list_no 只能出库一次
                c.execute('CREATE UNIQUE INDEX IF NOT EXISTS uq_ob_items_list ON outbound_items(list_no)')
            except sqlite3.IntegrityError:
                app.logger.warning('历史数据存在重复 list_no，跳过 uq_ob_items_list；并发防护由事务兜底')

            # --- 默认数据（幂等） ---
            if conn.execute('SELECT COUNT(*) FROM factories').fetchone()[0] == 0:
                conn.executemany('INSERT OR IGNORE INTO factories (name, sort_order, created_at) VALUES (?,?,?)',
                                 [('仓库1', 1, now_bj_str()), ('仓库2', 2, now_bj_str())])
            conn.execute(
                "INSERT OR IGNORE INTO users (username, password, role, created_at) VALUES (?,?,?,?)",
                ('admin', hash_pwd('admin001'), 'admin', now_bj_str()))
            conn.commit()
        finally:
            conn.close()


def audit(action, target='', detail=''):
    """写审计日志；失败不影响主流程。"""
    try:
        ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or '')
        ip = ip.split(',')[0].strip()
        conn = get_db()
        conn.execute(
            'INSERT INTO audit_logs (ts, username, role, action, target, detail, ip) VALUES (?,?,?,?,?,?,?)',
            (now_bj_str(), session.get('user', ''), session.get('role', ''),
             action, str(target), str(detail), ip))
        conn.commit()
    except Exception:
        app.logger.exception('写入审计日志失败')


def gen_order_no(prefix):
    """北京时间 + 微秒 + 随机后缀，避免同一时刻碰撞。"""
    return prefix + now_bj().strftime('%Y%m%d%H%M%S%f') + secrets.token_hex(2).upper()


# ===================== 鉴权装饰器 =====================

def require_role(role=None):
    def deco(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user' not in session:
                return jsonify({'code': 401, 'msg': '未登录'}), 401
            if role and session.get('role') != role:
                return jsonify({'code': 403, 'msg': '无权限'}), 403
            return f(*args, **kwargs)
        return decorated
    return deco


def require_login(f):
    return require_role()(f)


def require_admin(f):
    return require_role('admin')(f)


# 简易登录限速（进程内；多 worker 各自计数，仍显著抬高爆破成本）
_LOGIN_FAILS = {}
_LOGIN_LOCK = threading.Lock()
_LOGIN_WINDOW = 300
_LOGIN_MAX = 5


def _throttle_ok(key):
    now = time.time()
    with _LOGIN_LOCK:
        rec = _LOGIN_FAILS.get(key)
        if rec and now - rec[0] < _LOGIN_WINDOW and rec[1] >= _LOGIN_MAX:
            return False
        return True


def _throttle_fail(key):
    now = time.time()
    with _LOGIN_LOCK:
        rec = _LOGIN_FAILS.get(key)
        if not rec or now - rec[0] >= _LOGIN_WINDOW:
            _LOGIN_FAILS[key] = (now, 1)
        else:
            _LOGIN_FAILS[key] = (rec[0], rec[1] + 1)


def _throttle_reset(key):
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)


# ===================== 静态文件 =====================

@app.route('/')
def index():
    return send_from_directory(os.path.join(BASE_DIR, 'templates'), 'index.html')


# 使用 Flask 内置 static 路由（自动支持 ETag/Last-Modified 协商缓存），不再重复定义。


# ===================== 认证 =====================

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    key = (request.remote_addr or '') + '|' + username
    if not _throttle_ok(key):
        return jsonify({'code': 429, 'msg': '尝试次数过多，请 5 分钟后再试'}), 429
    conn = get_db()
    try:
        user = conn.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if not user or not verify_pwd(user['password'], password):
            _throttle_fail(key)
            audit('login_failed', username)
            return jsonify({'code': 401, 'msg': '用户名或密码错误'}), 401
        # 旧 MD5 密码透明升级为新哈希
        if _is_legacy_hash(user['password']):
            conn.execute('UPDATE users SET password=? WHERE id=?', (hash_pwd(password), user['id']))
            conn.commit()
        _throttle_reset(key)
        session['user'] = username
        session['role'] = user['role']
        audit('login', username)
        return jsonify({'code': 200, 'msg': '登录成功', 'role': user['role'], 'username': username})
    except sqlite3.Error:
        app.logger.exception('login failed')
        return jsonify({'code': 500, 'msg': '登录失败，请稍后重试'}), 500


@app.route('/api/logout', methods=['POST'])
def logout():
    audit('logout', session.get('user', ''))
    session.clear()
    return jsonify({'code': 200, 'msg': '已退出'})


@app.route('/api/me', methods=['GET'])
def me():
    if 'user' in session:
        return jsonify({'code': 200, 'user': session['user'], 'role': session['role']})
    return jsonify({'code': 401, 'msg': '未登录'}), 401


# ==================== 仓库管理 API ====================

@app.route('/api/factories', methods=['GET'])
@require_login
def get_factories():
    conn = get_db()
    rows = conn.execute('SELECT id, name, sort_order, created_at FROM factories ORDER BY sort_order, id').fetchall()
    return jsonify({'code': 200, 'data': [dict(r) for r in rows]})


@app.route('/api/factories', methods=['POST'])
@require_admin
def add_factory():
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    if not name:
        return jsonify({'code': 400, 'msg': '仓库名称不能为空'})
    sort_order = data.get('sort_order', 0)
    conn = get_db()
    try:
        conn.execute('INSERT INTO factories (name, sort_order, created_at) VALUES (?,?,?)',
                     (name, sort_order, now_bj_str()))
        conn.commit()
        audit('factory_add', name)
        return jsonify({'code': 200, 'msg': '添加成功'})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'code': 400, 'msg': '仓库名称已存在'})


@app.route('/api/factories/<int:fid>', methods=['PUT'])
@require_admin
def update_factory(fid):
    data = request.get_json(silent=True) or {}
    name = str(data.get('name', '')).strip()
    sort_order = data.get('sort_order', 0)
    if not name:
        return jsonify({'code': 400, 'msg': '仓库名称不能为空'})
    conn = get_db()
    try:
        row = conn.execute('SELECT id, name FROM factories WHERE id=?', (fid,)).fetchone()
        if not row:
            return jsonify({'code': 404, 'msg': '仓库不存在'}), 404
        conn.execute('UPDATE factories SET name=?, sort_order=? WHERE id=?', (name, sort_order, fid))
        conn.commit()
        audit('factory_update', name, f'{row["name"]} -> {name}')
        return jsonify({'code': 200, 'msg': '修改成功'})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'code': 400, 'msg': '仓库名称已存在'})


@app.route('/api/factories/<int:fid>', methods=['DELETE'])
@require_admin
def delete_factory(fid):
    conn = get_db()
    row = conn.execute('SELECT id, name FROM factories WHERE id=?', (fid,)).fetchone()
    if not row:
        return jsonify({'code': 404, 'msg': '仓库不存在'}), 404
    conn.execute('DELETE FROM factories WHERE id=?', (fid,))
    conn.commit()
    audit('factory_delete', row['name'])
    return jsonify({'code': 200, 'msg': '删除成功'})


# ==================== 用户管理 API ====================

@app.route('/api/users', methods=['GET'])
@require_admin
def get_users():
    conn = get_db()
    users = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY id').fetchall()
    return jsonify({'code': 200, 'data': [dict(u) for u in users]})


@app.route('/api/users', methods=['POST'])
@require_admin
def add_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()
    role = data.get('role', 'user')
    if role not in ('user', 'admin'):
        role = 'user'
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    conn = get_db()
    try:
        conn.execute('INSERT INTO users (username, password, role, created_at) VALUES (?,?,?,?)',
                     (username, hash_pwd(password), role, now_bj_str()))
        conn.commit()
        audit('user_add', username, f'role={role}')
        return jsonify({'code': 200, 'msg': '添加成功'})
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({'code': 400, 'msg': '用户名已存在'})


@app.route('/api/users/<int:uid>', methods=['PUT'])
@require_admin
def update_user(uid):
    data = request.get_json(silent=True) or {}
    password = str(data.get('password', '')).strip()
    role = data.get('role', 'user')
    if role not in ('user', 'admin'):
        role = 'user'
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not user:
        return jsonify({'code': 404, 'msg': '用户不存在'}), 404
    if user['username'] == 'admin' and role != 'admin':
        return jsonify({'code': 400, 'msg': '不能修改超级管理员的角色'}), 400
    if password:
        conn.execute('UPDATE users SET password=?, role=? WHERE id=?', (hash_pwd(password), role, uid))
    else:
        conn.execute('UPDATE users SET role=? WHERE id=?', (role, uid))
    conn.commit()
    audit('user_update', user['username'], ('重置密码; ' if password else '') + f'role={role}')
    return jsonify({'code': 200, 'msg': '修改成功'})


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@require_admin
def delete_user(uid):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if user and user['username'] == 'admin':
        return jsonify({'code': 400, 'msg': '不能删除超级管理员'})
    if not user:
        return jsonify({'code': 404, 'msg': '用户不存在'}), 404
    conn.execute('DELETE FROM users WHERE id=?', (uid,))
    conn.commit()
    audit('user_delete', user['username'])
    return jsonify({'code': 200, 'msg': '删除成功'})


@app.route('/api/users/import', methods=['POST'])
@require_admin
def import_users():
    file = request.files.get('file')
    if not file:
        return jsonify({'code': 400, 'msg': '请选择文件'})
    if not file.filename.lower().endswith('.csv'):
        return jsonify({'code': 400, 'msg': '请上传 CSV 文件'})
    try:
        content = file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        return jsonify({'code': 400, 'msg': '文件编码错误，请使用 UTF-8 CSV'})
    rows = list(csv.reader(io.StringIO(content)))
    if len(rows) < 2:
        return jsonify({'code': 400, 'msg': '文件内容为空'})
    conn = get_db()
    added = skipped = 0
    errors = []
    try:
        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 3:
                errors.append(f'第{i}行：列数不足'); continue
            username, password, role = row[0].strip(), row[1].strip(), row[2].strip()
            if not username or not password:
                errors.append(f'第{i}行：用户名或密码为空'); continue
            if role not in ('user', 'admin'):
                role = 'user'
            try:
                conn.execute('INSERT INTO users (username, password, role, created_at) VALUES (?,?,?,?)',
                             (username, hash_pwd(password), role, now_bj_str()))
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
        audit('user_import', '', f'新增{added} 跳过{skipped}')
    except sqlite3.Error:
        conn.rollback()
        app.logger.exception('import users failed')
        return jsonify({'code': 500, 'msg': '导入失败，请稍后重试'}), 500
    msg = f'导入完成：新增{added}个，跳过{skipped}个（已存在）'
    if errors:
        msg += f'，{len(errors)}个错误'
    return jsonify({'code': 200, 'msg': msg, 'added': added, 'skipped': skipped, 'errors': errors})


# ==================== 审计日志 API ====================

@app.route('/api/audit/logs', methods=['GET'])
@require_admin
def audit_logs():
    try:
        limit = min(max(int(request.args.get('limit', 100)), 1), 500)
    except ValueError:
        limit = 100
    conn = get_db()
    rows = conn.execute('SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    return jsonify({'code': 200, 'data': [dict(r) for r in rows]})


# ==================== 概览 ====================

@app.route('/api/overview', methods=['GET'])
@require_login
def overview():
    now = now_bj()
    if now.hour < 8:
        today_8 = now.replace(hour=8, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
    else:
        today_8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    yesterday_8 = today_8 - datetime.timedelta(days=1)
    ib_start = yesterday_8.strftime('%Y-%m-%d %H:%M:%S')
    ib_end = today_8.strftime('%Y-%m-%d %H:%M:%S')
    ob_date = now.strftime('%Y-%m-%d')
    ob_start = ob_date + ' 00:00:00'
    ob_end = ob_date + ' 23:59:59'

    conn = get_db()
    try:
        ib_rows = conn.execute('''
            SELECT ii.equipment, ii.batch_no, COUNT(*) as pkg_count,
                   ROUND(SUM(ii.weight), 2) as total_weight
            FROM inbound_items ii JOIN inbound_orders io ON ii.order_no = io.order_no
            WHERE io.created_at >= ? AND io.created_at < ?
            GROUP BY ii.equipment, ii.batch_no ORDER BY ii.equipment, ii.batch_no
        ''', (ib_start, ib_end)).fetchall()
        ib_total = conn.execute('''
            SELECT COUNT(*) as pkg_count, ROUND(SUM(ii.weight), 2) as total_weight
            FROM inbound_items ii JOIN inbound_orders io ON ii.order_no = io.order_no
            WHERE io.created_at >= ? AND io.created_at < ?
        ''', (ib_start, ib_end)).fetchone()
        ob_rows = conn.execute('''
            SELECT oo.factory, oo.trip, COUNT(*) as pkg_count,
                   ROUND(SUM(oi.weight), 2) as total_weight
            FROM outbound_items oi JOIN outbound_orders oo ON oi.order_no = oo.order_no
            WHERE oo.created_at >= ? AND oo.created_at <= ?
            GROUP BY oo.factory, oo.trip ORDER BY oo.factory, oo.trip
        ''', (ob_start, ob_end)).fetchall()
        ob_total = conn.execute('''
            SELECT COUNT(DISTINCT oo.order_no) as trip_count, COUNT(*) as pkg_count,
                   ROUND(SUM(oi.weight), 2) as total_weight
            FROM outbound_items oi JOIN outbound_orders oo ON oi.order_no = oo.order_no
            WHERE oo.created_at >= ? AND oo.created_at <= ?
        ''', (ob_start, ob_end)).fetchone()
        return jsonify({
            'code': 200, 'ib_start': ib_start, 'ib_end': ib_end, 'ob_date': ob_date,
            'inbound': [dict(r) for r in ib_rows],
            'ib_total': {'pkg_count': ib_total['pkg_count'] or 0,
                         'total_weight': ib_total['total_weight'] or 0},
            'outbound': [dict(r) for r in ob_rows],
            'ob_total': {'trip_count': ob_total['trip_count'] or 0,
                         'pkg_count': ob_total['pkg_count'] or 0,
                         'total_weight': ob_total['total_weight'] or 0}
        })
    except sqlite3.Error:
        app.logger.exception('overview failed')
        return jsonify({'code': 500, 'msg': '统计失败，请稍后重试'}), 500


# ==================== 入库 ====================

@app.route('/api/inbound', methods=['POST'])
@require_login
def create_inbound():
    data = request.get_json(silent=True) or {}
    factory = str(data.get('factory', '')).strip()
    equipment = str(data.get('equipment', '')).strip()
    package_type = str(data.get('package_type', '标包')).strip() or '标包'
    items = data.get('items') or []
    if not factory or not equipment or not items:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    # 服务端校验条目，避免脏数据。
    # 注意：每行设备可独立输入（手机端卡片布局），list_no 必须用该行自己的设备，
    # 否则与前端预览 / 出库库存校验使用的 list_no 规则不一致。
    cleaned = []
    for it in items:
        b = str(it.get('batch_no', '')).strip()
        e = str(it.get('equipment', '')).strip() or equipment
        p = str(it.get('package_no', '')).strip()
        try:
            w = float(it.get('weight', 0))
        except (ValueError, TypeError):
            w = 0
        if not b or not e or not p or w <= 0:
            return jsonify({'code': 400, 'msg': '条目批号/设备/包号不能为空且质量须大于0'})
        cleaned.append((b, e, p, w, f'{b}-{e}-{p}'))
    order_no = gen_order_no('RK')
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('INSERT INTO inbound_orders (order_no, factory, equipment, package_type, operator, created_at) '
                     'VALUES (?,?,?,?,?,?)',
                     (order_no, factory, equipment, package_type, session['user'], now_bj_str()))
        for idx, (b, e, p, w, list_no) in enumerate(cleaned, 1):
            conn.execute(
                'INSERT INTO inbound_items (order_no, seq, batch_no, equipment, package_no, list_no, weight) '
                'VALUES (?,?,?,?,?,?,?)',
                (order_no, idx, b, e, p, list_no, w))
        conn.commit()
        audit('inbound_create', order_no, f'{len(cleaned)}包 {factory}/{equipment}')
        return jsonify({'code': 200, 'msg': '入库成功', 'order_no': order_no})
    except sqlite3.Error:
        conn.rollback()
        app.logger.exception('create inbound failed')
        return jsonify({'code': 500, 'msg': '入库失败，请稍后重试'}), 500


@app.route('/api/inbound/query', methods=['GET'])
@require_login
def query_inbound():
    date_start = request.args.get('date_start', '')
    date_end = request.args.get('date_end', '')
    factory = request.args.get('factory', '')
    equipment = request.args.get('equipment', '')
    batch_no = request.args.get('batch_no', '')
    sql = '''SELECT o.order_no, o.factory, o.equipment, o.package_type, o.operator, o.created_at,
                    i.seq, i.batch_no, i.equipment as item_line, i.package_no, i.list_no, i.weight
             FROM inbound_orders o JOIN inbound_items i ON o.order_no = i.order_no
             WHERE 1=1'''
    params = []
    if date_start:
        sql += ' AND o.created_at >= ?'; params.append(date_start)
    if date_end:
        sql += ' AND o.created_at <= ?'; params.append(date_end)
    if factory:
        sql += ' AND o.factory = ?'; params.append(factory)
    if equipment:
        sql += ' AND o.equipment LIKE ?'; params.append(f'%{equipment}%')
    if batch_no:
        sql += ' AND i.batch_no LIKE ?'; params.append(f'%{batch_no}%')
    sql += ' ORDER BY o.created_at DESC, i.seq'
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    return jsonify({'code': 200, 'data': [dict(r) for r in rows]})


# ==================== 库存查询与修改 ====================

@app.route('/api/inventory', methods=['GET'])
@require_login
def query_inventory():
    batch_no = request.args.get('batch_no', '').strip()
    equipment = request.args.get('equipment', '').strip()
    package_no = request.args.get('package_no', '').strip()
    # NOT EXISTS 配合 idx 优于 NOT IN 子查询
    sql = '''SELECT ii.id, ii.order_no, ii.seq, ii.batch_no, ii.equipment,
                    ii.package_no, ii.list_no, ii.weight,
                    io.factory, io.package_type, io.created_at as inbound_time
             FROM inbound_items ii JOIN inbound_orders io ON ii.order_no = io.order_no
             WHERE NOT EXISTS (SELECT 1 FROM outbound_items ob WHERE ob.list_no = ii.list_no)'''
    params = []
    if batch_no:
        sql += ' AND ii.batch_no LIKE ?'; params.append(f'%{batch_no}%')
    if equipment:
        sql += ' AND ii.equipment LIKE ?'; params.append(f'%{equipment}%')
    if package_no:
        sql += ' AND ii.package_no LIKE ?'; params.append(f'%{package_no}%')
    sql += ' ORDER BY ii.id DESC LIMIT 500'
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    result = [{
        'id': r['id'], 'order_no': r['order_no'], 'batch_no': r['batch_no'],
        'equipment': r['equipment'], 'package_no': r['package_no'], 'list_no': r['list_no'],
        'weight': r['weight'], 'factory': r['factory'],
        'package_type': r['package_type'] or '', 'inbound_time': r['inbound_time']
    } for r in rows]
    return jsonify({'code': 200, 'data': result, 'total': len(result)})


@app.route('/api/inventory/<int:item_id>', methods=['PUT'])
@require_login
def update_inventory(item_id):
    """修改单条入库明细；仓库修改作用于该条目所属的整个入库单。"""
    data = request.get_json(silent=True) or {}
    batch_no = str(data.get('batch_no', '')).strip()
    equipment = str(data.get('equipment', '')).strip()
    package_no = str(data.get('package_no', '')).strip()
    weight = data.get('weight')
    factory = str(data.get('factory', '')).strip()
    if not batch_no or not equipment or not package_no or weight is None or not factory:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    try:
        weight = float(weight)
        if weight < 0:
            return jsonify({'code': 400, 'msg': '质量不能为负数'})
    except (ValueError, TypeError):
        return jsonify({'code': 400, 'msg': '质量格式错误'})
    new_list_no = f'{batch_no}-{equipment}-{package_no}'
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id, order_no, list_no FROM inbound_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            conn.rollback()
            return jsonify({'code': 404, 'msg': '记录不存在'}), 404
        old_list_no, order_no = row['list_no'], row['order_no']
        if new_list_no != old_list_no:
            conflict = conn.execute('SELECT id FROM inbound_items WHERE list_no=? AND id!=?',
                                    (new_list_no, item_id)).fetchone()
            if conflict:
                conn.rollback()
                return jsonify({'code': 409, 'msg': f'清单包号 {new_list_no} 已存在，请检查是否重复'}), 409
        conn.execute('UPDATE inbound_items SET batch_no=?, equipment=?, package_no=?, list_no=?, weight=? WHERE id=?',
                     (batch_no, equipment, package_no, new_list_no, weight, item_id))
        conn.execute('UPDATE inbound_orders SET factory=? WHERE order_no=?', (factory, order_no))
        conn.commit()
        audit('inventory_update', new_list_no, f'{old_list_no} -> {new_list_no}; 仓库={factory}')
        return jsonify({'code': 200, 'msg': '修改成功', 'list_no': new_list_no})
    except sqlite3.Error:
        conn.rollback()
        app.logger.exception('update inventory failed')
        return jsonify({'code': 500, 'msg': '修改失败，请稍后重试'}), 500


# ==================== 出库 ====================

def _stock_flags(conn, list_nos):
    """批量返回 {list_no: (has_inbound, shipped)}，替代逐条 N+1 查询。"""
    unique = list(dict.fromkeys(list_nos))
    in_set, shipped_set = set(), set()
    for i in range(0, len(unique), 400):
        chunk = unique[i:i + 400]
        ph = ','.join('?' * len(chunk))
        in_set.update(r[0] for r in conn.execute(
            f'SELECT DISTINCT list_no FROM inbound_items WHERE list_no IN ({ph})', chunk))
        shipped_set.update(r[0] for r in conn.execute(
            f'SELECT DISTINCT list_no FROM outbound_items WHERE list_no IN ({ph})', chunk))
    return {ln: (ln in in_set, ln in shipped_set) for ln in unique}


def _check_stock(conn, items):
    """返回 (in_stock, no_stock)，每项附加 list_no。有库存 = 已入库且未出库。"""
    normalized = []
    for item in items:
        b = str(item.get('batch_no', '')).strip()
        e = str(item.get('equipment', '')).strip()
        p = str(item.get('package_no', '')).strip()
        d = dict(item)
        d['list_no'] = f'{b}-{e}-{p}'
        normalized.append(d)
    flags = _stock_flags(conn, [x['list_no'] for x in normalized])
    in_stock, no_stock = [], []
    for x in normalized:
        has_in, shipped = flags.get(x['list_no'], (False, False))
        (in_stock if has_in and not shipped else no_stock).append(x)
    return in_stock, no_stock


@app.route('/api/outbound/check', methods=['POST'])
@require_login
def check_outbound_stock():
    data = request.get_json(silent=True) or {}
    items = data.get('items') or []
    if not items:
        return jsonify({'code': 400, 'msg': '条目不能为空'})
    conn = get_db()
    in_stock, no_stock = _check_stock(conn, items)
    return jsonify({'code': 200, 'in_stock': in_stock, 'no_stock': no_stock,
                    'in_stock_count': len(in_stock), 'no_stock_count': len(no_stock)})


@app.route('/api/outbound', methods=['POST'])
@require_login
def create_outbound():
    """原子出库：BEGIN IMMEDIATE + INSERT..SELECT WHERE 存在入库且未被出库，杜绝重复出库。"""
    data = request.get_json(silent=True) or {}
    factory = str(data.get('factory', '')).strip()
    trip = str(data.get('trip', '')).strip()
    items = data.get('items') or []
    if not factory or not trip or not items:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        cleaned = []
        for it in items:
            b = str(it.get('batch_no', '')).strip()
            e = str(it.get('equipment', '')).strip()
            p = str(it.get('package_no', '')).strip()
            try:
                w = float(it.get('weight', 0))
            except (ValueError, TypeError):
                w = 0
            if b and e and p:
                cleaned.append((b, e, p, w, f'{b}-{e}-{p}'))
        if not cleaned:
            conn.rollback()
            return jsonify({'code': 400, 'msg': '没有有效条目'})
        order_no = gen_order_no('CK')
        conn.execute('INSERT INTO outbound_orders (order_no, factory, trip, operator, created_at) '
                     'VALUES (?,?,?,?,?)', (order_no, factory, trip, session['user'], now_bj_str()))
        in_stock, no_stock = [], []
        for b, e, p, w, list_no in cleaned:
            cur = conn.execute(
                'INSERT INTO outbound_items (order_no, seq, batch_no, equipment, package_no, list_no, weight) '
                'SELECT ?,?,?,?,?,?,? '
                'WHERE EXISTS (SELECT 1 FROM inbound_items WHERE list_no=?) '
                '  AND NOT EXISTS (SELECT 1 FROM outbound_items WHERE list_no=?)',
                (order_no, len(in_stock) + 1, b, e, p, list_no, w, list_no, list_no))
            if cur.rowcount == 1:
                in_stock.append({'batch_no': b, 'equipment': e, 'package_no': p,
                                 'weight': w, 'list_no': list_no})
            else:
                no_stock.append({'batch_no': b, 'equipment': e, 'package_no': p,
                                 'weight': w, 'list_no': list_no})
        if not in_stock:
            conn.rollback()
            return jsonify({'code': 400, 'msg': '所有条目均无库存，无法出库', 'no_stock': no_stock})
        conn.commit()
        audit('outbound_create', order_no, f'{len(in_stock)}包 跳过{len(no_stock)} {factory}/{trip}')
        return jsonify({'code': 200, 'msg': f'出库成功，共 {len(in_stock)} 条'
                        + (f'；{len(no_stock)} 条无库存已跳过' if no_stock else ''),
                        'order_no': order_no, 'in_stock_count': len(in_stock),
                        'no_stock_count': len(no_stock), 'no_stock': no_stock})
    except sqlite3.Error:
        conn.rollback()
        app.logger.exception('create outbound failed')
        return jsonify({'code': 500, 'msg': '出库失败，请稍后重试'}), 500


@app.route('/api/outbound/query', methods=['GET'])
@require_login
def query_outbound():
    date = request.args.get('date', '')
    factory = request.args.get('factory', '')
    trip = request.args.get('trip', '')
    batch_no = request.args.get('batch_no', '')
    sql = '''SELECT o.order_no, o.factory, o.trip, o.operator, o.created_at,
                    i.seq, i.batch_no, i.equipment, i.package_no, i.list_no, i.weight
             FROM outbound_orders o JOIN outbound_items i ON o.order_no = i.order_no
             WHERE 1=1'''
    params = []
    if date:
        sql += ' AND date(o.created_at) = ?'; params.append(date)
    if factory:
        sql += ' AND o.factory = ?'; params.append(factory)
    if trip:
        sql += ' AND o.trip LIKE ?'; params.append(f'%{trip}%')
    if batch_no:
        sql += ' AND i.batch_no LIKE ?'; params.append(f'%{batch_no}%')
    sql += ' ORDER BY o.created_at DESC, i.seq'
    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    return jsonify({'code': 200, 'data': [dict(r) for r in rows]})


# ==================== 数据清理（管理员） ====================

@app.route('/api/records/preview', methods=['GET'])
@require_admin
def preview_delete_records():
    before_date = request.args.get('before_date', '')
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    conn = get_db()
    ib = conn.execute('SELECT COUNT(*) FROM inbound_orders WHERE created_at < ?', (before_date,)).fetchone()[0]
    ob = conn.execute('SELECT COUNT(*) FROM outbound_orders WHERE created_at < ?', (before_date,)).fetchone()[0]
    return jsonify({'code': 200, 'inbound': ib, 'outbound': ob})


@app.route('/api/records/delete', methods=['POST'])
@require_admin
def delete_records():
    data = request.get_json(silent=True) or {}
    before_date = str(data.get('before_date', '')).strip()
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    conn = get_db()
    try:
        conn.execute('BEGIN IMMEDIATE')
        ib = conn.execute('SELECT COUNT(*) FROM inbound_orders WHERE created_at < ?', (before_date,)).fetchone()[0]
        ob = conn.execute('SELECT COUNT(*) FROM outbound_orders WHERE created_at < ?', (before_date,)).fetchone()[0]
        # 先删子表（外键 ON DELETE CASCADE 下亦可省略，但显式更稳妥）
        conn.execute('DELETE FROM inbound_items WHERE order_no IN '
                     '(SELECT order_no FROM inbound_orders WHERE created_at < ?)', (before_date,))
        conn.execute('DELETE FROM inbound_orders WHERE created_at < ?', (before_date,))
        conn.execute('DELETE FROM outbound_items WHERE order_no IN '
                     '(SELECT order_no FROM outbound_orders WHERE created_at < ?)', (before_date,))
        conn.execute('DELETE FROM outbound_orders WHERE created_at < ?', (before_date,))
        conn.commit()
        audit('records_delete', before_date, f'入库{ib} 出库{ob}')
        return jsonify({'code': 200, 'msg': f'删除成功：入库单 {ib} 条，出库单 {ob} 条',
                        'inbound': ib, 'outbound': ob})
    except sqlite3.Error:
        conn.rollback()
        app.logger.exception('delete records failed')
        return jsonify({'code': 500, 'msg': '删除失败，请稍后重试'}), 500


# ==================== 数据库备份管理（管理员） ====================

def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


@app.route('/api/backup/create', methods=['POST'])
@require_admin
def create_backup():
    """用 sqlite3 backup API 生成一致性快照（WAL 模式下直接拷贝文件会损坏）。"""
    _ensure_backup_dir()
    ts = now_bj().strftime('%Y%m%d_%H%M%S')
    filename = f'wms_{ts}.db'
    dest = os.path.join(BACKUP_DIR, filename)
    src = dst = None
    try:
        src = sqlite3.connect(DB_PATH, timeout=30)
        dst = sqlite3.connect(dest)
        src.backup(dst)          # 在线一致性备份
        dst.close(); dst = None
        size = os.path.getsize(dest)
        audit('backup_create', filename, f'{size} bytes')
        return jsonify({'code': 200, 'msg': f'备份成功：{filename}',
                        'filename': filename, 'size': size, 'created_at': ts[:8]})
    except sqlite3.Error:
        app.logger.exception('create backup failed')
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        return jsonify({'code': 500, 'msg': '备份失败，请稍后重试'}), 500
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()


@app.route('/api/backup/list', methods=['GET'])
@require_admin
def list_backups():
    _ensure_backup_dir()
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, 'wms_*.db')), reverse=True)
    result = []
    for f in files:
        name = os.path.basename(f)
        date_part = ''
        display = name
        try:
            date_part = name[4:12]      # YYYYMMDD
            time_part = name[13:19]     # HHMMSS
            display = (f'{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} '
                       f'{time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}')
        except (IndexError, ValueError):
            pass
        result.append({'filename': name, 'display': display,
                       'date': date_part if len(name) >= 12 else '',
                       'size': os.path.getsize(f)})
    return jsonify({'code': 200, 'data': result})


@app.route('/api/backup/delete', methods=['POST'])
@require_admin
def delete_backups():
    data = request.get_json(silent=True) or {}
    before_date = str(data.get('before_date', '')).strip()
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    cutoff = before_date.replace('-', '')
    _ensure_backup_dir()
    deleted, errors = 0, []
    for f in glob.glob(os.path.join(BACKUP_DIR, 'wms_*.db')):
        name = os.path.basename(f)
        try:
            if name[4:12] < cutoff:
                os.remove(f)
                deleted += 1
        except OSError as e:
            errors.append(str(e))
    audit('backup_delete', before_date, f'删除{deleted} 失败{len(errors)}')
    if errors:
        return jsonify({'code': 500, 'msg': '部分删除失败，请稍后重试', 'deleted': deleted})
    return jsonify({'code': 200, 'msg': f'已删除 {deleted} 个备份文件', 'deleted': deleted})


# ===================== 启动 =====================
# 模块级调用：gunicorn app:app 也会执行（__name__ != '__main__' 时同样建表）。
init_db()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
