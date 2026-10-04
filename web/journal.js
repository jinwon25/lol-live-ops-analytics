'use strict';
// 개인 기록은 브라우저에만 보관한다. 과거 EUN 집계와 합치지 않는다.
window.ReviewJournal = (() => {
  const KEY = 'lol-ranked-reviews-v1';
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
      typeof c.played_at === 'string' && /(?:Z|[+-]\d{2}:\d{2})$/.test(c.played_at) &&
      Number.isFinite(Date.parse(c.played_at)) && Date.parse(c.played_at) <= Date.now() + 300000 &&
      allowed.focus.includes(record.focus) &&
      ['gpm','dpm','vision_per_minute'].every(key => Number.isFinite(m[key]) && m[key] >= 0) &&
      (m.kill_participation === null || (Number.isFinite(m.kill_participation) && m.kill_participation >= 0 && m.kill_participation <= 1)) &&
      typeof record.scene === 'string' && record.scene.length <= 400 &&
      typeof record.action === 'string' && record.action.length <= 200;
  }
  function read() {
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || '[]');
      if (!Array.isArray(raw)) return [];
      const unique = new Map();
      raw.filter(valid).forEach(record => unique.set(id(record.context), record));
      return [...unique.values()].sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at)).slice(-50);
    } catch { return []; }
  }
  function save(record) {
    if (!valid(record)) throw new Error('완료 경기의 조건과 기록을 확인해주세요. 합성 예제는 저장할 수 없습니다.');
    const all = read(), recordId = id(record.context);
    const updated = all.some(item => id(item.context) === recordId);
    const result = [...all.filter(item => id(item.context) !== recordId), record];
    result.sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at));
    localStorage.setItem(KEY, JSON.stringify(result.slice(-50)));
    return updated;
  }
  function remove(recordId) {
    localStorage.setItem(KEY, JSON.stringify(read().filter(item => id(item.context) !== recordId)));
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
  return {read, save, remove, compare, group, id, valid};
})();
