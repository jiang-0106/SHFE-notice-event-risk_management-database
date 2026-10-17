from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


DEFAULT_INPUT = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.20_20261017"
    r"\SHFE公告参数市场同步数据库_公告参数变更点对应_v0.20_final.sqlite3"
)
DEFAULT_OUTPUT = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.21_20261017"
    r"\SHFE公告参数市场同步数据库_证据质量增强_v0.21_final.sqlite3"
)


EVENTS = [
    {
        "event_id": "AO_CTX_001", "product_code": "AO", "event_date": "20251101", "event_end_date": "20251130",
        "category_code": "supply_surplus", "category_en": "Supply surplus and high operating capacity", "category_cn": "供应宽松与高运行产能",
        "event_name_en": "High alumina output and inventories kept the market under supply pressure in November 2025",
        "event_name_cn": "2025年11月氧化铝高产量和库存使市场继续承受供应宽松压力",
        "description_cn": "行业月报回顾显示，11月氧化铝运行产能维持高位，供应过剩加剧，现货价格继续走弱。",
        "transmission_en": "High output and inventories weakened spot prices and market expectations.",
        "transmission_cn": "高产量与库存压力通过现货价格和供应预期影响期货市场。",
        "source_title": "新湖有色（铝）12月报：铝价高位波动，氧化铝重心下移", "source_org": "新湖期货（世铝网转载）",
        "source_url": "https://market.cnal.com/analysis/2025/12-04/1764812784656345.shtml", "source_date": "20251204",
        "evidence_grade": "B", "evidence_status": "retrospective_industry_context", "independent_source_2": "",
        "limit_cn": "来源为次月行业回顾，只能作为11月市场背景，不能证明其导致交易所调整。",
    },
    {
        "event_id": "AO_CTX_002", "product_code": "AO", "event_date": "20260101", "event_end_date": "20260131",
        "category_code": "supply_inventory_weather", "category_en": "Supply, inventory, and winter logistics", "category_cn": "供应、库存与冬季物流扰动",
        "event_name_en": "Alumina prices weakened amid ample supply and inventories, while cold weather temporarily disrupted logistics",
        "event_name_cn": "供应和库存宽松压低氧化铝价格，极寒天气阶段性扰动物流",
        "description_cn": "行业月评显示，1月现货均价环比下降，供应未出现长期大规模减产，库存压力较大；月末极寒天气和部分设备检修造成阶段性供应扰动。",
        "transmission_en": "Supply pressure weakened prices, while weather and maintenance created short-lived delivery constraints.",
        "transmission_cn": "供应压力压低价格，天气和检修又通过发运与阶段性产量形成短期扰动。",
        "source_title": "月评：供应端波动增加且春节临近 1月氧化铝价格先跌后趋稳", "source_org": "我的钢铁网",
        "source_url": "https://youse.m.mysteel.com/a/26020417/388CBE712484C32C_abc.html", "source_date": "20260130",
        "evidence_grade": "B", "evidence_status": "industry_monthly_context", "independent_source_2": "",
        "limit_cn": "月度背景同时包含宽松与扰动因素，方向并不单一；与具体公告仅为候选时间对应。",
    },
    {
        "event_id": "AO_ADMIN_003", "product_code": "AO", "event_date": "20260427", "event_end_date": "20260505",
        "category_code": "holiday_calendar", "category_en": "Official Labour Day holiday arrangement", "category_cn": "劳动节休市安排",
        "event_name_en": "Official 2026 Labour Day holiday schedule", "event_name_cn": "2026年劳动节官方放假调休安排",
        "description_cn": "国务院办公厅公布2026年劳动节5月1日至5日放假调休，交易所据此进行节日期间风险参数安排。",
        "transmission_en": "A multi-day market closure creates an administrative need for temporary holiday risk controls.",
        "transmission_cn": "连续休市使交易所需要进行节假日前后的临时风险参数安排。",
        "source_title": "国务院办公厅关于2026年部分节假日安排的通知", "source_org": "国务院办公厅",
        "source_url": "https://www.beijing.gov.cn/zhengce/zhengcefagui/202511/t20251104_4258873.html", "source_date": "20251104",
        "evidence_grade": "A", "evidence_status": "official_administrative_trigger", "independent_source_2": "",
        "limit_cn": "这是节假日行政触发因素，不应与供需冲击或价格异常事件混为一类。",
    },
    {
        "event_id": "BU_CTX_001", "product_code": "BU", "event_date": "20251203", "event_end_date": "20251231",
        "category_code": "seasonal_demand_supply", "category_en": "Seasonal weak demand and easing crude-cost support", "category_cn": "季节性需求偏弱与原油成本支撑下降",
        "event_name_en": "Bitumen stayed weak as winter demand slowed and crude-cost support eased",
        "event_name_cn": "冬季需求放缓且原油成本支撑减弱，沥青市场维持偏弱状态",
        "description_cn": "行业报道指出冬季需求偏弱、国际原油重心下移，沥青供需双弱并等待冬储启动。",
        "transmission_en": "Weaker road demand and lower crude-cost support affected refinery pricing, inventories, and futures expectations.",
        "transmission_cn": "道路需求走弱和原油成本支撑下降通过炼厂定价、库存和预期影响期货市场。",
        "source_title": "供需双弱沥青低位震荡 后市或需等待冬储启动", "source_org": "中国金融信息网（期货日报稿）",
        "source_url": "https://www.cnfin.com/dz-lb/detail/20251203/4344189_1.html", "source_date": "20251203",
        "evidence_grade": "B", "evidence_status": "industry_context_before_notice", "independent_source_2": "https://www.oilchem.net/25-1212-09-0de061c97fdc3537.html",
        "limit_cn": "属于公告前市场背景候选，不足以单独解释交易所调整决定。",
    },
    {
        "event_id": "BU_EVT_002", "product_code": "BU", "event_date": "20260228", "event_end_date": "20260309",
        "category_code": "middle_east_oil_supply_shock", "category_en": "Middle East conflict and oil-supply shock", "category_cn": "中东冲突与原油供应冲击",
        "event_name_en": "Middle East military conflict disrupted Hormuz traffic and sharply lifted crude oil prices",
        "event_name_cn": "中东军事冲突扰动霍尔木兹海峡运输并推动原油价格大幅上涨",
        "description_cn": "美国能源信息署记录，2月28日中东军事行动开始后，霍尔木兹海峡大部分航运受阻，布伦特现货均价由2月27日约71美元升至3月9日约104美元。",
        "transmission_en": "The crude-oil supply shock directly raised bitumen feedstock costs and market volatility.",
        "transmission_cn": "原油供应冲击通过沥青原料成本和风险溢价直接放大市场波动。",
        "source_title": "Short-Term Energy Outlook: Global Oil Markets, March 2026", "source_org": "U.S. Energy Information Administration",
        "source_url": "https://www.eia.gov/outlooks/steo/archives/Mar26.pdf", "source_date": "20260309",
        "evidence_grade": "A", "evidence_status": "authoritative_sector_event", "independent_source_2": "https://www.iea.org/news/iea-member-countries-to-carry-out-largest-ever-oil-stock-release-amid-market-disruptions-from-middle-east-conflict",
        "limit_cn": "事件与沥青成本高度相关且时间接近，但仍不能仅凭对应关系认定其导致交易所参数调整。",
    },
]


