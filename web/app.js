'use strict';
const $ = id => document.getElementById(id);
let selectedChampion = null, championRequest = 0;
let championItems = [], overviewData = null, preferences = {};
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
function championPortrait(id, className = 'champion-portrait') {
  const img = node('img', undefined, className);
  img.alt = ''; img.width = 48; img.height = 48; img.loading = 'eager'; img.decoding = 'async';
  // 백업의 임의 ID를 URL 경로나 외부 요청으로 변환하지 않는다.
  if (championItems.some(item => item.id === id)) {
    const version = overviewData?.static_data.version;
    let fallbackUsed = false;
    img.addEventListener('error', () => {
      if (!fallbackUsed && /^\d+\.\d+\.\d+$/.test(version || '')) {
        fallbackUsed = true;
        img.referrerPolicy = 'no-referrer';
        img.src = `https://ddragon.leagueoflegends.com/cdn/${version}/img/champion/${id}.png`;
      } else {
        // 초상 로딩 실패에도 이름과 선택 기능은 유지한다.
        img.hidden = true;
        img.parentElement?.classList.add('portrait-unavailable');
      }
    });
    img.src = `/assets/images/champions/${id}.png?v=${encodeURIComponent(version || 'local')}`;
  } else img.hidden = true;
  return img;
}
function actionPill(record) {return node('span',actionLabels[record.action_status || 'planned'],'state-pill '+(record.action_status || 'planned'));}
async function api(path, payload) {
  const response = await fetch(path, payload ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)} : {});
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const retry=Number(response.headers.get('Retry-After'));
    throw new Error((typeof detail.detail === 'string' ? detail.detail : response.status === 422 ? '입력 범위·킬/도움·경기 일시와 조건을 확인해주세요.' : '자료를 불러오지 못했습니다. 서버 연결을 확인해주세요.')+(response.status===429&&retry>0?` ${retry}초 뒤 다시 시도해주세요.`:''));
  }
  return response.json();
}
function externalLink(title, href) {
  const link = node('a', title + ' ↗');
  const url = new URL(href);
  const allowed = ['github.com','ddragon.leagueoflegends.com','developer.riotgames.com','www.leagueoflegends.com','lol.ps','www.fow.lol','zenodo.org','huggingface.co','www.kaggle.com','oracleselixir.com','creativecommons.org'];
  if (url.protocol !== 'https:' || !allowed.includes(url.hostname)) return node('span', title);
  link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}
