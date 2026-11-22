'use strict';
window.PracticeNotes = (() => {
  const KEY = 'lol-insight-notes-v1', FORMAT = 'lol-insight-practice-notes';
  const MAX = 10, MAX_BACKUP_BYTES = 16 * 1024;
  const results = ['', 'tried', 'missed'];
  const identity = item => JSON.stringify([item.date, item.text]);
  function clean(item) {
    if (!item || typeof item.text !== 'string' || item.text.length > 200 ||
        (item.date != null && (typeof item.date !== 'string' || item.date.length > 40)) ||
        (Object.hasOwn(item, 'result') && !results.includes(item.result))) return null;
    return {date:item.date || '',text:item.text,result:item.result ?? ''};
  }
  function read() {
    let raw, items;
    try {
      raw = localStorage.getItem(KEY) || '[]';
      if (raw.length > MAX_BACKUP_BYTES) throw new Error();
      items = JSON.parse(raw);
    } catch {throw new Error('행동 노트 저장소를 읽을 수 없습니다. 기존 자료를 변경하지 않았습니다.');}
    if (!Array.isArray(items) || items.length > MAX || items.some(x => x !== null && !clean(x)))
      throw new Error('저장된 행동 노트 형식을 확인할 수 없습니다. 기존 자료를 변경하지 않았습니다.');
    // 이전 버전의 null 항목은 건너뛰고 정상 노트를 유지한다.
    return [...new Map(items.filter(x => x !== null).map(clean).map(x => [identity(x),x])).values()];
  }
  function save(text) {
    if (typeof text !== 'string' || !text.trim() || text.trim().length > 200) throw new Error('행동을 1~200자로 입력해주세요.');
    const item = {date:new Date().toLocaleDateString('ko-KR'),text:text.trim()}, items = read();
    if (items.some(x => identity(x) === identity(item))) return;
    if (items.length >= MAX) throw new Error('행동 노트는 최대 10개입니다. 백업 후 완료한 노트를 정리해주세요. 기존 자료는 유지했습니다.');
    localStorage.setItem(KEY,JSON.stringify([...items,item]));
  }
  function remove(item) {
    const items = read(), index = items.findIndex(x => identity(x) === identity(item));
    if (index < 0) throw new Error('다른 탭에서 이 노트가 바뀌었습니다. 최신 목록을 확인해주세요.');
    const removed = items.splice(index,1);
    localStorage.setItem(KEY,JSON.stringify(items));
    return removed;
  }
  function setResult(item, result) {
    if (!results.includes(result)) throw new Error('연습 결과를 확인해주세요.');
    const items = read();
    const current = items.find(row => identity(row) === identity(item));
    if (!current) throw new Error('이 행동 노트를 찾을 수 없습니다. 최신 목록을 확인해주세요.');
    current.result = result;
    localStorage.setItem(KEY, JSON.stringify(items));
  }
  function clear() {
    const items = read(); localStorage.removeItem(KEY); return items;
  }
  function backup() {
    return JSON.stringify({format:FORMAT,version:1,exported_at:new Date().toISOString(),notes:read()},null,2);
  }
  function prepareImport(raw) {
    if (typeof raw !== 'string' || new TextEncoder().encode(raw).length > MAX_BACKUP_BYTES) throw new Error('행동 노트 백업 파일은 16KB 이하여야 합니다.');
    let data;
    try {data = JSON.parse(raw);} catch {throw new Error('JSON 백업 파일을 읽을 수 없습니다.');}
    if (!data || data.format !== FORMAT || data.version !== 1 || !Array.isArray(data.notes) || data.notes.length > MAX || data.notes.some(x => !clean(x)))
      throw new Error('이 서비스에서 내보낸 버전 1 행동 노트 백업을 선택해주세요.');
    const incoming = data.notes.map(clean);
    if (new Set(incoming.map(identity)).size !== incoming.length) throw new Error('백업 안에 같은 행동 노트가 중복되어 있습니다.');
    const merged = new Map(read().map(x => [identity(x),x])); let added = 0;
    incoming.forEach(x => {if (!merged.has(identity(x))) {merged.set(identity(x),x); added++;}});
    if (merged.size > MAX) throw new Error('합치면 행동 노트가 10개를 넘습니다. 기존 자료는 유지했습니다.');
    return {incoming,notes:[...merged.values()],added,duplicates:incoming.length-added,count:merged.size};
  }
  function restore(preview) {
    const checked = prepareImport(JSON.stringify({format:FORMAT,version:1,notes:preview.incoming}));
    localStorage.setItem(KEY,JSON.stringify(checked.notes));
    return {added:checked.added,duplicates:checked.duplicates,count:checked.count};
  }
  return {KEY,MAX_BACKUP_BYTES,read,save,remove,setResult,clear,backup,prepareImport,restore};
})();
