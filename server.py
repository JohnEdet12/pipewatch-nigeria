"""PipeWatch Nigeria local server.

Serves the dashboard and keeps data.json in step with the NOSDRA Oil Spill Monitor:
it syncs on start-up, then every --interval hours, and on demand from the page (POST /api/refresh).

    python server.py --port 8095 --interval 6
"""
import argparse, datetime, json, threading, time, traceback
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pipeline

HERE = Path(__file__).resolve().parent
STATE = {'syncing': False, 'last_ok': None, 'last_try': None, 'error': None, 'next': None, 'interval_h': 6,
         'version': None, 'records': None, 'max_date': None, 'added': 0}
LOCK = threading.Lock()


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_meta():
    p = HERE / 'data.json'
    if p.exists():
        try:
            m = json.loads(p.read_text(encoding='utf8'))['meta']
            STATE.update(version=m.get('version'), records=m.get('records'), max_date=m.get('max_date'),
                         last_ok=m.get('synced_at'))
        except Exception:
            pass


def sync(refresh_osm=False):
    if not LOCK.acquire(blocking=False):
        return
    STATE.update(syncing=True, last_try=now())
    try:
        before = STATE['records']
        m = pipeline.run(refresh_osm=refresh_osm)
        STATE.update(version=m['version'], records=m['records'], max_date=m['max_date'], last_ok=m['synced_at'],
                     error=None, added=(m['records'] - before) if before else 0)
        print(f"[sync] ok {m['records']} spills, latest incident {m['max_date']}", flush=True)
    except Exception as e:
        STATE['error'] = f'{type(e).__name__}: {e}'
        print('[sync] failed', STATE['error'], flush=True)
        traceback.print_exc()
    finally:
        STATE['syncing'] = False
        LOCK.release()


def loop(interval_h):
    while True:
        sync()
        STATE['next'] = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=interval_h)).strftime('%Y-%m-%dT%H:%M:%SZ')
        time.sleep(interval_h * 3600)


class Handler(SimpleHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/status'):
            return self._json(STATE)
        if self.path.split('?')[0] not in ('/', '/index.html', '/data.json'):
            return self.send_error(404)
        super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/refresh'):
            if not STATE['syncing']:
                threading.Thread(target=sync, daemon=True).start()
            return self._json({'started': True})
        self.send_error(404)

    def end_headers(self):
        if self.path.split('?')[0].endswith('data.json'):
            self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        if '/api/status' not in str(args[0] if args else ''):
            super().log_message(fmt, *args)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8095)
    ap.add_argument('--interval', type=float, default=6, help='hours between NOSDRA syncs')
    a = ap.parse_args()
    STATE['interval_h'] = a.interval
    load_meta()
    threading.Thread(target=loop, args=(a.interval,), daemon=True).start()
    print(f'PipeWatch Nigeria on http://{a.host}:{a.port} (NOSDRA sync every {a.interval:g} h)', flush=True)
    ThreadingHTTPServer((a.host, a.port), partial(Handler, directory=str(HERE))).serve_forever()
