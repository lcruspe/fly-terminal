#!/usr/bin/env python3
"""Network Map — read-only network observability for Mac Gateway.

stdlib only; probes have strict deadlines, no credentials, shell input or network mutations.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import http.server
import json
import os
import pathlib
import plistlib
import re
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from contextlib import closing

ROOT = pathlib.Path(__file__).resolve().parent
HOST = '127.0.0.1'
PORT = int(os.environ.get('NETWORKMAP_PORT', '7799'))
INTERVAL = max(15, int(os.environ.get('NETWORKMAP_INTERVAL', '30')))
FALLBACK = pathlib.Path.home() / 'Library/Application Support/NetworkMap'
SSD = pathlib.Path('/Volumes/MacSSD\u00a0— данные/Infrastructure/NetworkMap')
DATA = pathlib.Path(os.environ.get('NETWORKMAP_DATA_DIR', str(SSD if SSD.parent.exists() else FALLBACK)))
DB = DATA / 'monitor.sqlite3'
DATA.mkdir(parents=True, exist_ok=True)

NODE_DEFS = [
    ('internet','Интернет','Внешняя сеть','cloud','wan','Внешнее подключение'),
    ('router','Домашний роутер','192.168.1.1','router','lan','Маршрутизатор LAN'),
    ('mac','Mac Mini','192.168.1.201','desktop','lan','Основной сервер'),
    ('linux','Linux Gateway','Lima VM · ts','linux','vpn','Изолированный Tailscale'),
    ('openwrt','OpenWrt','192.168.1.115','router','lan','Raspberry Pi / VPN'),
    ('sprut','Sprut.Hub','192.168.1.100','home','lan','Умный дом'),
    ('mate','Mate','100.89.149.37','laptop','remote','Windows · источник RoomAudio'),
    ('iphone','iPhone','100.127.96.44','mobile','remote','Мобильный клиент'),
    ('macbook','MacBook','100.91.31.34','laptop','remote','Удалённый Mac'),
    ('commander','Commander Hub','100.79.10.55','server','vpn','Удалённое управление'),
    ('oracle','Oracle Relay','129.158.49.130','cloud','wan','Публичный HTTPS / SSH relay'),
]
EDGES = [
    ('internet','router','uplink','Интернет'),('router','mac','ethernet','LAN'),
    ('router','openwrt','ethernet','LAN'),('router','sprut','ethernet','LAN'),
    ('mac','linux','virtual','Lima · NAT'),('mac','oracle','relay','SSH relay'),
    ('linux','mate','tailscale','Tailnet'),('linux','iphone','tailscale','Tailnet'),
    ('linux','macbook','tailscale','Tailnet'),('linux','commander','tailscale','Tailnet'),
]
SERVICES = [
    ('internetcheck','internet','Внешний HTTPS','http','https://example.com/','','Проверка выхода в интернет'),
    ('gateway','mac','Gateway','http','http://127.0.0.1:8080/','/','Caddy · стартовая страница'),
    ('terminal','mac','Fly Terminal','http','http://127.0.0.1:8081/','terminal','Веб-терминал'),
    ('webrtc','mac','Remote Desktop','tcp','127.0.0.1:5907','desktop','WebRTC мост'),
    ('stream','mac','Desktop Stream','tcp','127.0.0.1:5905','desktop','60 FPS стример'),
    ('native','mac','Native Browser','tcp','127.0.0.1:5906','browser','Нативный стример'),
    ('chromium','mac','Chromium fallback','http','http://127.0.0.1:7690/','browser','Colima / Chromium'),
    ('roomaudio','mac','RoomAudio','http','http://127.0.0.1:8766/','/roomaudio/','Аудиоархив'),
    ('yt','mac','YT Transcript','http','http://127.0.0.1:8080/yt-transcriber/','/yt-transcriber/','Транскрипция видео'),
    ('control','mac','Gateway Control','http','http://127.0.0.1:7684/','', 'Управление сервисами'),
    ('spruthub','sprut','Sprut.Hub Web','http','http://192.168.1.100/','sprut','Панель умного дома'),
    ('luci','openwrt','OpenWrt LuCI','http','http://192.168.1.115/','openwrt','Веб-конфигурация'),
    ('routerweb','router','Router Web','tcp','192.168.1.1:80','', 'Порт маршрутизатора'),
    ('oracleweb','oracle','HTTPS Relay','http','https://129-158-49-130.sslip.io/','oracle','Публичный шлюз'),
]
PEER_IPS = {'mate':'100.89.149.37','iphone':'100.127.96.44','macbook':'100.91.31.34','commander':'100.79.10.55'}
OPENER=urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler())
LOCK = threading.RLock()
SNAPSHOT = None


def run(argv, timeout=5, env=None):
    try:
        result=subprocess.run(argv, capture_output=True,text=True,timeout=timeout,env=env)
        return result.stdout if result.returncode==0 else None
    except (OSError,subprocess.TimeoutExpired):
        return None


def probe(kind,target):
    start=time.monotonic()
    try:
        if kind=='tcp':
            host,port=target.rsplit(':',1)
            with socket.create_connection((host,int(port)),timeout=1.7): pass
            code=None
            label='TCP доступен'
        else:
            req=urllib.request.Request(target,headers={'User-Agent':'MacGateway-NetworkMap/1.0','Accept':'*/*'})
            try:
                with OPENER.open(req,timeout=2.4) as resp: code=resp.status
            except urllib.error.HTTPError as e: code=e.code
            if not (100<=code<500): raise OSError('HTTP '+str(code))
            if code in (404,410,429):
                return {'status':'degraded','ms':round((time.monotonic()-start)*1000),'detail':'HTTP '+str(code),'http':code}
            label=('Требуется вход' if code in (401,403,407) else ('Перенаправление' if code in (301,302,303,307,308) else 'Отвечает'))
        return {'status':'up','ms':round((time.monotonic()-start)*1000),'detail':label,'http':code}
    except Exception as e:
        return {'status':'down','ms':None,'detail':type(e).__name__ if not isinstance(e,urllib.error.HTTPError) else 'HTTP error','http':None}


def tailscale_state():
    plist=pathlib.Path.home()/'Library/LaunchAgents/homebrew.mxcl.colima.plist'
    try:
        with plist.open('rb') as f: colima=plistlib.load(f)['EnvironmentVariables']['COLIMA_HOME']
        home=colima.rsplit('/Colima/fly-terminal-live',1)[0]+'/Infrastructure/lima'
        env={**os.environ,'LIMA_HOME':home}
        # Tailnet status is authoritative; no redundant polling of VM list.
        raw=run(['/opt/homebrew/bin/limactl','shell','ts','--','tailscale','status','--json'],timeout=7,env=env)
        if not raw: return 'unknown',{},'Нет ответа от Tailscale в VM'
        d=json.loads(raw)
        state='up' if d.get('BackendState')=='Running' and (d.get('Self') or {}).get('Online') else 'degraded'
        peers={}
        for v in (d.get('Peer') or {}).values():
            for ip in v.get('TailscaleIPs') or []:
                peers[ip]={'online':bool(v.get('Online')),'last_seen':v.get('LastSeen'),'relay':v.get('Relay','')}
        return state,peers,d.get('BackendState','unknown')
    except (OSError,ValueError,KeyError):return 'unknown',{},'Нет данных от VM'


def amnezia_state():
    processes=run(['/usr/bin/pgrep','-fl','amneziawg-go'],timeout=2)
    route=run(['/sbin/route','-n','get','1.1.1.1'],timeout=2) or ''
    match=re.search(r'^\s*interface:\s*(\S+)',route,re.M)
    interface=match.group(1) if match else None
    if processes and interface and interface.startswith('utun'):
        return 'up','VPN · '+interface
    if processes:return 'degraded','VPN запущен · основной маршрут '+(interface or 'неизвестен')
    return 'down','Нет процесса Amnezia'


def summarize_node(items,node_id,old=None):
    ss=[s for s in items if s['node']==node_id]
    if not ss:return ('unknown','Нет проверки сервисов')
    up=sum(s['status']=='up' for s in ss)
    if up==len(ss):return ('up',f'{up} сервисов доступны')
    if up:return ('degraded',f'{up}/{len(ss)} сервисов доступны')
    if any(s['status']=='degraded' for s in ss):return ('degraded','Сервисы отвечают с ошибками')
    return ('down','Сервисы не отвечают')


def db_connect():
    conn=sqlite3.connect(DB,timeout=5)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS samples (stamp INTEGER, node TEXT, status TEXT, ms INTEGER, PRIMARY KEY(stamp,node))')
        conn.execute('CREATE TABLE IF NOT EXISTS events (stamp INTEGER, node TEXT, previous TEXT, status TEXT, message TEXT)')
        conn.execute('CREATE INDEX IF NOT EXISTS ix_samples_stamp ON samples(stamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS ix_events_stamp ON events(stamp)')
        return conn
    except BaseException:
        conn.close()
        raise


def record(snapshot,previous):
    now=int(time.time())
    try:
        with closing(db_connect()) as conn, conn:
            for n in snapshot['nodes']:
                conn.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?,?)',(now,n['id'],n['status'],n.get('latency_ms')))
                prev=next((x for x in previous['nodes'] if x['id']==n['id']),None) if previous else None
                if prev and prev['status'] !=n['status'] and not (prev['status']=='unknown' and n['status']=='up'):
                    conn.execute('INSERT INTO events VALUES (?,?,?,?,?)',(now,n['id'],prev['status'],n['status'],n.get('detail','')[:200]))
            # Record individual service availability as well as overall node state.
            for service in snapshot['services']:
                key='svc:'+service['id']
                conn.execute('INSERT OR REPLACE INTO samples VALUES (?,?,?,?)',(now,key,service['status'],service.get('ms')))
                prev=next((x for x in previous['services'] if x['id']==service['id']),None) if previous else None
                if prev and prev['status']!=service['status']:
                    conn.execute('INSERT INTO events VALUES (?,?,?,?,?)',(now,key,prev['status'],service['status'],service['detail'][:200]))
            conn.execute('DELETE FROM samples WHERE stamp < ?', (now-86400*7,))
            conn.execute('DELETE FROM events WHERE stamp < ?', (now-86400*30,))
    except (sqlite3.Error,OSError) as e: print('history warning:',type(e).__name__,flush=True)


def capture():
    started=time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        work=[pool.submit(probe,kind,target) for _,_,_,kind,target,_,_ in SERVICES]
        checks=[task.result() for task in work]
        route_task=pool.submit(probe,'tcp','192.168.1.1:53')
        # Touch DNS port only if HTTP management unavailable, never alter router.
        route_extra=route_task.result()
    services=[]
    for spec,info in zip(SERVICES,checks):
        sid,node,label,kind,target,link,note=spec
        services.append({'id':sid,'node':node,'name':label,'link':link,'note':note,**info})
    nodes=[]
    for identifier,label,address,icon,zone,note in NODE_DEFS:
        status,detail=summarize_node(services,identifier)
        if identifier=='router' and status=='down' and route_extra['status']=='up':status='up';detail='DNS отвечает · веб-порт закрыт'
        if identifier=='mac':status='up' if status!='down' else 'degraded';detail='Главный сервер · '+detail
        nodes.append({'id':identifier,'name':label,'address':address,'icon':icon,'zone':zone,'description':note,'status':status,'detail':detail,'latency_ms':None})
    index={n['id']:n for n in nodes}
    linux,peers,linux_detail=tailscale_state()
    index['linux'].update(status=linux,detail='Tailscale · '+linux_detail)
    for identifier,ip in PEER_IPS.items():
        item=peers.get(ip)
        if item is None:
            index[identifier].update(status='unknown',detail='Нет данных о клиенте')
        else:
            index[identifier].update(status='up' if item['online'] else 'down',detail='Tailscale · '+('в сети' if item['online'] else 'не в сети'),last_seen=item.get('last_seen'))
    vpn,vpn_detail=amnezia_state()
    index['mac']['vpn']={'status':vpn,'detail':vpn_detail}
    if vpn!='up' and index['mac']['status']=='up':index['mac']['status']='degraded'
    links=[]
    for a,b,kind,label in EDGES:
        if kind=='tailscale':status='up' if linux=='up' and index[b]['status']=='up' else 'unknown' if index[b]['status']=='unknown' else 'down'
        elif kind=='relay':status=index['oracle']['status']
        else:
            if index[a]['status']=='down' or index[b]['status']=='down':status='down'
            elif index[a]['status']=='unknown' or index[b]['status']=='unknown':status='unknown'
            else:status='up'
        links.append({'source':a,'target':b,'kind':kind,'label':label,'status':status})
    counts=Counter(n['status'] for n in nodes)
    online_services=sum(s['status']=='up' for s in services)
    return {'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'elapsed_ms':round((time.monotonic()-started)*1000),
            'nodes':nodes,'edges':links,'services':services,
            'summary':{'nodes_online':counts['up'],'nodes_degraded':counts['degraded'],'nodes_down':counts['down'],
                       'nodes_unknown':counts['unknown'],'nodes_total':len(nodes),'services_online':online_services,
                       'services_total':len(services),'vpn':vpn,'tailnet':linux}}


def monitor():
    global SNAPSHOT
    while True:
        start=time.monotonic()
        try:
            data=capture()
            with LOCK:
                before=SNAPSHOT
                SNAPSHOT=data
            record(data,before)
        except Exception as e: print('probe warning:',repr(e)[:150],flush=True)
        time.sleep(max(1,INTERVAL-(time.monotonic()-start)))


def get_history():
    try:
        with closing(db_connect()) as c, c:
            since=int(time.time())-86400
            events=[{'stamp':r[0],'node':r[1],'previous':r[2],'status':r[3],'message':r[4]}
                    for r in c.execute('SELECT stamp,node,previous,status,message FROM events ORDER BY stamp DESC LIMIT 60')]
            rows=c.execute('SELECT node,status,COUNT(*) FROM samples WHERE stamp>=? GROUP BY node,status',(since,)).fetchall()
            trends={}
            for node,status,count in rows:trends.setdefault(node,{})[status]=count
        return {'events':events,'trends':trends,'window_hours':24}
    except (sqlite3.Error,OSError):return {'events':[],'trends':{}}


class Handler(http.server.BaseHTTPRequestHandler):
    server_version='NetworkMap/1.0'
    def response(self,code,body,content_type,cache='no-store'):
        if isinstance(body,str):body=body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control',cache)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','SAMEORIGIN')
        self.send_header('Referrer-Policy','no-referrer')
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)
    def do_GET(self):self.dispatch()
    def do_HEAD(self):self.dispatch()
    def dispatch(self):
        path=self.path.split('?',1)[0]
        if path in ('','/','/index.html'):
            path='/index.html'
        if path=='/api/snapshot':
            with LOCK: state=SNAPSHOT
            self.response(200,json.dumps(state if state else {'loading':True},ensure_ascii=False),'application/json; charset=utf-8');return
        if path=='/api/history':
            self.response(200,json.dumps(get_history(),ensure_ascii=False),'application/json; charset=utf-8');return
        if path=='/healthz':
            self.response(200,json.dumps({'ok':SNAPSHOT is not None}),'application/json');return
        assets={'/index.html':'text/html; charset=utf-8','/style.css':'text/css; charset=utf-8',
                '/app.js':'application/javascript; charset=utf-8','/favicon.svg':'image/svg+xml'}
        if path in assets:
            self.response(200,(ROOT/path.lstrip('/')).read_bytes(),assets[path],'public, max-age=300' if path!='/index.html' else 'no-store');return
        self.response(404,'Not found','text/plain; charset=utf-8')
    def do_POST(self):self.response(405,'Read-only','text/plain')
    def log_message(self,*args):pass


def main():
    threading.Thread(target=monitor,daemon=True,name='network-probes').start()
    server=http.server.ThreadingHTTPServer((HOST,PORT),Handler)
    print(f'Network Map listening on {HOST}:{PORT}; data {DB}',flush=True)
    server.serve_forever(poll_interval=.4)

if __name__=='__main__':main()
