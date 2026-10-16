'use strict';
// 개인 기록은 브라우저에만 보관한다. 과거 EUN 집계와 합치지 않는다.
window.ReviewJournal = (() => {
  const KEY = 'lol-ranked-reviews-v1';
  const FORMAT = 'lol-insight-ranked-reviews';
  const MAX_RECORDS = 500, MAX_BACKUP_BYTES = 2 * 1048576;
  const CONDITIONS = ['region', 'queue', 'patch', 'tier', 'champion_id', 'role'];
  const METRICS = ['gpm', 'dpm', 'vision_per_minute', 'kill_participation'];
  const allowed = {
    region: ['KR', 'EUN', 'EUW', 'NA'], queue: ['RANKED_SOLO', 'RANKED_FLEX'],
    tier: ['IRON','BRONZE','SILVER','GOLD','PLATINUM','EMERALD','DIAMOND','MASTER','GRANDMASTER','CHALLENGER'],
    role: ['TOP','JUNGLE','MID','BOT','SUPPORT'],
    focus: ['vision','fight_setup','resource','matchup']
  };
  const group = context => CONDITIONS.map(key => context[key]).join('|');
  const id = context => group(context) + '|' + new Date(context.played_at).toISOString();
  function valid(record) {
    if (!record || record.is_example !== false || !record.context || !record.metrics) return false;
    const c = record.context, m = record.metrics;
    return Object.keys(allowed).filter(key => key !== 'focus').every(key => allowed[key].includes(c[key])) &&
      typeof c.patch === 'string' && /^\d{2}\.\d{1,2}$/.test(c.patch) &&
      typeof c.champion_id === 'string' && /^[A-Za-z0-9]{1,40}$/.test(c.champion_id) &&
      typeof c.champion_name === 'string' && c.champion_name.length <= 40 &&
      typeof c.played_at === 'string' && c.played_at.length <= 40 && /(?:Z|[+-]\d{2}:\d{2})$/.test(c.played_at) &&
      Number.isFinite(Date.parse(c.played_at)) && Date.parse(c.played_at) <= Date.now() + 300000 &&
      allowed.focus.includes(record.focus) &&
      ['gpm','dpm','vision_per_minute'].every(key => Number.isFinite(m[key]) && m[key] >= 0 && m[key] <= ({gpm:20000,dpm:100000,vision_per_minute:200})[key]) &&
      (m.kill_participation === null || (Number.isFinite(m.kill_participation) && m.kill_participation >= 0 && m.kill_participation <= 1)) &&
      typeof record.scene === 'string' && record.scene.length <= 400 &&
      typeof record.action === 'string' && record.action.length <= 200 &&
      (record.action_status === undefined || ['planned','tried','reviewed'].includes(record.action_status)) &&
      (record.reflection === undefined || (typeof record.reflection === 'string' && record.reflection.length <= 300));
  }
  function read() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '[]');
      if (!Array.isArray(raw)) return [];
      const unique = new Map();
      raw.filter(valid).forEach(record => unique.set(id(record.context), record));
      return [...unique.values()].sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at)).slice(-MAX_RECORDS);
    } catch { return []; }
  }
  function save(record) {
    if (!valid(record)) throw new Error('완료 경기의 조건과 기록을 확인해주세요. 합성 예제는 저장할 수 없습니다.');
    const all = writableRecords(), recordId = id(record.context);
    const updated = all.some(item => id(item.context) === recordId);
    const previous = all.find(item => id(item.context) === recordId);
    if (previous && record.action_status === undefined) record = {...record,action_status:previous.action === record.action ? previous.action_status || 'planned' : 'planned',reflection:previous.action === record.action ? previous.reflection || '' : ''};
    const result = [...all.filter(item => id(item.context) !== recordId), record];
    result.sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at));
    if (result.length > MAX_RECORDS) throw new Error(`최대 ${MAX_RECORDS}경기를 보관할 수 있습니다. 백업 후 불필요한 기록을 정리해주세요. 기존 기록은 유지했습니다.`);
    localStorage.setItem(KEY, JSON.stringify(result));
    return updated;
  }
  function remove(recordId) {
    localStorage.setItem(KEY, JSON.stringify(writableRecords().filter(item => id(item.context) !== recordId)));
  }
  function update(recordId, expected, changes) {
    const current = writableRecords().find(record => id(record.context) === recordId);
    if (!current) throw new Error('이 경기는 이미 삭제되었습니다. 기록 목록을 다시 확인해주세요.');
    if (JSON.stringify(portable(current)) !== JSON.stringify(portable(expected))) throw new Error('다른 탭에서 이 기록이 바뀌었습니다. 최신 기록을 다시 열어 수정해주세요.');
    const revised = {...current};
    for (const field of ['focus','scene','action','action_status','reflection']) if (field in changes) revised[field] = changes[field];
    return save(revised);
  }
  function undoRemove(record) {
    if (writableRecords().some(item => id(item.context) === id(record.context))) throw new Error('같은 경기가 다시 저장되어 삭제 취소로 덮어쓰지 않았습니다.');
    return save(record);
  }
  function portable(record) {
    return {
      context: Object.fromEntries([...CONDITIONS, 'champion_name', 'played_at'].map(key => [key, record.context[key]])),
      metrics: Object.fromEntries(METRICS.map(key => [key, record.metrics[key]])),
      focus: record.focus, is_example: false, scene: record.scene, action: record.action,
      action_status: record.action_status || 'planned', reflection: record.reflection || ''
    };
  }
  function backup() {
    return JSON.stringify({format: FORMAT, version: 1, exported_at: new Date().toISOString(), records: read().map(portable)}, null, 2);
  }
  function writableRecords() {
    // 복원 중 손상된 기존 기록을 조용히 버리지 않는다.
    let raw;
    try {raw = JSON.parse(localStorage.getItem(KEY) || '[]');}
    catch {throw new Error('기존 저장 기록에 접근할 수 없어 변경하지 않았습니다.');}
    if (!Array.isArray(raw) || raw.length > MAX_RECORDS || raw.some(record => !valid(record))) throw new Error('기존 저장 기록을 확인할 수 없어 변경하지 않았습니다.');
    return read();
  }
  function mergeImport(incoming) {
    const existing = writableRecords(), unique = new Map(existing.map(record => [id(record.context), record]));
    let added = 0, duplicates = 0;
    incoming.forEach(record => {
      const recordId = id(record.context);
      if (unique.has(recordId)) duplicates++;
      else {unique.set(recordId, portable(record)); added++;}
    });
    const merged = [...unique.values()].sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at));
    if (merged.length > MAX_RECORDS) throw new Error(`합치면 ${merged.length}경기로 ${MAX_RECORDS}개 보관 한도를 넘습니다. 기존 기록은 유지했습니다.`);
    return {records: merged, added, duplicates};
  }
  function prepareImport(text) {
    if (typeof text !== 'string' || new TextEncoder().encode(text).length > MAX_BACKUP_BYTES) throw new Error('백업 파일은 2MB 이하여야 합니다.');
    let data;
    try {data = JSON.parse(text);} catch {throw new Error('JSON 백업 파일을 읽을 수 없습니다.');}
    if (!data || data.format !== FORMAT || data.version !== 1 || !Array.isArray(data.records) || data.records.length > MAX_RECORDS)
      throw new Error('이 서비스의 버전 1 경기 백업 파일을 선택해주세요.');
    if (data.records.some(record => !valid(record))) throw new Error('유효하지 않은 경기 또는 합성 예제가 있어 복원하지 않았습니다.');
    const identities = data.records.map(record => id(record.context));
    if (new Set(identities).size !== identities.length) throw new Error('백업 안에 같은 조건·일시의 경기가 중복되어 있습니다.');
    const incoming = data.records.map(portable), result = mergeImport(incoming);
    return {incoming, added: result.added, duplicates: result.duplicates, count: result.records.length};
  }
  function restore(preview) {
    // 미리보기 이후 바뀐 기존 기록도 보존하면서 다시 병합한다.
    const checked = prepareImport(JSON.stringify({format: FORMAT, version: 1, records: preview.incoming}));
    const result = mergeImport(checked.incoming);
    localStorage.setItem(KEY, JSON.stringify(result.records));
    return {added: result.added, duplicates: result.duplicates, count: result.records.length};
  }
  function compare(records, key) {
    const matching = records.filter(valid).filter(item => group(item.context) === key)
      .sort((a,b) => Date.parse(b.context.played_at) - Date.parse(a.context.played_at));
    if (matching.length < 6) return {count: matching.length, metrics: null};
    const mean = (items, metric) => {
      const values = items.map(item => item.metrics[metric]).filter(Number.isFinite);
      return {value: values.length ? values.reduce((a,b) => a+b, 0)/values.length : null, n: values.length};
    };
    return {count: matching.length, metrics: Object.fromEntries(METRICS.map(metric => [metric, {
      recent: mean(matching.slice(0,3), metric), previous: mean(matching.slice(3,6), metric)
    }]))};
  }
  return {read, save, remove, update, undoRemove, compare, group, id, valid, backup, prepareImport, restore, MAX_RECORDS, MAX_BACKUP_BYTES};
})();
