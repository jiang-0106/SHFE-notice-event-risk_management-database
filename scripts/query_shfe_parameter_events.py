import argparse,csv,sqlite3
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--product');p.add_argument('--parameter');p.add_argument('--reason');p.add_argument('--from-date');p.add_argument('--to-date');p.add_argument('--review-status');p.add_argument('--monthly-match');p.add_argument('--daily-match');p.add_argument('--out',default='参数事件查询结果.csv');a=p.parse_args();c=sqlite3.connect(a.db)
sql='select e.*,n.title,n.source_url,n.local_path from parameter_events e join notices n using(notice_id) where 1=1';v=[]
for arg,col in [(a.product,'e.product_code'),(a.parameter,'e.parameter_code'),(a.reason,'e.reason_code'),(a.review_status,'e.manual_review_status'),(a.monthly_match,'e.monthly_match'),(a.daily_match,'e.daily_match')]:
 if arg:sql+=f' and {col}=?';v.append(arg.upper() if col=='e.product_code' else arg)
if a.from_date:sql+=' and coalesce(e.effective_date_candidate,e.announcement_date)>=?';v.append(a.from_date)
if a.to_date:sql+=' and coalesce(e.effective_date_candidate,e.announcement_date)<=?';v.append(a.to_date)
sql+=' order by coalesce(e.effective_date_candidate,e.announcement_date),e.notice_id,e.product_code,e.parameter_code';cur=c.execute(sql,v);cols=[x[0] for x in cur.description];rows=cur.fetchall();c.close();o=Path(a.out);o.parent.mkdir(parents=True,exist_ok=True)
with o.open('w',newline='',encoding='utf-8-sig') as f:w=csv.writer(f);w.writerow(cols);w.writerows(rows)
print(f'rows={len(rows)} output={o.resolve()}')
