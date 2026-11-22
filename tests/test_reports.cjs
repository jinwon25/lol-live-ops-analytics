const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup() {
  const data=new Map(); const context={TextEncoder,window:{},localStorage:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)}};
  vm.runInNewContext(fs.readFileSync('web/reports.js','utf8'),context);
  return {reports:context.window.MatchReports,data,storage:context.localStorage};
}
function row() {return {champion_id:'Ezreal',champion_name:'이즈리얼',region:'KR',queue:'RANKED_SOLO',role:'BOT',patch:'16.19',played_at:'2026-09-25T12:00:00Z',duration_minutes:30,gold:12000,damage:21000,vision:24,kills:5,assists:8,team_kills:24,win:true,report:{version:1,metrics:{gpm:400,dpm:700,vision_per_minute:.8,kill_participation:.542,cs_per_minute:null,damage_share:null},focus:{id:'resource',label:'파밍과 귀환 선택'},facts:['관측한 수치'],questions:['장면을 확인하세요'],next_step:'조건 하나를 확인하세요',limitations:['종료 수치 요약']}};}
test('공식 리포트를 메모나 경기 당시 티어 없이 보관하고 식별자를 제외한다',()=>{
  const {reports,data}=setup(); reports.save({...row(),puuid:'private-id',game_name:'private-name',participants:[{}]});
  assert.equal(reports.read().length,1); const stored=data.get('lol-match-reports-v1');
  assert.ok(!stored.includes('private')); assert.ok(!stored.includes('participants'));
  reports.save(row()); assert.equal(reports.read().length,1);
  reports.remove(row()); assert.equal(reports.read().length,0);
});
test('손상된 보관함과 용량 한도 초과는 기존 리포트를 덮어쓰지 않는다',()=>{
  const {reports,data}=setup(); data.set('lol-match-reports-v1','broken');
  assert.throws(()=>reports.save(row())); assert.equal(data.get('lol-match-reports-v1'),'broken');
  data.set('lol-match-reports-v1','[]');
  for(let i=0;i<50;i++) reports.save({...row(),played_at:new Date(Date.UTC(2026,7,1,0,i)).toISOString()});
  const before=data.get('lol-match-reports-v1'); assert.throws(()=>reports.save(row())); assert.equal(data.get('lol-match-reports-v1'),before);
  const oversized=JSON.stringify([...JSON.parse(before),row()]); data.set('lol-match-reports-v1',oversized);
  assert.throws(()=>reports.save(row())); assert.equal(data.get('lol-match-reports-v1'),oversized);
});
test('알 수 없는 지표나 불가능한 비율은 보관하지 않는다',()=>{
  const {reports}=setup(); const invalid=row(); invalid.report.metrics.damage_share=1.2;
  assert.throws(()=>reports.save(invalid)); invalid.report.metrics.damage_share=null; invalid.report.metrics.gpm=NaN;
  assert.throws(()=>reports.save(invalid));
});

test('리포트 백업을 왕복하고 중복은 현재 보관함의 내용을 유지한다',()=>{
  const source=setup(), target=setup();
  source.reports.save({...row(),puuid:'private-id'});
  const raw=source.reports.backup(); assert.ok(!raw.includes('private-id'));
  const preview=target.reports.prepareImport(raw);
  assert.equal(target.reports.read().length,0); assert.equal(preview.added,1);
  target.reports.restore(preview); assert.equal(target.reports.read().length,1);
  const changed=row(); changed.report.next_step='현재 브라우저에서 수정한 질문'; target.reports.save(changed);
  const duplicate=target.reports.prepareImport(raw);
  assert.equal(duplicate.added,0); assert.equal(duplicate.duplicates,1);
  target.reports.restore(duplicate);
  assert.equal(target.reports.read()[0].report.next_step,'현재 브라우저에서 수정한 질문');
});

test('미리보기 뒤 다른 탭의 추가와 저장 실패를 기존 자료 손실 없이 처리한다',()=>{
  const {reports,data,storage}=setup(), source=setup(); source.reports.save(row());
  const preview=reports.prepareImport(source.reports.backup());
  reports.save({...row(),played_at:'2026-09-24T12:00:00Z'});
  const before=data.get('lol-match-reports-v1'), original=storage.setItem;
  storage.setItem=()=>{throw new Error('quota');};
  assert.throws(()=>reports.restore(preview)); assert.equal(data.get('lol-match-reports-v1'),before);
  storage.setItem=original; reports.restore(preview); assert.equal(reports.read().length,2);
});

