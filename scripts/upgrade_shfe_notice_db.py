import argparse, csv, hashlib, json, shutil, sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',required=True); p.add_argument('--source-db',required=True); p.add_argument('--output',required=True); a=p.parse_args()
    root=Path(a.root).resolve(); src=Path(a.source_db).resolve(); out=Path(a.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    dbp=out/'SHFE多维公告标签数据库_正式版.sqlite3'; shutil.copy2(src,dbp)
    c=sqlite3.connect(dbp); c.execute('pragma foreign_keys=on'); c.execute('pragma journal_mode=WAL'); c.execute('pragma synchronous=NORMAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS database_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS reason_dictionary(reason_code TEXT PRIMARY KEY,reason_name TEXT,definition TEXT,display_order INTEGER);
    CREATE TABLE IF NOT EXISTS parameter_dictionary(parameter_code TEXT PRIMARY KEY,parameter_name TEXT,definition TEXT);
    CREATE TABLE IF NOT EXISTS product_dictionary(product_code TEXT PRIMARY KEY,product_name TEXT);
    CREATE INDEX IF NOT EXISTS ix_notices_date_reason ON notices(publish_date,primary_reason_code);
    CREATE INDEX IF NOT EXISTS ix_notices_review ON notices(review_status,reason_confidence);
    CREATE INDEX IF NOT EXISTS ix_products_product_notice ON notice_products(product_code,notice_id);
    CREATE INDEX IF NOT EXISTS ix_parameters_parameter_notice ON notice_parameters(parameter_code,notice_id);
    CREATE INDEX IF NOT EXISTS ix_dates_value_notice ON notice_dates(date_value,notice_id);
    CREATE VIEW IF NOT EXISTS v_notice_query AS
      SELECT n.notice_id,n.title,n.publish_date,n.primary_reason_code,n.primary_reason,n.reason_confidence,n.parameter_related,n.review_status,
       (SELECT group_concat(product_code,',') FROM notice_products p WHERE p.notice_id=n.notice_id) product_codes,
       (SELECT group_concat(product_name,'、') FROM notice_products p WHERE p.notice_id=n.notice_id) product_names,
       (SELECT group_concat(parameter_code,',') FROM notice_parameters m WHERE m.notice_id=n.notice_id) parameter_codes,
       (SELECT group_concat(parameter_name,'、') FROM notice_parameters m WHERE m.notice_id=n.notice_id) parameter_names,
       (SELECT group_concat(contract_codes,',') FROM notice_products p WHERE p.notice_id=n.notice_id AND contract_codes<>'') contract_codes,
       n.source_url,n.local_path
      FROM notices n;
    CREATE VIEW IF NOT EXISTS v_review_queue AS
      SELECT * FROM v_notice_query WHERE review_status LIKE '%待人工复核%' OR reason_confidence<0.75;
    ''')
    reasons=c.execute('select distinct primary_reason_code,primary_reason from notices order by primary_reason_code').fetchall()
    c.executemany('insert or replace into reason_dictionary values(?,?,?,?)',[(x,y,'按公告正文与标题自动识别；正式研究使用前应复核证据片段',i) for i,(x,y) in enumerate(reasons)])
    c.execute('insert or replace into parameter_dictionary select distinct parameter_code,parameter_name,? from notice_parameters',('参数标签允许一则公告多标签并存',))
    c.execute('insert or replace into product_dictionary select distinct product_code,product_name from notice_products')
    meta={'version':'2.0-formal','generated_at':datetime.now().astimezone().isoformat(timespec='seconds'),'root':str(root),'classification_method':'规则词典+证据片段+置信度+人工复核队列','dimensions':'调整原因、调整参数、时间、品种/合约'}
    c.executemany('insert or replace into database_metadata values(?,?)',meta.items())
    # Old absolute paths are redirected to the flattened root when the relative tail is identifiable.
    for nid,lp in c.execute('select notice_id,local_path from notices').fetchall():
        s=str(lp or '').replace('/','\\'); pos=s.lower().find('details\\')
        if pos>=0: c.execute('update notices set local_path=? where notice_id=?',(str(root/s[pos:]),nid))
    c.commit(); integrity=c.execute('pragma integrity_check').fetchone()[0]
    cols=[x[1] for x in c.execute('pragma table_info(v_notice_query)')]
    rows=c.execute('select * from v_notice_query order by publish_date,notice_id').fetchall()
    with (out/'公告多维查询总表.csv').open('w',newline='',encoding='utf-8-sig') as f: w=csv.writer(f); w.writerow(cols); w.writerows(rows)
    review=c.execute('select * from v_review_queue order by publish_date,notice_id').fetchall()
    with (out/'待人工复核.csv').open('w',newline='',encoding='utf-8-sig') as f: w=csv.writer(f); w.writerow(cols); w.writerows(review)
    audit={'generated_at':meta['generated_at'],'integrity':integrity,'notices':len(rows),'review_queue':len(review),'products':c.execute('select count(*) from product_dictionary').fetchone()[0],'parameters':c.execute('select count(*) from parameter_dictionary').fetchone()[0],'reasons':c.execute('select count(*) from reason_dictionary').fetchone()[0],'missing_local_paths':sum(not Path(r[-1]).exists() for r in rows if r[-1]),'database_sha256':None,'reason_distribution':dict(Counter(r[3] for r in rows))}
    c.execute('pragma wal_checkpoint(truncate)'); c.close(); audit['database_sha256']=sha256(dbp)
    (out/'数据库质量审计_正式版.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'README_正式版.md').write_text('''# SHFE多维公告标签数据库（正式版）\n\n主查询维度为：为什么调整（原因）、调整了什么（参数）、什么时候调整（公告日/候选生效日）、调整哪个品种或合约。\n\n- `SHFE多维公告标签数据库_正式版.sqlite3`：主数据库，含全文检索、组合索引、词典表、查询视图和人工复核视图。\n- `SHFE公告多维查询总表_正式版.xlsx`：面向非技术用户的筛选入口。\n- `query_shfe_notices.py`：命令行组合查询并导出CSV。\n- `数据库质量审计_正式版.json`：完整性、数量、路径和哈希审计。\n\n自动标签是研究初筛工具，不代替人工确认。重要事件研究前应复核公告正文、证据片段和生效日期。\n''',encoding='utf-8')
    print(json.dumps(audit,ensure_ascii=True,indent=2))
if __name__=='__main__': main()
