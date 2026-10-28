import json, sqlite3, threading, time, uuid, logging
from pathlib import Path
from fastapi import HTTPException, Request
from pydantic import ValidationError

DB = Path(__file__).with_name('jobs.sqlite3')
log = logging.getLogger('yt-jobs')
worker_lock = threading.Lock()
wakeup = threading.Event()

def connect():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c

def setup():
    with connect() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, url TEXT NOT NULL, language TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL, progress REAL, title TEXT, result TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL)''')
        c.execute("UPDATE jobs SET status='queued', stage='Ожидает повторного запуска после перезапуска сервиса', progress=NULL, updated=? WHERE status='running'", (time.time(),))
    threading.Thread(target=worker, daemon=True, name='transcription-queue').start()
    wakeup.set()

def update(job_id, **values):
    values['updated'] = time.time()
    with connect() as c:
        c.execute('UPDATE jobs SET ' + ','.join(k+'=?' for k in values) + ' WHERE id=?', (*values.values(), job_id))

def run_job(job):
    from app import extract_info, pick_caption_track, fetch_caption_json3, transcribe_with_whisper
    id = job['id']
    last_stage, last_time = None, 0.0
    def report(stage, progress=None):
        nonlocal last_stage, last_time
        now = time.monotonic()
        if stage != last_stage or now - last_time >= 2:
            update(id, stage=stage, progress=progress)
            last_stage, last_time = stage, now
    report('Получение информации о видео')
    info = extract_info(job['url'])
    update(id, title=info.get('title') or 'Транскрипт')
    report('Поиск субтитров')
    selected = pick_caption_track(info, job['language'])
    result = None
    if selected:
        source, code, fmt = selected
        report('Загрузка субтитров')
        segments = fetch_caption_json3(fmt)
        if segments:
            result = {'title': info.get('title') or 'Транскрипт', 'source': 'captions', 'captionType': source, 'language': code, 'duration': info.get('duration'), 'segments': segments, 'text': ' '.join(s['text'] for s in segments)}
    if result is None:
        result = transcribe_with_whisper(job['url'], info, job['language'], job['model'], report=report)
    if not (result.get('text') or '').strip():
        raise RuntimeError('Речь не обнаружена или транскрипт пуст')
    update(id, status='done', stage='Готово', progress=100, result=json.dumps(result, ensure_ascii=False), error=None)

def worker():
    while True:
        try:
            with connect() as c:
                row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row:
                    job = dict(row)
                    c.execute("UPDATE jobs SET status='running', stage='Подготовка', updated=? WHERE id=? AND status='queued'", (time.time(),job['id']))
                else:
                    job = None
            if job:
                try:
                    run_job(job)
                except Exception as exc:
                    log.exception('Job %s failed', job['id'])
                    update(job['id'], status='failed', stage='Ошибка', progress=None, error=str(exc)[:2000])
                continue
        except Exception:
            log.exception('Queue error')
        wakeup.wait(5)
        wakeup.clear()

def public(row, include_result=False):
    d = dict(row)
    raw = d.pop('result')
    if include_result:
        d['result'] = json.loads(raw) if raw else None
    return d

def install(app, require_session, RequestModel, host_ok):
    @app.on_event('startup')
    def startup(): setup()
    @app.post('/api/ui/jobs', status_code=202)
    def create(payload: RequestModel, request: Request):
        require_session(request)
        url = str(payload.url)
        if not host_ok(url): raise HTTPException(400, 'Поддерживаются только ссылки YouTube')
        if payload.model not in {'base','small','medium'} or payload.language not in {'auto','ru','en'}:
            raise HTTPException(400, 'Неподдерживаемые параметры')
        job_id = uuid.uuid4().hex
        now = time.time()
        with connect() as c:
            c.execute('INSERT INTO jobs (id,url,language,model,status,stage,created,updated) VALUES (?,?,?,?,?,?,?,?)', (job_id,url,payload.language,payload.model,'queued','В очереди',now,now))
        wakeup.set()
        return {'id':job_id}
    @app.get('/api/ui/jobs')
    def listing(request: Request):
        require_session(request)
        with connect() as c:
            rows = c.execute('SELECT * FROM jobs ORDER BY created DESC LIMIT 200').fetchall()
        return [public(row) for row in rows]
    @app.get('/api/ui/jobs/{job_id}')
    def detail(job_id: str, request: Request):
        require_session(request)
        with connect() as c:
            row = c.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row: raise HTTPException(404, 'Задача не найдена')
        return public(row, True)
