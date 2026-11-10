"""Gunicorn 生产配置。

说明：建表/迁移在 app 模块加载时由 init_db() 自动完成（跨进程有文件锁），
因此多 worker 直接启动即可，无需 --preload。
日志目录需可写；用 supervisor 时其 stdout/stderr 也会落盘。
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

workers = int(os.environ.get('WMS_WORKERS', '2'))
bind = os.environ.get('WMS_BIND', '0.0.0.0:5000')
timeout = 120                      # 备份/大查询留足时间
graceful_timeout = 30
keepalive = 5
accesslog = os.path.join(LOG_DIR, 'gunicorn-access.log')
errorlog = os.path.join(LOG_DIR, 'gunicorn-error.log')
loglevel = os.environ.get('WMS_LOGLEVEL', 'info')
capture_output = True
worker_class = 'sync'
max_requests = 1000                # 定期回收 worker，避免长跑内存增长
max_requests_jitter = 200
