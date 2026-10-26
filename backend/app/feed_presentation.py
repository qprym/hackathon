"""Reading aids and action availability; never rewrite source evidence or model grades."""
import re
from sqlalchemy import select
from .config import settings
from .models import Run


def reading_notes(text, publisher):
    if publisher != 'Банк России':return []
    found={m.group(0).lower() for m in re.finditer(r'\b(?:[12]п|[1-4]к)\d{2}\b',text,re.I)}
    return [{'term':term,'meaning':f'{term[0]}-е полугодие 20{term[2:]} года' if term[1]=='п'
             else f'{term[0]}-й квартал 20{term[2:]} года'} for term in sorted(found)]


def article_preview(doc):
    if not doc:return {'summary':'','summary_truncated':False,'source_coverage':'unknown','reading_notes':[]}
    text=doc.content.strip()
    # Complete opening sentences, including one long sentence if necessary. No mid-word cuts.
    stops=list(re.finditer(r'[.!?…](?=\s|$)',text))
    end=stops[0].end() if stops else len(text)
    if len(stops)>1 and stops[1].end()<=520:end=stops[1].end()
    summary=text[:end]
    return {'summary':summary,'summary_truncated':end<len(text),
            'source_coverage':(doc.ingestion_meta or {}).get('coverage','unknown'),
            'reading_notes':reading_notes(summary,doc.publisher)}


def analysis_states(db,user,company_id,role,event_ids,synthetic):
    cfg=settings()
    if not cfg.preview_cached_only or synthetic:
        return {key:{'status':'available','mode':'demo' if cfg.demo_mode else 'llm'} for key in event_ids}
    states={key:{'status':'unavailable','message':'Для этой компании, роли и новости сохранённого разбора нет. Вызовы модели отключены. Полный текст статьи доступен без LLM.'} for key in event_ids}
    rows=db.execute(select(Run.id,Run.event_id,Run.access_scope).where(
        Run.user_id==user.id,Run.company_id==company_id,Run.role==role,Run.event_id.in_(event_ids),
        Run.question.is_(None),Run.status=='completed',Run.result['mode'].as_string()=='live')
        .order_by(Run.created_at.desc())).all()
    for run_id,event_id,scope in rows:
        if states[event_id]['status']=='unavailable' and scope and set(scope).issubset(user.company_ids):
            states[event_id]={'status':'saved','run_id':run_id,'historical':True}
    return states
