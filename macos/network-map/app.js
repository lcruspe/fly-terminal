(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const svgNS = 'http://www.w3.org/2000/svg';
  const host = location.hostname;
  const local = ['127.0.0.1','localhost','192.168.1.201'].includes(host);
  const commander = host === 'commander-hub.tail1c55c5.ts.net';
  const point = {
    internet:[115,95],router:[388,240],mac:[660,354],linux:[966,364],
    openwrt:[365,490],sprut:[116,604],mate:[1100,118],iphone:[1262,300],
    macbook:[1246,556],commander:[963,629],oracle:[684,85]
  };
  const symbol = {cloud:'☁',router:'⌁',desktop:'⌘',linux:'◆',home:'⌂',laptop:'▣',mobile:'▯',server:'▤'};
  const labels = {up:'В сети',degraded:'Частично',down:'Недоступен',unknown:'Нет данных'};
  const shortStatus = {up:'Работает',degraded:'Проблема',down:'Недоступен',unknown:'Нет данных'};
  const colors = {up:'#8ad6b2',degraded:'#f2bf79',down:'#ed8586',unknown:'#798693'};
  let state = null;
  let history = {events:[],trends:{}};
  let selection = 'mac';
  let filter = 'all';
  let zoom = 1;
  let loading = false;
  let lastConnection = null;
  let firstMap = true;
  const safe = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const time = stamp => {try{return new Date(stamp).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});}catch{return '—';}};
  const fmtDate = stamp => {try{return new Date(stamp*1000).toLocaleString('ru-RU',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});}catch{return '—';}};
  const displayIp = addr => addr?.startsWith('Lima VM')?'LIMA · TAILNET':addr;
  function terminalBase() {
    if(commander)return location.origin+'/fly/';
    if(local)return `http://${host}:8081/`;
    return `${location.protocol}//${host}:8443/`;
  }
  function hrefFor(link) {
    if(!link)return '';
    if(link === 'terminal' || link === 'desktop' || link === 'browser') {
      const base = terminalBase();
      return base+(link==='desktop'?'desktop/webrtc.html?path=desktop-stream-ws&autoconnect=true':link==='browser'?'browser/':'');
    }
    if(link==='sprut')return local?`http://${host}:8082/`:`https://${host}:10000/`;
    if(link==='openwrt') {
      if(host==='mac-gateway.tail1c55c5.ts.net')return `https://${host}:10443/cgi-bin/luci/`;
      if(commander)return location.origin+'/cgi-bin/luci/';
      if(local)return 'http://192.168.1.115/cgi-bin/luci/';
      return '';
    }
    if(link==='oracle')return 'https://129-158-49-130.sslip.io/';
    if(link[0]==='/')return link;
    return '';
  }
  function createSVG(tag, attrs={}, text='') {
    const el = document.createElementNS(svgNS,tag);
    Object.entries(attrs).forEach(([key,value])=>el.setAttribute(key,String(value)));
    if(text)el.textContent=text;
    return el;
  }
  function centroid(node) {const p=point[node];return {x:p[0]+94,y:p[1]+43};}
  function route(a,b) {
    const s=centroid(a),t=centroid(b),dx=t.x-s.x,dy=t.y-s.y;
    const intersect=(v,ux,uy) => {
      const len=Math.min(Math.abs(90/(ux||1e-6)),Math.abs(40/(uy||1e-6)));
      return {x:v.x+ux*len,y:v.y+uy*len};
    };
    const norm=Math.hypot(dx,dy)||1;
    const p=intersect(s,dx/norm,dy/norm),q=intersect(t,-dx/norm,-dy/norm);
    const vx=q.x-p.x,vy=q.y-p.y;
    const bend=Math.max(25,Math.min(90,Math.abs(vx)*.17));
    const curve=`M ${p.x} ${p.y} C ${p.x+Math.sign(vx)*bend} ${p.y}, ${q.x-Math.sign(vx)*bend} ${q.y}, ${q.x} ${q.y}`;
    return {curve,middle:{x:(p.x+q.x)/2,y:(p.y+q.y)/2}};
  }
  function renderGraph() {
    if(!state)return;
    const edgeLayer=$('edgeLayer'),nodeLayer=$('nodeLayer');
    edgeLayer.replaceChildren();nodeLayer.replaceChildren();
    for(const [id,radius] of [['mac',190],['linux',162]]){
      const c=centroid(id);
      edgeLayer.append(createSVG('circle',{cx:c.x,cy:c.y,r:radius,stroke:'#5c877b','stroke-opacity':'.13','stroke-dasharray':'4 10',fill:'none','stroke-width':1.2}));
      edgeLayer.append(createSVG('circle',{cx:c.x,cy:c.y,r:radius+35,stroke:'#6d9a87','stroke-opacity':'.06',fill:'none','stroke-width':1}));
    }
    state.edges.forEach(edge=>{
      const {curve,middle}=route(edge.source,edge.target);
      edgeLayer.append(createSVG('path',{d:curve,class:`edge-track ${edge.kind} ${edge.status}`,fill:'none'}));
      edgeLayer.append(createSVG('path',{d:curve,class:`edge-flow ${edge.kind} ${edge.status==='up'?'':'inactive'}`,fill:'none'}));
      if(['virtual','relay','uplink'].includes(edge.kind)){
        edgeLayer.append(createSVG('text',{x:middle.x,y:middle.y-13,class:'edge-label'},edge.label));
      }
    });
    state.nodes.forEach(node=>{
      const [x,y]=point[node.id]||[0,0];
      const group=createSVG('g',{class:`node ${selection===node.id?'selected':''}`,tabindex:0,role:'button','aria-label':`${node.name} — ${labels[node.status]}`,'data-id':node.id});
      group.append(createSVG('rect',{x,y,width:188,height:86,rx:13,ry:13,class:'node-body'}));
      group.append(createSVG('rect',{x:x+12,y:y+19,width:37,height:37,rx:10,class:'node-icon-bg'}));
      group.append(createSVG('text',{x:x+30,y:y+44,class:'node-icon'},symbol[node.icon]||'◆'));
      group.append(createSVG('text',{x:x+59,y:y+31,class:'node-name'},node.name));
      const address=node.address.replace(/^Lima VM · /,'');
      group.append(createSVG('text',{x:x+59,y:y+49,class:'node-address'},address.length>23?address.slice(0,22)+'…':address));
      group.append(createSVG('circle',{cx:x+173,cy:y+13,r:5,class:`node-status ${node.status}`}));
      group.append(createSVG('line',{x1:x+13,y1:y+67,x2:x+175,y2:y+67,stroke:'#40525c','stroke-opacity':'.6'}));
      group.append(createSVG('text',{x:x+14,y:y+79,class:'node-flag'},node.zone.toUpperCase()+'  /  '+(labels[node.status]).toUpperCase()));
      group.addEventListener('click',()=>selectNode(node.id));
      group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectNode(node.id);}});
      nodeLayer.append(group);
    });
  }
  function statusTag(status) {return `<span class="state-pill ${safe(status)}"><i class="status-dot ${safe(status)}"></i>${safe(labels[status]||'Нет данных')}</span>`;}
  function nodeLink(id){return hrefFor(({mac:'/',linux:'/',openwrt:'openwrt',sprut:'sprut',oracle:'oracle'})[id]||'');}
  function scrollToSelected(){
    const viewport=$('mapScroller'),svg=$('topologySvg');
    if(!point[selection]||viewport.scrollWidth<=viewport.clientWidth)return;
    const center=(point[selection][0]+94)/1460*svg.clientWidth;
    viewport.scrollTo({left:Math.max(0,center-viewport.clientWidth/2),behavior:'smooth'});
  }
  function selectNode(id) {
    selection=id;document.querySelectorAll('[data-id]').forEach(e=>e.classList.toggle('selected',e.dataset.id===id));
    renderDetail();
  }
  function renderDetail(){
    const node=state?.nodes.find(n=>n.id===selection);
    if(!node){$('detailContent').innerHTML='<div class="detail-empty">Нет данных о выбранном устройстве.</div>';return;}
    const own=state.services.filter(s=>s.node===node.id).sort((a,b)=>(a.status==='down'?0:1)-(b.status==='down'?0:1));
    const link=nodeLink(node.id);const sample=history.trends[node.id]||{};
    const total=Object.values(sample).reduce((a,b)=>a+b,0);const pct=total?Math.round(100*(sample.up||0)/total):null;
    const avglat=own.filter(s=>s.ms!=null).map(s=>s.ms);
    const lat=avglat.length?Math.round(avglat.reduce((a,b)=>a+b,0)/avglat.length):null;
    let html=`<div class="detail-main"><div class="detail-top"><div class="detail-avatar" aria-hidden="true">${safe(symbol[node.icon]||'◆')}</div><h3 class="detail-name">${safe(node.name)}</h3><span class="detail-address">${safe(node.address)}</span><div class="detail-state"><span class="status-dot ${safe(node.status)}"></span>${safe(labels[node.status])}</div><div class="detail-description">${safe(node.description)}<br>${safe(node.detail)}</div>`;
    if(node.vpn){html+=`<div class="detail-metric"><span>Amnezia VPN</span><strong style="color:${colors[node.vpn.status]}">${safe(shortStatus[node.vpn.status])}</strong></div>`;}
    html+=`<div class="detail-metric"><span>Доступность проверок · 24 ч</span><strong>${pct===null?'Нет данных':pct+'% · '+total+' проб'}</strong></div><div class="detail-metric"><span>Средняя задержка</span><strong>${lat===null?'—':lat+' мс'}</strong></div>`;
    if(node.last_seen && node.status!=='up')html+=`<div class="detail-muted">Последняя активность: ${safe(node.last_seen)}</div>`;
    if(link)html+=`<a href="${safe(link)}" class="detail-open" rel="noopener" target="_blank">Открыть сервис ↗</a>`;
    html+=`</div><div class="detail-list"><div class="detail-subheading"><span>Сервисы узла</span><small>${own.length} шт.</small></div><div class="detail-services">`;
    if(own.length)for(const s of own){html+=`<div class="detail-service"><div><div class="detail-service-title"><i class="status-dot ${safe(s.status)}"></i>${safe(s.name)}</div><div class="detail-service-note">${safe(s.note)}</div></div><div class="service-right"><div class="service-ms">${s.ms!==null?s.ms+' мс':'—'}</div><div class="service-live">${safe(s.detail)}</div></div></div>`;}
    else html+='<div class="detail-muted">Отслеживается доступность узла через Tailscale. Отдельные сервисы не настроены.</div>';
    html+='</div></div></div>';
    $('detailContent').innerHTML=html;
  }
  function updateMetrics(){
    const {summary}=state;
    $('metricNodes').textContent=summary.nodes_online;
    $('metricNodesTotal').textContent='/ '+summary.nodes_total;
    $('metricNodesSub').textContent=summary.nodes_degraded+' частично · '+summary.nodes_down+' недоступны · '+summary.nodes_unknown+' неизвестно';
    $('metricServices').textContent=summary.services_online;
    $('metricServicesTotal').textContent='/ '+summary.services_total;
    $('metricServicesSub').textContent=summary.services_total-summary.services_online+' требуют внимания';
    $('metricTailnet').textContent={up:'В сети',down:'Отключён',degraded:'Проблема',unknown:'Нет данных'}[summary.tailnet];
    $('metricVpn').textContent={up:'Защищён',down:'Отключён',degraded:'Частично',unknown:'Нет данных'}[summary.vpn];
    for(const [id,key] of [['tailIndicator','tailnet'],['vpnIndicator','vpn']])$(''+id).className='metric-indicator '+(summary[key]==='up'?'ok':summary[key]==='degraded'?'degraded':summary[key]==='down'?'offline':'neutral');
    const vpn=state.nodes.find(n=>n.id==='mac')?.vpn;
    $('vpnDescription').textContent=vpn?.detail||'Маршрут Mac Mini';
    $('lastChecked').textContent='Проверено в '+time(state.generated_at);
    $('checkDuration').textContent='Цикл '+(state.elapsed_ms/1000).toFixed(1)+' сек · интервал 30 сек';
    $('footerStamp').textContent='UTC '+state.generated_at.slice(11,19);
    $('nodesCounter').textContent=state.nodes.length;
  }
  function updateTable(){
    if(!state)return;
    const rows=state.nodes.filter(n=>filter==='all'||n.status!=='up');
    $('nodesTable').innerHTML=rows.length?rows.map(node=>{
      const sample=history.trends[node.id]||{},total=Object.values(sample).reduce((a,b)=>a+b,0);
      const pct=total?Math.round((sample.up||0)*100/total):null;
      return `<tr tabindex="0" data-select-node="${safe(node.id)}"><td><span class="cell-name"><span class="device-logo">${safe(symbol[node.icon]||'◆')}</span>${safe(node.name)}</span></td><td><span class="device-ip">${safe(displayIp(node.address))}</span></td><td class="uptime-cell"><div class="uptime-track"><div class="uptime-bar" style="width:${pct??0}%;background:${pct!==null&&pct<85?'#f2bf79':'#8fd6aa'}"></div></div><div class="uptime-note">${pct===null?'НЕТ ИСТОРИИ':pct+'% · '+total+' ПРОБ'}</div></td><td>${statusTag(node.status)}</td></tr>`;
    }).join(''):'<tr class="empty-row"><td class="table-placeholder" colspan="4">Проблемных узлов не обнаружено.</td></tr>';
    document.querySelectorAll('[data-select-node]').forEach(row=>{
      const action=()=>{selectNode(row.dataset.selectNode);scrollToSelected();window.scrollTo({top:0,behavior:'smooth'});};
      row.addEventListener('click',action);
      row.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();action();}});
    });
  }
  function renderEvents(){
    const box=$('eventList');
    if(!history.events.length){box.innerHTML='<div class="event-empty">Журнал чист.<br>Изменения состояния устройств появятся здесь автоматически.</div>';return;}
    const names=Object.fromEntries([...(state?.nodes||[]).map(n=>[n.id,n.name]),...(state?.services||[]).map(s=>['svc:'+s.id,s.name])]);
    box.innerHTML=history.events.slice(0,12).map(e=>`<div class="event-row"><span class="event-pin ${safe(e.status)}"></span><div><div class="event-name">${safe(names[e.node]||e.node)}</div><div class="event-desc">${safe(labels[e.previous]||'Неизвестно')} → ${safe(labels[e.status]||'Неизвестно')} · ${safe(e.message)}</div><div class="event-stamp">${safe(fmtDate(e.stamp))}</div></div></div>`).join('');
  }
  async function getJson(url){const ctrl=new AbortController();const timer=setTimeout(()=>ctrl.abort(),11000);try{const res=await fetch(url,{cache:'no-store',credentials:'same-origin',signal:ctrl.signal});if(!res.ok)throw Error('HTTP '+res.status);return await res.json();}finally{clearTimeout(timer);}}
  async function refresh(){
    if(loading)return;
    loading=true;$('refreshButton').classList.add('busy');
    try{
      const next=await getJson('./api/snapshot');
      if(!next.loading&&Array.isArray(next.nodes)){
        state=next;lastConnection=Date.now();updateMetrics();renderGraph();renderDetail();updateTable();
        if(firstMap){firstMap=false;requestAnimationFrame(scrollToSelected);}
        const h=await getJson('./api/history');history=h;renderEvents();renderDetail();updateTable();
        const led=document.querySelector('.live-flag .led');
        const stale=Date.now()-Date.parse(state.generated_at)>95000;
        led?.classList.toggle('stale',stale);
        led?.classList.remove('offline');
        if(stale) $('lastChecked').textContent='Данные устарели · '+time(state.generated_at);
      }
    }catch(err){$('lastChecked').textContent='Нет связи с Network Map';$('checkDuration').textContent=String(err.message||'Ошибка соединения');const led=document.querySelector('.live-flag .led');led?.classList.add('offline');led?.classList.remove('stale');}
    finally{loading=false;$('refreshButton').classList.remove('busy');}
  }
  function setZoom(next){zoom=Math.min(1.8,Math.max(.78,next));const map=$('topologySvg');map.style.width=Math.round(1320*zoom)+'px';map.style.minWidth=Math.round(1320*zoom)+'px';}
  $('zoomIn').addEventListener('click',()=>setZoom(zoom+.18));
  $('zoomOut').addEventListener('click',()=>setZoom(zoom-.18));
  $('zoomReset').addEventListener('click',()=>{setZoom(1);$('mapScroller').scrollTo({left:0,behavior:'smooth'});});
  $('topologySvg').addEventListener('wheel',e=>{if(e.ctrlKey||e.metaKey){e.preventDefault();setZoom(zoom+(e.deltaY>0?-.09:.09));}},{passive:false});
  $('refreshButton').addEventListener('click',refresh);
  document.querySelectorAll('[data-filter]').forEach(el=>el.addEventListener('click',()=>{filter=el.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===el));updateTable();}));
  setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});},1000);
  setInterval(refresh,15000);
  refresh();
})();