LINKS = [
    ("t20251104_829423", "AO_CTX_001", "contextual_candidate", "公告日前后同月背景；来源为次月回顾"),
    ("t20260123_830226", "AO_CTX_002", "contextual_candidate", "公告位于月度事件区间内"),
    ("t20260128_830274", "AO_CTX_002", "contextual_candidate", "公告位于月度事件区间内"),
    ("t20260205_830383", "AO_CTX_002", "contextual_candidate", "距离1月月末背景较近，不能视为直接触发"),
    ("t20260427_831528", "AO_ADMIN_003", "verified_administrative_link", "公告明确为劳动节期间安排"),
    ("t20251205_829720", "BU_CTX_001", "contextual_candidate", "公告前两日行业背景"),
    ("t20260309_830615", "BU_EVT_002", "strong_temporal_sector_link", "原油冲击与公告日重合且传导渠道直接"),
    ("t20260310_830641", "BU_EVT_002", "strong_temporal_sector_link", "原油冲击持续且传导渠道直接"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-db", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-db", type=Path, default=DEFAULT_OUTPUT)
    cfg = parser.parse_args()
    cfg.output_db.parent.mkdir(parents=True, exist_ok=True)
    building = cfg.output_db.with_suffix(cfg.output_db.suffix + ".building")
    if building.exists():
        building.unlink()
    shutil.copy2(cfg.input_db, building)
    imported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(building)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS ao_bu_real_event_evidence;
            DROP TABLE IF EXISTS ao_bu_policy_event_evidence_link;
            CREATE TABLE ao_bu_real_event_evidence (
              event_id TEXT PRIMARY KEY, product_code TEXT NOT NULL, event_date TEXT NOT NULL, event_end_date TEXT,
              category_code TEXT NOT NULL, category_en TEXT NOT NULL, category_cn TEXT NOT NULL,
              event_name_en TEXT NOT NULL, event_name_cn TEXT NOT NULL, description_cn TEXT NOT NULL,
              transmission_en TEXT NOT NULL, transmission_cn TEXT NOT NULL, source_title TEXT NOT NULL,
              source_org TEXT NOT NULL, source_url TEXT NOT NULL, source_date TEXT NOT NULL,
              evidence_grade TEXT NOT NULL, evidence_status TEXT NOT NULL, independent_source_2 TEXT,
              interpretation_limit_cn TEXT NOT NULL, source_row_json TEXT NOT NULL, imported_at TEXT NOT NULL
            );
            CREATE TABLE ao_bu_policy_event_evidence_link (
              notice_id TEXT NOT NULL, event_id TEXT NOT NULL, link_status TEXT NOT NULL, link_note_cn TEXT NOT NULL,
              reviewed_by TEXT NOT NULL, reviewed_at TEXT NOT NULL,
              PRIMARY KEY(notice_id,event_id), FOREIGN KEY(event_id) REFERENCES ao_bu_real_event_evidence(event_id)
            );
            """
        )
        keys = list(EVENTS[0])
        conn.executemany(
            "INSERT INTO ao_bu_real_event_evidence VALUES (" + ",".join("?" for _ in range(22)) + ")",
            [tuple(item[key] or None for key in keys) + (json.dumps(item, ensure_ascii=False, sort_keys=True), imported_at) for item in EVENTS],
        )
        conn.executemany(
            "INSERT INTO ao_bu_policy_event_evidence_link VALUES (?,?,?,?,?,?)",
            [(notice, event, status, note, "Codex evidence-screening; mentor review pending", imported_at) for notice, event, status, note in LINKS],
        )
        conn.commit()
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
    finally:
        conn.close()
    os.replace(building, cfg.output_db)
    print(json.dumps({"output": str(cfg.output_db), "events": len(EVENTS), "links": len(LINKS)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
