"""Read-only HNSW vs exact recall/latency benchmark using stored vectors.

No crawl, embedding generation or paid LLM. This measures index recall, not
human relevance. Use --company to measure filtered retrieval separately.
"""
import argparse
import json
import time

import psycopg

from interviewlens.config import settings
from interviewlens.db.processing_reads import READY_POST_SQL
from interviewlens.db.attribution import question_scope_sql
from interviewlens.embedding import EMBEDDING_VERSION


def evaluate(samples=20, k=20, company=None):
    if not 1 <= samples <=100 or not 1<=k<=100:
        raise ValueError('Bound samples and top-k to 1..100')
    url=settings.database_url_sync.replace('postgresql+psycopg://','postgresql://',1)
    with psycopg.connect(url) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        conn.execute("SET LOCAL statement_timeout='15s'")
        conn.execute("SET LOCAL hnsw.ef_search=200")
        conn.execute("SET LOCAL hnsw.iterative_scan=strict_order")
        clauses=[READY_POST_SQL,"po.extract_status='done'","q.embedding IS NOT NULL",
                 "q.embedding_model=%(model)s","q.embedding_version=%(version)s"]
        if company:
            clauses.append(question_scope_sql(company='%(company)s',position=None))
        params={'model':settings.embedding_model,'version':EMBEDDING_VERSION,'company':company,'samples':samples,'k':k}
        where=' AND '.join(clauses)
        anchors=conn.execute(f'SELECT q.id,q.embedding::text FROM questions q JOIN posts po ON po.id=q.post_id WHERE {where} ORDER BY md5(q.id::text) LIMIT %(samples)s',params).fetchall()
        measurements=[]
        query=f'SELECT q.id,q.embedding <=> %(vec)s::vector AS distance FROM questions q JOIN posts po ON po.id=q.post_id WHERE {where} AND q.id<>%(anchor)s ORDER BY q.embedding <=> %(vec)s::vector LIMIT %(k)s'
        for anchor,vector in anchors:
            params.update(anchor=anchor,vec=vector)
            conn.execute('SET LOCAL enable_indexscan=off')
            conn.execute('SET LOCAL enable_seqscan=on')
            start=time.perf_counter(); exact_rows=conn.execute(query,params).fetchall(); exact={row[0] for row in exact_rows}; exact_ms=(time.perf_counter()-start)*1000
            conn.execute('SET LOCAL enable_indexscan=on')
            conn.execute('SET LOCAL enable_seqscan=off')
            start=time.perf_counter(); ann_rows=conn.execute(query,params).fetchall(); approximate={row[0] for row in ann_rows}; ann_ms=(time.perf_counter()-start)*1000
            boundary=max((row[1] for row in exact_rows),default=None)
            measurements.append({'anchor':anchor,'exact_count':len(exact),'ann_count':len(approximate),
                                 'recall':len(exact & approximate)/len(exact) if exact else None,
                                 'distance_recall':sum(row[1]<=boundary+1e-6 for row in ann_rows)/len(exact) if exact else None,
                                 'exact_ms':round(exact_ms,2),'ann_ms':round(ann_ms,2)})
        values=[m['recall'] for m in measurements if m['recall'] is not None]
        distance_values=[m['distance_recall'] for m in measurements if m['distance_recall'] is not None]
        return {'samples':len(measurements),'k':k,'company':company,'mean_recall':sum(values)/len(values) if values else None,
                'mean_distance_recall':sum(distance_values)/len(distance_values) if distance_values else None,
                'measurements':measurements,'scope':'index recall; human relevance not assessed'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=20)
    parser.add_argument('--k',type=int,default=20)
    parser.add_argument('--company')
    args=parser.parse_args()
    try:
        print(json.dumps(evaluate(args.samples,args.k,args.company),ensure_ascii=False))
    except Exception as error:
        print(f'Evaluation failed ({type(error).__name__}); credentials withheld.')
        raise SystemExit(1) from None
