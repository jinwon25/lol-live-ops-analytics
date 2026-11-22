'use strict';
const rolePractice = {
  TOP: {
    title: '첫 귀환 전 다음 웨이브 확인',
    action: '탑에서 첫 귀환을 누르기 전에 미니맵으로 다음 미니언 웨이브 위치를 확인한다.',
    check: '첫 귀환 직전, 다음 웨이브가 내 포탑에 닿을 때 내가 어디 있었는지 돌아보세요.',
  },
  JUNGLE: {
    title: '첫 드래곤 전에 아군 합류 확인',
    action: '첫 드래곤을 치기 전에 미니맵으로 미드와 바텀 아군이 합류할 수 있는 위치인지 확인한다.',
    check: '첫 드래곤을 시도했다면, 시작 직전 미드와 바텀 아군이 어디 있었는지 확인하세요.',
  },
  MID: {
    title: '강가로 움직이기 전 내 웨이브 확인',
    action: '미드에서 처음 강가로 움직이기 전에 내 포탑 쪽으로 들어오는 미니언이 있는지 확인한다.',
    check: '첫 강가 이동 직전, 떠나는 동안 포탑에 닿은 미니언이 있었는지 돌아보세요.',
  },
  BOT: {
    title: '견제하기 전 막타부터 보기',
    action: '원딜로 첫 5분 동안 상대를 견제하기 전에 곧 쓰러질 미니언이 있는지 확인한다.',
    check: '첫 5분 리플레이에서 견제할 때 놓친 막타가 있었는지 한 장면을 확인하세요.',
  },
  SUPPORT: {
    title: '와드하러 가기 전 가까운 아군 확인',
    action: '서포터로 첫 드래곤 전 와드를 설치하러 이동할 때 미니맵에서 가까운 아군의 위치를 확인한다.',
    check: '와드를 설치하러 갔다면, 그때 가까운 아군이 함께 움직일 수 있었는지 돌아보세요.',
  },
};

function renderNextGamePractice(role, openFlow) {
  const practice = Object.hasOwn(rolePractice, role) ? rolePractice[role] : null;
  if (!practice) return null;
  const section = node('section', undefined, 'next-game-practice');
  section.append(
    node('p', '다음 경기에서 연습할 행동', 'section-kicker'),
    node('h3', practice.title),
    node('p', practice.action),
    node('p', practice.check, 'muted'),
  );
  const controls = node('div', undefined, 'practice-controls');
  const save = node('button', '행동 노트에 저장', 'primary');
  const status = node('p', '', 'muted');
  status.setAttribute('role', 'status');
  save.addEventListener('click', () => {
    try {
      practiceNotes.save(practice.action);
      renderNotes();
      status.textContent = '이 브라우저의 행동 노트에 저장했습니다.';
    } catch (error) {
      status.textContent = error.message || '행동 노트를 저장하지 못했습니다.';
    }
  });
  controls.append(save);
  const history = node('button', '지난 연습 돌아보기', 'text-button');
  history.addEventListener('click', () => {
    const heading = $('practice-log-heading');
    heading.scrollIntoView({block:'start'});
    heading.focus({preventScroll:true});
  });
  controls.append(history);
  if (openFlow) {
    const review = node('button', '첫 15분 복기 장면 보기', 'text-button');
    review.addEventListener('click', openFlow);
    controls.append(review);
  }
  section.append(controls, status);
  return section;
}

