import os, sys, tempfile, time, shutil
from pathlib import Path
root=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)
    shutil.copy(root/'app.py',p/'app.py')
    shutil.copy(root/'jobs.py',p/'jobs.py')
    sys.path.insert(0,str(p))
    os.environ['YT_SESSION_SECRET']='testsecret'
    import app, jobs
    from fastapi.testclient import TestClient
    app.extract_info=lambda url:{'title':'Тест видео','duration':10}
    app.pick_caption_track=lambda info,lang: ('subtitles','ru',{})
    app.fetch_caption_json3=lambda fmt:[{'start':0,'end':1,'text':'Привет'}]
    try:
        with TestClient(app.app) as client:
            assert client.get('/api/ui/jobs').status_code==401
            cookie=app._make_session('test')
            client.cookies.set(app.SESSION_COOKIE,cookie)
            assert client.post('/api/ui/jobs',json={'url':'https://example.com/x'}).status_code==400
            r=client.post('/api/ui/jobs',json={'url':'https://youtu.be/abcdefghijk'})
            assert r.status_code==202, r.text
            job_id=r.json()['id']
            for i in range(100):
                job=client.get('/api/ui/jobs/'+job_id).json()
                if job['status']=='done': break
                time.sleep(.05)
            assert job['status']=='done',job
            assert job['title']=='Тест видео' and job['result']['text']=='Привет',job
            assert client.get('/api/ui/jobs').json()[0]['status']=='done'
            with jobs.connect() as c:
                c.execute("UPDATE jobs SET status='running' WHERE id=?",(job_id,))
            jobs.setup()
            for i in range(100):
                job=client.get('/api/ui/jobs/'+job_id).json()
                if job['status']=='done': break
                time.sleep(.05)
            assert job['status']=='done', job
        print('PASS: authentication, validation, queue, persistence, result and restart recovery')
    except Exception:
        raise
