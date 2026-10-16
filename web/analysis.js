'use strict';
// 저장된 개인 경기만 사용한다. 비교 조건·계산 불가 값은 journal 규칙을 따른다.
window.PersonalAnalysis = (() => {
  const metricInfo = {
    gpm:{label:'분당 골드',focus:'resource',question:'파밍을 멈추거나 귀환한 장면에서, 포기한 자원과 얻은 이득은 무엇이었나요?',image:'1055.png'},
    dpm:{label:'분당 피해량',focus:'fight_setup',question:'교전 직전 합류 위치·체력·자원을 확인하면 피해량의 차이를 설명할 수 있나요?',image:'SummonerFlash.png'},
    vision_per_minute:{label:'분당 시야 점수',focus:'vision',question:'오브젝트 준비 장면에서 시야를 확보한 시점과 아군 합류 위치는 어땠나요?',image:'3340.png'},
    kill_participation:{label:'킬 관여율',focus:'fight_setup',question:'아군 교전이 시작될 때, 합류할 수 있는 위치였는지 장면으로 확인해보세요.',image:'SummonerFlash.png'}
  };
  function report(records, key, metric) {
    if (!Object.hasOwn(metricInfo,metric)) metric = 'gpm';
    const matching = records.filter(window.ReviewJournal.valid).filter(item => window.ReviewJournal.group(item.context) === key)
      .sort((a,b) => Date.parse(a.context.played_at) - Date.parse(b.context.played_at));
    const comparison = window.ReviewJournal.compare(matching,key);
    const trend = matching.slice(-10).map(record => ({played_at:record.context.played_at,value:record.metrics[metric]}));
    const pending = matching.filter(record => record.action.trim() && (record.action_status || 'planned') !== 'reviewed').length;
    return {metric,info:metricInfo[metric],count:matching.length,trend,comparison,pending,
      latest:matching.at(-1) || null};
  }
  // 화면에 보여 줄 과제: 최신 미완료 기록 3개. 경기 일시 순서를 유지한다.
  function tasks(records) {
    return records.filter(window.ReviewJournal.valid).filter(record => record.action.trim() && (record.action_status || 'planned') !== 'reviewed')
      .sort((a,b) => Date.parse(b.context.played_at) - Date.parse(a.context.played_at)).slice(0,3);
  }
  return {report,tasks,metricInfo};
})();
