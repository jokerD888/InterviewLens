"""Evaluate stored classifications against independently labelled profiles.

JSON labels: [{"post_id":1,"ordinal":0,"category":"后端",
"specializations":["基础架构"],"domains":[],"skills":["Java"]}].
This tool does not generate its own ground truth or call an LLM.
"""
import argparse
import json
from pathlib import Path

import psycopg

from interviewlens.config import settings


def compare(labels, profiles):
    hits=0
    metrics={field:{'tp':0,'fp':0,'fn':0} for field in ('specializations','domains','skills')}
    for label in labels:
        profile=profiles.get((label['post_id'],label.get('ordinal',0)))
        if profile is None:
            raise ValueError('An annotated profile is missing; do not silently skip it')
        hits += profile.get('category')==label['category']
        for field,m in metrics.items():
            expected=set(label[field]); actual=set(profile.get(field,[]))
            m['tp']+=len(expected & actual); m['fp']+=len(actual-expected); m['fn']+=len(expected-actual)
    for field,m in metrics.items():
        denominator=2*m['tp']+m['fp']+m['fn']
        m['micro_f1']=2*m['tp']/denominator if denominator else None
    return {'labelled_profiles':len(labels),'category_accuracy':hits/len(labels),'facets':metrics,
            'scope':'supplied annotations only; not an unlabelled full-library accuracy claim'}


def evaluate(path):
    labels=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(labels,list) or not labels or len(labels)>1000:
        raise ValueError('Supply 1..1000 independently labelled profiles')
    identities=[(label['post_id'],label.get('ordinal',0)) for label in labels]
    if len(set(identities))!=len(identities):
        raise ValueError('Duplicate labelled profiles bias the evaluation')
    url=settings.database_url_sync.replace('postgresql+psycopg://','postgresql://',1)
    with psycopg.connect(url) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        rows=conn.execute('SELECT post_id,ordinal,payload FROM post_position_profiles WHERE post_id=ANY(%s)',([item[0] for item in identities],)).fetchall()
        return compare(labels,{(post_id,ordinal):payload for post_id,ordinal,payload in rows})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels',type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(evaluate(args.labels),ensure_ascii=False))
    except Exception as error:
        print(f'Profile evaluation failed ({type(error).__name__}); credentials withheld.')
        raise SystemExit(1) from None
