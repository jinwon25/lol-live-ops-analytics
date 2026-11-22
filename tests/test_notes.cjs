const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup() {
  const data = new Map(), storage = {getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};
  const context = {window:{},TextEncoder,localStorage:storage};
  vm.runInNewContext(fs.readFileSync('web/notes.js','utf8'),context);
  return {notes:context.window.PracticeNotes,data,storage};
}
test('이전 null 항목을 건너뛰고 백업에서 계정 필드를 제외한다',()=>{
  const {notes,data} = setup();
  data.set(notes.KEY,JSON.stringify([null,{date:'기존 날짜',text:'보존할 행동',puuid:'private'}]));
  notes.save('새 행동'); assert.equal(notes.read().length,2);
  assert.ok(!notes.backup().includes('private'));
});
test('손상된 저장소에 추가·삭제·복원·백업하여 덮어쓰지 않는다',()=>{
  const {notes,data} = setup();
  for (const raw of ['broken','{}','[null,{}]']) {
    data.set(notes.KEY,raw);
    for (const action of [()=>notes.save('새 행동'),()=>notes.clear(),()=>notes.remove({date:'',text:''}),()=>notes.backup(),()=>notes.restore({incoming:[]})]) assert.throws(action);
    assert.equal(data.get(notes.KEY),raw);
  }
});
test('10개 이후 저장을 거부하고 선택 삭제·취소로 기존 노트를 보존한다',()=>{
  const {notes,data} = setup();
  for (let i=0;i<10;i++) notes.save(`행동 ${i}`);
  const before = data.get(notes.KEY); assert.throws(()=>notes.save('11번째 행동')); assert.equal(data.get(notes.KEY),before);
  const removed = notes.remove(notes.read()[0]); assert.equal(notes.read().length,9);
  notes.restore({incoming:removed}); assert.equal(notes.read().length,10);
  assert.throws(()=>notes.remove({date:'없는 날짜',text:'다른 탭에서 바뀐 행동'}));
});
test('이전 행동 노트에서 연습 결과를 기록하고 백업·삭제 취소로 복원한다', () => {
  const {notes, data} = setup();
  data.set(notes.KEY, JSON.stringify([{date:'기존 날짜', text:'귀환 전 웨이브 확인'}]));
  const item = notes.read()[0];
  assert.equal(item.result, '');
  notes.setResult(item, 'missed');
  assert.equal(notes.read()[0].result, 'missed');
  const target = setup().notes;
  target.restore(target.prepareImport(notes.backup()));
  assert.equal(target.read()[0].result, 'missed');
  notes.setResult(item, 'tried');
  assert.equal(notes.read()[0].result, 'tried');
  const removed = notes.remove(item);
  assert.throws(() => notes.setResult(item, 'tried'));
  notes.restore({incoming:removed});
  assert.equal(notes.read()[0].result, 'tried');
  assert.throws(() => notes.setResult(item, 'invalid'));
  notes.setResult(item, '');
  assert.equal(notes.read()[0].result, '');
});
test('최대 길이 한국어 노트의 백업·복원과 중복 병합은 미리보기 이후 변경을 보존한다',()=>{
  const source = setup(), target = setup();
  for (let i=0;i<9;i++) source.notes.save(`${i}${'가'.repeat(199)}`);
  const raw = source.notes.backup(); assert.ok(new TextEncoder().encode(raw).length<source.notes.MAX_BACKUP_BYTES);
  const preview = target.notes.prepareImport(raw); assert.equal(target.notes.read().length,0);
  target.notes.save('미리보기 뒤 추가한 행동'); target.notes.restore(preview); assert.equal(target.notes.read().length,10);
  const duplicate = target.notes.prepareImport(raw); assert.equal(duplicate.added,0); assert.equal(duplicate.duplicates,9);
  target.notes.restore(duplicate); assert.equal(target.notes.read().length,10);
});
test('복원 형식·중복·크기·합계 초과와 저장 실패에서 기존 자료를 유지한다',()=>{
  const {notes,data,storage} = setup(), source = setup();
  notes.save('보존할 행동'); source.notes.save('새 행동');
  const before = data.get(notes.KEY), valid = JSON.parse(source.notes.backup());
  for(const raw of ['broken',JSON.stringify({...valid,version:2}),JSON.stringify({...valid,notes:[...valid.notes,...valid.notes]}),JSON.stringify({...valid,notes:[{text:'가'.repeat(201)}]}),'가'.repeat(6000)]) assert.throws(()=>notes.prepareImport(raw));
  assert.equal(data.get(notes.KEY),before);
  const preview = notes.prepareImport(source.notes.backup());
  storage.setItem = ()=>{throw new Error('quota');}; storage.removeItem = ()=>{throw new Error('denied');};
  assert.throws(()=>notes.restore(preview)); assert.throws(()=>notes.clear()); assert.equal(data.get(notes.KEY),before);
  const full = setup(); for(let i=0;i<10;i++) full.notes.save(`행동 ${i}`);
  assert.throws(()=>full.notes.prepareImport(source.notes.backup()));
});