function page(name) {
  if (name==='assistant') {
    page('champions'); document.querySelector('.assistant-drawer').open=true;
    $('assistant').scrollIntoView({block:'start'}); return;
  }
  if (!$(name) || $(name).getAttribute('role') !== 'tabpanel') return;
  document.querySelectorAll('main > section[role=tabpanel]').forEach(item => item.hidden = item.id !== name);
  document.querySelectorAll('nav [role=tab]').forEach(item => {
    const selected = item.dataset.page === name;
    item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
  });
  window.scrollTo({top:0,behavior:'instant'});
}
document.addEventListener('keydown', event => {
  if ((!event.ctrlKey && !event.metaKey) || event.altKey || event.shiftKey || event.key.toLowerCase() !== 'k') return;
  event.preventDefault();
  const target = !$('champions').hidden ? ($('champion-guide-panel').hidden ? $('meta-search') : $('champion-search')) : !$('overview').hidden ? $('journal-search') : $('riot-form').elements.game_name;
  target.focus(); target.select();
});
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => page(button.dataset.page)));
document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => page(button.dataset.open)));
$('open-data-sources').addEventListener('click', () => {
  page('champions'); const drawer = document.querySelector('.reference-drawer'); drawer.open = true;
  drawer.scrollIntoView({block:'start'}); drawer.querySelector('summary').focus({preventScroll:true});
});
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
  page('assistant'); $('assistant-question').value = button.dataset.question; $('assistant-question').focus();
}));
document.querySelector('nav').addEventListener('keydown', event => {
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  event.preventDefault(); const tabs = [...document.querySelectorAll('nav [role=tab]')];
  const index = tabs.indexOf(document.activeElement); const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].focus(); page(tabs[next].dataset.page);
});
function metric(label, value, description) {
  const card = node('div', undefined, 'metric');
  card.append(node('span', label), node('strong', value), node('small', description)); return card;
}
async function load() {
  try {
    $('error-banner').hidden = true;
    const [data, champs, defaults] = await Promise.all([api('/api/overview'), api('/api/champions'), api('/api/riot/preferences').catch(() => ({}))]);
    preferences = defaults;
    if (preferences.champions?.length) {
      const names = preferences.champions.map(id => champs.items.find(c => c.id === id)?.name || id).join(' / ');
      $('personal-context').textContent = `기존 복기 참고 조건: ${preferences.region} · ${preferences.tier} ${preferences.division} · ${preferences.role} · ${names}. 과거 경기의 조건은 별도로 확인해주세요.`;
      champs.items.sort((a,b) => Number(preferences.champions.includes(b.id)) - Number(preferences.champions.includes(a.id)));
    }
    overviewData = data; championItems = champs.items;
    $('data-status').textContent = `공식 정적 자료 ${data.static_data.version} · 기존 경기 분석 15.1↔15.3 (2025년 초, EUN) · KR 완료 전적은 경기 복기에서 조회`;
    renderJournal();
    renderSavedReports();
    $('segment-bars').replaceChildren();
    data.segments.forEach(item => {
      const row = node('div', undefined, 'bar-row'), label = node('div', undefined, 'bar-label');
      label.append(node('span', item.persona), node('span', `${item.share_pct}%`));
      const track = node('div', undefined, 'bar-track'), fill = node('div', undefined, 'bar-fill');
      fill.style.width = `${Math.max(0, Math.min(100, Number(item.share_pct)))}%`; track.append(fill); row.append(label, track); $('segment-bars').append(row);
    });
    $('official-reference').textContent = `정적 자료 ${data.static_data.version} · 패치 노트 ${data.patch_notes.patch}. 정적 자료 확인 ${new Date(data.static_data.checked_at).toLocaleDateString('ko-KR')}.`;
    $('official-links').replaceChildren(externalLink('공식 패치 노트', data.patch_notes.url), externalLink('챔피언 정적 자료 원본', data.static_data.source_url));
    renderChampions();
    window.ChampionInsights?.render();
  } catch(error) { $('error-banner').hidden = false; $('error-text').textContent = error.message; $('data-status').textContent = '자료 연결 확인이 필요합니다.'; }
}
$('retry').addEventListener('click', load);
function renderChampions() {
  const query = $('champion-search').value.trim().toLowerCase();
  const category = $('champion-class').value;
  $('champion-quick-filters').querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.category === category)));
  const items = championItems.filter(item => (!category || item.tags.includes(category)) && (item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query)));
  $('champion-count').textContent = `${items.length} / ${championItems.length} 챔피언`;
  $('champion-list').replaceChildren();
  items.forEach(item => {
    const button = node('button', undefined, 'champion-button' + (selectedChampion === item.id ? ' active' : ''));
    button.append(championPortrait(item.id),node('span',item.name));
    button.setAttribute('aria-pressed', String(selectedChampion === item.id)); button.addEventListener('click', () => selectChampion(item.id)); $('champion-list').append(button);
  });
  if (!items.length) $('champion-list').append(node('p', '검색 결과가 없습니다.', 'muted'));
}
$('champion-search').addEventListener('input', renderChampions);
$('champion-class').addEventListener('change', renderChampions);
for (const option of $('champion-class').options) {
  const button=node('button',option.value ? option.textContent : '전체','champion-filter');
  button.type='button'; button.dataset.category=option.value; button.setAttribute('aria-pressed',String(!option.value));
  button.addEventListener('click',()=> {$('champion-class').value=option.value; renderChampions();});
  $('champion-quick-filters').append(button);
}
async function selectChampion(id) {
  const sequence = ++championRequest;
  try {
    const data = await api(`/api/champions/${encodeURIComponent(id)}`);
    if (sequence !== championRequest) return;
    selectedChampion = id; renderChampions(); const detail = $('champion-detail'); detail.replaceChildren(); detail.hidden=false; $('champion-hint').hidden=true;
    const title = node('div',undefined,'champion-detail-heading'), text = node('div');
    text.append(node('p', `공식 정적 자료 ${data.static_version}`, 'eyebrow'), node('h2', data.champion.name));
    const close=node('button','닫기','text-button'); close.setAttribute('aria-label','챔피언 상세 닫기');
    close.addEventListener('click',()=> {championRequest++; selectedChampion=null; detail.hidden=true; $('champion-hint').hidden=false; $('selected-context').textContent='선택한 챔피언 없음'; renderChampions(); [...$('champion-list').querySelectorAll('button')].find(button=>button.textContent===data.champion.name)?.focus();});
    title.append(championPortrait(id),text,close); detail.append(title);
    const tags = node('div'); data.champion.tags.forEach(tag => tags.append(node('span', [...$('champion-class').options].find(o=>o.value===tag)?.textContent || tag, 'tag'))); detail.append(tags, node('p', '공식 분류 태그입니다. 역할·추천 순위와는 별개입니다.', 'muted'));
    const stats = data.champion.stats; detail.append(node('p', `기본 체력 ${stats.hp} · 기본 공격력 ${stats.attackdamage} · 이동 속도 ${stats.movespeed}`, 'muted'));
    const metaRows=window.ChampionInsights?.rows(id) || [];
    const current=node('section',undefined,'champion-current'); current.append(node('h3','현재 패치에서의 관측'));
    if (metaRows.length) metaRows.forEach(r=>current.append(node('p',`${r.role} · ${r.games}회 · ${r.win_rate===null?'승률 표시 보류 (30회 미만)':`승률 ${r.win_rate}% · 참고 구간 ${r.interval.join('–')}%`} · 역할 내 픽 ${r.pick_rate}%`,'muted')));
    else current.append(node('p','수집 표본에서 관측하지 못했습니다. 강함이나 약함을 뜻하지 않습니다.','muted'));
    if (window.ChampionInsights?.stale()) current.append(node('p','갱신이 필요한 자료입니다. 현재 추천으로 사용하지 마세요.','muted'));
    const skills=node('section',undefined,'champion-skills');skills.append(node('h3',data.abilities?.title ? `기술 · ${data.abilities.title}` : '공식 기술 정보'));
    if (data.abilities?.available) {
      data.abilities.skills.forEach(skill=>{const row=node('details',undefined,'skill-row'),summary=node('summary'),text=node('span');
        text.append(node('b',skill.key),node('strong',skill.name));
        if (skill.image_url) {const img=node('img');img.src=skill.image_url;img.alt='';img.width=32;img.height=32;img.referrerPolicy='no-referrer';img.addEventListener('error',()=>img.hidden=true);summary.append(img);}
        summary.append(text);row.append(summary,node('p',skill.description));skills.append(row);
      });
      if (data.abilities.ally_tips?.length) {const tips=node('details');tips.append(node('summary','플레이 팁'));data.abilities.ally_tips.forEach(t=>tips.append(node('p',t,'muted')));skills.append(tips);}
      skills.append(externalLink('공식 기술 설명 원본',data.abilities.source_url));
    } else skills.append(node('p','공식 기술 설명을 불러오지 못했습니다. 잠시 뒤 챔피언을 다시 선택해주세요.','muted'));
    const championBody=node('div',undefined,'champion-data-body');championBody.append(current,skills);detail.append(championBody);
    const visible = data.history.filter(item => Number(item.pick_count) >= data.minimum_display_rows);
    if (visible.length) {
      const wrap = node('div', undefined, 'table-scroll'), table = node('table'), head = node('thead'), header = node('tr');
      table.append(node('caption', '과거 코호트 관측 · 15.1 / 15.3'));
      ['패치','역할','참여 행','관측 승률','Wilson 하한'].forEach(text => header.append(node('th', text))); head.append(header); table.append(head); const body = node('tbody');
      visible.forEach(item => {const row = node('tr'); [item.patch,item.role,Number(item.pick_count).toLocaleString(),`${item.win_rate_pct}%`,`${item.wilson_low_pct}%`].forEach(value => row.append(node('td', value))); body.append(row);});
      table.append(body); wrap.append(table); detail.append(wrap);
      const historical=node('details',undefined,'champion-history');historical.append(node('summary','과거 관측 · 2025 EUN'),wrap,node('p', '과거 EUN·PLATINUM/EMERALD/DIAMOND 표본입니다. Wilson 하한은 강함의 확정값이나 예측 점수가 아닙니다. 30행 미만 집계는 승률 설명을 보류합니다.', 'muted'));detail.append(historical);
    } else detail.append(node('p', '표시할 과거 표본이 충분하지 않습니다.', 'muted'));
    const ask = node('button', '이 챔피언의 과거 집계를 도우미에게 묻기', 'text-button'); ask.addEventListener('click', () => {page('assistant'); $('assistant-question').value = '선택한 챔피언의 패치 변화와 승률은?';}); detail.append(ask);
    $('selected-context').textContent = `선택한 챔피언: ${data.champion.name} · 과거 집계만 질문 가능`;
  } catch(error) { if (sequence === championRequest) { $('champion-detail').hidden=false; $('champion-detail').replaceChildren(node('p', error.message, 'error-text')); } }
}
$('assistant-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('assistant-error').textContent = '';
  try {
    const data = await api('/api/assistant', {question:$('assistant-question').value,champion_id:selectedChampion}); const box = $('assistant-answer'); box.replaceChildren();
    box.append(node('span', data.status === 'insufficient_data' ? '추가 자료가 필요한 답변' : '등록된 분석 근거로 확인한 답변', 'answer-label'), node('p', data.answer));
    box.append(node('p', `${data.scope.region} · ${data.scope.patches.join(' / ')} · ${data.scope.cohort}`, 'evidence-note'));
    const sources = node('div', undefined, 'source-list'); data.sources.forEach(source => sources.append(externalLink(source.title, source.url))); box.append(sources);
    if (data.external_references) { const references = node('div', undefined, 'external-references'); references.append(node('p', '외부에서 확인하기 · 답변의 수치 근거로 수집한 자료는 아닙니다.', 'muted')); data.external_references.forEach(ref => references.append(externalLink(ref.title, ref.url))); box.append(references); }
    const caveats = node('ul'); data.caveats.forEach(caveat => caveats.append(node('li', caveat))); box.append(caveats, node('div', data.next_step, 'answer-step'));
  } catch(error) { $('assistant-error').textContent = error.message; } finally {button.disabled = false;}
});
const NOTE_KEY = 'lol-insight-notes-v1';
function notes() { try {const saved = JSON.parse(localStorage.getItem(NOTE_KEY) || '[]'); return Array.isArray(saved) ? saved.filter(item => item && typeof item.text === 'string' && item.text.length <= 200).slice(-10) : [];} catch {return [];} }
function renderNotes() { $('practice-list').replaceChildren(); notes().forEach(item => $('practice-list').append(node('li', `${item.date || ''} · ${item.text}`))); }
$('note-form').addEventListener('submit', event => {
  event.preventDefault(); const text = $('practice-note').value.trim(); if (!text) return;
  try {localStorage.setItem(NOTE_KEY, JSON.stringify([...notes(),{date:new Date().toLocaleDateString('ko-KR'),text}].slice(-10))); $('practice-note').value = ''; $('note-status').textContent = '이 브라우저에 기록했습니다. 서버로 전송하지 않습니다.'; renderNotes();} catch {$('note-status').textContent = '브라우저 저장이 제한되어 기록하지 못했습니다.';}
});
$('clear-notes').addEventListener('click', () => {try {localStorage.removeItem(NOTE_KEY); renderNotes(); $('note-status').textContent = '이 브라우저의 복기 기록을 지웠습니다.';} catch {$('note-status').textContent = '브라우저 저장소에 접근하지 못했습니다.';}});
const journal = window.ReviewJournal;
let importPreview = null, importSequence = 0, deletedRecord = null, sessionLimit = 20;
$('export-journal').addEventListener('click', () => {
  try {
    if (!journal.read().length) { $('backup-status').textContent = '내보낼 경기 기록이 없습니다.'; return; }
    const url = URL.createObjectURL(new Blob([journal.backup()], {type:'application/json'}));
    const link = node('a'); link.href = url; link.download = `lol-review-backup-${new Date().toISOString().slice(0,10)}.json`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    $('backup-status').textContent = '경기 백업 파일을 내려받았습니다. 개인 기록이 담긴 파일을 보관하세요.';
  } catch { $('backup-status').textContent = '경기 기록을 내보내지 못했습니다.'; }
});
$('import-journal').addEventListener('change', async event => {
  const sequence = ++importSequence, file = event.target.files[0]; importPreview = null; $('restore-journal').disabled = true;
  $('backup-status').textContent = '';
  if (!file) return;
  try {
    if (file.size > journal.MAX_BACKUP_BYTES) throw new Error('백업 파일은 2MB 이하여야 합니다.');
    const text = await file.text(); if (sequence !== importSequence) return;
    importPreview = journal.prepareImport(text);
    $('backup-status').textContent = `미리보기: 추가 ${importPreview.added}개 · 기존 유지 ${importPreview.duplicates}개 · 복원 후 ${importPreview.count}경기. 기록 합치기를 누르면 반영합니다.`;
    $('restore-journal').disabled = false;
  } catch(error) { if (sequence === importSequence) $('backup-status').textContent = error.message || '백업 파일을 확인하지 못했습니다.'; }
});
$('restore-journal').addEventListener('click', () => {
  if (!importPreview) return;
  try {
    const result = journal.restore(importPreview); renderJournal();
    $('backup-status').textContent = `복원 완료: 추가 ${result.added}개 · 기존 유지 ${result.duplicates}개 · 현재 ${result.count}경기.`;
    importPreview = null; $('import-journal').value = ''; $('restore-journal').disabled = true;
  } catch(error) { $('backup-status').textContent = error.message || '브라우저 저장에 실패했습니다.'; }
});
const metricLabels = {gpm:'분당 골드',dpm:'분당 챔피언 피해',vision_per_minute:'분당 시야 점수',kill_participation:'킬 관여율'};
const focusLabels = {vision:'오브젝트 전 시야 준비',fight_setup:'교전 전 합류와 자원',resource:'파밍과 귀환 선택',matchup:'라인전 상대와 선택'};
const actionLabels = {planned:'시도 전',tried:'시도함',reviewed:'돌아봄'};
function conditionLabel(c) { return `${c.champion_name} · ${c.role} · ${c.region} · ${c.queue === 'RANKED_SOLO' ? '솔로듀오' : '자유랭크'} · ${c.patch} · ${c.tier}`; }
function renderJournal() {
  const records = journal.read(), selected = $('comparison-group').value, groups = new Map();
  $('overview').classList.toggle('has-records',records.length > 0);
  const reportCard = document.querySelector('.analysis-layout'), board = document.querySelector('.board-layout');
  // 시각적 순서와 키보드·화면 읽기 순서를 함께 바꾼다.
  if (records.length && reportCard.nextElementSibling !== board) board.before(reportCard);
  else if (!records.length && board.nextElementSibling !== reportCard) board.after(reportCard);
  [...records].reverse().forEach(record => groups.set(journal.group(record.context), record.context));
  const picker = $('comparison-group'); picker.replaceChildren();
  if (!groups.size) { const empty = node('option', '비교할 기존 복기 기록이 없습니다.'); empty.value = ''; picker.append(empty); }
  [...groups.entries()].forEach(([key,context]) => {const option = node('option', conditionLabel(context)); option.value = key; picker.append(option);});
  if (groups.has(selected)) picker.value = selected;
  $('overview-metrics').replaceChildren(metric('기존 복기 경기', `${records.length}경기`, `전적 리포트와 별도 · 최대 ${journal.MAX_RECORDS}개`), metric('복기 행동 기록', `${records.filter(item => item.action.trim()).length}개`, `시도함·돌아봄 ${records.filter(item => ['tried','reviewed'].includes(item.action_status)).length}개 · 본인 체크`), metric('같은 조건 비교', `${groups.size}개 조건`, '6경기부터 최근 3 / 직전 3 표시'));
  renderComparison(); renderSessions(records);
}
function renderSessions(records) {
  const query = $('journal-search').value.trim().toLocaleLowerCase('ko-KR');
  const state = $('journal-state').value;
  const matches = [...records].reverse().filter(record => (!state || (record.action_status || 'planned') === state) && [conditionLabel(record.context),record.context.champion_id,new Date(record.context.played_at).toLocaleString('ko-KR'),focusLabels[record.focus],actionLabels[record.action_status || 'planned'],record.scene,record.action,record.reflection || ''].join(' ').toLocaleLowerCase('ko-KR').includes(query));
  $('session-count').textContent = `전체 ${records.length}경기 · 조건에 맞는 ${matches.length}경기 · 표시 ${Math.min(matches.length,sessionLimit)}경기${!matches.length && (query || state) ? ' · 검색 결과가 없습니다.' : ''}`;
  $('more-sessions').hidden = matches.length <= sessionLimit;
  $('session-list').replaceChildren();
  let emptyBox = $('journal-empty');
  if (!emptyBox) {emptyBox = node('div'); emptyBox.id='journal-empty'; $('session-list').before(emptyBox);}
  emptyBox.replaceChildren(); emptyBox.hidden = matches.length > 0;
  if (!matches.length) {
    const empty = node('div',undefined,'empty-journal');
    if (!records.length) {
      const portraits = node('div',undefined,'empty-portraits');
      ['Ezreal','Lucian','Viktor'].forEach(id => portraits.append(championPortrait(id))); empty.append(portraits);
      empty.append(node('h3','기존 복기 기록이 없습니다.'),node('p','예전에 저장한 복기는 아래에서 백업을 불러올 수 있습니다. 새 경기의 분석은 전적을 조회해 리포트로 보관하세요.'));
      const start = node('button','전적 불러와 분석하기','primary'); start.addEventListener('click',()=>page('review')); empty.append(start);
    } else empty.append(node('h3','조건에 맞는 기록이 없습니다.'),node('p','검색어나 행동 상태를 바꾸어 찾아보세요.'));
    emptyBox.append(empty);
  }
  matches.slice(0,sessionLimit).forEach(record => {
    const row = node('li'), c = record.context;
    row.dataset.recordId = journal.id(c);
    const top = node('div',undefined,'record-top'), heading = node('div',undefined,'record-heading');
    heading.append(node('strong',`${c.champion_name} · ${c.role}`),node('small',`${new Date(c.played_at).toLocaleString('ko-KR')} · ${c.region} / ${c.queue === 'RANKED_SOLO' ? '솔로듀오':'자유랭크'} / ${c.tier} / ${c.patch}`));
    top.append(championPortrait(c.champion_id),heading,actionPill(record)); row.append(top);
    const actionText = node('p',undefined,'record-action'); actionText.append(node('span','다음 행동'),document.createTextNode(record.action)); row.append(actionText);
    const bottom = node('div',undefined,'record-bottom'), numbers = node('div',undefined,'record-numbers'), buttons = node('div',undefined,'record-buttons');
    [['GPM',record.metrics.gpm],['DPM',record.metrics.dpm],['시야/분',record.metrics.vision_per_minute]].forEach(([label,value])=>{const item=node('span');item.append(node('b',Number(value).toLocaleString('ko-KR',{maximumFractionDigits:1})),document.createTextNode(label)); numbers.append(item);});
    bottom.append(numbers,buttons); row.append(bottom);
    const details = node('details',undefined,'record-details');
    details.append(node('summary',`장면 · ${focusLabels[record.focus]}`),node('p',`확인한 사실: ${record.scene}`));
    if (record.reflection) details.append(node('p', `시도 후 돌아본 내용: ${record.reflection}`));
    row.append(details);
    const edit = node('button', '복기 기록 수정', 'text-button');
    edit.addEventListener('click', () => {
      const form = node('form', undefined, 'journal-fields');
      const focus = node('select'); Object.entries(focusLabels).forEach(([value,label]) => {const option = node('option',label); option.value = value; focus.append(option);}); focus.value = record.focus;
      const scene = node('textarea'); scene.value = record.scene; scene.maxLength = 400; scene.required = true;
      const action = node('textarea'); action.value = record.action; action.maxLength = 200; action.required = true;
      for (const [title,input] of [['복기 초점',focus],['장면에서 확인한 사실 · 시각',scene],['다음 경기에서 확인할 행동',action]]) {const label = node('label',title); label.append(input); form.append(label);}
      const save = node('button', '수정 저장', 'primary'); save.type = 'submit';
      const state = node('select'); Object.entries(actionLabels).forEach(([value,text]) => {const option = node('option',text); option.value = value; state.append(option);}); state.value = record.action_status || 'planned';
      const reflection = node('textarea'); reflection.value = record.reflection || ''; reflection.maxLength = 300;
      for (const [title,input] of [['행동 진행 상태',state],['시도 후 돌아본 내용',reflection]]) {const label = node('label',title); label.append(input); form.append(label);}
      const cancel = node('button', '취소', 'text-button'); cancel.type = 'button'; cancel.addEventListener('click', () => {renderJournal(); $('journal-search').focus();});
      const status = node('p', '경기 조건과 수치는 유지하고 복기 내용을 수정합니다.', 'muted'); status.setAttribute('role','status');
      form.append(save,cancel,status); row.replaceChildren(node('strong',conditionLabel(c)),form); focus.focus();
      form.addEventListener('submit', event => {
        event.preventDefault();
        if (!scene.value.trim() || !action.value.trim()) {status.textContent = '확인한 사실과 다음 행동을 각각 적어주세요.'; return;}
        try {
          journal.update(journal.id(c),record,{focus:focus.value,scene:scene.value.trim(),action:action.value.trim(),action_status:state.value,reflection:reflection.value.trim()});
          $('journal-status').textContent = '복기 내용을 수정했습니다. 경기 조건과 수치는 유지했습니다.'; renderJournal();
          $('journal-search').focus();
        } catch(error) {status.textContent = error.message || '브라우저 저장에 실패했습니다.';}
      });
    }); buttons.append(edit);
    const remove = node('button', '이 경기 삭제', 'text-button'); remove.addEventListener('click', () => {try {journal.remove(journal.id(c)); deletedRecord = record; $('undo-delete').hidden = false; $('journal-status').textContent = '경기를 삭제했습니다. 이 화면에서 방금 삭제한 한 경기를 되돌릴 수 있습니다.'; renderJournal(); $('undo-delete').focus();} catch(error) {$('journal-status').textContent = error.message || '브라우저 저장소에 접근하지 못했습니다.';}}); buttons.append(remove); $('session-list').append(row);
  });
}
$('journal-search').addEventListener('input', () => {sessionLimit = 20; renderSessions(journal.read());});
$('journal-state').addEventListener('change', () => {sessionLimit = 20; renderSessions(journal.read());});
$('more-sessions').addEventListener('click', () => {sessionLimit += 20; renderSessions(journal.read());});
$('undo-delete').addEventListener('click', () => {
  if (!deletedRecord) return;
  try {journal.undoRemove(deletedRecord); deletedRecord = null; $('undo-delete').hidden = true; renderJournal(); $('journal-status').textContent = '삭제한 경기를 되돌렸습니다.'; $('journal-search').focus();}
  catch(error) {$('journal-status').textContent = error.message || '삭제한 경기를 되돌리지 못했습니다.';}
});
window.addEventListener('storage', event => {
  if (event.key === 'lol-ranked-reviews-v1' || event.key === null) {
    if (!$('session-list').querySelector('form')) renderJournal();
    $('journal-status').textContent = '다른 탭에서 기록이 바뀌었습니다. 수정 중인 기록은 최신 내용을 확인하고 다시 저장해주세요.';
  }
  if (event.key === NOTE_KEY || event.key === null) renderNotes();
});
function renderComparison() {
  renderPersonalAnalysis(); renderTasks();
  const result = journal.compare(journal.read(), $('comparison-group').value), box = $('self-comparison');
  box.replaceChildren(node('p', `${result.count}경기 · ${result.metrics ? '플레이 일시 순서로 최근 3경기 / 직전 3경기 비교' : `비교하려면 같은 조건의 경기 ${Math.max(0,6-result.count)}개가 더 필요합니다.`}`, 'evidence-note'));
  if (!result.metrics) return;
  const wrap = node('div', undefined, 'table-scroll'), table = node('table'), header = node('tr');
  table.append(node('caption', '내 경기 평균의 관측 변화 · 검증되지 않은 직접 입력'));
  ['지표','직전 3경기','최근 3경기','차이'].forEach(label => header.append(node('th', label))); const head = node('thead'); head.append(header); table.append(head); const body = node('tbody');
  Object.entries(result.metrics).forEach(([key,value]) => {
    const scale = key === 'kill_participation' ? 100 : 1, suffix = key === 'kill_participation' ? '%' : '';
    const display = item => item.value === null ? `계산 불가 (n=${item.n})` : `${(item.value*scale).toFixed(2)}${suffix} (n=${item.n})`;
    const delta = value.recent.value === null || value.previous.value === null ? '계산 불가' : `${((value.recent.value-value.previous.value)*scale).toFixed(2)}${key === 'kill_participation' ? '%p' : ''}`;
    const row = node('tr'); [metricLabels[key],display(value.previous),display(value.recent),delta].forEach(text => row.append(node('td',text))); body.append(row);
  }); table.append(body); wrap.append(table); box.append(wrap);
}
$('comparison-group').addEventListener('change', renderComparison);
$('report-metric').addEventListener('change',renderPersonalAnalysis);
function renderTasks() {
  const records = journal.read(), tasks = window.PersonalAnalysis.tasks(records), box = $('next-game-tasks');
  box.replaceChildren();
  if (!tasks.length) {
    const empty = node('div',undefined,'task-empty');
    empty.append(node('strong',records.length ? '남긴 과제를 모두 돌아봤어요.' : '아직 남겨둔 과제가 없어요.'),node('p','기존 복기 기록의 과제를 다시 확인하는 곳입니다. 새 행동은 내 전적·리포트의 행동 노트에 기록하세요.','muted')); box.append(empty); return;
  }
  tasks.forEach(record => {
    const item = node('div',undefined,'task-item'), meta = node('div',undefined,'task-meta');
    meta.append(championPortrait(record.context.champion_id),node('span',`${record.context.champion_name} · ${record.context.role}`),actionPill(record));
    item.append(meta,node('p',record.action));
    const buttons = node('div',undefined,'task-buttons'), reuse = node('button','행동 노트에 가져오기','text-button');
    reuse.addEventListener('click',() => reusePractice(record.action));
    const open = node('button','기록 열어 돌아보기','text-button');
    open.addEventListener('click',() => {
      $('journal-search').value = ''; $('journal-state').value = ''; sessionLimit = journal.MAX_RECORDS;
      renderSessions(journal.read());
      const row = [...$('session-list').children].find(row => row.dataset.recordId === journal.id(record.context));
      if (row) { row.querySelector('button').click(); row.scrollIntoView({block:'center'}); }
    });
    buttons.append(reuse,open); item.append(buttons); box.append(item);
  });
}
function renderPersonalAnalysis() {
  const report = window.PersonalAnalysis.report(journal.read(),$('comparison-group').value,$('report-metric').value), box = $('personal-analysis');
  box.replaceChildren();
  if (!report.count) {
    box.append(node('div','기존 복기 기록 또는 경기 백업을 불러오면 같은 조건의 수치 추이를 확인할 수 있습니다. 전적 리포트의 이전 경기 비교는 내 전적·리포트에서 확인하세요.','empty-state')); return;
  }
  const body = node('div',undefined,'report-body'), chartBox = node('div'), title = node('div',undefined,'chart-heading');
  title.append(node('strong',`${report.info.label} 추이`),node('small',`최근 ${report.trend.length}경기 · 시간순`)); chartBox.append(title);
  const chart = node('div',undefined,'trend-chart'); chart.setAttribute('aria-hidden','true');
  const finite = report.trend.map(item=>item.value).filter(Number.isFinite), max = Math.max(...finite,1);
  const scale = report.metric === 'kill_participation' ? 100 : 1, suffix = scale === 100 ? '%' : '';
  const format = value => Number.isFinite(value) ? `${(value*scale).toLocaleString('ko-KR',{maximumFractionDigits:2})}${suffix}` : '계산 불가';
  const values = node('details',undefined,'trend-values'); values.append(node('summary','경기별 수치 보기'));
  const tableWrap = node('div',undefined,'table-scroll'), table = node('table'), head = node('thead'), tr = node('tr'), tbody = node('tbody');
  table.append(node('caption',`${report.info.label} · 내 경기 기록`)); ['경기 일시','수치'].forEach(text=>tr.append(node('th',text))); head.append(tr); table.append(head);
  report.trend.forEach(item => {
    const column = node('div',undefined,'trend-column'), bar = node('div',undefined,'bar'), date = new Date(item.played_at);
    bar.style.height = Number.isFinite(item.value) ? `${item.value/max*90}px` : '0px';
    column.append(node('span',item.value === null ? '—' : format(item.value),'value'),bar,node('span',`${date.getMonth()+1}/${date.getDate()}`,'date')); chart.append(column);
    const row = node('tr'); row.append(node('td',date.toLocaleString('ko-KR')),node('td',format(item.value))); tbody.append(row);
  });
  table.append(tbody); tableWrap.append(table); values.append(tableWrap); chartBox.append(chart,values);
  const note = node('div',undefined,'analysis-question'), image = node('img',undefined,'focus-image'); image.src = `/assets/images/game/${report.info.image}`; image.alt = ''; image.width=29; image.height=29;
  const label = node('div'); label.append(image,node('span','수치에서 장면으로','eyebrow')); note.append(label);
  const summary = report.comparison.metrics?.[report.metric];
  if (summary && summary.recent.value !== null && summary.previous.value !== null) {
    const difference = (summary.recent.value-summary.previous.value)*scale;
    note.append(node('h3',`최근 평균 ${format(summary.recent.value)}`),node('p',`직전 평균 ${format(summary.previous.value)} → 차이 ${difference > 0 ? '+' : ''}${difference.toFixed(2)}${scale === 100 ? '%p' : ''} (유효 n=${summary.previous.n} / ${summary.recent.n})`,'muted'));
  } else if (report.count < 6) note.append(node('h3','이번 조건의 기록을 쌓는 중'),node('p',`같은 조건 ${report.count}경기 · 평균 비교까지 ${6-report.count}경기 더 필요합니다.`,'muted'));
  else note.append(node('h3','평균을 계산할 수 없습니다.'),node('p','최근 또는 직전 구간에 유효한 수치가 없습니다. 경기별 수치에서 계산 불가 항목을 확인해주세요.','muted'));
  note.append(node('p',report.info.question),node('p',`이 조건에서 아직 돌아보지 않은 과제 ${report.pending}개 · 수치의 차이는 원인을 확정하지 않습니다.`,'muted'));
  const review = node('button','이 질문을 행동 노트로 가져오기','text-button');
  review.addEventListener('click',()=>reusePractice(report.info.question));
  note.append(review); body.append(chartBox,note); box.append(body);
}
function reusePractice(text) {
  page('review');
  if (text.length > $('practice-note').maxLength) {
    $('note-status').textContent='200자를 넘는 내용은 기존 기록에서 확인하고, 이번 경기에서 실행할 행동 하나로 줄여 적어주세요. 기존 내용은 유지했습니다.';
  } else {
    $('practice-note').value=text;
    $('note-status').textContent='기존 내용을 가져왔습니다. 이번 경기에서 확인할 행동을 정리한 뒤 기록하세요.';
  }
  $('practice-note').scrollIntoView({block:'center'}); $('practice-note').focus();
}
async function loadRiotStatus() {
  try { const data = await api('/api/riot/status'); $('riot-status').textContent = data.configured ? 'KR 솔로듀오 전적 연결 · 조회 시 연결 상태를 확인합니다.' : '전적 연결 설정이 필요합니다. 아래 연결 안내를 확인해주세요.'; }
  catch(error) { $('riot-status').textContent = error.message; }
}
let recentReportItems = [], autoReportSequence=0, localCoachAvailable=false;
function reportOutcome(item) {return item.win === true ? '승리' : item.win === false ? '패배' : '결과 미확인';}
function renderAutoReport(item, peers = []) {
  const sequence=++autoReportSequence;
  const box = $('auto-report'); box.replaceChildren();
  if (!item.report) {box.append(node('p','리포트를 생성하지 못했습니다. 전적을 다시 조회해주세요.','error-text')); return;}
  const report = item.report, heading = node('div',undefined,'auto-match-heading'), title = node('div');
  title.append(node('h3',`${item.champion_name} · ${item.role}`),node('p',`${new Date(item.played_at).toLocaleString('ko-KR')} · ${item.duration_minutes}분 · KR 솔로듀오 · ${item.patch}`,'muted'));
  const championInfo=node('button','챔피언 정보 →','text-button');championInfo.addEventListener('click',()=>{page('champions');window.ChampionInsights?.champion(item.champion_id);});title.append(championInfo);
  heading.append(championPortrait(item.champion_id),title,node('span',reportOutcome(item),'outcome '+(item.win === true ? 'win' : item.win === false ? 'loss' : ''))); box.append(heading);
  const metrics = node('div',undefined,'auto-report-metrics');
  const labels = {gpm:'분당 골드',dpm:'분당 챔피언 피해',vision_per_minute:'분당 시야',kill_participation:'킬 관여율',cs_per_minute:'분당 CS',damage_share:'팀 내 피해 비중'};
  const format = (key,value) => value === null ? '—' : ['kill_participation','damage_share'].includes(key) ? `${(value*100).toFixed(1)}%` : String(value);
  Object.entries(labels).forEach(([key,label]) => metrics.append(metric(label,format(key,report.metrics[key]),''))); box.append(metrics,node('p','경기 전체 종료 수치 · CS는 정글 몬스터 포함 · 피해 비중은 아군 합계 대비 · 분모가 0이면 —','metric-context muted'));
  const tabs=node('div',undefined,'report-tabs'), overviewPane=node('section'), teamPane=node('section'), flowPane=node('section'); tabs.setAttribute('role','tablist'); tabs.setAttribute('aria-label','경기 분석 보기');
  let flowLoaded=false;
  [overviewPane,teamPane,flowPane].forEach((pane,i)=>{pane.id=`report-pane-${sequence}-${i}`;pane.setAttribute('role','tabpanel');pane.hidden=i!==0;});
  ['핵심 요약','팀 비교','시간대별 흐름'].forEach((label,i)=>{const button=node('button',label);button.id=`report-tab-${sequence}-${i}`;button.setAttribute('role','tab');button.setAttribute('aria-selected',String(i===0));button.setAttribute('aria-controls',`report-pane-${sequence}-${i}`);button.tabIndex=i===0?0:-1;
    [overviewPane,teamPane,flowPane][i].setAttribute('aria-labelledby',button.id);
    button.addEventListener('click',()=>{[overviewPane,teamPane,flowPane].forEach((pane,j)=>pane.hidden=i!==j);tabs.querySelectorAll('button').forEach((b,j)=>{b.setAttribute('aria-selected',String(i===j));b.tabIndex=i===j?0:-1;});if(i===2 && !flowLoaded){flowLoaded=true;renderMatchFlow(flowPane,item,sequence);}});tabs.append(button);
  });
  tabs.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...tabs.querySelectorAll('button')],i=buttons.indexOf(document.activeElement),next=event.key==='Home'?0:event.key==='End'?2:(i+(event.key==='ArrowRight'?1:-1)+3)%3;buttons[next].focus();buttons[next].click();});
  box.append(tabs,overviewPane,teamPane,flowPane); renderMatchTeam(teamPane,item);
  const grid = node('div',undefined,'report-insights'), facts = node('section'), questions = node('section');
  facts.append(node('h3','수치에서 확인한 사실'));
  const list = node('ul'); report.facts.forEach(text => list.append(node('li',text))); facts.append(list);
  questions.append(node('p','복기할 장면','section-kicker'),node('h3',report.focus.label));
  report.questions.forEach(text => questions.append(node('p',text))); questions.append(node('div',report.next_step,'answer-step')); grid.append(facts,questions); overviewPane.append(grid);
  const compatible = peers.filter(other => other !== item && other.champion_id===item.champion_id && other.role===item.role && other.patch===item.patch && Date.parse(other.played_at)<Date.parse(item.played_at));
  const comparison = node('section',undefined,'auto-comparison'); comparison.append(node('h3','같은 조건의 이전 경기'));
  if (compatible.length) {
    const table = node('table'), head = node('tr'); ['지표','이번 경기',`이전 ${compatible.length}경기 평균`,'차이'].forEach(t=>head.append(node('th',t))); const thead=node('thead'); thead.append(head); table.append(thead);
    const body=node('tbody'); ['gpm','dpm','vision_per_minute','kill_participation'].forEach(key => {
      const values=compatible.map(x=>x.report?.metrics[key]).filter(x=>Number.isFinite(x)), current=report.metrics[key], average=values.length ? values.reduce((a,b)=>a+b,0)/values.length : null;
      const row=node('tr'), difference=current!==null && average!==null ? current-average : null;
      const decimals=key==='vision_per_minute'?2:1, delta=difference===null?null:Number((difference*(key==='kill_participation'?100:1)).toFixed(decimals));
      [labels[key],format(key,current),average===null ? '—' : format(key,Number(average.toFixed(3))),delta===null ? '—' : `${delta>0?'+':''}${delta.toFixed(decimals)}${key==='kill_participation'?'%p':''}`].forEach(t=>row.append(node('td',t))); body.append(row);
    }); table.append(body); const wrap=node('div',undefined,'table-scroll'); wrap.append(table); comparison.append(wrap,node('p',`같은 챔피언·포지션·패치의 이전 ${compatible.length}경기만 사용합니다. 경기 당시 티어는 알 수 없고, 평균의 차이가 실력 변화나 승패 원인을 뜻하지는 않습니다.`,'muted'));
  } else comparison.append(node('p','이번에 불러온 경기 안에 같은 챔피언·포지션·패치의 이전 경기가 없습니다. 비교 가능한 경기가 생기면 자동으로 표시합니다.','muted'));
  overviewPane.append(comparison);
  const ai=node('section',undefined,'local-coach-panel'), aiButton=node('button','로컬 AI 복기 제안 · 실험','text-button'), aiResult=node('div'); aiResult.setAttribute('aria-live','polite'); aiButton.hidden=!localCoachAvailable; aiButton.dataset.localCoach='true';
  aiButton.addEventListener('click',async()=>{
    aiButton.disabled=true; aiResult.replaceChildren(node('p','이 컴퓨터에서 복기 초점을 검토하고 있습니다.','muted'));
    try {
      const result=await api('/api/riot/coach',{role:item.role,metrics:report.metrics});
      if (sequence!==autoReportSequence) return;
      aiResult.replaceChildren(node('h3',result.label),node('p',result.caveat,'muted'));
      if (result.model) aiResult.append(node('p',`${result.model} · 이 컴퓨터에서 실행`,'muted'));
      aiResult.append(node('p',`참고 지표: ${result.evidence_keys.map(key=>`${labels[key]} ${format(key,report.metrics[key])}`).join(' · ')}`,'muted'));
      result.questions.forEach(text=>aiResult.append(node('p',text))); aiResult.append(node('div',result.next_step,'answer-step'));
    } catch(error) {if (sequence===autoReportSequence) aiResult.replaceChildren(node('p',error.message,'muted'));}
    finally {aiButton.disabled=false;}
  }); ai.append(aiButton,aiResult); overviewPane.append(ai);
  const tools=node('div',undefined,'auto-report-tools'), keep=node('button','이 리포트 보관','primary'), status=node('p','별도 입력 없이 보관할 수 있습니다. 이 브라우저에 최대 50경기 보관하며, Riot ID·PUUID는 저장하지 않습니다.','muted'); status.setAttribute('role','status');
  keep.addEventListener('click',()=> {try {window.MatchReports.save(item); status.textContent='경기 리포트를 보관했습니다. 보관함에서 다시 열 수 있습니다.'; renderSavedReports();} catch(error) {status.textContent=error.message || '브라우저 저장 공간을 확인해주세요.';}});
  tools.append(keep); box.append(tools,status); const limits=node('details',undefined,'report-method'); limits.append(node('summary','분석 기준과 확인 범위')); report.limitations.forEach(text=>limits.append(node('p',text,'muted'))); box.append(limits);
}
function renderSavedReports() {
  const box=$('saved-reports'); box.replaceChildren();
  try {
    const items=window.MatchReports.read(); $('saved-report-count').textContent=`${items.length} / 50경기`;
    if (!items.length) {box.append(node('p','전적을 불러오고 리포트를 보관하면, 다음 방문에도 여기에서 다시 볼 수 있습니다.','muted')); return;}
    items.forEach(item=>{
      const row=node('div',undefined,'saved-report-row'), text=node('div'); text.append(node('strong',`${item.champion_name} · ${item.role}`),node('small',`${new Date(item.played_at).toLocaleString('ko-KR')} · ${reportOutcome(item)}`));
      const open=node('button','리포트 보기','text-button'); open.addEventListener('click',()=>{page('review'); $('riot-matches').querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed','false')); renderAutoReport(item); $('auto-report-card').scrollIntoView({block:'start'});});
      const remove=node('button','삭제','text-button'); remove.setAttribute('aria-label',`${item.champion_name} ${new Date(item.played_at).toLocaleString('ko-KR')} 리포트 삭제`); remove.addEventListener('click',()=>{try {window.MatchReports.remove(item); renderSavedReports(); $('report-library-status').textContent='선택한 리포트를 삭제했습니다.';} catch(error) {$('report-library-status').textContent=error.message;}});
      row.append(championPortrait(item.champion_id),text,open,remove); box.append(row);
    });
  } catch(error) {$('report-library-status').textContent=error.message || '보관한 리포트를 읽지 못했습니다.';}
}
$('riot-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('riot-error').textContent = ''; $('riot-matches').replaceChildren();
  recentReportItems=[]; autoReportSequence++; $('account-summary').hidden=true; $('recent-role').value=''; $('riot-matches').append(node('p','최근 경기를 불러오는 중입니다.','muted')); $('auto-report').replaceChildren(node('p','최근 경기를 불러와 리포트를 만드는 중입니다.','empty-state'));
  try {
    const data = await api('/api/riot/recent', Object.fromEntries(new FormData(event.target))), box = $('riot-matches'); box.replaceChildren();
    renderAccountSummary(data);
    if (data.items.length) {
      const wins=data.items.filter(item=>item.win===true).length, losses=data.items.filter(item=>item.win===false).length;
      const known=wins+losses, unknown=data.items.length-known, summary=node('div',undefined,'recent-summary');
      summary.append(node('span',`${data.items.length}경기 요약`),node('strong',`${wins}승 ${losses}패`));
      summary.append(node('span',known ? `승률 ${(wins/known*100).toFixed(0)}%` : '승률 —'));
      if (unknown) summary.append(node('small',`결과 미확인 ${unknown}경기 · 승률에서 제외`));
      $('account-summary').prepend(summary);
    }
    if (!data.items.length) box.append(node('p', '불러올 수 있는 최근 KR 솔로듀오 완료 경기가 없습니다.'));
    recentReportItems = data.items;
    data.items.forEach(item => {
      const row = node('div', undefined, 'match-import'), select=node('button',undefined,'match-select');
      row.dataset.role=item.role;
      const date=new Date(item.played_at).toLocaleDateString('ko-KR',{month:'numeric',day:'numeric'});
      const label=`${item.champion_name} · ${item.role} · ${reportOutcome(item)} · ${date} 분석 리포트`;
      if (item.win===true) row.classList.add('match-win');
      else if (item.win===false) row.classList.add('match-loss');
      select.setAttribute('aria-label',label); select.setAttribute('aria-pressed','false');
      const text=node('span',undefined,'match-summary'), meta=node('span',undefined,'match-meta');
      text.append(node('strong',item.champion_name),node('span',`${item.role} · ${item.duration_minutes}분`));
      const kda=[item.kills,item.deaths,item.assists].map(value=>value===null || value===undefined?'—':value).join(' / ');
      text.append(node('span',`${kda} KDA`,'match-kda'));
      meta.append(node('strong',reportOutcome(item)),node('span',date));
      select.append(championPortrait(item.champion_id),text,meta);
      select.addEventListener('click', () => {
        box.querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button===select)));
        renderAutoReport(item,recentReportItems);
        if (window.matchMedia('(max-width: 1000px)').matches) $('auto-report-card').scrollIntoView({block:'start'});
      }); row.append(select); box.append(row);
    });
    if (data.items.length) {renderAutoReport(data.items[0],recentReportItems); box.querySelector('button').setAttribute('aria-pressed','true');}
    else $('auto-report').replaceChildren(node('p','지원하는 최근 완료 경기가 없습니다.','empty-state'));
  } catch(error) { $('riot-error').textContent = error.message; $('riot-matches').replaceChildren(node('p','경기를 불러오지 못했습니다. 연결 상태를 확인하고 다시 조회해주세요.','muted')); $('auto-report').replaceChildren(node('p','전적을 불러오지 못했습니다. 위의 연결 안내를 확인하고 다시 조회해주세요.','empty-state')); } finally {button.disabled = false;}
});
window.addEventListener('storage',event=>{if (event.key==='lol-match-reports-v1' || event.key===null) renderSavedReports();});
  api('/api/riot/coach/status').then(data=>{localCoachAvailable=data.available; document.querySelectorAll('[data-local-coach]').forEach(button=>{button.hidden=!localCoachAvailable;});}).catch(()=>{});
