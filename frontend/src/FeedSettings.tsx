import {useEffect,useState} from 'react';
import type {FormEvent} from 'react';
type Config={revision:string;automatic:boolean;interval_seconds:number;sources:string[];catalog:{key:string;name:string;url:string}[]};
type Status={items:{key:string;scheduled:boolean;status:string;next_refresh_at:string|null;last_finished_at:string|null;error?:string|null}[]};
type Request=<T>(path:string,options?:RequestInit)=>Promise<T>;

export default function FeedSettings({request,onSaved}:{request:Request;onSaved:()=>void}){
  const [form,setForm]=useState<Config|null>(null),[status,setStatus]=useState<Status|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{
    let active=true;
    request<Config>('/admin/feed-settings').then(value=>{if(active)setForm(value);}).catch(e=>{if(active)setError(e.message);});
    const refresh=()=>request<Status>('/feeds/status').then(value=>{if(active)setStatus(value);}).catch(()=>{});
    void refresh();const timer=setInterval(()=>void refresh(),10000);
    return()=>{active=false;clearInterval(timer);};
  },[request]);
  async function save(event:FormEvent){
    event.preventDefault();if(!form)return;setBusy(true);setError('');setMessage('');
    try{
      const {catalog,...body}=form;void catalog;
      const saved=await request<Config>('/admin/feed-settings',{method:'POST',body:JSON.stringify(body)});
      setForm(saved);setStatus(await request<Status>('/feeds/status'));
      setMessage(saved.automatic?'Автообновление включено. Расписание сохранено.':'Автообновление отключено. Уже начатая загрузка завершится.');onSaved();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function update(patch:Partial<Config>){setForm(previous=>previous?{...previous,...patch}:null);setMessage('');}
  return <section className="panel feed-settings" aria-label="Автообновление новостей">
    <h2>Автообновление новостей</h2>
    <p className="muted">Парсер загружает доступные статьи из выбранных RSS-лент. Подключение модели и автоматический нейросетевой отбор задаются отдельно в «Настройки LLM».</p>
    {error&&<p className="error-box" role="alert">{error}</p>}
    {message&&<p role="status">{message}</p>}
    {form?<form onSubmit={save}>
      <label className="checkbox"><input type="checkbox" checked={form.automatic} onChange={e=>update({automatic:e.target.checked})}/>Автоматически загружать новости</label>
      <label>Интервал обновления, минуты<input type="number" min={1} max={1440} step="any" required value={form.interval_seconds/60} onChange={e=>update({interval_seconds:Math.round(Number(e.target.value)*60)})}/></label>
      <div className="sources-grid">{form.catalog.map(source=>{
        const state=status?.items.find(item=>item.key===source.key);
        return <div key={source.key} className="feed-setting-source">
          <label className="checkbox"><input type="checkbox" checked={form.sources.includes(source.key)} onChange={e=>update({sources:e.target.checked?[...form.sources,source.key]:form.sources.filter(key=>key!==source.key)})}/>{source.name}</label>
          <a className="small" href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a>
          <p className="small muted">{state?.status==='running'?'Загрузка выполняется':state?.scheduled?`Следующая загрузка: ${state.next_refresh_at?new Date(state.next_refresh_at).toLocaleString('ru-RU'):'в ближайшие 10 секунд'}`:'Автозагрузка источника отключена'}</p>
          {state?.last_finished_at&&<p className="small muted">Последняя проверка: {new Date(state.last_finished_at).toLocaleString('ru-RU')}</p>}
          {state?.error&&<p className="small">{state.error}</p>}
        </div>;
      })}</div>
      <button className="primary" type="submit" disabled={busy}>{busy?'Сохраняем…':'Сохранить расписание'}</button>
    </form>:!error&&<p>Загружаем настройки…</p>}
  </section>;
}
