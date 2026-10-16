const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function setup() {
  const data=new Map(); const context={window:{},localStorage:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)}};
  vm.runInNewContext(fs.readFileSync('web/reports.js','utf8'),context);
  return {reports:context.window.MatchReports,data};
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
