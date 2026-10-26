import {useEffect,useState} from 'react';
import type {FormEvent} from 'react';

type Connection = {
  revision:string;source:string;enabled:boolean;provider_mode:'local'|'remote';base_url:string;
  api_key_configured:boolean;approved_models:string[];
  analysis_model:string;analysis_id:string;extraction_model:string;extraction_id:string;model_revision:string;
  timeout_seconds:number;context_characters:number;automatic:boolean;active_company_ids:string;
  input_rub_per_million:number;output_rub_per_million:number;daily_limit_rub:number;test_limit_rub:number;request_limit:number;
};
type Request = <T>(path:string,options?:RequestInit)=>Promise<T>;

export default function LlmSettings({request,onSaved}:{request:Request;onSaved:()=>void}) {
  const [form,setForm]=useState<Connection|null>(null);
  const [token,setToken]=useState('');
  const [clearKey,setClearKey]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const [savedTarget,setSavedTarget]=useState('');
  function accept(data:Connection){setForm(data);setToken('');setClearKey(false);setSavedTarget(data.provider_mode+'|'+data.base_url);}
  useEffect(()=>{request<Connection>('/admin/llm-settings').then(accept).catch(e=>setError(e.message));},[request]);
  const update=(patch:Partial<Connection>)=>{setForm(previous=>previous?{...previous,...patch}:previous);setMessage('');};
  async function submit(event:FormEvent){
    event.preventDefault();if(!form)return;
    setBusy(true);setError('');setMessage('');
    const {source,approved_models,api_key_configured,...values}=form;
    void source;void approved_models;void api_key_configured;
    try {
      accept(await request<Connection>('/admin/llm-settings',{method:'POST',body:JSON.stringify({...values,api_key:token||null,clear_api_key:clearKey})}));
      setMessage('Настройки сохранены. Проверочный запрос к модели не отправлялся.');onSaved();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function reset(){
    if(!form)return;setBusy(true);setError('');setMessage('');
    try{accept(await request<Connection>('/admin/llm-settings/reset',{method:'POST',body:JSON.stringify({revision:form.revision})}));
      setMessage('Восстановлены настройки из окружения сервера.');onSaved();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  if(!form)return <div className="panel">{error||'Загружаем настройки…'}</div>;
  const sameTarget=savedTarget===form.provider_mode+'|'+form.base_url;
  const names=(name:string)=>form.approved_models.includes(name)?form.approved_models:[name,...form.approved_models];
  const numeric=(key:keyof Connection,label:string,min=0,max?:number)=> <label key={key}>{label}
    <input type="number" min={min} max={max} step={key.endsWith('_rub')||key.endsWith('_million')?'any':1}
      required value={String(form[key])} onChange={e=>update({[key]:Number(e.target.value)})}/></label>;
  return <div className="panel llm-settings">
    <h2>Подключение модели</h2>
    <p className="muted">Настройки общие для API и worker. Токен хранится на сервере и не возвращается в браузер. Изменения применяются без перезапуска.</p>
    {error&&<div className="error-box" role="alert">{error}</div>}
    {message&&<div className="panel" role="status">{message}</div>}
    <form className="import-form" onSubmit={submit} autoComplete="off">
      <div className="form-row">
        <label>Тип подключения<select value={form.provider_mode} onChange={e=>{
          setToken('');setClearKey(false);
          update({provider_mode:e.target.value as 'local'|'remote',automatic:false,
            base_url:e.target.value==='local'?'http://host.docker.internal:8001/v1':'https://api.deepseek.com'});
        }}><option value="remote">Удалённый API</option><option value="local">Локальная модель</option></select></label>
        <label>Адрес API<input type="url" value={form.base_url} required={form.enabled} placeholder="https://api.deepseek.com"
          onChange={e=>update({base_url:e.target.value})}/></label>
      </div>
      <label>Токен API<input type="password" autoComplete="new-password" spellCheck={false} maxLength={4096}
        value={token} onChange={e=>{setToken(e.target.value);setClearKey(false);setMessage('');}}
        placeholder={form.api_key_configured&&sameTarget?'Ключ сохранён · оставьте пустым, чтобы сохранить':'Вставьте токен; для локального сервера он может не требоваться'}/></label>
      <p className="form-note">{form.api_key_configured&&sameTarget?'Сохранённый ключ не отображается.':'Для нового адреса сохранённый ключ не переносится — введите его заново при необходимости.'}</p>
      {form.api_key_configured&&<label className="checkbox"><input type="checkbox" checked={clearKey} onChange={e=>{
        setClearKey(e.target.checked);if(e.target.checked){setToken('');if(form.provider_mode==='remote')update({enabled:false});}
      }}/>Удалить сохранённый ключ при сохранении</label>}
      <div className="form-row">
        <label>Модель анализа<select value={form.analysis_model} onChange={e=>update({analysis_model:e.target.value,
          ...(form.extraction_model===form.analysis_model?{extraction_model:e.target.value}:{})})}>
          {names(form.analysis_model).map(name=><option key={name}>{name}</option>)}</select></label>
        <label>ID модели анализа<input value={form.analysis_id} required={form.enabled} placeholder="Точный ID на вашем сервере"
          onChange={e=>update({analysis_id:e.target.value,...(form.extraction_id===form.analysis_id?{extraction_id:e.target.value}:{})})}/></label>
      </div>
      {form.provider_mode==='remote'&&<button type="button" className="text-button" onClick={()=>{
        setToken('');update({base_url:'https://api.deepseek.com',analysis_model:'DeepSeek-V4.1-Flash',extraction_model:'DeepSeek-V4.1-Flash',
          analysis_id:'deepseek-flash',extraction_id:'deepseek-flash'});
      }}>Подставить параметры DeepSeek Flash</button>}
      <details><summary>Дополнительные параметры модели</summary>
        <div className="form-row">
          <label>Модель извлечения<select value={form.extraction_model} onChange={e=>update({extraction_model:e.target.value})}>
            {names(form.extraction_model).map(name=><option key={name}>{name}</option>)}</select></label>
          <label>ID модели извлечения<input value={form.extraction_id} required={form.enabled} onChange={e=>update({extraction_id:e.target.value})}/></label>
        </div>
        <div className="form-row">{numeric('timeout_seconds','Таймаут ответа, сек',1,3600)}{numeric('context_characters','Контекст, символов',4000,10000000)}</div>
        <label>Версия весов или настроек модели<input value={form.model_revision} onChange={e=>update({model_revision:e.target.value})} placeholder="Меняйте при замене весов с прежним ID"/></label>
      </details>
      {form.provider_mode==='local'?<>
        <p className="form-note">Для модели на компьютере с Docker используйте host.docker.internal вместо localhost. Денежных лимитов и квоты запросов в локальном режиме нет.</p>
      </>:<details open><summary>Бюджет удалённого API</summary>
        <p className="form-note">Укажите тарифы провайдера. Сохранённая история расходов не обнуляется. Автоматическая обработка расходует этот же бюджет.</p>
        <div className="form-row">{numeric('input_rub_per_million','Ввод, ₽ за миллион токенов')}{numeric('output_rub_per_million','Вывод, ₽ за миллион токенов')}</div>
        <div className="form-row">{numeric('test_limit_rub','Общий лимит теста, ₽',0,500)}{numeric('request_limit','Общий лимит обращений')}</div>
        {numeric('daily_limit_rub','Дневной лимит, ₽',0,500)}
      </details>}
      <label className="checkbox"><input type="checkbox" checked={form.enabled} onChange={e=>update({enabled:e.target.checked,...(!e.target.checked?{automatic:false}:{})})}/>Разрешить вызовы LLM</label>
      <label className="checkbox"><input type="checkbox" disabled={!form.enabled} checked={form.automatic} onChange={e=>update({automatic:e.target.checked})}/>Автоматически обрабатывать новые новости</label>
      {form.automatic&&<label>Компании для автоматической обработки<input value={form.active_company_ids} onChange={e=>update({active_company_ids:e.target.value})}/></label>}
      <p className="form-note">{form.enabled&&form.automatic
        ?form.provider_mode==='remote'?'После сохранения модель будет оценивать новые и изменённые статьи для выбранных компаний и проверять оценки. Расходы ограничены указанным бюджетом. Старый архив и сравнительная перестройка всей ленты запускаются отдельно.'
        :'После сохранения начнётся автоматическая обработка выбранных компаний локальной моделью.'
        :'Само сохранение не отправляет запросов к модели.'}</p>
      <div className="showcase-actions"><button type="submit" className="primary" disabled={busy}>{busy?'Сохраняем…':'Сохранить настройки'}</button>
        {form.source==='interface'&&<button type="button" className="secondary" disabled={busy} onClick={()=>void reset()}>Вернуть настройки из .env</button>}</div>
    </form>
  </div>;
}