function matchClock(minute) {
  const seconds = Math.round(minute * 60);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function renderAccountSummary(data) {
  const box=$('account-summary');box.replaceChildren();box.hidden=false;
  const rank=node('div',undefined,'account-rank'); rank.append(node('small','현재 솔로랭크'));
  rank.append(node('strong',data.current_rank?`${data.current_rank.tier} ${data.current_rank.rank}`:'랭크 정보 없음'));
  rank.append(node('span',data.current_rank?`${data.current_rank.leaguePoints} LP`:'현재 조회 결과','muted'));box.append(rank);
  const pool=node('div',undefined,'account-pool');pool.append(node('small','이번에 불러온 챔피언'));
  const counts=new Map(); data.items.forEach(item=>{const row=counts.get(item.champion_id)||{id:item.champion_id,name:item.champion_name,count:0,wins:0,known:0};row.count++;row.wins+=Number(item.win===true);row.known+=Number(typeof item.win==='boolean');counts.set(row.id,row);});
  const list=node('div',undefined,'account-champions');[...counts.values()].sort((a,b)=>b.count-a.count).slice(0,4).forEach(r=>{const button=node('button',undefined,'pool-champion'), text=node('span');text.append(node('strong',r.name),node('small',`${r.count}경기 · ${r.known?`${Math.round(r.wins/r.known*100)}%`:'승률 —'}`));button.append(championPortrait(r.id),text);button.addEventListener('click',()=>{page('champions');window.ChampionInsights?.champion(r.id);});list.append(button);});pool.append(list);box.append(pool);
  const disclosure=node('details',undefined,'account-source');disclosure.append(node('summary','조회 범위'));
  disclosure.append(node('p',`${data.source} · 분석 ${data.items.length}경기 · 제외 ${data.skipped}경기${data.cached?' · 60초 캐시':''}`,'muted'),node('p',data.caveat,'muted'));
  if (data.exclusion_counts) Object.entries(data.exclusion_counts).forEach(([reason,count])=>disclosure.append(node('p',`${reason} ${count}경기`,'muted')));
  if (data.checked_at) disclosure.append(node('p',`조회 ${new Date(data.checked_at).toLocaleString('ko-KR')}`,'muted')); box.append(disclosure);
}

function renderMatchTeam(box,item) {
  if (!item.scoreboard?.length) {box.append(node('p','팀 비교는 전적을 새로 조회한 경기에서 확인할 수 있습니다. 보관한 리포트에는 개인 요약을 저장합니다.','empty-state'));return;}
  const wrap=node('div',undefined,'table-scroll'), table=node('table'), header=node('tr'); table.append(node('caption','참가자 이름을 제외한 경기 종료 수치'));
  ['팀','챔피언','포지션','K / D / A','골드','챔피언 피해','시야'].forEach(t=>{const th=node('th',t);th.scope='col';header.append(th);});const head=node('thead');head.append(header);table.append(head);const body=node('tbody');
  const order=['TOP','JUNGLE','MID','BOT','SUPPORT'];[...item.scoreboard].sort((a,b)=>Number(b.is_ally)-Number(a.is_ally)||order.indexOf(a.role)-order.indexOf(b.role)).forEach(p=>{
    const row=node('tr',undefined,p.is_self?'scoreboard-self':'');row.append(node('td',p.is_ally?'아군':'상대'));
    const cell=node('td',undefined,'scoreboard-champion');cell.append(championPortrait(p.champion_id),node('span',`${p.champion_name}${p.is_self?' · 나':''}`));row.append(cell,node('td',p.role),node('td',[p.kills,p.deaths,p.assists].map(v=>v??'—').join(' / ')));
    [p.gold,p.damage,p.vision].forEach(v=>row.append(node('td',v===null||v===undefined?'—':v.toLocaleString('ko-KR'))));body.append(row);
  });table.append(body);wrap.append(table);box.append(wrap,node('p','수치는 종료 시점의 기록입니다. 높은 수치만으로 기여도·팀운·실력을 판정하지 않습니다.','muted'));
}

function reviewWindow(points) {
  let best = null;
  for (let i = 1; i < points.length; i++) {
    const start = points[i - 1], end = points[i];
    const duration = end.minute - start.minute;
    if (!Number.isFinite(duration) || duration < 0.95 || duration > 1.05 ||
        !Number.isFinite(start.gold_difference) || !Number.isFinite(end.gold_difference)) continue;
    const drop = start.gold_difference - end.gold_difference;
    if (drop > 0 && (!best || drop > best.drop)) best = {start, end, drop};
  }
  return best;
}

async function renderMatchFlow(box,item,sequence) {
  box.replaceChildren();
  if (!item.timeline_ref) {box.append(node('p','이 경기의 흐름을 보려면 전적을 다시 불러와주세요. 경기 연결은 조회 후 30분 동안 유지됩니다.','empty-state'));return;}
  box.append(node('p','공식 타임라인을 불러오는 중입니다.','muted'));
  try {
    const data=await api(`/api/riot/timeline/${encodeURIComponent(item.timeline_ref)}`);
    if (sequence!==autoReportSequence) return;box.replaceChildren();
    if (!data.available) {box.append(node('p','표시할 타임라인 프레임이 없습니다.','empty-state'));return;}
    const earlyDeaths = data.deaths.filter(t => Number.isFinite(t) && t >= 0 && t < 15);
    if (earlyDeaths.length) {
      const scene = node('section', undefined, 'next-game-practice');
      scene.append(
        node('h3', `첫 데스 · ${matchClock(Math.min(...earlyDeaths))}`),
        node('p', '리플레이에서 이 시각으로 이동해 데스 직전 내 위치와 가까운 아군의 위치를 살펴보세요.', 'muted'),
      );
      box.append(scene);
    } else {
      box.append(node('p', '공식 타임라인에 15분 전 본인 데스 기록이 없습니다. 아래 표에서 초반 흐름을 살펴보세요.', 'muted'));
    }
    box.append(node('h3','같은 포지션 상대와 골드 차이'));
    const windowToReview = reviewWindow(data.points);
    if (windowToReview) {
      const {start, end, drop} = windowToReview;
      const formatTime = minute => {
        const seconds = Math.round(minute * 60);
        return Math.floor(seconds / 60) + ':' + String(seconds % 60).padStart(2, '0');
      };
      const deaths = data.deaths.filter(t => t > start.minute && t <= end.minute);
      box.append(node('h3', '리플레이에서 다시 볼 1분'),
        node('p', `${formatTime(start.minute)}–${formatTime(end.minute)} · 같은 포지션 상대 대비 골드 차이가 ${drop.toLocaleString('ko-KR')}G 줄었습니다.`),
        node('p', `비교 가능한 1분 구간 중 감소 폭이 가장 큽니다. 이 구간의 내 데스 ${deaths.length}회. 당시 양쪽의 파밍과 교전 참여를 리플레이에서 확인해 보세요.`, 'muted'));
    }
    const points=data.points.filter(p=>Number.isFinite(p.gold_difference));
    if (points.length>1) {
      const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 720 220');svg.setAttribute('role','img');svg.setAttribute('aria-label','시간에 따른 같은 포지션 상대 대비 골드 차이');svg.classList.add('timeline-chart');
      const maxTime=Math.max(1,...points.map(p=>p.minute)), maxDelta=Math.max(500,...points.map(p=>Math.abs(p.gold_difference)));
      const x=p=>52+p.minute/maxTime*640, y=p=>100-p.gold_difference/maxDelta*72;
      function draw(tag,attrs,text){const el=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));if(text!==undefined)el.textContent=text;svg.append(el);return el;}
      for (const value of [-maxDelta,0,maxDelta]) {const yy=100-value/maxDelta*72;draw('line',{x1:52,x2:692,y1:yy,y2:yy,class:'timeline-grid'});draw('text',{x:45,y:yy+4,'text-anchor':'end'},`${value>0?'+':''}${Math.round(value).toLocaleString()}`);}
      for (let minute=0;minute<=maxTime;minute+=5) draw('text',{x:52+minute/maxTime*640,y:198,'text-anchor':'middle'},`${minute}분`);
      draw('polyline',{points:points.map(p=>`${x(p)},${y(p)}`).join(' '),fill:'none',class:'timeline-line'});box.append(svg);
    }
    const table=node('table'), header=node('tr');table.append(node('caption','주요 시점의 실제 프레임 · CS는 정글 몬스터 포함'));
    ['시점','내 골드','상대 골드','골드 차이','내 CS','상대 CS','CS 차이'].forEach(t=>{const th=node('th',t);th.scope='col';header.append(th);});const head=node('thead');head.append(header);table.append(head);const body=node('tbody');
    const milestones=data.points.filter(p=>p.minute>0 && Math.abs(p.minute/5-Math.round(p.minute/5))<.02);const last=data.points.at(-1);if (last&&!milestones.includes(last)) milestones.push(last);
    milestones.forEach(p=>{const row=node('tr');[`${p.minute}분`,p.gold,p.opponent_gold,p.gold_difference,p.cs,p.opponent_cs,p.cs_difference].forEach((v,i)=>row.append(node('td',v===null?'—':i===0?v:`${[3,6].includes(i)&&v>0?'+':''}${Number(v).toLocaleString()}`)));body.append(row);});table.append(body);const wrap=node('div',undefined,'table-scroll');wrap.append(table);box.append(wrap);
    box.append(node('p',`데스 시점: ${data.deaths.length ? data.deaths.map(matchClock).join(' · ') : '기록 없음'}`,'muted'),node('p',data.caveat,'muted'));
  } catch(error) {if(sequence===autoReportSequence){box.replaceChildren(node('p',error.message,'error-text'));const retry=node('button','흐름 다시 불러오기','text-button');retry.addEventListener('click',()=>renderMatchFlow(box,item,sequence));box.append(retry);}}
}

$('recent-role').addEventListener('change',()=>{
  const role=$('recent-role').value, rows=[...$('riot-matches').querySelectorAll('.match-import')];rows.forEach(row=>row.hidden=!!role&&row.dataset.role!==role);
  const selected=rows.find(row=>row.querySelector('[aria-pressed=true]'));
  if (selected?.hidden || !selected) {const first=rows.find(row=>!row.hidden);if(first)first.querySelector('button').click();else {rows.forEach(row=>row.querySelector('button').setAttribute('aria-pressed','false'));autoReportSequence++;$('auto-report').replaceChildren(node('p','이번 조회 범위에 해당 포지션 경기가 없습니다.','empty-state'));}}
});
