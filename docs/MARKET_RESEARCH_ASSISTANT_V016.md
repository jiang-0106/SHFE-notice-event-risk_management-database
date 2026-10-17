# SHFE 公告参数与交易强度研究助手 v0.16

## 功能范围

v0.16在v0.15只读数据库上增加三个派生功能：

1. 已核验公告参数的起始日、结束日、开放区间及手工复核覆盖层；
2. 品种日度交易强度、激烈交易日和文献指标分项；
3. 输入品种后生成历史交易状态、流动性、风险、公告参数与数据新鲜度摘要，并可选择调用OpenAI进行受约束解释。

本工具不预测涨跌方向，不输出开仓、平仓、止盈或止损指令，不将公告与市场异常的同步出现直接解释为因果。

## 启动

```powershell
python scripts/run_market_research_assistant.py
```

默认打开 `http://127.0.0.1:8765/`。如果数据库位于其他目录：

```powershell
python scripts/run_market_research_assistant.py --db "完整数据库路径"
```

## 公告参数区间

表 `notice_parameter_policy_interval` 保存系统推导区间：

- `start_date`：已核验公告的生效日；
- `end_date`：同品种同参数下一次不同已核验公告值的前一日；
- `interval_status=open_ended`：尚无更晚的不同已核验公告值；
- `derivation_limit_cn`：提醒该区间是品种层公告基准，不替代合约临近交割等从高适用值。

网页中的“复核”按钮把手工起止日写入 `policy_interval_manual_override`。视图 `v_policy_interval_effective` 优先显示手工值，同时保留修改原因、复核人和更新时间。重新构建v0.16时，稳定区间ID对应的手工覆盖会被继承。

## 激烈交易日指标

系统对每个品种仅使用当日前的最多252个历史观测计算分位数，避免使用未来数据。综合分包括：

| 分项 | 权重 | 含义 |
|---|---:|---|
| 绝对对数收益历史分位 | 25% | 收益冲击 |
| Parkinson区间波动历史分位 | 20% | 日内高低价波动 |
| 成交量历史分位 | 20% | 交易活跃度 |
| 成交额历史分位 | 10% | 资金活动代理 |
| 持仓变化绝对值历史分位 | 10% | 仓位调整强度 |
| Amihud非流动性历史分位 | 10% | 单位成交额价格冲击 |
| 成交量/持仓量历史分位 | 5% | 换手强度 |

分级规则：

- `extreme`：综合分不低于97.5，且至少4个分项达到80分位；
- `intense`：综合分不低于90，且至少3个分项达到80分位；
- `active`：综合分不低于80，且至少2个分项达到80分位；
- `normal`：其余具有足够历史数据的交易日；
- `insufficient_history`：历史观测不足60个交易日。

综合分只用于筛选“值得进一步研究的异常日”，不代表看多、看空或交易收益概率。

## 数据新鲜度保护

`product_research_snapshot`使用构建日与数据库最后日期的自然日差：

- 0—3日：`fresh`；
- 4—10日：`lagged`；
- 超过10日：`stale`。

当状态为 `stale` 时，网页和AI提示都必须说明不能判断当下是否适合交易。当前v0.16的最后完整市场日为2026-09-09，相对构建日2026-10-02已经滞后23个自然日。

## AI解释

量化分析和网页查询不需要API密钥。启用AI解释前，在当前PowerShell设置：

```powershell
$env:OPENAI_API_KEY = '你的API密钥'
$env:OPENAI_MODEL = 'gpt-6-astra'
python scripts/run_market_research_assistant.py
```

程序使用Responses API结构化输出。发送给模型的是当前品种的量化指标、公告区间、参数变化和数据边界，不发送整个SQLite文件。输出模式强制包含 `trade_decision=not_assessed`，因此AI只解释研究关注度，不生成交易指令。

不要把API密钥写入代码、Git仓库、CSV或截图。模型名称可以通过环境变量替换，以适配后续官方模型更新。

## 主要数据表

- `notice_parameter_policy_interval`
- `policy_interval_manual_override`
- `v_policy_interval_effective`
- `product_trading_intensity_daily`
- `product_research_snapshot`
- `indicator_literature_registry`
- `research_assistant_build_metadata`

## 重建数据库

```powershell
python scripts/build_market_research_assistant_v016.py
```

原v0.15数据库不会被修改。构建程序先复制v0.15，再增加v0.16派生表，并执行SQLite完整性检查。

## 文献基础与适用限制

1. Parkinson (1980), DOI `10.1086/296071`：高低价区间波动估计。
2. Bessembinder & Seguin (1993), DOI `10.2307/2331149`：期货波动、成交量与市场深度。
3. Amihud (2002), DOI `10.1016/S1386-4181(01)00024-6`：价格冲击非流动性指标；本项目只在同品种内部比较。
4. Andersen et al. (2003), DOI `10.1111/1468-0262.00418`：实现波动率框架；本项目只有日频代理量，不称为严格的高频实现波动率。
