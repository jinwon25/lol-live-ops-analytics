'use strict';
(() => {
  let data=null, role='BOT';
  const roleNames={TOP:'탑',JUNGLE:'정글',MID:'미드',BOT:'원딜',SUPPORT:'서포터'};
  function guide(show) {
    $('meta-panel').hidden=show; $('champion-guide-panel').hidden=!show;
    $('show-meta-data').setAttribute('aria-pressed',String(!show)); $('show-champion-guide').setAttribute('aria-pressed',String(show));
  }
  async function champion(id) {guide(true); await selectChampion(id); if (selectedChampion===id && !$('champions').hidden && !$('champion-guide-panel').hidden) {$('champion-detail').scrollIntoView({block:'start'});$('champion-detail').setAttribute('tabindex','-1');$('champion-detail').focus({preventScroll:true});}}
  function name(id) {return championItems.find(c=>c.id===id)?.name || id;}
  function render() {
    const box=$('meta-table'); box.replaceChildren();box.parentElement.querySelectorAll('.meta-table-hint').forEach(el=>el.remove()); box.tabIndex=0;box.setAttribute('aria-label','챔피언 통계 표 · 좁은 화면에서 좌우 스크롤'); $('meta-highlights').replaceChildren();
    if (!data?.available) {$('meta-status').textContent=data?.reason || '현재 패치 표본이 아직 없습니다.'; return;}
    const q=$('meta-search').value.trim().toLowerCase(), minimum=$('meta-minimum').checked;
    const all=data.items.filter(r=>r.role===role), items=all.filter(r=>(!minimum || r.games>=data.minimum_games) && (name(r.champion_id).toLowerCase().includes(q) || r.champion_id.toLowerCase().includes(q)));
    const key=$('meta-sort').value;
    items.sort((a,b)=>(key==='lower' ? (b.interval?.[0]??-1)-(a.interval?.[0]??-1) : key==='win_rate' ? (b.win_rate??-1)-(a.win_rate??-1) : b.games-a.games) || b.games-a.games || name(a.champion_id).localeCompare(name(b.champion_id),'ko'));
    $('meta-scope').textContent=`KR · 솔로듀오 · ${data.scope.patch} · ${data.games.toLocaleString()}경기 · 실버 II 계정에서 출발한 표본`;
    $('meta-freshness').textContent=data.stale ? '갱신 필요' : `수집 ${new Date(data.collected_at).toLocaleDateString('ko-KR')}`;
    $('meta-status').textContent=`${roleNames[role]} ${items.length}챔피언 · 포지션 참여 ${data.role_denominators[role] || 0}행. ${data.stale?'이전 수집 자료입니다. 현재 추천으로 사용하지 마세요.':'모든 참가자가 실버 II라는 뜻은 아닙니다.'}`;
    const eligible=all.filter(r=>r.win_rate!==null);
    const popular=[...all].sort((a,b)=>b.games-a.games)[0];
    const leading=[...eligible].sort((a,b)=>b.interval[0]-a.interval[0])[0];
    for (const [label,r,description] of [['많이 선택한 챔피언',popular,popular?`${popular.games}회 · 역할 내 픽 ${popular.pick_rate}%`:null],['승률 구간 하한이 높은 챔피언',leading,leading?`${leading.win_rate}% · 참고 구간 ${leading.interval.join('–')}%`:null]]) {
      const card=node('div',undefined,'meta-highlight'); card.append(node('small',label));
      if (r) {const button=node('button',undefined,'meta-champion'); button.append(championPortrait(r.champion_id),node('strong',name(r.champion_id)));button.addEventListener('click',()=>champion(r.champion_id));card.append(button,node('p',description,'muted'));}
      else card.append(node('strong','표본을 더 모으는 중'),node('p','30회 이상 관측한 챔피언이 없습니다.','muted'));
      $('meta-highlights').append(card);
    }
    if (leading) $('meta-highlights').append(node('p','표본에서 확인할 후보입니다. 구간이 겹치면 우열을 확정할 수 없고, 숙련도·상대 조합의 차이도 남습니다.','meta-caution muted'));
    if (!items.length) {box.append(node('p','조건에 맞는 챔피언이 없습니다. 검색어나 최소 표본 필터를 조정해보세요.','empty-state'));return;}
    const table=node('table'), thead=node('thead'), header=node('tr'); table.append(node('caption',`${roleNames[role]} · 현재 패치 관측 통계`));
    ['순서','챔피언','관측 승률','승률 참고 구간','역할 내 픽','밴 비중','표본','관측 상태'].forEach(t=>{const th=node('th',t);th.scope='col';header.append(th);});thead.append(header);table.append(thead);
    const body=node('tbody');items.forEach((r,i)=>{
      const row=node('tr');row.append(node('td',String(i+1)));
      const cell=node('td'), button=node('button',undefined,'meta-champion');button.append(championPortrait(r.champion_id),node('span',name(r.champion_id)));button.addEventListener('click',()=>champion(r.champion_id));cell.append(button);row.append(cell);
      [r.win_rate===null?'—':`${r.win_rate}%`,r.interval?`${r.interval.join('–')}%`:'30회 미만',`${r.pick_rate}%`,r.ban_rate===null?'—':`${r.ban_rate}%`,`${r.games}회`,r.signal==='positive'&&!data.stale?'긍정 신호':r.signal==='small_sample'?'소표본':'우열 미확정'].forEach(t=>row.append(node('td',t))); body.append(row);
    });table.append(body);box.append(table);const hint=node('p','표를 좌우로 넘기면 픽·밴 비중과 표본 수를 볼 수 있습니다.','meta-table-hint muted');box.after(hint);
  }
  async function load() {
    try {data=await api('/api/meta'); render(); const box=$('meta-method-content');box.replaceChildren();
      if (data.available) {
        box.append(node('p',`수집 시각 ${new Date(data.collected_at).toLocaleString('ko-KR')} · 경기 범위 ${new Date(data.period.first).toLocaleDateString('ko-KR')}–${new Date(data.period.last).toLocaleDateString('ko-KR')}`,'muted'));
        data.caveats.forEach(t=>box.append(node('p',t,'muted'))); data.sources.forEach(s=>box.append(externalLink(s.title,s.url)));
        box.append(node('p','자동 주기 수집은 아직 설정하지 않았습니다. 수집 후 3일이 지나거나 정적 패치가 달라지면 갱신 필요로 표시합니다.','muted'));
      }
    } catch(error) {$('meta-status').textContent=error.message;}
  }
  $('show-meta-data').addEventListener('click',()=>guide(false)); $('show-champion-guide').addEventListener('click',()=>guide(true));
  $('meta-roles').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{role=button.dataset.role;$('meta-roles').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));render();}));
  ['meta-sort','meta-minimum'].forEach(id=>$(id).addEventListener('change',render));$('meta-search').addEventListener('input',render);
  window.ChampionInsights={load,render,guide,champion,rows:id=>data?.available?data.items.filter(r=>r.champion_id===id):[],stale:()=>data?.stale};
  load();
})();
