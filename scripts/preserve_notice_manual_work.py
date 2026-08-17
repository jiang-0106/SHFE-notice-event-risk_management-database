import argparse,json,sqlite3
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('mode',choices=['export','restore']);p.add_argument('--db',required=True);p.add_argument('--file',required=True);a=p.parse_args();db=Path(a.db);f=Path(a.file)
if a.mode=='export':
 c=sqlite3.connect(db); tables={x[0] for x in c.execute("select name from sqlite_master where type='table'")}; data={'manual_overrides':[],'review_tasks':[],'event_reviews':[]}
 if 'manual_overrides' in tables:
  cols=[x[1] for x in c.execute('pragma table_info(manual_overrides)')];data['manual_overrides']=[dict(zip(cols,r)) for r in c.execute('select * from manual_overrides')]
 if 'review_tasks' in tables:
  cols=[x[1] for x in c.execute('pragma table_info(review_tasks)')];data['review_tasks']=[dict(zip(cols,r)) for r in c.execute("select * from review_tasks where status<>'待复核' or assigned_to is not null or note is not null")]
 if 'parameter_events' in tables:
  cols=['event_id','old_value','new_value','unit','direction','effective_date_candidate','restore_date_candidate','monthly_match','daily_match','expansion_trigger','validation_conclusion','manual_review_status']
  data['event_reviews']=[dict(zip(cols,r)) for r in c.execute('select '+','.join(cols)+" from parameter_events where manual_review_status<>'待复核' or old_value is not null or new_value is not null or validation_conclusion is not null")]
 c.close();f.parent.mkdir(parents=True,exist_ok=True);f.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');print({k:len(v) for k,v in data.items()})
else:
 if not f.exists(): print('no manual work file');raise SystemExit(0)
 data=json.loads(f.read_text(encoding='utf-8'));c=sqlite3.connect(db)
 for r in data.get('manual_overrides',[]):
  cols=list(r);c.execute('insert or replace into manual_overrides('+','.join(cols)+') values('+','.join('?'*len(cols))+')',[r[x] for x in cols])
 for r in data.get('review_tasks',[]):
  c.execute('update review_tasks set status=?,assigned_to=?,reviewed_at=?,note=? where notice_id=?',(r.get('status'),r.get('assigned_to'),r.get('reviewed_at'),r.get('note'),r['notice_id']))
 for r in data.get('event_reviews',[]):
  cols=[x for x in r if x!='event_id'];c.execute('update parameter_events set '+','.join(x+'=?' for x in cols)+' where event_id=?',[r[x] for x in cols]+[r['event_id']])
 c.commit();c.close();print({k:len(v) for k,v in data.items()})
