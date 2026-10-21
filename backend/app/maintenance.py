"""Explicit maintenance actions; never delete source material."""
import argparse
import json
import os
from sqlalchemy import select
from .auth import hash_password
from .db import SessionLocal
from .models import Company, Document, Event, User
from .retrieval import classify

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['reclassify', 'create-admin'])
parser.add_argument('--username')
args = parser.parse_args()
with SessionLocal() as db:
    if args.action == 'reclassify':
        documents = db.scalars(select(Document)).all()
        for document in documents:
            document.topics = classify(document.title + ' ' + document.content)
        db.flush()
        for event in db.scalars(select(Event)).all():
            docs = [db.get(Document, i) for i in event.document_ids]
            event.topics = sorted({topic for doc in docs if doc for topic in doc.topics})
        db.commit()
        print(json.dumps({'reclassified_documents': len(documents)}))
    else:
        password = os.environ.get('NEW_ADMIN_PASSWORD', '')
        if not args.username or len(password) < 12:
            raise SystemExit('Provide --username and NEW_ADMIN_PASSWORD (at least 12 characters).')
        if db.scalar(select(User).where(User.username == args.username)):
            raise SystemExit('User already exists. Existing credentials are not modified.')
        db.add(User(username=args.username, name=args.username, password_hash=hash_password(password),
                    is_admin=True, company_ids=list(db.scalars(select(Company.id)).all())))
        db.commit()
        print('Admin created. Password is not logged.')
