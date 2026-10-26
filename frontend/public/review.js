'use strict';
const $ = id => document.getElementById(id);
let data, filename, records = [], index = 0, changed = false;
const roleNotes = {CEO:'Стратегия, спрос, рыночные риски и возможности.',CFO:'Финансирование, доходы и расходы, условия банковских продуктов.',TREASURER:'Платежи, сроки обязательств, ликвидность и резервы.'};
const node = (tag, text, cls) => { const e=document.createElement(tag); if(text!=null)e.textContent=String(text); if(cls)e.className=cls; return e; };
const claimsMode = () => Array.isArray(data?.claims);
const key = () => $('company').value+':'+$('role').value;
const entry = () => records[index];
const value = r => claimsMode() ? r.supported : r.relevance[key()];
function dirty(){changed=true;updateProgress();}
function updateProgress(){
  const all=claimsMode()?data.claims:data.events.flatMap(e=>Object.values(e.relevance));
  const done=claimsMode()?all.filter(c=>typeof c.supported==='boolean').length:all.filter(v=>Number.isInteger(v)).length;
  $('progress').textContent='Оценено '+done+' из '+all.length+(changed?' · есть несохранённые изменения':'');
}
function options(select, values){ select.replaceChildren(...values.map(([value,text])=>{const e=node('option',text);e.value=value;return e;})); }
function refreshRecords(){
  records=claimsMode()?data.claims:data.events.filter(e=>e.split===$('split').value);
  index=0;render();
}
function contextTable(features, target){
  const table=node('table');
  for(const [name,f] of Object.entries(features||{})){
    const row=node('tr'),a=node('th',f.label||name),b=node('td');
    b.append(node('div',JSON.stringify(f.value)),node('small',String(f.origin||f.provenance||f.source||'Происхождение не указано')));
    row.append(a,b);table.append(row);
  }
  target.append(table);
}
function sourceBlock(source){
  const detail=node('details'), summary=node('summary',source.publisher+' · '+source.title);
  detail.append(summary,node('p',source.published_at||'', 'muted'));
  if(source.url && /^https?:\/\//i.test(source.url)){
    const a=node('a','Открыть первоисточник');a.href=source.url;a.target='_blank';a.rel='noreferrer';detail.append(a);
  }
  if(source.coverage==='summary')detail.append(node('p','Доступна только аннотация, полного текста нет.','warning'));
  detail.append(node('div',source.content??source.excerpt??'', 'source source-scroll'));
  return detail;
}
function render(){
  $('workspace').hidden=false; const claim=claimsMode(),r=entry();
  for(const name of ['companyLabel','roleLabel','splitLabel'])$(name).hidden=claim;
  $('holdout').hidden=claim||$('split').value!=='holdout';
  $('position').textContent=records.length?(index+1)+' / '+records.length:'Нет утверждений для проверки';
  $('prev').disabled=index===0;$('next').disabled=index>=records.length-1;$('unmarked').disabled=!records.length;
  $('materials').replaceChildren();$('context').replaceChildren();
  if(!r){$('title').textContent='Материалы отсутствуют';$('label').disabled=true;$('comment').disabled=true;updateProgress();return;}
  $('label').disabled=false;$('comment').disabled=false;
  $('assessmentTitle').textContent=claim?'Проверка утверждения':'Оценка релевантности';
  $('meta').textContent=claim?r.company_id+' / '+r.role+' / '+r.section:r.published_at;
  $('title').textContent=claim?r.text:r.title;
  $('roleNote').textContent=roleNotes[claim?r.role:$('role').value]||'';
  $('rubric').textContent=claim?'Подтверждается: основания достаточны, ограничения и предпосылки корректны. Не подтверждается: ошибка или недостаток оснований. Для сценария проверяйте фактические предпосылки.':Object.entries(data.rubric||{}).map(([k,v])=>k+' — '+v).join('. ');
  options($('label'),claim?[['','Не оценено'],['true','Подтверждается'],['false','Не подтверждается']]:[['','Не оценено'],['0','0 · Не релевантно'],['1','1 · Полезная косвенная связь'],['2','2 · Приоритетно']]);
  $('label').value=value(r)==null?'':String(value(r));
  $('comment').value=claim?r.comment||'':r.comments?.[key()]||'';
  const materials=claim?r.evidence:r.sources;
  if(claim){
    $('materials').append(node('p',r.assumption?'Сценарий / предположение. Не входит в долю подтверждённых фактов.':'Фактическое утверждение.'));
    if(r.outdated)$('materials').append(node('p','Исторический разбор: выполнен по прежней версии проверки. Не подтверждает качество текущей версии.','warning'));
    $('materials').append(node('p','Запуск: '+r.run_id+' · проверка: '+(r.validation_version||'не указана'),'muted'));
    contextTable(r.context_features,$('context'));
  }else{
    const c=data.contexts[$('company').value];
    $('context').append(node('h3',c.name||c.company_id),node('p',c.industry),node('p',c.region));
    for(const text of [...(c.missing||[]),...(c.limitations||[])])$('context').append(node('p',text,'muted'));
    const detail=node('details');detail.append(node('summary','Признаки и их происхождение'));contextTable(c.features,detail);$('context').append(detail);
  }
  for(const source of materials||[])$('materials').append(sourceBlock(source));
  const first=$('materials').querySelector('details');if(first)first.open=true;
  updateProgress();
}
$('file').addEventListener('change',async event=>{
  if(changed&&!confirm('Заменить открытый файл? Несохранённые оценки будут потеряны.')){event.target.value='';return;}
  try{
    const file=event.target.files[0];if(!file)return;
    if(file.size>25*1024*1024)throw Error('Файл больше 25 МБ.');
    const loaded=JSON.parse(await file.text());
    if(loaded.schema_version!==2)throw Error('Нужен набор версии 2 с текстами источников и снимками профилей.');
    if(!Array.isArray(loaded.claims)&&(!Array.isArray(loaded.events)||loaded.companies?.length!==3||!loaded.contexts))throw Error('Неизвестная структура набора.');
    if(loaded.events?.some(e=>!e.relevance||!Array.isArray(e.sources)))throw Error('В наборе отсутствуют оценки или источники.');
    data=loaded;filename=file.name;changed=false;$('error').textContent='';$('reviewer').value=data.reviewer||'';$('save').disabled=false;
    $('provenance').hidden=data.reviewer_kind!=='ai';
    $('provenance').textContent='Предварительная AI-разметка. Это не независимая экспертная проверка. Редактирование и смена имени сохраняют происхождение оценок; для независимой разметки используйте исходный пустой набор.';
    if(!claimsMode())options($('company'),data.companies.map(c=>[c,c+' · '+(data.contexts[c]?.industry||'')]));
    refreshRecords();
  }catch(e){$('error').textContent=e.message;}
});
for(const id of ['company','role'])$(id).addEventListener('change',render);
$('split').addEventListener('change',refreshRecords);
$('prev').onclick=()=>{if(index>0){index--;render();}};
$('next').onclick=()=>{if(index<records.length-1){index++;render();}};
$('unmarked').onclick=()=>{for(let i=1;i<=records.length;i++){const next=(index+i)%records.length;if(value(records[next])==null){index=next;render();return;}}$('progress').textContent+=' · в этом профиле все оценки заполнены';};
$('label').onchange=()=>{
  if(!entry())return;
  const selected=$('label').value;
  if(claimsMode()){entry().supported=selected===''?null:selected==='true';entry().reviewer=$('reviewer').value.trim()||null;}
  else entry().relevance[key()]=selected===''?null:Number(selected);
  dirty();
};
$('comment').oninput=()=>{if(!entry())return;if(claimsMode())entry().comment=$('comment').value;else{entry().comments??={};entry().comments[key()]=$('comment').value;}dirty();};
$('reviewer').oninput=()=>{if(data)dirty();};
$('save').onclick=()=>{
  const reviewer=$('reviewer').value.trim();if(!reviewer){$('error').textContent='Укажите автора оценки перед сохранением.';$('reviewer').focus();return;}
  data.reviewer=reviewer;data.reviewed_at=new Date().toISOString();
  if(claimsMode())for(const c of data.claims)if(typeof c.supported==='boolean'&&!c.reviewer)c.reviewer=reviewer;
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob),a=node('a');a.href=url;a.download=filename.replace(/(?:\.reviewed)?\.json$/,'.reviewed.json');document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  changed=false;$('error').textContent='';updateProgress();
};
window.addEventListener('beforeunload',e=>{if(changed){e.preventDefault();e.returnValue='';}});
