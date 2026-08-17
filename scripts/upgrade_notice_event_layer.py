import argparse,csv,hashlib,json,shutil,sqlite3
from datetime import datetime,date
from pathlib import Path

TARGET={'AU','AG','CU','RB','FU'}
CORE={'price_limit','margin','margin_general','margin_hedge','trading_limit','intraday_open_limit','position_limit','trading_hours','night_session'}
def h(s): return hashlib.sha256(s.encode()).hexdigest()[:20]
def export(c,path,sql):
    cur=c.execute(sql); cols=[x[0] for x in cur.description]
    with path.open('w',newline='',encoding='utf-8-sig') as f: w=csv.writer(f); w.writerow(cols); w.writerows(cur)
def main():
    a=argparse.ArgumentParser(); a.add_argument('--db',required=True); a.add_argument('--out',required=True); x=a.parse_args(); dbp=Path(x.db); out=Path(x.out); out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(dbp); c.execute('pragma foreign_keys=on')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS manual_overrides(
      override_id INTEGER PRIMARY KEY,notice_id TEXT NOT NULL,dimension TEXT NOT NULL,action TEXT NOT NULL,
      original_code TEXT,replacement_code TEXT,replacement_value TEXT,effective_date TEXT,restore_date TEXT,
      old_value TEXT,new_value TEXT,reviewer TEXT,reviewed_at TEXT,evidence TEXT,note TEXT,
      UNIQUE(notice_id,dimension,action,original_code,replacement_code));
    CREATE TABLE IF NOT EXISTS product_tag_assessment(
      notice_id TEXT,product_code TEXT,usage_class TEXT,risk_flag TEXT,assessment_reason TEXT,
      review_status TEXT DEFAULT '自动评估',PRIMARY KEY(notice_id,product_code));
    CREATE TABLE IF NOT EXISTS review_tasks(
      notice_id TEXT PRIMARY KEY,priority TEXT,task_type TEXT,task_reason TEXT,status TEXT DEFAULT '待复核',assigned_to TEXT,reviewed_at TEXT,note TEXT);
    CREATE TABLE IF NOT EXISTS parameter_events(
      event_id TEXT PRIMARY KEY,notice_id TEXT,product_code TEXT,contract_codes TEXT,parameter_code TEXT,parameter_name TEXT,
      announcement_date TEXT,effective_date_candidate TEXT,restore_date_candidate TEXT,value_candidates TEXT,
      old_value TEXT,new_value TEXT,unit TEXT,direction TEXT,reason_code TEXT,reason_name TEXT,
      extraction_confidence REAL,event_status TEXT,evidence TEXT,
      monthly_match TEXT DEFAULT '未验证',daily_match TEXT DEFAULT '未验证',announcement_match TEXT DEFAULT '已匹配',
      expansion_trigger TEXT DEFAULT '待确认',validation_conclusion TEXT,manual_review_status TEXT DEFAULT '待复核');
    CREATE INDEX IF NOT EXISTS ix_events_product_param_date ON parameter_events(product_code,parameter_code,effective_date_candidate);
    CREATE INDEX IF NOT EXISTS ix_events_notice ON parameter_events(notice_id);
    CREATE INDEX IF NOT EXISTS ix_review_priority ON review_tasks(priority,status);
    CREATE INDEX IF NOT EXISTS ix_override_notice_dim ON manual_overrides(notice_id,dimension);
    DROP VIEW IF EXISTS v_final_products;
    CREATE VIEW v_final_products AS
      SELECT p.* FROM notice_products p WHERE NOT EXISTS(
       SELECT 1 FROM manual_overrides o WHERE o.notice_id=p.notice_id AND o.dimension='品种' AND o.action='remove' AND o.original_code=p.product_code)
      UNION ALL SELECT o.notice_id,o.replacement_code,coalesce(o.replacement_value,o.replacement_code),'','','人工修订',1.0,'人工确认'
       FROM manual_overrides o WHERE o.dimension='品种' AND o.action='add';
    DROP VIEW IF EXISTS v_final_parameters;
    CREATE VIEW v_final_parameters AS
      SELECT p.* FROM notice_parameters p WHERE NOT EXISTS(
       SELECT 1 FROM manual_overrides o WHERE o.notice_id=p.notice_id AND o.dimension='参数' AND o.action='remove' AND o.original_code=p.parameter_code)
      UNION ALL SELECT o.notice_id,o.replacement_code,coalesce(o.replacement_value,o.replacement_code),'人工修订',o.evidence,coalesce(o.new_value,''),1.0,'人工确认'
       FROM manual_overrides o WHERE o.dimension='参数' AND o.action='add';
    DROP VIEW IF EXISTS v_event_research_ready;
    CREATE VIEW v_event_research_ready AS SELECT e.*,n.title,n.source_url,n.local_path
      FROM parameter_events e JOIN notices n USING(notice_id)
      WHERE e.manual_review_status='已确认' AND e.effective_date_candidate IS NOT NULL;
    ''')
    c.execute('delete from product_tag_assessment'); c.execute('delete from review_tasks'); c.execute('delete from parameter_events')
    notices={r[0]:r for r in c.execute('select notice_id,publish_date,parameter_related,primary_reason_code,primary_reason,reason_confidence,review_status,title from notices')}
    products={}
    for r in c.execute('select notice_id,product_code,contract_codes,evidence from notice_products'):
        products.setdefault(r[0],[]).append(r[1:])
        usage='参数事件品种' if notices[r[0]][2] else '上下文相关品种'
        risk='需核对事件关联' if not notices[r[0]][2] else ('重点五品种' if r[1] in TARGET else '')
        c.execute('insert into product_tag_assessment values(?,?,?,?,?,?)',(r[0],r[1],usage,risk,'品种出现不等于发生参数调整；需与参数标签共同使用','自动评估'))
    params={}
    for r in c.execute('select notice_id,parameter_code,parameter_name,value_candidates,evidence,confidence from notice_parameters'):
        params.setdefault(r[0],[]).append(r[1:])
    dates={}
    for nid,dtype,dval,ev,conf in c.execute('select notice_id,date_type,date_value,evidence,confidence from notice_dates order by date_value'):
        dates.setdefault(nid,[]).append((dtype,dval,ev,conf))
    for nid,n in notices.items():
        pub=n[1]; ps=products.get(nid,[]); ms=params.get(nid,[]); target=any(p[0] in TARGET for p in ps); core=any(m[0] in CORE for m in ms)
        if n[2] and target and core: pri,typ,why='P0','五品种核心参数事件','五品种涉及涨跌停板、保证金、限额或交易时间，优先复核'
        elif n[2] and n[3] in ('02','03'): pri,typ,why='P0','临时风控/扩板事件','直接关系临时风险控制或连续涨跌停扩板机制'
        elif n[2] and (n[3]=='08' or n[5]<.75): pri,typ,why='P1','低置信度参数事件','原因未明确或置信度较低'
        elif n[2]: pri,typ,why='P2','一般参数事件','参数相关公告，按研究进度复核'
        else: pri,typ,why='P3','非参数公告','仅作公告档案或品种上下文，不进入参数事件研究'
        c.execute('insert into review_tasks(notice_id,priority,task_type,task_reason) values(?,?,?,?)',(nid,pri,typ,why))
        if not n[2] or not ms: continue
        ds=[]
        try: pubd=date.fromisoformat(pub)
        except: pubd=None
        for dtype,dval,ev,conf in dates.get(nid,[]):
            if dval==pub: continue
            try: dd=date.fromisoformat(dval)
            except: continue
            if pubd and pubd<=dd and (dd-pubd).days<=120: ds.append((dd,dval,ev,conf))
        ds.sort(); eff=ds[0][1] if ds else None
        prows=ps or [('UNSPECIFIED','','')]
        for pc,contracts,pev in prows:
          for mc,mn,vals,mev,mconf in ms:
            eid=h('|'.join([nid,pc,mc])); conf=min(n[5] or .5,mconf or .5)
            status='候选事件-待人工确认'; trigger='规则触发待确认' if n[3]=='03' else '非扩板或待确认'
            c.execute('''insert into parameter_events(event_id,notice_id,product_code,contract_codes,parameter_code,parameter_name,announcement_date,effective_date_candidate,value_candidates,reason_code,reason_name,extraction_confidence,event_status,evidence,expansion_trigger) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(eid,nid,pc,contracts,mc,mn,pub,eff,vals,n[3],n[4],conf,status,mev,trigger))
    c.commit()
    export(c,out/'参数事件候选表.csv','select * from parameter_events order by announcement_date,notice_id,product_code,parameter_code')
    export(c,out/'分级人工复核队列.csv','''select r.priority,r.task_type,r.task_reason,r.status,n.notice_id,n.title,n.publish_date,n.primary_reason_code,n.primary_reason,n.reason_confidence,n.parameter_related,q.product_codes,q.parameter_names,n.source_url,n.local_path from review_tasks r join notices n using(notice_id) left join v_notice_query q using(notice_id) order by r.priority,n.publish_date,n.notice_id''')
    export(c,out/'五品种P0复核队列.csv',"""select r.priority,n.notice_id,n.title,n.publish_date,q.product_codes,q.parameter_names,n.primary_reason_code,n.primary_reason,n.reason_confidence,n.source_url,n.local_path from review_tasks r join notices n using(notice_id) left join v_notice_query q using(notice_id) where r.priority='P0' and exists(select 1 from notice_products p where p.notice_id=n.notice_id and p.product_code in ('AU','AG','CU','RB','FU')) order by n.publish_date""")
    counts=dict(c.execute('select priority,count(*) from review_tasks group by priority'))
    audit={'generated_at':datetime.now().astimezone().isoformat(timespec='seconds'),'integrity':c.execute('pragma integrity_check').fetchone()[0],'review_priority':counts,'event_candidates':c.execute('select count(*) from parameter_events').fetchone()[0],'five_product_p0':c.execute("select count(*) from review_tasks r where priority='P0' and exists(select 1 from notice_products p where p.notice_id=r.notice_id and p.product_code in ('AU','AG','CU','RB','FU'))").fetchone()[0],'manual_overrides':c.execute('select count(*) from manual_overrides').fetchone()[0],'research_ready_events':c.execute('select count(*) from v_event_research_ready').fetchone()[0],'note':'参数事件均为自动候选；生效日期、前后值和扩板触发关系必须人工或跨表确认。'}
    (out/'事件层质量审计.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8'); c.close(); print(json.dumps(audit,ensure_ascii=True,indent=2))
if __name__=='__main__': main()
