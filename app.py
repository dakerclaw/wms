from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
import sqlite3
import os
import hashlib
import datetime
import json
import csv
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = 'wms_secret_key_2026'
CORS(app, resources={r"/api/*": {"origins": "*"}})
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

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
    # 入库单表
    c.execute('''CREATE TABLE IF NOT EXISTS inbound_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_no TEXT UNIQUE NOT NULL,
        factory TEXT NOT NULL,
        equipment TEXT NOT NULL,
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
    conn.commit()

    # 初始化管理员账号
    pwd = hashlib.md5('st999777'.encode()).hexdigest()
    try:
        c.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                  ('shangtai', pwd, 'admin'))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()


def hash_pwd(pwd):
    return hashlib.md5(pwd.encode()).hexdigest()


def gen_order_no(prefix):
    now = datetime.datetime.now()
    return f"{prefix}{now.strftime('%Y%m%d%H%M%S%f')[:18]}"


def require_login(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'code': 401, 'msg': '未登录'}), 401
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    from functools import wraps
    @wraps(f)
    @require_login
    def decorated(*args, **kwargs):
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


@app.route('/templates/<path:filename>')
def serve_template(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'templates'), filename)


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
        if user and user['username'] == 'shangtai':
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


# ===== 入库 =====
@app.route('/api/inbound', methods=['POST'])
@require_login
def create_inbound():
    data = request.json
    if not data:
        return jsonify({'code': 400, 'msg': '请求格式错误'})
    factory = data.get('factory', '')
    equipment = data.get('equipment', '')
    items = data.get('items', [])
    if not factory or not equipment or not items:
        return jsonify({'code': 400, 'msg': '参数不完整'})
    order_no = gen_order_no('RK')
    conn = get_db()
    try:
        conn.execute("INSERT INTO inbound_orders (order_no, factory, equipment, operator) VALUES (?,?,?,?)",
                     (order_no, factory, equipment, session['user']))
        for idx, item in enumerate(items):
            list_no = f"{item['batch_no']}-{equipment}-{item['package_no']}"
            conn.execute(
                "INSERT INTO inbound_items (order_no, seq, batch_no, equipment, package_no, list_no, weight) VALUES (?,?,?,?,?,?,?)",
                (order_no, idx + 1, item['batch_no'], equipment, item['package_no'], list_no, item['weight'])
            )
        conn.commit()
        return jsonify({'code': 200, 'msg': '入库成功', 'order_no': order_no})
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

    sql = '''SELECT o.order_no, o.factory, o.equipment, o.operator, o.created_at,
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


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=False)
