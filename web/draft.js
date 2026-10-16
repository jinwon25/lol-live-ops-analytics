'use strict';
// 입력 중인 경기 초안만 보관한다. Riot ID·API 키는 포함하지 않는다.
window.ReviewDraft = (() => {
  const KEY = 'lol-review-draft-v1';
  const FIELDS = ['champion_id','region','queue','tier','patch','played_at','role','focus','duration_minutes','gold','damage','vision','kills','assists','team_kills'];
  function valid(data) {
    return !!data && data.version === 1 && typeof data.is_example === 'boolean' &&
      data.values && typeof data.values === 'object' && !Array.isArray(data.values) &&
      Object.keys(data.values).every(key => FIELDS.includes(key)) &&
      FIELDS.every(key => typeof data.values[key] === 'string' && data.values[key].length <= 80) &&
      typeof data.scene === 'string' && data.scene.length <= 400 &&
      typeof data.action === 'string' && data.action.length <= 200 &&
      typeof data.saved_at === 'string' && Number.isFinite(Date.parse(data.saved_at));
  }
  function read() {
    try {const raw = JSON.parse(localStorage.getItem(KEY) || 'null'); return valid(raw) ? raw : null;}
    catch {return null;}
  }
  function save(data) {
    if (!valid(data)) throw new Error('경기 초안의 입력을 확인해주세요.');
    const safe = {version:1,is_example:data.is_example,values:Object.fromEntries(FIELDS.map(key => [key,data.values[key]])),scene:data.scene,action:data.action,saved_at:data.saved_at};
    localStorage.setItem(KEY,JSON.stringify(safe));
  }
  function clear() {localStorage.removeItem(KEY);}
  return {read,save,clear,FIELDS};
})();
