# Feishu Base → ASG Lead Command Center 映射方案

Date: 2026-06-21
Status: **Resolved 2026-06-21** — see 「Resolution」 below. 本文档下半部分是原始提案(历史背景),实际落地的决定与之不同。

## Resolution(2026-06-21 实际落地)

经操作员确认,**放弃复用现有中文运营表**(避免英文 LCC 字段污染中文表 + AI/手工数据混在一起),改为在同一个 Base 内新建 **8 张专用 `LeadCC·` 前缀表**:

| 逻辑表 | 实际表名 | table_id 来源 | 写入路径 |
|---|---|---|---|
| lead | `LeadCC·Lead Pool` | `.env` FEISHU_LEAD_TABLE_ID | `run_lead_pipeline.py --write-feishu` |
| score | `LeadCC·Lead Scoring` | FEISHU_SCORE_TABLE_ID | 同上 |
| outreach | `LeadCC·Outreach Task` | FEISHU_OUTREACH_TABLE_ID | 同上 |
| conversation | `LeadCC·Conversation Log` | FEISHU_CONVERSATION_TABLE_ID | (由 classify_reply 输出,n8n 写入) |
| prompt | `LeadCC·Prompt Version` | FEISHU_PROMPT_TABLE_ID | (手工维护版本) |
| **content** | **`LeadCC·Content Opportunity`** | FEISHU_CONTENT_TABLE_ID | **`generate_content_opportunities.py --write-feishu`**(2026-06-21 新增) |
| **report** | **`LeadCC·Daily Report`** | FEISHU_REPORT_TABLE_ID | **`generate_daily_report.py --feishu`**(按 Report Date upsert,2026-06-21 新增) |
| contact | (暂不新建) | — | 联系人信息内嵌在客户库,V1 跳过 |

- **Content / Daily Report** 经多 agent 团队发现原候选(`11 关键词迭代表` / `20 管理仪表盘数据表`)是线上在用运营表,写入会混入手工数据;操作员选择新建专用表。两张表字段已按 docs/02 §6.6/§6.7 创建并验证(字段类型正确:Number/DateTime/SingleSelect/MultiSelect/User)。
- content 写入:`build_content_fields` 把机会字典映射为 PascalCase 字段(Content ID=`CTNT-YYYYMMDD-NNNN`,Status 默认 `Idea`),`write_opportunities_to_feishu` 逐条 create(单条失败不中断)。
- report 写入:`build_report_fields` 把指标映射为 Daily Report 字段(Report Date=UTC 午夜 ms 时间戳),`write_daily_report_to_feishu` 按 Report Date **upsert**(同日重跑更新而非堆叠)。
- 两路径均已通过本地单测(FakeClient)+ 实时端到端烟测(写/读/upsert/删,表留空)。

下方原始提案保留作历史背景。

---

真实 table_id 仅记录在 gitignored 的 `config/feishu_tables.local.json`,本文档不含 table_id。

## 背景

操作员共享的飞书 Base 是一个已有 **57 张表**的真实运营库。经字段级盘点,8 张 LCC 逻辑表中:
- **4 张有强匹配的现有表**(建议复用,不新建)
- **4 张是真实缺口**(需新建或进一步决策)

⚠️ 重要约束:现有表字段为**中文**,LCC 脚本写入的是**英文字段名**(Lead ID / ASG Fit Score …)。直接把复用表接入写入路径会用英文列污染中文表。因此在操作员确认 + 字段映射层建好之前,**复用表的 table_id 不接入 `--write-feishu` 写入路径**(.env 的 FEISHU_*_TABLE_ID 保持空,确保安全失败)。

---

## A. 建议复用(4 张,强匹配)

### LCC Lead Pool ← `01 客户数据库`(22 字段,命中约 14/20)
| LCC 字段 | 现有字段 |
|---|---|
| Lead ID | 客户编号 |
| Company / Store Name | 客户名称 |
| Website URL | 官网链接 |
| Platform | 平台 |
| Country / Region | 国家/地区 |
| Category | 品类 |
| Estimated Order Volume | 预计日单量 |
| Current Supplier Guess | 现供应商/平台 |
| Pain Signal | 核心痛点 |
| ASG Fit Score | AI评分 |
| Priority | 客户等级 |
| Status | 当前状态 |
| Owner | 负责人 |
| Notes | 备注 |
| Last Updated | 最后跟进时间 |
缺口(需补字段或忽略):Source Channel / Source URL / Evidence Text / Estimated Stage。
额外可用:邮箱 / WhatsApp / 社媒链接 / 主要市场 / 是否稳定SKU / 下一步动作。

