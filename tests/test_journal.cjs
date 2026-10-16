// 브라우저 없이 기록 병합·보관 경계와 실패 시 기존 기록 보존을 확인한다.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function fixture(module='journal') {
  const store = new Map();
  const localStorage = {getItem:key => store.get(key) ?? null, setItem:(key,value) => store.set(key,value),removeItem:key => store.delete(key)};
  const context = vm.createContext({window:{},localStorage,TextEncoder});
  vm.runInContext(fs.readFileSync(path.join(__dirname,`../web/${module}.js`),'utf8'),context);
  return {j:context.window.ReviewJournal,d:context.window.ReviewDraft,store,localStorage};
}
function record(day=0) {
  return {context:{region:'KR',queue:'RANKED_SOLO',patch:'16.19',tier:'GOLD',role:'BOT',champion_id:'Ezreal',champion_name:'이즈리얼',played_at:new Date(Date.UTC(2026,0,1,0,day)).toISOString()},metrics:{gpm:400,dpm:700,vision_per_minute:0.8,kill_participation:null},focus:'resource',is_example:false,scene:'모의 장면',action:'모의 행동'};
}
const key = 'lol-ranked-reviews-v1';
const payload = records => JSON.stringify({format:'lol-insight-ranked-reviews',version:1,records});
test('백업 왕복과 중복 병합은 현재 기록을 보존한다', () => {
  const {j,store} = fixture();
  j.save({...record(),puuid:'excluded',context:{...record().context,account:'excluded'}});
  const backup = j.backup();
  assert.equal(backup.includes('excluded'),false);
  assert.equal(JSON.parse(backup).records.length,1);
  const original = store.get(key);
  const preview = j.prepareImport(payload([{...record(),action:'예전 행동'},record(1)]));
  assert.equal(store.get(key),original,'미리보기는 저장소를 변경하지 않음');
  assert.equal(preview.added,1); assert.equal(preview.duplicates,1);
  j.restore(preview);
  assert.equal(j.read().length,2);
  assert.equal(j.read()[0].action,'모의 행동');
  const target = fixture(); target.j.restore(target.j.prepareImport(j.backup()));
  assert.equal(target.j.backup().includes('예전 행동'),false);
  assert.equal(target.j.read().length,2);
});
test('잘못된 백업·합성·미래·중복 경기를 모두 거부하고 기존 기록을 보존한다', () => {
  const {j,store} = fixture(); j.save(record()); const before = store.get(key);
  const invalid = ['bad json',JSON.stringify({format:'other',version:1,records:[]}),
    JSON.stringify({format:'lol-insight-ranked-reviews',version:2,records:[]}),
    payload([{...record(),is_example:true}]),payload([record(),record()]),
    payload([{...record(),context:{...record().context,played_at:'2099-01-01T00:00:00Z'}}]),
    payload([{...record(),metrics:{...record().metrics,kill_participation:2}}]),
    payload(Array.from({length:501},(_,i)=>record(i))), '가'.repeat(800000)];
  for (const text of invalid) {assert.throws(()=>j.prepareImport(text)); assert.equal(store.get(key),before);}
});
test('50개를 넘어 장기 기록을 보관하고 500개 초과 시 기존 기록을 유지한다', () => {
  const {j,store} = fixture();
  j.restore(j.prepareImport(payload(Array.from({length:500},(_,i)=>record(i)))));
  assert.equal(j.read().length,500);
  const before = store.get(key);
  assert.throws(()=>j.save(record(500))); assert.equal(store.get(key),before);
  assert.throws(()=>j.prepareImport(payload([record(500)]))); assert.equal(store.get(key),before);
  j.save({...record(),action:'기존 기록 갱신'}); assert.equal(j.read().length,500);
});
test('미리보기 이후 변경된 기록과 저장 실패 시 기존 기록을 보존한다', () => {
  const {j,store,localStorage} = fixture(); j.save(record());
  const preview = j.prepareImport(payload([record(1)])); j.save({...record(1),action:'미리보기 후 기록'});
  const result = j.restore(preview); assert.equal(result.added,0); assert.equal(result.duplicates,1);
  assert.equal(j.read()[1].action,'미리보기 후 기록');
  const next = j.prepareImport(payload([record(2)])), before = store.get(key);
  localStorage.setItem = () => {throw new Error('quota');};
  assert.throws(()=>j.restore(next)); assert.equal(store.get(key),before);
});
test('손상된 기존 저장소를 복원으로 덮어쓰지 않는다', () => {
  const {j,store} = fixture(); store.set(key,'[null]');
  assert.throws(()=>j.prepareImport(payload([record()]))); assert.equal(store.get(key),'[null]');
  assert.throws(()=>j.save(record())); assert.equal(store.get(key),'[null]');
  assert.throws(()=>j.remove('any')); assert.equal(store.get(key),'[null]');
});
test('이전 기록은 행동 상태 기본값을 받고 새 상태·돌아본 내용을 백업한다', () => {
  const {j} = fixture(); j.save(record());
  assert.equal(JSON.parse(j.backup()).records[0].action_status,'planned');
  j.update(j.id(record().context),record(),{action_status:'reviewed',reflection:'모의 확인',context:{region:'NA'}});
  const restored = fixture(); restored.j.restore(restored.j.prepareImport(j.backup()));
  assert.equal(restored.j.read()[0].reflection,'모의 확인');
  assert.equal(restored.j.read()[0].action_status,'reviewed');
  assert.equal(restored.j.read()[0].context.region,'KR');
  assert.equal(j.valid({...record(),action_status:'invalid'}),false);
});
test('수정 중 다른 탭의 변경이나 삭제를 덮어쓰지 않는다', () => {
  const {j,store} = fixture(); j.save(record()); const expected = j.read()[0];
  j.save({...record(),action:'다른 탭의 수정'}); const before = store.get(key);
  assert.throws(()=>j.update(j.id(record().context),expected,{action:'덮어쓰기'})); assert.equal(store.get(key),before);
  j.remove(j.id(record().context));
  assert.throws(()=>j.update(j.id(record().context),expected,{action:'다시 생성'})); assert.equal(j.read().length,0);
});
test('삭제 취소는 이미 다시 저장된 경기를 덮어쓰지 않는다', () => {
  const {j} = fixture(); j.save(record()); j.remove(j.id(record().context));
  j.undoRemove(record()); assert.equal(j.read().length,1);
  j.save({...record(),action:'다시 작성'}); assert.throws(()=>j.undoRemove(record()));
  assert.equal(j.read()[0].action,'다시 작성');
});
test('같은 경기 재요약은 수행 기록을 보존하고 다른 행동은 시도 전으로 시작한다', () => {
  const {j} = fixture(); j.save({...record(),action_status:'reviewed',reflection:'모의 확인'});
  j.save({...record(),scene:'새 장면'}); assert.equal(j.read()[0].reflection,'모의 확인');
  j.save({...record(),action:'다른 행동'}); assert.equal(j.read()[0].action_status,'planned'); assert.equal(j.read()[0].reflection,'');
});
test('최대 길이 한국어 기록 500개의 백업도 크기 한도 안에서 왕복한다', () => {
  const {j} = fixture();
  const records = Array.from({length:500},(_,i)=>({...record(i),context:{...record(i).context,champion_name:'가'.repeat(40)},scene:'가'.repeat(400),action:'가'.repeat(200),reflection:'가'.repeat(300),action_status:'reviewed'}));
  j.restore(j.prepareImport(payload(records)));
  assert.ok(Buffer.byteLength(j.backup(),'utf8') <= j.MAX_BACKUP_BYTES);
  const target = fixture(); target.j.restore(target.j.prepareImport(j.backup())); assert.equal(target.j.read().length,500);
});
function draft(d) {
  return {version:1,values:Object.fromEntries(d.FIELDS.map(key=>[key,''])),is_example:true,scene:'초안 장면',action:'초안 행동',saved_at:new Date().toISOString()};
}
test('불완전한 초안을 보관하고 합성 여부·장면·행동을 유지한다', () => {
  const {d} = fixture('draft'), data = draft(d); data.values.gold='123'; d.save(data);
  assert.equal(d.read().is_example,true); assert.equal(d.read().values.gold,'123');
  assert.equal(d.read().scene,'초안 장면'); d.clear(); assert.equal(d.read(),null);
});
test('초안에 계정·키 필드를 넣을 수 없고 손상된 초안은 적용하지 않는다', () => {
  const {d,store} = fixture('draft'), data = draft(d); d.save(data);
  const before = store.get('lol-review-draft-v1');
  assert.throws(()=>d.save({...data,values:{...data.values,RIOT_API_KEY:'excluded'}}));
  assert.equal(store.get('lol-review-draft-v1'),before);
  d.save({...data,puuid:'excluded'}); assert.equal(store.get('lol-review-draft-v1').includes('excluded'),false);
  store.set('lol-review-draft-v1','null'); assert.equal(d.read(),null);
  store.set('lol-review-draft-v1','{invalid'); assert.equal(d.read(),null);
});
test('초안 저장 용량 오류 시 이전 초안을 보존한다', () => {
  const {d,store,localStorage} = fixture('draft'), data = draft(d); d.save(data);
  const before = store.get('lol-review-draft-v1'); localStorage.setItem=()=>{throw new Error('quota');};
  assert.throws(()=>d.save({...data,action:'실패할 변경'})); assert.equal(store.get('lol-review-draft-v1'),before);
});
