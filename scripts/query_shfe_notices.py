import argparse,csv,sqlite3
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--db',required=True); p.add_argument('--reason'); p.add_argument('--parameter'); p.add_argument('--product'); p.add_argument('--contract'); p.add_argument('--from-date'); p.add_argument('--to-date'); p.add_argument('--keyword'); p.add_argument('--review-only',action='store_true'); p.add_argument('--limit',type=int,default=100000); p.add_argument('--out',default='查询结果.csv'); a=p.parse_args()
c=sqlite3.connect(a.db); sql='select * from v_notice_query n where 1=1'; v=[]
if a.reason: sql+=' and (n.primary_reason_code=? or n.primary_reason like ?)'; v += [a.reason.zfill(2),'%'+a.reason+'%']
if a.parameter: sql+=' and exists(select 1 from notice_parameters m where m.notice_id=n.notice_id and (m.parameter_code=? or m.parameter_name like ?))'; v += [a.parameter,'%'+a.parameter+'%']
if a.product: sql+=' and exists(select 1 from notice_products p where p.notice_id=n.notice_id and (p.product_code=? or p.product_name like ?))'; v += [a.product.upper(),'%'+a.product+'%']
if a.contract: sql+=' and n.contract_codes like ?'; v += ['%'+a.contract.upper()+'%']
if a.from_date: sql+=' and n.publish_date>=?'; v += [a.from_date]
if a.to_date: sql+=' and n.publish_date<=?'; v += [a.to_date]
if a.keyword: sql+=' and n.notice_id in(select notice_id from notice_fts where notice_fts match ?)'; v += [a.keyword]
if a.review_only: sql+=" and (n.review_status like '%待人工复核%' or n.reason_confidence<0.75)"
sql+=' order by n.publish_date,n.notice_id limit ?'; v += [a.limit]; cur=c.execute(sql,v); cols=[x[0] for x in cur.description]; rows=cur.fetchall(); c.close()
o=Path(a.out); o.parent.mkdir(parents=True,exist_ok=True)
with o.open('w',newline='',encoding='utf-8-sig') as f: w=csv.writer(f); w.writerow(cols); w.writerows(rows)
print(f'rows={len(rows)} output={o.resolve()}')