test('손상·중복·다른 형식·과대 파일과 병합 한도 초과를 거부한다',()=>{
  const {reports,data}=setup(); reports.save(row()); const before=data.get('lol-match-reports-v1');
  const valid=JSON.parse(reports.backup());
  for(const raw of ['broken',JSON.stringify({...valid,version:99}),JSON.stringify({...valid,reports:[row(),row()]}),JSON.stringify({...valid,reports:[{...row(),report:null}]}),'가'.repeat(1400000)]) {
    assert.throws(()=>reports.prepareImport(raw)); assert.equal(data.get('lol-match-reports-v1'),before);
  }
  for(let i=0;i<49;i++) reports.save({...row(),played_at:new Date(Date.UTC(2026,7,1,0,i)).toISOString()});
  const full=data.get('lol-match-reports-v1'), other=setup(); other.reports.save({...row(),played_at:'2026-09-20T12:00:00Z'});
  assert.throws(()=>reports.prepareImport(other.reports.backup())); assert.equal(data.get('lol-match-reports-v1'),full);
  data.set('lol-match-reports-v1','broken');
  assert.throws(()=>reports.backup()); assert.throws(()=>reports.prepareImport(JSON.stringify(valid)));
  assert.equal(data.get('lol-match-reports-v1'),'broken');
});

test('최대 길이 한국어 리포트 50개도 백업 한도 안에서 복원한다',()=>{
  const source=setup(), target=setup();
  for(let i=0;i<50;i++) {
    const item={...row(),played_at:new Date(Date.UTC(2026,7,1,0,i)).toISOString()};
    item.report={...item.report,facts:Array(10).fill('가'.repeat(600)),questions:Array(10).fill('나'.repeat(600)),limitations:Array(10).fill('다'.repeat(600))};
    source.reports.save(item);
  }
  const raw=source.reports.backup(); assert.ok(new TextEncoder().encode(raw).length<=source.reports.MAX_BACKUP_BYTES);
  target.reports.restore(target.reports.prepareImport(raw)); assert.equal(target.reports.read().length,50);
});

test('삭제를 취소하고 같은 경기의 새 기록은 덮어쓰지 않는다',()=>{
  const {reports}=setup(); reports.save(row()); reports.remove(row()); reports.undoRemove(row());
  assert.equal(reports.read().length,1);
  const changed=row(); changed.report.next_step='다시 보관한 리포트'; reports.save(changed);
  assert.throws(()=>reports.undoRemove(row())); assert.equal(reports.read()[0].report.next_step,'다시 보관한 리포트');
});

test('보관함 검색과 포지션·결과 필터는 함께 적용되고 원문은 변경하지 않는다',()=>{
  const {reports,data}=setup();
  reports.save(row());
  reports.save({...row(),played_at:'2026-09-24T12:00:00Z',win:false});
  reports.save({...row(),played_at:'2026-09-23T12:00:00Z',role:'MID',win:null});
  const before=data.get('lol-match-reports-v1'), items=reports.read();
  assert.equal(reports.filter(items,{query:' 원딜 '}).length,2);
  assert.equal(reports.filter(items,{query:'eZrEaL',role:'BOT',outcome:'loss'}).length,1);
  assert.equal(reports.filter(items,{outcome:'unknown'}).length,1);
  assert.equal(reports.filter(items,{role:'MID',outcome:'win'}).length,0);
  assert.equal(reports.filter(items,{query:'16.20'}).length,0);
  assert.equal(reports.filter(items).length,3);
  assert.equal(data.get('lol-match-reports-v1'),before);
});

test('두 경기 비교는 일시순으로 정렬하고 6개 지표의 차이를 반환한다',()=>{
  const {reports}=setup(), newer=row(), older={...row(),played_at:'2026-09-24T12:00:00Z',duration_minutes:40};
  older.report=structuredClone(older.report); older.report.metrics.gpm=350; older.report.metrics.kill_participation=.442;
  const before=JSON.stringify([newer,older]), result=reports.compare(newer,older);
  assert.equal(result.compatible,true); assert.equal(result.older.played_at,older.played_at);
  assert.equal(result.metrics.length,6); assert.equal(result.metrics[0].delta,50);
  assert.ok(Math.abs(result.metrics.find(x=>x.key==='kill_participation').delta-.1)<1e-10);
  assert.equal(JSON.stringify([newer,older]),before);
});

test('비교의 누락 지표는 0으로 대체하지 않고 한쪽만 누락되어도 차이를 보류한다',()=>{
  const {reports}=setup(), older={...row(),played_at:'2026-09-24T12:00:00Z'}, newer=row();
  newer.report.metrics.cs_per_minute=6;
  const cs=reports.compare(older,newer).metrics.find(x=>x.key==='cs_per_minute');
  assert.equal(cs.before,null); assert.equal(cs.after,6); assert.equal(cs.delta,null);
  older.report.metrics.vision_per_minute=0;
  assert.equal(reports.compare(older,newer).metrics.find(x=>x.key==='vision_per_minute').delta,.8);
});

test('비교 조건이 다른 경기·같은 경기·손상된 리포트는 차이를 만들지 않는다',()=>{
  const {reports}=setup(), older={...row(),played_at:'2026-09-24T12:00:00Z'};
  for(const change of [{champion_id:'Lucian'},{role:'MID'},{patch:'16.20'}]) {
    const result=reports.compare(older,{...row(),...change});
    assert.equal(result.compatible,false); assert.equal(result.metrics.length,0);
  }
  assert.throws(()=>reports.compare(row(),row()));
  assert.throws(()=>reports.compare(older,{...row(),report:null}));
});
