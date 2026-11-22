'use strict';
/* 식별자 없이 사용자가 선택한 경기 리포트만 보관한다. 기존 수동 복기 기록과 별개다. */
(() => {
  const KEY = 'lol-match-reports-v1', MAX = 50;
  const FORMAT = 'lol-insight-match-reports', MAX_BACKUP_BYTES = 4 * 1048576;
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
    if (new Set(rows.map(identity)).size !== rows.length) throw new Error('보관함에 중복된 경기가 있습니다. 기존 자료는 변경하지 않았습니다.');
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
  function undoRemove(item) {
    if (read().some(x => identity(x) === identity(item))) throw new Error('같은 경기가 이미 보관되어 삭제 취소로 덮어쓰지 않았습니다.');
    save(item);
  }
  function backup() {
    return JSON.stringify({format:FORMAT,version:1,exported_at:new Date().toISOString(),reports:read()},null,2);
  }
  function prepareImport(raw) {
    if (typeof raw !== 'string' || new TextEncoder().encode(raw).length > MAX_BACKUP_BYTES) throw new Error('리포트 백업 파일은 4MB 이하여야 합니다.');
    let data;
    try {data = JSON.parse(raw);} catch {throw new Error('JSON 백업 파일을 읽을 수 없습니다.');}
    if (!data || data.format !== FORMAT || data.version !== 1 || !Array.isArray(data.reports) || data.reports.length > MAX || data.reports.some(x => !clean(x)))
      throw new Error('이 서비스에서 내보낸 버전 1 리포트 백업 파일을 선택해주세요.');
    const incoming = data.reports.map(clean);
    if (new Set(incoming.map(identity)).size !== incoming.length) throw new Error('백업 안에 같은 경기가 중복되어 있습니다.');
    const merged = new Map(read().map(x => [identity(x),x]));
    let added = 0;
    incoming.forEach(x => {if (!merged.has(identity(x))) {merged.set(identity(x),x); added++;}});
    if (merged.size > MAX) throw new Error('합치면 50경기를 넘습니다. 백업 후 불필요한 리포트를 정리해주세요. 기존 자료는 유지했습니다.');
    const reports = [...merged.values()];
    if (JSON.stringify(reports).length > 1024 * 1024) throw new Error('복원할 리포트가 보관함 크기 한도를 넘습니다. 기존 자료는 유지했습니다.');
    return {incoming,reports,added,duplicates:incoming.length-added,count:merged.size};
  }
  function restore(preview) {
    // 미리보기 이후 다른 탭에서 추가·수정한 리포트도 보존한다.
    const checked = prepareImport(JSON.stringify({format:FORMAT,version:1,reports:preview.incoming}));
    localStorage.setItem(KEY,JSON.stringify(checked.reports));
    return {added:checked.added,duplicates:checked.duplicates,count:checked.count};
  }
  function filter(items, {query = '', role = '', outcome = ''} = {}) {
    const search = query.trim().toLocaleLowerCase('ko-KR');
    const roles = {TOP:'탑',JUNGLE:'정글',MID:'미드',BOT:'원딜 바텀',SUPPORT:'서포터 서폿'};
    return items.filter(item => (!role || item.role === role) &&
      (!outcome || (outcome === 'win' ? item.win === true : outcome === 'loss' ? item.win === false : item.win !== true && item.win !== false)) &&
      `${item.champion_name} ${item.champion_id} ${item.role} ${roles[item.role]} ${item.patch}`.toLocaleLowerCase('ko-KR').includes(search));
  }
  function compare(first, second) {
    const rows = [clean(first),clean(second)];
    if (rows.some(item => !item)) throw new Error('비교할 리포트를 확인할 수 없습니다. 보관함을 다시 확인해주세요.');
    if (identity(rows[0]) === identity(rows[1])) throw new Error('서로 다른 경기 두 개를 선택해주세요.');
    const [older,newer] = rows.sort((a,b) => Date.parse(a.played_at)-Date.parse(b.played_at));
    const compatible = ['champion_id','region','queue','role','patch'].every(key => older[key] === newer[key]);
    return {older,newer,compatible,metrics:compatible ? metricKeys.map(key => {
      const before=older.report.metrics[key], after=newer.report.metrics[key];
      return {key,before,after,delta:before === null || after === null ? null : after-before};
    }) : []};
  }
  window.MatchReports = {read,save,remove,clean,undoRemove,backup,prepareImport,restore,filter,compare,identity,MAX_BACKUP_BYTES};
})();
