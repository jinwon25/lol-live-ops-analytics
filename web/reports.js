'use strict';
/* 식별자 없이 사용자가 선택한 경기 리포트만 보관한다. 기존 수동 복기 기록과 별개다. */
(() => {
  const KEY = 'lol-match-reports-v1', MAX = 50;
  const fields = ['champion_id','champion_name','region','queue','role','patch','played_at','duration_minutes','gold','damage','vision','kills','assists','team_kills','win','deaths','cs','team_damage'];
  const metricKeys = ['gpm','dpm','vision_per_minute','kill_participation','cs_per_minute','damage_share'];
  const text = (v, max = 600) => typeof v === 'string' && v.length > 0 && v.length <= max;
  function clean(item) {
    if (!item || !text(item.champion_id,40) || !text(item.champion_name,60) || item.region !== 'KR' || item.queue !== 'RANKED_SOLO' ||
        !['TOP','JUNGLE','MID','BOT','SUPPORT'].includes(item.role) || !/^\d{2}\.\d{1,2}$/.test(item.patch || '') ||
        !text(item.played_at,40) || !Number.isFinite(Date.parse(item.played_at)) || !Number.isFinite(item.duration_minutes) || item.duration_minutes < 5 || item.duration_minutes > 90) return null;
    const report = item.report;
    if (!report || report.version !== 1 || !report.metrics || !['vision','resource','fight_setup','matchup'].includes(report.focus?.id) || !text(report.focus.label,100) || !text(report.next_step)) return null;
    const arrays = ['facts','questions','limitations'];
    if (arrays.some(k => !Array.isArray(report[k]) || report[k].length > 10 || report[k].some(v => !text(v)))) return null;
    if (metricKeys.some(k => report.metrics[k] !== null && (!Number.isFinite(report.metrics[k]) || report.metrics[k] < 0))) return null;
    if (['kill_participation','damage_share'].some(k => report.metrics[k] !== null && report.metrics[k] > 1)) return null;
    if (['gold','damage','vision','kills','assists','team_kills'].some(k => !Number.isFinite(item[k]) || item[k] < 0)) return null;
    const out = {};
    fields.forEach(k => {out[k] = typeof item[k] === 'number' || typeof item[k] === 'boolean' || typeof item[k] === 'string' ? item[k] : null;});
    out.report = {version:1,metrics:Object.fromEntries(metricKeys.map(k => [k,report.metrics[k]])),focus:{id:report.focus.id,label:report.focus.label},next_step:report.next_step};
    arrays.forEach(k => {out.report[k] = [...report[k]];});
    return out;
  }
  const identity = x => [x.played_at,x.champion_id,x.role,x.patch].join('|');
  function read() {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    if (raw.length > 1024 * 1024) throw new Error('보관한 리포트가 너무 큽니다. 브라우저 저장소를 확인해주세요.');
    const rows = JSON.parse(raw);
    if (!Array.isArray(rows) || rows.length > MAX || rows.some(x => !clean(x))) throw new Error('보관한 리포트 형식을 확인할 수 없습니다. 기존 자료는 덮어쓰지 않았습니다.');
    return rows.map(clean).sort((a,b) => Date.parse(b.played_at)-Date.parse(a.played_at));
  }
  function save(item) {
    const row = clean(item);
    if (!row) throw new Error('검증 가능한 공식 경기 리포트만 보관할 수 있습니다.');
    const rows = read().filter(x => identity(x) !== identity(row)); rows.push(row);
    if (rows.length > MAX) throw new Error('리포트는 50경기까지 보관합니다. 필요 없는 리포트를 삭제한 뒤 다시 저장해주세요.');
    localStorage.setItem(KEY,JSON.stringify(rows));
  }
  function remove(item) {localStorage.setItem(KEY,JSON.stringify(read().filter(x => identity(x) !== identity(item))));}
  window.MatchReports = {read,save,remove,clean};
})();
