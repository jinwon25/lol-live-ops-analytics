'use strict';
const $ = id => document.getElementById(id);
let selectedChampion = null, reviewIsExample = false, championRequest = 0, reviewSequence = 0;
let championItems = [], overviewData = null, reviewResult = null, preferences = {};
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
async function api(path, payload) {
  const response = await fetch(path, payload ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)} : {});
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(typeof detail.detail === 'string' ? detail.detail : response.status === 422 ? '입력 범위·킬/도움·경기 일시와 조건을 확인해주세요.' : '자료를 불러오지 못했습니다. 서버 연결을 확인해주세요.');
  }
  return response.json();
}
function externalLink(title, href) {
  const link = node('a', title + ' ↗');
  const url = new URL(href);
  const allowed = ['github.com','ddragon.leagueoflegends.com','developer.riotgames.com','www.leagueoflegends.com','lol.ps','www.fow.lol'];
  if (url.protocol !== 'https:' || !allowed.includes(url.hostname)) return node('span', title);
  link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
  return link;
}
function page(name) {
  document.querySelectorAll('[role=tabpanel]').forEach(item => item.hidden = item.id !== name);
  document.querySelectorAll('nav [role=tab]').forEach(item => {
    const selected = item.dataset.page === name;
    item.setAttribute('aria-selected', String(selected)); item.tabIndex = selected ? 0 : -1;
  });
}
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => page(button.dataset.page)));
document.querySelectorAll('[data-open]').forEach(button => button.addEventListener('click', () => page(button.dataset.open)));
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
      $('personal-context').textContent = `현재 기본 조건: ${preferences.region} · ${preferences.tier} ${preferences.division} · ${preferences.role} · ${names}. 과거 경기의 조건은 별도로 확인해주세요.`;
      ['region','queue','tier','role'].forEach(key => $('review-form').elements[key].value = preferences[key]);
      champs.items.sort((a,b) => Number(preferences.champions.includes(b.id)) - Number(preferences.champions.includes(a.id)));
    }
    overviewData = data; championItems = champs.items;
    $('data-status').textContent = `공식 정적 자료 ${data.static_data.version} · 기존 경기 분석 15.1↔15.3 (2025년 초, EUN) · 실시간 전적 미연결`;
    $('review-champion').replaceChildren(node('option', '선택해 주세요'));
    $('review-champion').firstChild.value = '';
    champs.items.forEach(item => { const option = node('option', item.name); option.value = item.id; $('review-champion').append(option); });
    renderJournal();
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
  } catch(error) { $('error-banner').hidden = false; $('error-text').textContent = error.message; $('data-status').textContent = '자료 연결 확인이 필요합니다.'; }
}
$('retry').addEventListener('click', load);
function renderChampions() {
  const query = $('champion-search').value.trim().toLowerCase();
  const items = championItems.filter(item => item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query));
  $('champion-list').replaceChildren();
  items.forEach(item => {
    const button = node('button', item.name, 'champion-button' + (selectedChampion === item.id ? ' active' : ''));
    button.setAttribute('aria-pressed', String(selectedChampion === item.id)); button.addEventListener('click', () => selectChampion(item.id)); $('champion-list').append(button);
  });
  if (!items.length) $('champion-list').append(node('p', '검색 결과가 없습니다.', 'muted'));
}
$('champion-search').addEventListener('input', renderChampions);
async function selectChampion(id) {
  const sequence = ++championRequest;
  try {
    const data = await api(`/api/champions/${encodeURIComponent(id)}`);
    if (sequence !== championRequest) return;
    selectedChampion = id; renderChampions(); const detail = $('champion-detail'); detail.replaceChildren();
    detail.append(node('p', `공식 정적 자료 ${data.static_version}`, 'eyebrow'), node('h2', data.champion.name));
    const tags = node('div'); data.champion.tags.forEach(tag => tags.append(node('span', tag, 'tag'))); detail.append(tags, node('p', '공식 분류 태그입니다. 역할·추천 순위와는 별개입니다.', 'muted'));
    const stats = data.champion.stats; detail.append(node('p', `기본 체력 ${stats.hp} · 기본 공격력 ${stats.attackdamage} · 이동 속도 ${stats.movespeed}`, 'muted'));
    const visible = data.history.filter(item => Number(item.pick_count) >= data.minimum_display_rows);
    if (visible.length) {
      const wrap = node('div', undefined, 'table-scroll'), table = node('table'), head = node('thead'), header = node('tr');
      table.append(node('caption', '과거 코호트 관측 · 15.1 / 15.3'));
      ['패치','역할','참여 행','관측 승률','Wilson 하한'].forEach(text => header.append(node('th', text))); head.append(header); table.append(head); const body = node('tbody');
      visible.forEach(item => {const row = node('tr'); [item.patch,item.role,Number(item.pick_count).toLocaleString(),`${item.win_rate_pct}%`,`${item.wilson_low_pct}%`].forEach(value => row.append(node('td', value))); body.append(row);});
      table.append(body); wrap.append(table); detail.append(wrap);
      detail.append(node('p', '과거 EUN·PLATINUM/EMERALD/DIAMOND 표본입니다. Wilson 하한은 강함의 확정값이나 예측 점수가 아닙니다. 30행 미만 집계는 승률 설명을 보류합니다.', 'muted'));
    } else detail.append(node('div', '표시할 과거 표본이 충분하지 않습니다. 최신 승률은 아직 연결되지 않았습니다.', 'empty-state'));
    const ask = node('button', '이 챔피언의 과거 집계를 도우미에게 묻기', 'text-button'); ask.addEventListener('click', () => {page('assistant'); $('assistant-question').value = '선택한 챔피언의 패치 변화와 승률은?';}); detail.append(ask);
    $('selected-context').textContent = `선택한 챔피언: ${data.champion.name} · 과거 집계만 질문 가능`;
  } catch(error) { if (sequence === championRequest) $('champion-detail').replaceChildren(node('p', error.message, 'error-text')); }
}
$('fill-example').addEventListener('click', () => {
  const values = {role:'MID',champion_id:'Ezreal',region:'KR',queue:'RANKED_SOLO',tier:'SILVER',patch:'16.19',played_at:'2026-09-25T20:00',focus:'vision',duration_minutes:30,gold:12000,damage:21000,vision:24,kills:5,assists:8,team_kills:24};
  for (const [key,value] of Object.entries(values)) $('review-form').elements[key].value = value;
  reviewIsExample = true; invalidateReview(); $('review-source').textContent = '합성 예제 · 수정해도 내 경기 기록으로 저장되지 않습니다.';
});
function invalidateReview() { reviewSequence++; reviewResult = null; $('save-session').disabled = true; }
$('start-personal').addEventListener('click', () => {
  $('review-form').reset(); reviewIsExample = false; invalidateReview();
  ['region','queue','tier','role'].forEach(key => { if (preferences[key]) $('review-form').elements[key].value = preferences[key]; });
  $('scene-note').value = ''; $('next-action').value = '';
  $('review-result').replaceChildren(node('div', '내 완료 경기 수치를 입력하고 요약을 확인해주세요.', 'empty-state'));
  $('review-source').textContent = '직접 입력 · 전적 검증 전';
});
$('review-form').addEventListener('input', invalidateReview);
$('review-form').addEventListener('change', invalidateReview);
$('review-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('review-error').textContent = '';
  const values = Object.fromEntries(new FormData(event.target));
  ['duration_minutes','gold','damage','vision','kills','assists','team_kills'].forEach(key => values[key] = Number(values[key]));
  ['champion_id','region','queue','tier','patch','played_at'].forEach(key => { if (!values[key]) values[key] = null; });
  if (values.played_at) values.played_at = new Date(values.played_at).toISOString();
  values.is_example = reviewIsExample; invalidateReview(); const sequence = reviewSequence;
  try {
    const data = await api('/api/review', values); if (sequence !== reviewSequence) return;
    const box = $('review-result'); box.replaceChildren(node('span', data.source, 'answer-label'));
    const metrics = node('div', undefined, 'review-metrics');
    metrics.append(metric('분당 골드', data.metrics.gpm, '획득 골드 / 시간'), metric('분당 챔피언 피해량', data.metrics.dpm, '챔피언 피해 / 시간'), metric('분당 시야 점수', data.metrics.vision_per_minute, '시야 점수 / 시간'), metric('킬 관여율', data.metrics.kill_participation === null ? '계산 불가' : `${(data.metrics.kill_participation*100).toFixed(1)}%`, '팀 킬 0이면 미정의'));
    box.append(metrics, node('h3', data.focus.label), node('p', data.explanation, 'muted')); const list = node('ul'); data.questions.forEach(question => list.append(node('li', question))); box.append(list, node('p', data.focus.measurement, 'evidence-note'));
    reviewResult = data; $('save-session').disabled = !data.personal_record_eligible;
    $('save-status').textContent = data.is_example ? '합성 예제는 저장되지 않습니다. 내 경기 입력 시작으로 초기화해주세요.' : data.personal_record_eligible ? '장면에서 확인한 사실과 다음 행동을 적고 저장하세요.' : '챔피언·지역·큐·경기 당시 티어·게임 버전·일시를 채우면 저장할 수 있습니다.';
  } catch(error) { if (sequence === reviewSequence) $('review-error').textContent = error.message; } finally {button.disabled = false;}
});
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
function notes() { try {const saved = JSON.parse(localStorage.getItem(NOTE_KEY) || '[]'); return Array.isArray(saved) ? saved.filter(item => typeof item.text === 'string' && item.text.length <= 200).slice(-10) : [];} catch {return [];} }
function renderNotes() { $('practice-list').replaceChildren(); notes().forEach(item => $('practice-list').append(node('li', `${item.date || ''} · ${item.text}`))); }
$('note-form').addEventListener('submit', event => {
  event.preventDefault(); const text = $('practice-note').value.trim(); if (!text) return;
  try {localStorage.setItem(NOTE_KEY, JSON.stringify([...notes(),{date:new Date().toLocaleDateString('ko-KR'),text}].slice(-10))); $('practice-note').value = ''; $('note-status').textContent = '이 브라우저에 기록했습니다. 서버로 전송하지 않습니다.'; renderNotes();} catch {$('note-status').textContent = '브라우저 저장이 제한되어 기록하지 못했습니다.';}
});
$('clear-notes').addEventListener('click', () => {try {localStorage.removeItem(NOTE_KEY); renderNotes(); $('note-status').textContent = '이 브라우저의 복기 기록을 지웠습니다.';} catch {$('note-status').textContent = '브라우저 저장소에 접근하지 못했습니다.';}});
const journal = window.ReviewJournal;
const metricLabels = {gpm:'분당 골드',dpm:'분당 챔피언 피해',vision_per_minute:'분당 시야 점수',kill_participation:'킬 관여율'};
function conditionLabel(c) { return `${c.champion_name} · ${c.role} · ${c.region} · ${c.queue === 'RANKED_SOLO' ? '솔로듀오' : '자유랭크'} · ${c.patch} · ${c.tier}`; }
function renderJournal() {
  const records = journal.read(), selected = $('comparison-group').value, groups = new Map();
  [...records].reverse().forEach(record => groups.set(journal.group(record.context), record.context));
  const picker = $('comparison-group'); picker.replaceChildren();
  if (!groups.size) { const empty = node('option', '아직 저장한 내 경기가 없습니다.'); empty.value = ''; picker.append(empty); }
  [...groups.entries()].forEach(([key,context]) => {const option = node('option', conditionLabel(context)); option.value = key; picker.append(option);});
  if (groups.has(selected)) picker.value = selected;
  $('overview-metrics').replaceChildren(metric('저장한 내 경기', `${records.length}경기`, '직접 입력 · 최근 일시 50개 보관'), metric('복기 행동 기록', `${records.filter(item => item.action.trim()).length}개`, '경기마다 확인할 행동 한 가지'), metric('같은 조건 비교', `${groups.size}개 조건`, '6경기부터 최근 3 / 직전 3 표시'));
  renderComparison(); $('session-list').replaceChildren();
  [...records].reverse().forEach(record => {
    const row = node('li'), c = record.context;
    row.append(node('strong', `${new Date(c.played_at).toLocaleString('ko-KR')} · ${conditionLabel(c)}`), node('p', `확인한 사실: ${record.scene}`), node('p', `다음 행동: ${record.action}`));
    const remove = node('button', '이 경기 삭제', 'text-button'); remove.addEventListener('click', () => {try {journal.remove(journal.id(c)); renderJournal();} catch {$('journal-status').textContent = '브라우저 저장소에 접근하지 못했습니다.';}}); row.append(remove); $('session-list').append(row);
  });
}
function renderComparison() {
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
$('save-session').addEventListener('click', () => {
  if (!reviewResult?.personal_record_eligible || reviewIsExample) return;
  const scene = $('scene-note').value.trim(), action = $('next-action').value.trim();
  if (!scene || !action) { $('save-status').textContent = '장면에서 확인한 사실과 다음 행동을 각각 적어주세요.'; return; }
  try {
    const updated = journal.save({context:reviewResult.context, metrics:reviewResult.metrics, focus:reviewResult.focus.id, is_example:false, scene, action});
    $('save-status').textContent = `${updated ? '같은 조건·일시의 기록을 갱신' : '내 경기 기록을 저장'}했습니다. 이 브라우저에만 보관합니다.`; renderJournal();
  } catch(error) { $('save-status').textContent = error.message || '브라우저 저장에 실패했습니다.'; }
});
async function loadRiotStatus() {
  try { const data = await api('/api/riot/status'); $('riot-status').textContent = data.configured ? '서버 키 설정됨 · 실제 키 유효성은 조회 시 확인합니다.' : '서버 키 미설정 · 실행 안내에서 연결 설정을 확인해주세요.'; }
  catch(error) { $('riot-status').textContent = error.message; }
}
$('riot-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('riot-error').textContent = ''; $('riot-matches').replaceChildren();
  try {
    const data = await api('/api/riot/recent', Object.fromEntries(new FormData(event.target))), box = $('riot-matches');
    box.append(node('p', `${data.source} · ${data.items.length}경기 · 제외 ${data.skipped}경기${data.cached ? ' · 60초 캐시' : ''}`, 'evidence-note'));
    if (data.current_rank) box.append(node('p', `현재 랭크: ${data.current_rank.tier} ${data.current_rank.rank} · ${data.current_rank.leaguePoints}LP. 경기 당시 티어는 따로 확인해주세요.`, 'muted'));
    box.append(node('p', data.caveat, 'muted'));
    if (!data.items.length) box.append(node('p', '불러올 수 있는 최근 KR 솔로듀오 완료 경기가 없습니다.'));
    data.items.forEach(item => {
      const row = node('div', undefined, 'match-import'), label = `${new Date(item.played_at).toLocaleString('ko-KR')} · ${item.champion_name} · ${item.role} · ${item.win ? '승리' : '패배'}`;
      row.append(node('p', label)); const select = node('button', '이 경기 복기하기', 'text-button');
      select.addEventListener('click', () => {
        $('review-form').reset(); reviewIsExample = false; invalidateReview();
        Object.entries(item).forEach(([key,value]) => {if ($('review-form').elements[key] && value !== null) $('review-form').elements[key].value = value;});
        const date = new Date(item.played_at); $('review-form').elements.played_at.value = new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
        $('review-source').textContent = 'Riot API에서 불러온 수치 · 경기 당시 티어를 확인하고 요약해주세요. 수정한 값은 직접 입력으로 취급합니다.';
        $('scene-note').value = ''; $('next-action').value = ''; $('review-result').replaceChildren(node('div', '불러온 경기 조건을 확인하고 요약 버튼을 눌러주세요.', 'empty-state'));
        $('review-form').scrollIntoView({behavior:'smooth',block:'start'});
      }); row.append(select); box.append(row);
    });
  } catch(error) { $('riot-error').textContent = error.message; } finally {button.disabled = false;}
});
page('overview'); renderNotes(); renderJournal(); load(); loadRiotStatus();