### LCC Outreach Task ← `02 客户经理派单与跟进`(16 字段,命中约 7/14)
| LCC 字段 | 现有字段 |
|---|---|
| Owner | 客户经理 |
| Channel | 渠道 |
| Message Type | 话术版本 |
| Send Status | 触达状态 |
| Result | 回复状态 |
| Next Follow-up Date | 截止时间 / 下一步动作 |
| Notes | 备注 |
缺口:Task ID / AI Draft / Human Edited Version / **Approval Status**(人工审核草稿流程在 02 里没有)。
相关渠道表:`03 邮件序列表`、`04 WhatsApp跟进表`(分渠道触达)。

### LCC Content Opportunity ← `11 关键词迭代表`(14 字段,命中约 7/11)
| LCC 字段 | 现有字段 |
|---|---|
| Topic | 关键词 |
| Pain Point | 对应痛点 |
| Search Intent | 意图类型 |
| Recommended Format | 推荐内容形式 |
| source | 客户原话 / 来源平台 |
| Status | 状态 |
| Owner | 负责人 |
备选:`28 SEO-GEO需求话题验证库`(79 字段,更重,含 ASG解决方案 + 多维评分,适合做验证型内容机会)。

### LCC Daily Report ← `20 管理仪表盘数据表`(18 字段,命中约 8/15)
| LCC 字段 | 现有字段 |
|---|---|
| Report Date | 日期 |
| New Leads | 新增客户 |
| Messages Sent | 有效触达 |
| Replies | 回复数 |
| Quote Requests | 报价机会 |
| Won Deals | 试单/成交 |
| Problems | 主要问题 |
| Tomorrow Actions | 明日重点 |
相关:`每日营销仪表盘`(发送/回复/意向按人拆分)、`16 销售早会记录表`、`22 每日反馈与迭代表`。

---

## B. 真实缺口(4 张,建议新建 — 待确认)

1. **Lead Scoring(评分明细)**:现有 `01 客户数据库` 只有 `AI评分` 单一数字,**没有** 6 维度拆分 / Reasoning / Recommended Offer / Risk / Review Needed。建议**新建**独立的 Lead Scoring 表(关联 客户数据库),用于可审计的评分依据。
2. **Conversation Log(统一沟通记录)**:回复数据分散在 `03 邮件序列表`、`04 WhatsApp跟进表`、`邮件回复审核`(后者有 AI意向分析/AI建议回复/审核状态,最接近)。**没有**统一的 Intent / Urgency / Next Action 日志。建议**新建**统一 Conversation Log(或扩展 `邮件回复审核`)。
3. **Contact Table(联系人)**:联系人信息已**内嵌**在 `01 客户数据库`(邮箱/WhatsApp/社媒链接);红人联系人在 `09 红人与合作库`。V1 可**暂不新建**,直接用 客户数据库 的联系字段;如需独立联系人维度再建。
4. **Prompt Version(Prompt 版本)**:`47 平台改写规范与Skills`、`50 外链平台类型改写规则库` 是改写规则,不是 Prompt 版本注册表(无 Version / Use Case / Output Schema / Test Result)。建议**新建** Prompt Version 表。

---

## C. 下一步(需操作员确认)

1. 确认 A 部分 4 张复用表的字段映射(尤其是缺口的 Source Channel / Evidence Text 等是否需要补字段)。
2. 确认 B 部分 4 张缺口表:全部新建?还是 Contact 暂缓?
3. 字段映射层:在 LCC 脚本里加一个 alias 层(英文 LCC 字段 ↔ 中文现有字段),这样 `--write-feishu` 才能安全写入复用表而不污染。
4. 新建表用 docs/02 的 schema,中文名建议加前缀(如 `LeadCC·`)与现有 57 表区分。
