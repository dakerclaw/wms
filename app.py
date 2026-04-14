from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from functools import wraps
import sqlite3
import os
import hashlib
import datetime
import json
import csv
import io
import shutil
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'backup')
app = Flask(__name__)
app.secret_key = os.environ.get('WMS_SECRET_KEY', 'wms_secret_key_2026')
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
# 禁用静态文件缓存，确保每次部署后浏览器立即拉取最新 JS/CSS
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_no_cache_headers(response):
    # 只对静态文件禁用缓存
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response



DB_PATH = os.path.join(os.path.dirname(__file__), 'wms.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    # 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'user',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    # 厂区表
    c.execute('''CREATE TABLE IF NOT EXISTS factories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    # 入库单表
    c.execute('''CREATE TABLE IF NOT EXISTS inbound_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL,
        factory TEXT NOT NULL,
        equipment TEXT NOT NULL,
        package_type TEXT NOT NULL DEFAULT '标包',
        operator TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    # 入库明细表
    c.execute('''CREATE TABLE IF NOT EXISTS inbound_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT NOT NULL,
        seq INTEGER NOT NULL,
        batch_no TEXT NOT NULL,
        equipment TEXT NOT NULL,
        package_no TEXT NOT NULL,
        list_no TEXT NOT NULL,
        weight REAL NOT NULL,
        FOREIGN KEY(order_no) REFERENCES inbound_orders(order_no)
    )''')
    # 出库单表
    c.execute('''CREATE TABLE IF NOT EXISTS outbound_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL,
        factory TEXT NOT NULL,
        trip TEXT NOT NULL,
        operator TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    # 出库明细表
    c.execute('''CREATE TABLE IF NOT EXISTS outbound_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT NOT NULL,
        seq INTEGER NOT NULL,
        batch_no TEXT NOT NULL,
        equipment TEXT NOT NULL,
        package_no TEXT NOT NULL,
        list_no TEXT NOT NULL,
        weight REAL NOT NULL,
        FOREIGN KEY(order_no) REFERENCES outbound_orders(order_no)
    )''')
    conn.commit()

    # 兼容旧数据库：将 production_line 字段重命名为 equipment
    for table in ['inbound_orders', 'inbound_items', 'outbound_items']:
        cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if 'production_line' in cols and 'equipment' not in cols:
            conn.execute(f"ALTER TABLE {table} RENAME COLUMN production_line TO equipment")
    # 兼容旧数据库：inbound_orders 增加 package_type 字段
    cols = [row[1] for row in conn.execute("PRAGMA table_info(inbound_orders)").fetchall()]
    if 'package_type' not in cols:
        conn.execute("ALTER TABLE inbound_orders ADD COLUMN package_type TEXT NOT NULL DEFAULT '标包'")
    conn.commit()

    # 初始化默认厂区（仅在表为空时插入）
    factory_count = conn.execute("SELECT COUNT(*) FROM factories").fetchone()[0]
    if factory_count == 0:
        conn.executemany("INSERT INTO factories (name, sort_order) VALUES (?, ?)",
                         [('3号厂房', 1), ('10号厂房', 2)])
        conn.commit()

    # 初始化管理员账号
    pwd = hashlib.md5('admin001'.encode()).hexdigest()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ('admin', pwd, 'admin'))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def hash_pwd(pwd):
    return hashlib.md5(pwd.encode()).hexdigest()


def gen_order_no(prefix):
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    return f"{prefix}{now.strftime('%Y%m%d%H%M%S%f')[:18]}"


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'code': 401, 'msg': '未登录'}), 401
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'code': 401, 'msg': '未登录'}), 401
        if session.get('role') != 'admin':
            return jsonify({'code': 403, 'msg': '无权限'}), 403
        return f(*args, **kwargs)
    return decorated


# ===== 静态文件 =====
@app.route('/')
def index():
    return send_from_directory(os.path.join(BASE_DIR, 'templates'), 'index.html')


@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)


# ===== 认证 =====
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                            (username, hash_pwd(password))).fetchone()
        if user:
            session['user'] = username
            session['role'] = user['role']
            return jsonify({'code': 200, 'msg': '登录成功', 'role': user['role'], 'username': username})
        return jsonify({'code': 401, 'msg': '用户名或密码错误'})
    finally:
        conn.close()


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'code': 200, 'msg': '已退出'})


@app.route('/api/me', methods=['GET'])
def me():
    if 'user' in session:
        return jsonify({'code': 200, 'user': session['user'], 'role': session['role']})
    return jsonify({'code': 401, 'msg': '未登录'})


# ===== 账号管理 =====
# ==================== 厂区管理 API ====================

@app.route('/api/factories', methods=['GET'])
@require_login
def get_factories():
    """获取所有厂区列表，所有已登录用户可用"""
    conn = get_db()
    try:
        rows = conn.execute("SELECT id, name, sort_order, created_at FROM factories ORDER BY sort_order, id").fetchall()
        return jsonify({'code': 200, 'data': [dict(r) for r in rows]})
    finally:
        conn.close()


@app.route('/api/factories', methods=['POST'])
@require_admin
def add_factory():
    """新增厂区（管理员）"""
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'code': 400, 'msg': '厂区名称不能为空'})
    sort_order = data.get('sort_order', 0)
    conn = get_db()
    try:
        conn.execute("INSERT INTO factories (name, sort_order) VALUES (?, ?)", (name, sort_order))
        conn.commit()
        return jsonify({'code': 200, 'msg': '添加成功'})
    except sqlite3.IntegrityError:
        return jsonify({'code': 400, 'msg': '厂区名称已存在'})
    finally:
        conn.close()


@app.route('/api/factories/<int:fid>', methods=['PUT'])
@require_admin
def update_factory(fid):
    """修改厂区（管理员）"""
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    name = data.get('name', '').strip()
    sort_order = data.get('sort_order', 0)
    if not name:
        return jsonify({'code': 400, 'msg': '厂区名称不能为空'})
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM factories WHERE id=?", (fid,)).fetchone()
        if not row:
            return jsonify({'code': 404, 'msg': '厂区不存在'}), 404
        conn.execute("UPDATE factories SET name=?, sort_order=? WHERE id=?", (name, sort_order, fid))
        conn.commit()
        return jsonify({'code': 200, 'msg': '修改成功'})
    except sqlite3.IntegrityError:
        return jsonify({'code': 400, 'msg': '厂区名称已存在'})
    finally:
        conn.close()


@app.route('/api/factories/<int:fid>', methods=['DELETE'])
@require_admin
def delete_factory(fid):
    """删除厂区（管理员）"""
    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM factories WHERE id=?", (fid,)).fetchone()
        if not row:
            return jsonify({'code': 404, 'msg': '厂区不存在'}), 404
        conn.execute("DELETE FROM factories WHERE id=?", (fid,))
        conn.commit()
        return jsonify({'code': 200, 'msg': '删除成功'})
    finally:
        conn.close()


# ==================== 用户管理 API ====================

@app.route('/api/users', methods=['GET'])
@require_admin
def get_users():
    conn = get_db()
    try:
        users = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
        return jsonify({'code': 200, 'data': [dict(u) for u in users]})
    finally:
        conn.close()


@app.route('/api/users', methods=['POST'])
@require_admin
def add_user():
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'user')
    if not username or not password:
        return jsonify({'code': 400, 'msg': '用户名和密码不能为空'})
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                     (username, hash_pwd(password), role))
        conn.commit()
        return jsonify({'code': 200, 'msg': '添加成功'})
    except sqlite3.IntegrityError:
        return jsonify({'code': 400, 'msg': '用户名已存在'})
    finally:
        conn.close()


@app.route('/api/users/<int:uid>', methods=['PUT'])
@require_admin
def update_user(uid):
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    password = data.get('password', '').strip()
    role = data.get('role', 'user')
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            return jsonify({'code': 404, 'msg': '用户不存在'}), 404
        if user['username'] == 'admin' and role != 'admin':
            return jsonify({'code': 400, 'msg': '不能修改超级管理员的角色'}), 400
        if password:
            conn.execute("UPDATE users SET password=?, role=? WHERE id=?",
                         (hash_pwd(password), role, uid))
        else:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, uid))
        conn.commit()
        return jsonify({'code': 200, 'msg': '修改成功'})
    finally:
        conn.close()


@app.route('/api/users/<int:uid>', methods=['DELETE'])
@require_admin
def delete_user(uid):
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if user and user['username'] == 'admin':
            return jsonify({'code': 400, 'msg': '不能删除超级管理员'})
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        return jsonify({'code': 200, 'msg': '删除成功'})
    finally:
        conn.close()



@app.route('/api/users/import', methods=['POST'])
@require_admin
def import_users():
    file = request.files.get('file')
    if not file:
        return jsonify({'code': 400, 'msg': '请选择文件'})
    if not file.filename.endswith('.csv'):
        return jsonify({'code': 400, 'msg': '请上传 CSV 文件'})
    content = file.read().decode('utf-8-sig')
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    if len(rows) < 2:
        return jsonify({'code': 400, 'msg': '文件内容为空'})
    # 跳过表头
    conn = get_db()
    try:
        added = 0
        skipped = 0
        errors = []
        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 3:
                errors.append(f'第{i}行：列数不足'); continue
            username = row[0].strip()
            password = row[1].strip()
            role = row[2].strip()
            if not username or not password:
                errors.append(f'第{i}行：用户名或密码为空'); continue
            if role not in ('user', 'admin'):
                role = 'user'
            try:
                conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                             (username, hash_pwd(password), role))
                added += 1
            except sqlite3.IntegrityError:
                skipped += 1
        conn.commit()
        msg = f'导入完成：新增{added}个，跳过{skipped}个（已存在）'
        if errors:
            msg += f'，{len(errors)}个错误'
        return jsonify({'code': 200, 'msg': msg, 'added': added, 'skipped': skipped, 'errors': errors})
    finally:
        conn.close()


# ===== 概览 =====
@app.route('/api/overview', methods=['GET'])
@require_admin
def overview():
    # 始终使用北京时间 UTC+8
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    if now.hour < 8:
        today_8 = now.replace(hour=8, minute=0, second=0, microsecond=0) - datetime.timedelta(days=1)
    else:
        today_8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
    # 昨日早8点
    yesterday_8 = today_8 - datetime.timedelta(days=1)
    ib_start = yesterday_8.strftime('%Y-%m-%d %H:%M:%S')
    ib_end = today_8.strftime('%Y-%m-%d %H:%M:%S')
    # 出库统计：今日自然日 00:00 ~ 现在（与出库查询日期逻辑一致）
    ob_date = now.strftime('%Y-%m-%d')
    ob_start = ob_date + ' 00:00:00'
    ob_end = ob_date + ' 23:59:59'

    conn = get_db()
    try:
        # 入库：按设备、物料批号汇总包数和总质量
        ib_rows = conn.execute("""
            SELECT ii.equipment, ii.batch_no,
                   COUNT(*) as pkg_count,
                   ROUND(SUM(ii.weight), 2) as total_weight
            FROM inbound_items ii
            JOIN inbound_orders io ON ii.order_no = io.order_no
            WHERE io.created_at >= ? AND io.created_at < ?
            GROUP BY ii.equipment, ii.batch_no
            ORDER BY ii.equipment, ii.batch_no
        """, (ib_start, ib_end)).fetchall()

        # 入库汇总合计
        ib_total = conn.execute("""
            SELECT COUNT(*) as pkg_count, ROUND(SUM(ii.weight), 2) as total_weight
            FROM inbound_items ii
            JOIN inbound_orders io ON ii.order_no = io.order_no
            WHERE io.created_at >= ? AND io.created_at < ?
        """, (ib_start, ib_end)).fetchone()

        # 出库：按厂区、车次汇总包数和总质量
        ob_rows = conn.execute("""
            SELECT oo.factory, oo.trip,
                   COUNT(*) as pkg_count,
                   ROUND(SUM(oi.weight), 2) as total_weight
            FROM outbound_items oi
            JOIN outbound_orders oo ON oi.order_no = oo.order_no
            WHERE oo.created_at >= ? AND oo.created_at <= ?
            GROUP BY oo.factory, oo.trip
            ORDER BY oo.factory, oo.trip
        """, (ob_start, ob_end)).fetchall()

        # 出库汇总合计（车次数、总包数、总质量）
        ob_total = conn.execute("""
            SELECT COUNT(DISTINCT oo.order_no) as trip_count,
                   COUNT(*) as pkg_count,
                   ROUND(SUM(oi.weight), 2) as total_weight
            FROM outbound_items oi
            JOIN outbound_orders oo ON oi.order_no = oo.order_no
            WHERE oo.created_at >= ? AND oo.created_at <= ?
        """, (ob_start, ob_end)).fetchone()

        return jsonify({
            'code': 200,
            'ib_start': ib_start,
            'ib_end': ib_end,
            'ob_date': ob_date,
            'inbound': [dict(r) for r in ib_rows],
            'ib_total': {'pkg_count': ib_total['pkg_count'] or 0,
                         'total_weight': ib_total['total_weight'] or 0},
            'outbound': [dict(r) for r in ob_rows],
            'ob_total': {'trip_count': ob_total['trip_count'] or 0,
                         'pkg_count': ob_total['pkg_count'] or 0,
                         'total_weight': ob_total['total_weight'] or 0}
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': f'服务器错误: {str(e)}'}), 500
    finally:
        conn.close()


# ===== 入库 =====
@app.route('/api/inbound', methods=['POST'])
@require_login
def create_inbound():
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    factory = data.get('factory', '')
    equipment = data.get('equipment', '')
    package_type = data.get('package_type', '标包')
    items = data.get('items', [])
    if not factory or not equipment or not items:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    order_no = gen_order_no('RK')
    conn = get_db()
    try:
        conn.execute("INSERT INTO inbound_orders (order_no, factory, equipment, package_type, operator) VALUES (?,?,?,?,?)",
                     (order_no, factory, equipment, package_type, session['user']))
        for idx, item in enumerate(items):
            list_no = f"{item['batch_no']}-{equipment}-{item['package_no']}"
            conn.execute(
                "INSERT INTO inbound_items (order_no, seq, batch_no, equipment, package_no, list_no, weight) VALUES (?,?,?,?,?,?,?)",
                (order_no, idx + 1, item['batch_no'], equipment, item['package_no'], list_no, item['weight'])
            )
        conn.commit()
        return jsonify({'code': 200, 'msg': '入库成功', 'order_no': order_no})
    except Exception as e:
        return jsonify({'code': 500, 'msg': f'入库失败：{str(e)}'}), 500
    finally:
        conn.close()


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
             FROM inbound_orders o
             JOIN inbound_items i ON o.order_no = i.order_no
             WHERE 1=1'''
    params = []
    if date_start:
        sql += ' AND o.created_at >= ?'
        params.append(date_start)
    if date_end:
        sql += ' AND o.created_at <= ?'
        params.append(date_end)
    if factory:
        sql += ' AND o.factory = ?'
        params.append(factory)
    if equipment:
        sql += ' AND o.equipment LIKE ?'
        params.append(f'%{equipment}%')
    if batch_no:
        sql += ' AND i.batch_no LIKE ?'
        params.append(f'%{batch_no}%')
    sql += ' ORDER BY o.created_at DESC, i.seq'

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return jsonify({'code': 200, 'data': [dict(r) for r in rows]})
    finally:
        conn.close()


# ===== 出库 =====
@app.route('/api/outbound', methods=['POST'])
@require_login
def create_outbound():
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    factory = data.get('factory', '')
    trip = data.get('trip', '')
    items = data.get('items', [])
    if not factory or not trip or not items:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    order_no = gen_order_no('CK')
    conn = get_db()
    try:
        conn.execute("INSERT INTO outbound_orders (order_no, factory, trip, operator) VALUES (?,?,?,?)",
                     (order_no, factory, trip, session['user']))
        for idx, item in enumerate(items):
            list_no = f"{item['batch_no']}-{item['equipment']}-{item['package_no']}"
            conn.execute(
                "INSERT INTO outbound_items (order_no, seq, batch_no, equipment, package_no, list_no, weight) VALUES (?,?,?,?,?,?,?)",
                (order_no, idx + 1, item['batch_no'], item['equipment'], item['package_no'], list_no, item['weight'])
            )
        conn.commit()
        return jsonify({'code': 200, 'msg': '出库成功', 'order_no': order_no})
    except Exception as e:
        return jsonify({'code': 500, 'msg': f'出库失败：{str(e)}'}), 500
    finally:
        conn.close()


@app.route('/api/outbound/query', methods=['GET'])
@require_login
def query_outbound():
    date = request.args.get('date', '')
    factory = request.args.get('factory', '')
    trip = request.args.get('trip', '')
    batch_no = request.args.get('batch_no', '')

    sql = '''SELECT o.order_no, o.factory, o.trip, o.operator, o.created_at,
                    i.seq, i.batch_no, i.equipment, i.package_no, i.list_no, i.weight
             FROM outbound_orders o
             JOIN outbound_items i ON o.order_no = i.order_no
             WHERE 1=1'''
    params = []
    if date:
        sql += ' AND date(o.created_at) = ?'
        params.append(date)
    if factory:
        sql += ' AND o.factory = ?'
        params.append(factory)
    if trip:
        sql += ' AND o.trip LIKE ?'
        params.append(f'%{trip}%')
    if batch_no:
        sql += ' AND i.batch_no LIKE ?'
        params.append(f'%{batch_no}%')
    sql += ' ORDER BY o.created_at DESC, i.seq'

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return jsonify({'code': 200, 'data': [dict(r) for r in rows]})
    finally:
        conn.close()


# ===== 数据清理（管理员） =====
@app.route('/api/records/preview', methods=['GET'])
@require_admin
def preview_delete_records():
    """预览将要删除的记录数量"""
    before_date = request.args.get('before_date', '')
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    conn = get_db()
    try:
        ib_count = conn.execute(
            "SELECT COUNT(*) FROM inbound_orders WHERE created_at < ?", (before_date,)
        ).fetchone()[0]
        ob_count = conn.execute(
            "SELECT COUNT(*) FROM outbound_orders WHERE created_at < ?", (before_date,)
        ).fetchone()[0]
        return jsonify({'code': 200, 'inbound': ib_count, 'outbound': ob_count})
    finally:
        conn.close()


@app.route('/api/records/delete', methods=['POST'])
@require_admin
def delete_records():
    """删除指定日期之前的入库出库记录"""
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    before_date = data.get('before_date', '')
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    conn = get_db()
    try:
        # 先查数量
        ib_count = conn.execute(
            "SELECT COUNT(*) FROM inbound_orders WHERE created_at < ?", (before_date,)
        ).fetchone()[0]
        ob_count = conn.execute(
            "SELECT COUNT(*) FROM outbound_orders WHERE created_at < ?", (before_date,)
        ).fetchone()[0]
        # 删除明细（先删子表）
        conn.execute(
            "DELETE FROM inbound_items WHERE order_no IN "
            "(SELECT order_no FROM inbound_orders WHERE created_at < ?)", (before_date,)
        )
        conn.execute(
            "DELETE FROM inbound_orders WHERE created_at < ?", (before_date,)
        )
        conn.execute(
            "DELETE FROM outbound_items WHERE order_no IN "
            "(SELECT order_no FROM outbound_orders WHERE created_at < ?)", (before_date,)
        )
        conn.execute(
            "DELETE FROM outbound_orders WHERE created_at < ?", (before_date,)
        )
        conn.commit()
        return jsonify({
            'code': 200,
            'msg': f'删除成功：入库单 {ib_count} 条，出库单 {ob_count} 条',
            'inbound': ib_count,
            'outbound': ob_count
        })
    finally:
        conn.close()


# ===== 数据库备份管理（管理员） =====

def _ensure_backup_dir():
    os.makedirs(BACKUP_DIR, exist_ok=True)


@app.route('/api/backup/create', methods=['POST'])
@require_admin
def create_backup():
    """立即创建一次数据库备份"""
    _ensure_backup_dir()
    ts = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    filename = f'wms_{ts}.db'
    dest = os.path.join(BACKUP_DIR, filename)
    try:
        shutil.copy2(DB_PATH, dest)
        size = os.path.getsize(dest)
        return jsonify({
            'code': 200,
            'msg': f'备份成功：{filename}',
            'filename': filename,
            'size': size,
            'created_at': ts[:8]  # YYYYMMDD
        })
    except Exception as e:
        return jsonify({'code': 500, 'msg': f'备份失败：{str(e)}'})


@app.route('/api/backup/list', methods=['GET'])
@require_admin
def list_backups():
    """获取所有备份文件列表"""
    _ensure_backup_dir()
    files = sorted(glob.glob(os.path.join(BACKUP_DIR, 'wms_*.db')), reverse=True)
    result = []
    for f in files:
        name = os.path.basename(f)
        size = os.path.getsize(f)
        # 从文件名解析日期 wms_YYYYMMDD_HHMMSS.db
        try:
            date_part = name[4:12]   # YYYYMMDD
            time_part = name[13:19]  # HHMMSS
            display = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]} {time_part[:2]}:{time_part[2:4]}:{time_part[4:6]}"
        except Exception:
            display = name
        result.append({
            'filename': name,
            'display': display,
            'date': date_part if len(name) >= 12 else '',
            'size': size
        })
    return jsonify({'code': 200, 'data': result})


@app.route('/api/backup/delete', methods=['POST'])
@require_admin
def delete_backups():
    """删除指定日期之前的备份文件"""
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    before_date = data.get('before_date', '')  # YYYY-MM-DD
    if not before_date:
        return jsonify({'code': 400, 'msg': '请选择日期'})
    # 转为 YYYYMMDD 格式方便比较
    cutoff = before_date.replace('-', '')
    _ensure_backup_dir()
    files = glob.glob(os.path.join(BACKUP_DIR, 'wms_*.db'))
    deleted = 0
    errors = []
    for f in files:
        name = os.path.basename(f)
        try:
            file_date = name[4:12]  # YYYYMMDD
            if file_date < cutoff:
                os.remove(f)
                deleted += 1
        except Exception as e:
            errors.append(str(e))
    if errors:
        return jsonify({'code': 500, 'msg': f'部分删除失败：{errors[0]}', 'deleted': deleted})
    return jsonify({'code': 200, 'msg': f'已删除 {deleted} 个备份文件', 'deleted': deleted})


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
