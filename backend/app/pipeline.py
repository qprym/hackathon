"""Local-only automatic source -> assessments -> complete feed reconciliation."""
from sqlalchemy import select
from .config import settings
from .db import SessionLocal, utcnow
from .models import Company, Event, User, FeedState, RankingJob
from .semantic_ranking import enqueue as enqueue_assessments, fingerprint
from .full_selection import enqueue as enqueue_feed, from_database, cached_job


def schedule():
    cfg=settings()
    # Remote trials remain explicitly initiated. This scheduler cannot spend their allowance.
    if not (cfg.auto_personalization and cfg.neural_ranking_worker and cfg.llm_provider_mode=='local'
            and cfg.llm_base_url and not cfg.demo_mode):return []
    outcomes=[]
    with SessionLocal() as db:
        users=db.scalars(select(User).order_by(User.username)).all()
        events=db.scalars(select(Event).where(Event.synthetic.is_(False)).order_by(Event.published_at.desc(),Event.id)).all()
        for company_id in filter(None,(x.strip() for x in cfg.active_company_ids.split(','))):
            company=db.get(Company,company_id)
            if not company:continue
            # Each access scope gets its own context; never broaden permissions for automation.
            scopes={}
            for user in users:
                if company_id in user.company_ids:scopes.setdefault(fingerprint(sorted(user.company_ids)),user)
            for scope,user in scopes.items():
                state_key='pipeline-'+fingerprint([company_id,scope])[:25]
                state=db.get(FeedState,state_key)
                if not state:state=FeedState(key=state_key);db.add(state);db.commit()
                try:
                    queued=enqueue_assessments(db,user,company,events)
                    pending=db.scalar(select(RankingJob.id).where(RankingJob.company_id==company_id,
                        RankingJob.user_id==user.id,RankingJob.status.in_(['queued','running'])).limit(1))
                    if pending:
                        report={'company_id':company_id,'stage':'processing','pending_job':pending,'queued':queued['articles_queued']}
                    elif not events:
                        report={'company_id':company_id,'stage':'waiting_sources'}
                    else:
                        # Complete selection also reconsiders articles with failed/negative preliminary scores.
                        job=enqueue_feed(db,user,company)
                        report={'company_id':company_id,'stage':job['status'],'job_id':job['job_id']}
                    state.status='idle';state.error=None;state.report=report
                except Exception as exc:
                    db.rollback();state=db.get(FeedState,state_key)
                    state.status='error';state.error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                    report={'company_id':company_id,'stage':'error','error':state.error}
                    state.report=report
                state.last_finished_at=utcnow();db.commit();outcomes.append(report)
    return outcomes