let publicFlowData = null;
function renderPublicFlow() {
  if (!publicFlowData) return;
  const selected = publicFlowData.phases.find(item => item.phase === Number($('public-phase').value));
  if (!selected) return;
  $('public-flow-metrics').replaceChildren(
    metric('검증한 공통 경기',`${selected.n.toLocaleString()}경기`,'5개 시점에 모두 있는 경기'),
    metric('해당 프레임 시각 중앙값',`${selected.median_elapsed_minutes}분`,'고정 시각이 아닌 비율별 시점'),
    metric('팀 골드 격차 중앙값',`${selected.median_abs_gold_gap.toLocaleString()}G`,'블루·레드 차이의 절댓값'));
  const table = node('table'), head = node('thead'), heading = node('tr'), body = node('tbody');
  table.append(node('caption','블루팀 기준 골드 차이와 최종 결과 · 30경기 미만은 승률 보류'));
  ['당시 골드 차이','경기 수','관측 승률'].forEach(text=>heading.append(node('th',text))); head.append(heading); table.append(head);
  selected.buckets.forEach(item=> {
    const row = node('tr');
    [item.label,item.n.toLocaleString(),item.blue_win_pct === null ? '표본 부족' : `${item.blue_win_pct}%`].forEach(value=>row.append(node('td',value)));
    body.append(row);
  });
  table.append(body); $('public-flow-table').replaceChildren(table);
}
async function loadPublicData() {
  try {
    const data = await api('/api/public-data'), flow = data.flow;
    publicFlowData = flow;
    $('public-data-status').textContent = `${flow.source.period} · ${flow.audit.included_matches.toLocaleString()}개 검증 경기 · 개인 비교 기준 아님`;
    const source = $('public-flow-source'); source.replaceChildren();
    source.append(externalLink(flow.source.title,flow.source.url),node('p',`${flow.source.authors.join(' · ')} · ${flow.source.license}`,'muted'),externalLink('라이선스와 출처 표시 조건',flow.source.license_url));
    source.append(node('p',`${flow.source.transformation}. 5~90분 경기만 포함하고, 시점 오차가 1.1분을 넘거나 결과·누적 골드가 불일치하는 경기는 제외합니다. 최종 100% 시점은 결과 관계 분석에서 제외했습니다.`,'muted'));
    const notes = node('ul'); flow.limitations.forEach(text=>notes.append(node('li',text))); source.append(notes);
    const audit = flow.audit;
    source.append(node('p',`원본 시점별 ${audit.phases['20'].input_rows.toLocaleString()}행 → 공통 ${audit.included_matches.toLocaleString()}경기. 5~90분 범위 밖 ${audit.phases['20'].invalid_rows.toLocaleString()}경기, 최종 프레임 시각 불일치 ${audit.phases['100'].invalid_reasons.frame_time_mismatch || 0}경기 제외. 파일 해시 확인 후 집계했습니다.`,'muted'));
    const catalogue = $('public-data-sources'); catalogue.replaceChildren(node('p',`확인 ${data.sources.checked_at} · ${data.sources.items.length}개 출처. 반영·후보·보류를 구분합니다.`,'muted'));
    data.sources.items.forEach(item=> {
      const row = node('article',undefined,'data-source-row');
      row.append(externalLink(item.title,item.url),node('span',item.status,'state-pill'),node('p',`${item.period} · ${item.license}`,'muted'),node('p',item.use),node('p',item.limits,'muted'));
      catalogue.append(row);
    });
    $('public-flow-content').hidden = false; renderPublicFlow();
  } catch {
    $('public-data-status').textContent = '공개 참고 자료를 불러오지 못했습니다. 서버의 집계 파일을 확인해주세요. 개인 복기 기능은 계속 사용할 수 있습니다.';
  }
}
$('public-phase').addEventListener('change',renderPublicFlow);
page('review'); renderNotes(); renderJournal(); load(); loadRiotStatus(); loadPublicData();
