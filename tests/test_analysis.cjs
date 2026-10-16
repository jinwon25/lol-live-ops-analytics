const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function fixture() {
  const context = vm.createContext({window:{},localStorage:{getItem:()=>null},TextEncoder});
  for (const file of ['journal','analysis']) vm.runInContext(fs.readFileSync(path.join(__dirname,`../web/${file}.js`),'utf8'),context);
  return {j:context.window.ReviewJournal,a:context.window.PersonalAnalysis};
}
function record(day=1) {
  return {context:{region:'KR',queue:'RANKED_SOLO',tier:'GOLD',role:'BOT',patch:'16.19',champion_id:'Ezreal',champion_name:'이즈리얼',played_at:new Date(Date.UTC(2026,0,day)).toISOString()},metrics:{gpm:day*100,dpm:700,vision_per_minute:0.8,kill_participation:null},focus:'vision',scene:'모의 장면',action:'시야 준비',is_example:false};
}
test('개인 추이는 시간순 최근 10경기만 사용하며 다른 조건과 예제를 배제한다',()=>{
  const {j,a}=fixture(), records=Array.from({length:12},(_,i)=>record(i+1)).reverse();
  records.push({...record(13),context:{...record(13).context,patch:'16.18'}},{...record(14),is_example:true});
  const before=JSON.stringify(records), report=a.report(records,j.group(record().context),'gpm');
  assert.equal(report.count,12); assert.equal(report.trend.length,10);
  assert.equal(report.trend[0].value,300); assert.equal(report.trend.at(-1).value,1200);
  assert.equal(report.comparison.metrics.gpm.previous.value,800); assert.equal(report.comparison.metrics.gpm.recent.value,1100);
  assert.equal(JSON.stringify(records),before,'보고서 계산은 원본 기록을 변경하지 않음');
});
test('미정의 킬 관여율은 0으로 표시하거나 평균에 섞지 않는다',()=>{
  const {j,a}=fixture(), records=Array.from({length:6},(_,i)=>record(i+1));
  records[0].metrics.kill_participation=.2; records[3].metrics.kill_participation=0; records[4].metrics.kill_participation=.8;
  const r=a.report(records,j.group(records[0].context),'kill_participation');
  assert.equal(r.trend[1].value,null);
  assert.equal(r.comparison.metrics.kill_participation.previous.n,1);
  assert.equal(r.comparison.metrics.kill_participation.recent.n,2);
  assert.equal(r.comparison.metrics.kill_participation.recent.value,.4);
});
test('6경기 미만과 비어 있는 조건에서는 평균 비교를 보류한다',()=>{
  const {j,a}=fixture(), records=[record(1),record(2)];
  const r=a.report(records,j.group(records[0].context),'untrusted-path');
  assert.equal(r.metric,'gpm'); assert.equal(r.comparison.metrics,null); assert.equal(r.count,2);
  const empty=a.report(records,'other','dpm'); assert.equal(empty.count,0); assert.equal(empty.latest,null); assert.equal(empty.trend.length,0);
});
test('과제는 최신 미완료 3개이며 완료·예제는 제외하고 기존 기록을 보존한다',()=>{
  const {j,a}=fixture(), records=Array.from({length:6},(_,i)=>record(i+1));
  records[5].action_status='reviewed'; records[4].action_status='tried'; records.push({...record(7),is_example:true},{...record(8),action:'  '});
  const before=JSON.stringify(records), tasks=a.tasks(records);
  assert.equal(tasks.length,3); assert.equal(tasks[0].context.played_at,records[4].context.played_at);
  assert.equal(tasks[0].action_status,'tried'); assert.equal(JSON.stringify(records),before);
  assert.equal(a.report(records,j.group(record().context),'gpm').pending,5,'빈 행동을 미완료 과제로 집계하지 않음');
});
