"""Fixtures are synthetic, versioned and included in the repository and image."""
from datetime import timedelta
from .auth import hash_password
from .config import settings
from .context import feature
from .db import SessionLocal, utcnow
from .ingestion import digest, import_document
from .models import Company, Link, User
from .showcase import bundle

DEMO_EVENTS=[(n['title'],n['topic'],n['content'],i) for i,n in enumerate(bundle()['news'])]


def seed(db):
    if db.get(Company,'demo-metal'):
        return
    data=bundle()
    for spec in data['companies']:
        db.add(Company(**{k:spec[k] for k in ('id','name','industry','region','group_id')},synthetic=True,
            features={k:feature(v,'Синтетический демонстрационный набор',label=k) for k,v in spec['features'].items()}))
    db.flush()
    for link in data['links']:
        db.add(Link(id=digest(f"demo:{link['source_id']}:{link['target_id']}"),kind='payment',**link,
                    details={'source':'Синтетический набор'}))
    password=hash_password(settings().demo_password)
    db.add(User(username='demo',name='Александр Иванов',password_hash=password,
                company_ids=[c['id'] for c in data['companies']],is_admin=True))
    db.add(User(username='viewer',name='Наблюдатель',password_hash=password,
                company_ids=['demo-metal'],is_admin=False))
    db.commit()
    for news in data['news']:
        import_document(db,title=news['title'],content=news['content'],kind='news',
            publisher='Учебная редакция · синтетический материал',
            published_at=utcnow()-timedelta(hours=news['age_hours']),synthetic=True)
    for bank in data['bank']:
        import_document(db,title=bank['title'],content=bank['content'],kind='bank',
            publisher='Учебная аналитика · не материал банка',
            published_at=utcnow()-timedelta(days=bank['age_days']),synthetic=True)


if __name__=='__main__':
    with SessionLocal() as session:
        seed(session)
