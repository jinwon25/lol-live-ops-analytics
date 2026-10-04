'use strict';
const $ = id => document.getElementById(id);
let selectedChampion = null, reviewIsExample = false, championRequest = 0;
let championItems = [], overviewData = null;
function node(tag, text, className) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (className) item.className = className;
  return item;
}
async function api(path, payload) {
  const response = await fetch(path, payload ? {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)} : {});
  if (!response.ok) throw new Error(response.status === 422 ? '입력 범위와 킬·도움·팀 킬 수를 확인해주세요.' : '자료를 불러오지 못했습니다. 서버 연결과 자료 파일을 확인해주세요.');
  return response.json();
}
function externalLink(title, href) {
  const link = node('a', title + ' ↗');
  const url = new URL(href);
  const allowed = ['github.com','ddragon.leagueoflegends.com','developer.riotgames.com','www.leagueoflegends.com'];
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
    const [data, champs] = await Promise.all([api('/api/overview'), api('/api/champions')]);
    overviewData = data; championItems = champs.items;
    $('data-status').textContent = `공식 정적 자료 ${data.static_data.version} · 기존 경기 분석 15.1↔15.3 (2025년 초, EUN) · 실시간 전적 미연결`;
    $('overview-metrics').replaceChildren(metric('기존 분석 경기', data.historic_matches.toLocaleString(), '두 패치 EUN 솔로듀오'), metric('공식 챔피언 정적 자료', data.static_data.version, 'KR realm · 한국어'), metric('공식 패치 노트', data.patch_notes.patch, `확인일 ${data.patch_notes.checked}`));
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
  const values = {role:'MID',duration_minutes:30,gold:12000,damage:21000,vision:24,kills:5,assists:8,team_kills:24};
  for (const [key,value] of Object.entries(values)) $('review-form').elements[key].value = value;
  reviewIsExample = true; $('review-source').textContent = '합성 예제 · 실제 플레이어의 전적이 아닙니다.';
});
$('review-form').addEventListener('input', () => {reviewIsExample = false; $('review-source').textContent = '직접 입력 · 전적 검증 전';});
$('review-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('review-error').textContent = '';
  const values = Object.fromEntries(new FormData(event.target));
  Object.keys(values).filter(key => key !== 'role').forEach(key => values[key] = Number(values[key])); values.is_example = reviewIsExample;
  try {
    const data = await api('/api/review', values), box = $('review-result'); box.replaceChildren(node('span', data.source, 'answer-label'));
    const metrics = node('div', undefined, 'review-metrics');
    metrics.append(metric('분당 골드', data.metrics.gpm, '획득 골드 / 시간'), metric('분당 챔피언 피해량', data.metrics.dpm, '챔피언 피해 / 시간'), metric('분당 시야 점수', data.metrics.vision_per_minute, '시야 점수 / 시간'), metric('킬 관여율', data.metrics.kill_participation === null ? '계산 불가' : `${(data.metrics.kill_participation*100).toFixed(1)}%`, '팀 킬 0이면 미정의'));
    box.append(metrics, node('p', data.explanation, 'muted')); const list = node('ul'); data.questions.forEach(question => list.append(node('li', question))); box.append(list);
  } catch(error) { $('review-error').textContent = error.message; } finally {button.disabled = false;}
});
$('assistant-form').addEventListener('submit', async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true; $('assistant-error').textContent = '';
  try {
    const data = await api('/api/assistant', {question:$('assistant-question').value,champion_id:selectedChampion}); const box = $('assistant-answer'); box.replaceChildren();
    box.append(node('span', data.status === 'insufficient_data' ? '추가 자료가 필요한 답변' : '등록된 분석 근거로 확인한 답변', 'answer-label'), node('p', data.answer));
    box.append(node('p', `${data.scope.region} · ${data.scope.patches.join(' / ')} · ${data.scope.cohort}`, 'evidence-note'));
    const sources = node('div', undefined, 'source-list'); data.sources.forEach(source => sources.append(externalLink(source.title, source.url))); box.append(sources);
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
page('overview'); renderNotes(); load();
