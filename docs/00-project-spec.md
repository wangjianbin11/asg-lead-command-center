# ASG Lead Command Center 开发文档 V1.0

## 0. 项目名称

**ASG Lead Command Center**

中文名：

**ASG 自动化获客与销售指挥中心**

项目仓库建议命名：

```text
asg-lead-command-center
```

---

## 1. 项目背景

ASG Dropshipping 当前已经具备中国采购、仓储、打包、质检、物流、Shopify 订单履约等供应链服务能力，但在获客端存在几个核心问题：

1. 线索来源分散，没有统一沉淀。
2. 客户是否值得跟进，主要靠人工判断，效率低。
3. 业务员每天不知道优先联系谁。
4. AI 生成内容、开发信、私信话术缺少统一标准。
5. Reddit、Quora、LinkedIn、Facebook、独立站等渠道没有形成闭环。
6. 获客动作和成交结果之间没有数据反馈。
7. 内容生产、客户痛点、销售话术、业务复盘之间没有互相反哺。

因此需要搭建一个内部系统，把 AI token 转化成可复用的业务资产：

**线索、客户评分、触达话术、业务员任务、销售复盘、内容机会、SOP、数据资产。**

---

## 2. 项目目标

本项目第一阶段不做复杂 SaaS，也不做完全自动群发。

V1 目标是搭建一个可运行的内部获客系统：

```text
发现客户 → 清洗线索 → 判断价值 → 生成话术 → 人工审核 → 人工触达 → 跟进记录 → 成交复盘 → 反哺内容
```

核心原则：

1. AI 负责找线索、判断、生成、复盘。
2. 业务员负责审核、触达、跟进、成交。
3. 飞书多维表格作为数据总控台。
4. n8n 作为自动化调度中心。
5. Claude Code 作为项目架构师。
6. Codex 作为开发执行员。
7. GitHub 仓库作为项目长期资产沉淀地。

---

## 3. 第一阶段边界

### 3.1 V1 要做

V1 只做以下内容：

1. 飞书多维表结构设计。
2. 线索录入与去重。
3. 客户评分模型。
4. AI 生成个性化触达话术。
5. 业务员任务分配。
6. 每日获客日报。
7. 客户回复分类。
8. 内容机会自动提取。
9. 基础 n8n 工作流。
10. GitHub 项目结构、Prompt、SOP、脚本沉淀。

### 3.2 V1 不做

V1 暂时不做：

1. 不做全自动群发邮件。
2. 不做 Reddit/Quora 自动发帖。
3. 不做 Facebook/LinkedIn 自动私信轰炸。
4. 不做复杂后台。
5. 不做复杂权限系统。
6. 不做大规模爬虫。
7. 不采集需要登录、绕过限制或违反平台规则的数据。
8. 不把 AI 生成内容直接发布到公网。

V1 的核心是：

> **AI 生成建议，人工确认执行。**

---

## 4. 总体架构

### 4.1 系统架构

```text
公开信息源 / 手动导入 / 业务员发现
        ↓
n8n 采集与清洗工作流
        ↓
AI 客户判断与评分
        ↓
飞书多维表格 Lead Command Center
        ↓
AI 生成触达话术与跟进建议
        ↓
业务员人工审核与执行
        ↓
跟进结果回填
        ↓
日报 / 周报 / 内容机会 / SOP 优化
```

### 4.2 工具分工

| 模块    | 工具                 | 作用                              |
| ----- | ------------------ | ------------------------------- |
| 项目资产  | GitHub             | 存放代码、文档、Prompt、n8n workflow、SOP |
| 数据总控  | 飞书多维表格             | 存放线索、联系人、任务、复盘、内容机会             |
| 自动化调度 | n8n                | 定时执行采集、评分、生成、日报                 |
| 总架构开发 | Claude Code        | 搭项目结构、写文档、设计流程、重构系统             |
| 并行开发  | Codex              | 写脚本、修 Bug、做 API、做数据清洗           |
| AI 判断 | GPT / Claude API   | 客户评分、话术生成、回复分类、日报生成             |
| 人工执行  | 业务员                | 审核、联系、跟进、报价、成交                  |
| 知识沉淀  | 飞书 Wiki / Obsidian | 沉淀 ASG 案例、话术、FAQ、SOP            |

---

## 5. GitHub 项目结构

创建仓库：

```text
asg-lead-command-center
```

目录结构：

```text
asg-lead-command-center/
  README.md

  docs/
    00-project-spec.md
    01-system-architecture.md
    02-feishu-base-schema.md
    03-lead-scoring-rules.md
    04-outreach-sop.md
    05-sales-followup-sop.md
    06-content-engine.md
    07-n8n-workflows.md
    08-security-and-compliance.md
    09-daily-ops-manual.md

  prompts/
    lead-scoring/
      lead-scoring-v1.md
      lead-quality-review-v1.md

    outreach/
      cold-email-v1.md
      linkedin-message-v1.md
      whatsapp-message-v1.md
      website-contact-form-v1.md

    sales/
      reply-classifier-v1.md
      objection-handling-v1.md
      followup-suggestion-v1.md

    content/
      content-opportunity-extractor-v1.md
      reddit-answer-draft-v1.md
      quora-answer-draft-v1.md
      linkedin-post-v1.md
      seo-article-brief-v1.md

    reports/
      daily-lead-report-v1.md
      weekly-sales-review-v1.md

  n8n-workflows/
    01-manual-lead-import.json
    02-lead-cleaning-dedup.json
    03-lead-scoring.json
    04-outreach-draft-generation.json
    05-reply-classification.json
    06-daily-command-report.json
    07-content-opportunity-generation.json

  scripts/
    clean_leads.py
    dedupe_leads.py
    score_leads.py
    enrich_store.py
    generate_outreach.py
    generate_daily_report.py
    feishu_client.py
    config.py

  data-samples/
    sample_leads.csv
    sample_contacts.csv
    sample_daily_report.md

  dashboard/
    README.md

  tests/
    test_dedupe_leads.py
    test_score_leads.py
    test_prompt_output_schema.py

  .env.example
  CLAUDE.md
  CODEX_TASKS.md
```

---

## 6. 飞书多维表格设计

飞书多维表格名称：

```text
ASG Lead Command Center
```

### 6.1 表 1：Lead Pool 线索池

用途：

存放所有潜在客户线索。

字段：

| 字段名                    | 类型  | 说明                                                                                            |
| ---------------------- | --- | --------------------------------------------------------------------------------------------- |
| Lead ID                | 文本  | 系统生成唯一 ID                                                                                     |
| Company / Store Name   | 文本  | 店铺或公司名                                                                                        |
| Website URL            | 链接  | 独立站网址                                                                                         |
| Platform               | 单选  | Shopify / WooCommerce / TikTok Shop / Amazon / Etsy / Unknown                                 |
| Country / Region       | 单选  | 美国、英国、加拿大、澳洲、欧洲、土耳其等                                                                          |
| Category               | 文本  | 产品类目                                                                                          |
| Source Channel         | 单选  | Google / Reddit / Quora / LinkedIn / Facebook / YouTube / Manual / Other                      |
| Source URL             | 链接  | 发现该线索的来源页面                                                                                    |
| Pain Signal            | 多选  | shipping delay / supplier issue / custom packaging / sourcing / QC / MOQ / fulfillment        |
| Evidence Text          | 长文本 | 证明该客户存在需求的原文片段                                                                                |
| Estimated Stage        | 单选  | New / Testing / Growing / Scaling / Unknown                                                   |
| Estimated Order Volume | 单选  | Unknown / 1-10 per day / 10-30 per day / 30-100 per day / 100+ per day                        |
| Current Supplier Guess | 文本  | 可能当前供应商，如 CJ、AliExpress、private agent                                                         |
| ASG Fit Score          | 数字  | 0-100                                                                                         |
| Priority               | 单选  | A / B / C / D                                                                                 |
| Status                 | 单选  | New / Scored / Contact Found / Assigned / Contacted / Replied / Quoted / Won / Lost / Not Fit |
| Owner                  | 人员  | 负责人                                                                                           |
| Created Time           | 日期  | 创建时间                                                                                          |
| Last Updated           | 日期  | 更新时间                                                                                          |
| Notes                  | 长文本 | 备注                                                                                            |

---

### 6.2 表 2：Contact Table 联系人表

用途：

存放联系人信息。

字段：

| 字段名               | 类型  | 说明                                                    |
| ----------------- | --- | ----------------------------------------------------- |
| Contact ID        | 文本  | 唯一 ID                                                 |
| Lead ID           | 关联  | 关联 Lead Pool                                          |
| Name              | 文本  | 联系人姓名                                                 |
| Role              | 文本  | Founder / Owner / Marketing / Operations / Purchasing |
| Email             | 邮箱  | 邮箱                                                    |
| Email Confidence  | 单选  | High / Medium / Low / Unknown                         |
| LinkedIn URL      | 链接  | LinkedIn                                              |
| WhatsApp          | 电话  | WhatsApp                                              |
| Facebook URL      | 链接  | Facebook                                              |
| Instagram URL     | 链接  | Instagram                                             |
| Contact Form URL  | 链接  | 官网表单                                                  |
| Preferred Channel | 单选  | Email / LinkedIn / WhatsApp / Website Form / Unknown  |
| Contact Status    | 单选  | Not Verified / Verified / Invalid / Need Manual Check |
| Notes             | 长文本 | 备注                                                    |

---

### 6.3 表 3：Lead Scoring 客户评分表

用途：

记录 AI 对客户的评分依据，避免只看一个总分。

字段：

| 字段名                    | 类型  | 说明                                                                                                    |
| ---------------------- | --- | ----------------------------------------------------------------------------------------------------- |
| Score ID               | 文本  | 唯一 ID                                                                                                 |
| Lead ID                | 关联  | 关联线索                                                                                                  |
| Total Score            | 数字  | 0-100                                                                                                 |
| Sourcing Need Score    | 数字  | 0-20                                                                                                  |
| Fulfillment Pain Score | 数字  | 0-20                                                                                                  |
| Custom Packaging Score | 数字  | 0-15                                                                                                  |
| Store Maturity Score   | 数字  | 0-15                                                                                                  |
| Contactability Score   | 数字  | 0-15                                                                                                  |
| ASG Service Fit Score  | 数字  | 0-15                                                                                                  |
| Reasoning Summary      | 长文本 | AI 判断理由                                                                                               |
| Main Pain Point        | 单选  | Supplier / Shipping / QC / Packaging / MOQ / Price / Scaling / Unknown                                |
| Recommended Offer      | 单选  | Supplier Switch Audit / Sourcing Help / Fulfillment Quote / Custom Packaging / Logistics Optimization |
| Risk                   | 单选  | Low / Medium / High                                                                                   |
| Review Needed          | 复选框 | 是否需要人工复审                                                                                              |

评分逻辑：

```text
80-100：A级，必须当天联系。
60-79：B级，可以进入跟进池。
40-59：C级，适合内容触达或观察。
0-39：D级，不建议业务员浪费时间。
```

---

### 6.4 表 4：Outreach Task 触达任务表

用途：

把 AI 判断后的客户转成业务员可执行任务。

字段：

| 字段名                  | 类型  | 说明                                                                                 |
| -------------------- | --- | ---------------------------------------------------------------------------------- |
| Task ID              | 文本  | 唯一 ID                                                                              |
| Lead ID              | 关联  | 关联客户                                                                               |
| Contact ID           | 关联  | 关联联系人                                                                              |
| Owner                | 人员  | 业务员                                                                                |
| Channel              | 单选  | Email / LinkedIn / WhatsApp / Website Form                                         |
| Message Type         | 单选  | First Touch / Follow-up 1 / Follow-up 2 / Reply / Quote Explanation                |
| AI Draft             | 长文本 | AI 生成话术                                                                            |
| Human Edited Version | 长文本 | 人工修改版本                                                                             |
| Approval Status      | 单选  | Pending Review / Approved / Rejected / Sent                                        |
| Send Status          | 单选  | Not Sent / Sent / Replied / Bounced / Failed                                       |
| Send Date            | 日期  | 发送时间                                                                               |
| Next Follow-up Date  | 日期  | 下次跟进时间                                                                             |
| Result               | 单选  | No Response / Interested / Not Interested / Need Quote / Need Meeting / Won / Lost |
| Notes                | 长文本 | 备注                                                                                 |

重要规则：

```text
AI Draft 不能直接发送。
必须由业务员在 Human Edited Version 中确认后，Approval Status 才能变成 Approved。
```

---

### 6.5 表 5：Conversation Log 沟通记录表

用途：

记录客户回复和业务员跟进过程。

字段：

| 字段名             | 类型  | 说明                                                                                     |
| --------------- | --- | -------------------------------------------------------------------------------------- |
| Conversation ID | 文本  | 唯一 ID                                                                                  |
| Lead ID         | 关联  | 关联线索                                                                                   |
| Contact ID      | 关联  | 关联联系人                                                                                  |
| Channel         | 单选  | Email / WhatsApp / LinkedIn / Facebook / Meeting / Other                               |
| Direction       | 单选  | Inbound / Outbound                                                                     |
| Message Content | 长文本 | 消息内容                                                                                   |
| AI Summary      | 长文本 | AI 总结                                                                                  |
| Intent          | 单选  | Inquiry / Quote Request / Complaint / Objection / Not Interested / Cooperation / Other |
| Urgency         | 单选  | High / Medium / Low                                                                    |
| Next Action     | 长文本 | AI 建议下一步                                                                               |
| Owner           | 人员  | 负责人                                                                                    |
| Created Time    | 日期  | 时间                                                                                     |

---

### 6.6 表 6：Content Opportunity 内容机会表

用途：

把客户痛点转化成内容选题。

字段：

| 字段名                    | 类型  | 说明                                                                                  |
| ---------------------- | --- | ----------------------------------------------------------------------------------- |
| Content ID             | 文本  | 唯一 ID                                                                               |
| Source Lead ID         | 关联  | 来源客户                                                                                |
| Source Conversation ID | 关联  | 来源沟通                                                                                |
| Pain Point             | 单选  | Supplier / Shipping / QC / Packaging / MOQ / Price / Scaling                        |
| Topic                  | 文本  | 内容标题                                                                                |
| Search Intent          | 单选  | Problem / Comparison / How-to / Checklist / Case Study / Pricing                    |
| Recommended Format     | 多选  | SEO Blog / LinkedIn / Reddit Answer / Quora Answer / Short Video / Email Newsletter |
| Draft Brief            | 长文本 | 内容简报                                                                                |
| Priority               | 单选  | High / Medium / Low                                                                 |
| Status                 | 单选  | New / Drafted / Reviewed / Published                                                |
| Owner                  | 人员  | 内容负责人                                                                               |

---

### 6.7 表 7：Daily Report 每日指挥日报

用途：

每天自动汇总获客系统表现。

字段：

| 字段名                       | 类型  | 说明      |
| ------------------------- | --- | ------- |
| Report Date               | 日期  | 日期      |
| New Leads                 | 数字  | 新增线索    |
| A Leads                   | 数字  | A级线索    |
| B Leads                   | 数字  | B级线索    |
| Contacts Found            | 数字  | 找到联系人数量 |
| Outreach Drafts Generated | 数字  | 生成话术数量  |
| Messages Sent             | 数字  | 实际发送数量  |
| Replies                   | 数字  | 回复数量    |
| Quote Requests            | 数字  | 报价请求    |
| Meetings                  | 数字  | 会议数     |
| Won Deals                 | 数字  | 成交数     |
| Lost Deals                | 数字  | 丢单数     |
| Main Findings             | 长文本 | 今日核心发现  |
| Problems                  | 长文本 | 卡点      |
| Tomorrow Actions          | 长文本 | 明日动作    |

---

### 6.8 表 8：Prompt Version Prompt 版本表

用途：

管理 Prompt，避免每个人乱改。

字段：

| 字段名            | 类型  | 说明                                            |
| -------------- | --- | --------------------------------------------- |
| Prompt ID      | 文本  | 唯一 ID                                         |
| Prompt Name    | 文本  | Prompt 名称                                     |
| Version        | 文本  | v1 / v2 / v3                                  |
| Use Case       | 单选  | Scoring / Outreach / Reply / Content / Report |
| Prompt Content | 长文本 | Prompt 内容                                     |
| Output Schema  | 长文本 | 要求输出格式                                        |
| Status         | 单选  | Draft / Active / Deprecated                   |
| Owner          | 人员  | 维护人                                           |
| Last Updated   | 日期  | 更新时间                                          |
| Test Result    | 长文本 | 测试结果                                          |

---

## 7. 客户评分模型

总分 100 分。

### 7.1 评分维度

| 维度      | 分值 | 判断标准                                            |
| ------- | -: | ----------------------------------------------- |
| 采购需求    | 20 | 是否需要从中国采购、找供应商、低 MOQ、定制产品                       |
| 履约痛点    | 20 | 是否有物流慢、发货不稳、追踪号慢、退货高等问题                         |
| 包装与品牌需求 | 15 | 是否有 custom packaging、private label、logo、插卡、贴标需求 |
| 店铺成熟度   | 15 | 是否已经有订单，是否像增长型卖家                                |
| 可联系性    | 15 | 是否能找到邮箱、LinkedIn、WhatsApp、官网表单                  |
| ASG 适配度 | 15 | ASG 是否能提供明显解决方案                                 |

### 7.2 优先级

```text
A：80-100 分
当天必须联系。适合业务员重点开发。

B：60-79 分
进入跟进池。适合邮件或 LinkedIn 触达。

C：40-59 分
不急着人工开发，可转成内容选题或长期观察。

D：0-39 分
暂不跟进。
```

### 7.3 高价值客户信号

以下信号会提高评分：

1. 网站已经有较完整产品页。
2. 产品有变体、SKU、多颜色、多尺码。
3. 店铺有品牌意识。
4. 客户使用 Shopify / WooCommerce。
5. 客户提到 shipping delay。
6. 客户提到 supplier problem。
7. 客户提到 custom packaging。
8. 客户提到 quality issue。
9. 客户需要从 1688 / China sourcing 找货。
10. 客户不是刚起步，而是已经有订单。

### 7.4 低价值客户信号

以下信号会降低评分：

1. 没有网站。
2. 没有明确产品。
3. 只想找最低价。
4. 只做 1 单测试且没有后续计划。
5. 联系方式不可用。
6. 产品不适合 ASG 履约。
7. 客户只问免费服务。
8. 明显不是电商卖家。

---

## 8. n8n 工作流设计

### 8.1 工作流 1：手动线索导入

名称：

```text
01 Manual Lead Import
```

触发方式：

```text
Webhook / 手动上传 CSV / 飞书表格新增记录
```

流程：

```text
接收线索 → 清洗字段 → 检查 URL → 去重 → 写入 Lead Pool → 标记 Status = New
```

输入：

```json
{
  "company_name": "Example Store",
  "website_url": "https://example.com",
  "source_channel": "Manual",
  "source_url": "",
  "notes": ""
}
```

输出：

```json
{
  "lead_id": "LEAD-20260621-0001",
  "status": "created"
}
```

验收标准：

1. 相同 Website URL 不重复创建。
2. 缺少 Website URL 时，标记为 Need Manual Check。
3. 创建成功后写入飞书 Lead Pool。
4. 所有错误进入 Error Log。

---

### 8.2 工作流 2：线索清洗与去重

名称：

```text
02 Lead Cleaning & Dedup
```

触发方式：

```text
每小时运行一次
```

流程：

```text
读取 Status = New 的线索
→ 标准化网址
→ 提取主域名
→ 检查重复
→ 补全平台判断
→ 更新 Lead Pool
```

标准化规则：

```text
https://www.example.com/products/a
→ example.com

http://example.com/
→ example.com
```

验收标准：

1. 能识别 www 和非 www 重复。
2. 能识别 http 和 https 重复。
3. 能识别带路径和不带路径重复。
4. 重复线索不删除，标记 Duplicate，并关联主记录。

---

### 8.3 工作流 3：AI 客户评分

名称：

```text
03 Lead Scoring
```

触发方式：

```text
每小时运行一次
```

筛选条件：

```text
Lead Pool.Status = New 或 Scored Needed
```

流程：

```text
读取线索
→ 读取 Website URL、Source URL、Evidence Text
→ 调用 AI 评分 Prompt
→ 输出 JSON
→ 写入 Lead Scoring 表
→ 更新 Lead Pool 的 ASG Fit Score、Priority、Status
```

AI 输出必须是 JSON：

```json
{
  "total_score": 86,
  "priority": "A",
  "main_pain_point": "Supplier",
  "recommended_offer": "Supplier Switch Audit",
  "reasoning_summary": "This store appears to be a growing Shopify brand with signs of fulfillment and supplier switching needs.",
  "risk": "Low",
  "review_needed": false
}
```

验收标准：

1. 所有 AI 输出必须能被 JSON 解析。
2. 解析失败时，进入人工复审。
3. A 级线索自动创建触达任务。
4. D 级线索不创建触达任务。
5. B 级线索进入观察或普通触达池。

---

### 8.4 工作流 4：触达话术生成

名称：

```text
04 Outreach Draft Generation
```

触发方式：

```text
当 Lead Priority = A 或 B，且存在可用联系方式
```

流程：

```text
读取 Lead 信息
→ 读取 Contact 信息
→ 读取客户评分理由
→ 判断推荐 Offer
→ 调用对应话术 Prompt
→ 生成 Email / LinkedIn / WhatsApp / Website Form 话术
→ 写入 Outreach Task
→ Approval Status = Pending Review
```

生成话术原则：

1. 简短。
2. 个性化。
3. 不夸大。
4. 不假装认识客户。
5. 不说“我们看到你遇到问题”这种过度推断。
6. 必须基于公开信息和合理推测。
7. 必须包含明确但轻量的 CTA。

示例 CTA：

```text
Would you like us to review your current fulfillment setup and see if there is room to reduce shipping delays or supplier coordination work?
```

验收标准：

1. 每个 A 级客户至少生成 1 封邮件。
2. 如果有 LinkedIn，生成 LinkedIn 私信。
3. 如果有 WhatsApp，生成 WhatsApp 短消息。
4. 不允许直接发送。
5. 必须等待人工审核。

---

### 8.5 工作流 5：客户回复分类

名称：

```text
05 Reply Classification
```

触发方式：

```text
业务员把客户回复粘贴到 Conversation Log
```

流程：

```text
读取客户回复
→ AI 判断意图
→ AI 总结重点
→ AI 生成下一步建议
→ 更新 Conversation Log
→ 如需报价，创建 Quote Task
→ 如需会议，创建 Meeting Task
```

回复分类：

```text
Inquiry：普通咨询
Quote Request：报价请求
Objection：异议
Not Interested：不感兴趣
Need More Info：需要更多信息
Meeting Request：想开会
Complaint：投诉
Cooperation：合作机会
```

验收标准：

1. 客户要求报价时，必须自动标记 High Urgency。
2. 客户表达不感兴趣时，不再继续高频跟进。
3. 客户问物流、价格、包装、MOQ 时，自动推荐对应 FAQ 和话术。
4. 所有建议必须写入 Next Action。

---

### 8.6 工作流 6：每日指挥日报

名称：

```text
06 Daily Command Report
```

触发方式：

```text
每天 18:30
```

流程：

```text
统计 Lead Pool
→ 统计 Contact Table
→ 统计 Outreach Task
→ 统计 Conversation Log
→ 调用 AI 生成日报
→ 写入 Daily Report
→ 推送到飞书群
```

日报结构：

```text
1. 今日新增线索
2. 今日 A 级线索
3. 今日已联系客户
4. 今日客户回复
5. 今日报价机会
6. 今日最大问题
7. 明天必须跟进的客户
8. 内容机会
9. 对业务员的建议
10. 对老板的建议
```

验收标准：

1. 每天自动生成。
2. 必须包含具体数字。
3. 必须列出明天要跟进的客户。
4. 不允许只写空泛总结。
5. 报告必须能让老板 3 分钟看懂今天获客情况。

---

### 8.7 工作流 7：内容机会生成

名称：

```text
07 Content Opportunity Generation
```

触发方式：

```text
每天 22:00
```

流程：

```text
读取当天客户痛点、回复、异议
→ 提取高频问题
→ 生成内容选题
→ 推荐发布渠道
→ 写入 Content Opportunity
```

内容类型：

1. SEO 文章。
2. LinkedIn 文章。
3. Reddit 回答草稿。
4. Quora 回答草稿。
5. 短视频脚本。
6. 邮件 Newsletter。
7. 客户案例。
8. 对比型内容。

验收标准：

1. 每天至少生成 5 个内容机会。
2. 每个内容机会必须对应真实客户痛点。
3. 不允许为了发内容而发内容。
4. 内容必须能反哺获客。

---

## 9. Prompt 规范

所有 Prompt 必须满足：

1. 明确角色。
2. 明确输入字段。
3. 明确输出 JSON。
4. 明确禁止事项。
5. 明确业务背景。
6. 明确 ASG 的服务边界。
7. 明确人工审核要求。

---

### 9.1 Lead Scoring Prompt

文件位置：

```text
prompts/lead-scoring/lead-scoring-v1.md
```

Prompt：

```text
You are an AI lead qualification analyst for ASG Dropshipping.

ASG provides China sourcing, dropshipping fulfillment, quality control, custom packaging, warehousing, Shopify order fulfillment, and logistics coordination for growing eCommerce sellers.

Your task is to evaluate whether a potential lead is a good fit for ASG.

Input:
- Company / Store Name
- Website URL
- Platform
- Country
- Product Category
- Source Channel
- Source URL
- Evidence Text
- Notes

Scoring dimensions:
1. Sourcing Need Score: 0-20
2. Fulfillment Pain Score: 0-20
3. Custom Packaging Score: 0-15
4. Store Maturity Score: 0-15
5. Contactability Score: 0-15
6. ASG Service Fit Score: 0-15

Total score: 0-100.

Priority:
- A: 80-100
- B: 60-79
- C: 40-59
- D: 0-39

Rules:
- Do not invent facts.
- If information is unclear, mark it as Unknown.
- Use cautious language.
- Do not assume the customer has a problem unless there is evidence.
- Recommend a practical ASG offer based on the available information.

Output valid JSON only:

{
  "total_score": 0,
  "priority": "A/B/C/D",
  "sourcing_need_score": 0,
  "fulfillment_pain_score": 0,
  "custom_packaging_score": 0,
  "store_maturity_score": 0,
  "contactability_score": 0,
  "asg_service_fit_score": 0,
  "main_pain_point": "Supplier/Shipping/QC/Packaging/MOQ/Price/Scaling/Unknown",
  "recommended_offer": "Supplier Switch Audit/Sourcing Help/Fulfillment Quote/Custom Packaging/Logistics Optimization/Not Fit",
  "reasoning_summary": "",
  "risk": "Low/Medium/High",
  "review_needed": true
}
```

---

### 9.2 Cold Email Prompt

文件位置：

```text
prompts/outreach/cold-email-v1.md
```

Prompt：

```text
You are writing a concise B2B outreach email for ASG Dropshipping.

ASG helps growing eCommerce sellers with China sourcing, fulfillment, QC, custom packaging, Shopify order fulfillment, and logistics coordination.

Input:
- Lead name
- Website
- Category
- Country
- Main pain point
- Recommended offer
- Evidence summary
- Contact role

Write one short email.

Requirements:
- 90-130 words.
- Natural and professional.
- No exaggerated claims.
- No fake familiarity.
- Do not say “I noticed you have problems” unless the evidence clearly says so.
- Mention one relevant ASG capability.
- End with a low-pressure CTA.
- Do not include spammy wording.

Output JSON only:

{
  "subject": "",
  "email_body": "",
  "cta": "",
  "personalization_reason": ""
}
```

---

### 9.3 WhatsApp Prompt

文件位置：

```text
prompts/outreach/whatsapp-message-v1.md
```

Prompt：

```text
Write a short WhatsApp message for a potential ASG Dropshipping lead.

Requirements:
- Under 60 words.
- Friendly but professional.
- No hard selling.
- One clear reason for reaching out.
- One simple question at the end.
- Do not include links unless provided.
- Do not claim we know their internal problems.

Output JSON only:

{
  "message": "",
  "reason": ""
}
```

---

### 9.4 Reply Classifier Prompt

文件位置：

```text
prompts/sales/reply-classifier-v1.md
```

Prompt：

```text
You are an AI sales assistant for ASG Dropshipping.

Classify the customer's reply and recommend the next action.

Input:
- Lead profile
- Previous outreach message
- Customer reply
- Current status

Output JSON only:

{
  "intent": "Inquiry/Quote Request/Objection/Not Interested/Need More Info/Meeting Request/Complaint/Cooperation/Other",
  "urgency": "High/Medium/Low",
  "summary": "",
  "customer_need": "",
  "recommended_next_action": "",
  "suggested_reply": "",
  "should_follow_up": true,
  "next_followup_days": 0
}
```

---

## 10. 脚本模块设计

### 10.1 clean_leads.py

作用：

清洗线索数据。

功能：

1. 标准化 URL。
2. 提取主域名。
3. 删除空格。
4. 统一国家名称。
5. 统一平台名称。
6. 标记缺失字段。

输入：

```csv
company_name,website_url,source_channel,source_url,notes
```

输出：

```json
{
  "company_name": "",
  "domain": "",
  "website_url": "",
  "source_channel": "",
  "is_valid": true,
  "missing_fields": []
}
```

---

### 10.2 dedupe_leads.py

作用：

线索去重。

去重规则：

1. domain 相同，判定为重复。
2. email 相同，判定为重复。
3. company name 高度相似，进入人工复审。
4. source_url 相同，判定为重复来源。

输出：

```json
{
  "is_duplicate": true,
  "duplicate_type": "domain/email/company/source_url",
  "master_lead_id": ""
}
```

---

### 10.3 score_leads.py

作用：

调用 AI 对客户评分。

功能：

1. 读取飞书 Lead Pool 中 Status = New 的记录。
2. 调用 Lead Scoring Prompt。
3. 校验 JSON。
4. 写入 Lead Scoring 表。
5. 更新 Lead Pool 状态。

失败处理：

1. AI 超时，重试 2 次。
2. JSON 解析失败，标记 Review Needed。
3. 分数异常，标记 Manual Review。

---

### 10.4 generate_outreach.py

作用：

生成开发信和私信草稿。

功能：

1. 读取 A/B 级线索。
2. 读取联系人。
3. 根据渠道选择 Prompt。
4. 生成 AI Draft。
5. 写入 Outreach Task。
6. 标记 Pending Review。

---

### 10.5 generate_daily_report.py

作用：

生成每日获客日报。

功能：

1. 统计当天新增线索。
2. 统计 A/B/C/D 分布。
3. 统计业务员任务完成情况。
4. 统计客户回复。
5. 统计报价机会。
6. 生成老板日报。
7. 推送到飞书群。

---

## 11. 环境变量

`.env.example`：

```text
# Feishu
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BASE_APP_TOKEN=
FEISHU_LEAD_TABLE_ID=
FEISHU_CONTACT_TABLE_ID=
FEISHU_SCORE_TABLE_ID=
FEISHU_OUTREACH_TABLE_ID=
FEISHU_CONVERSATION_TABLE_ID=
FEISHU_CONTENT_TABLE_ID=
FEISHU_REPORT_TABLE_ID=

# AI
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DEFAULT_AI_PROVIDER=openai
DEFAULT_MODEL=

# n8n
N8N_WEBHOOK_SECRET=
N8N_BASE_URL=

# Runtime
ENV=development
LOG_LEVEL=info
TIMEZONE=Asia/Shanghai
```

---

## 12. 开发实施顺序

### Day 1：搭项目骨架

目标：

完成 GitHub 仓库和基础文档。

任务：

1. 创建 `asg-lead-command-center` 仓库。
2. 创建目录结构。
3. 写入 README。
4. 写入本开发文档。
5. 创建 `.env.example`。
6. 创建 `CLAUDE.md`。
7. 创建 `CODEX_TASKS.md`。

验收标准：

1. 仓库结构完整。
2. Claude Code 能读取项目目标。
3. Codex 能看到具体任务。

---

### Day 2：搭飞书多维表

目标：

完成数据总控台。

任务：

1. 创建飞书多维表格。
2. 创建 8 张表。
3. 按字段配置类型。
4. 设置基础视图。
5. 设置业务员视图。
6. 设置老板日报视图。

建议视图：

```text
Lead Pool:
- All Leads
- A Leads Today
- Need Contact
- Contacted
- Replied
- Won / Lost

Outreach Task:
- My Tasks
- Pending Review
- Approved To Send
- Sent Today
- Need Follow-up

Daily Report:
- This Week
- This Month
```

验收标准：

1. 所有字段创建完成。
2. 至少手动录入 10 条测试线索。
3. 可以按 Priority 和 Owner 筛选。
4. 可以关联 Lead 与 Contact。

---

### Day 3：飞书 API 与脚本打通

目标：

让代码能读写飞书。

任务：

1. 编写 `feishu_client.py`。
2. 实现获取 token。
3. 实现读取表记录。
4. 实现新增记录。
5. 实现更新记录。
6. 实现分页读取。
7. 写测试脚本。

验收标准：

1. 本地脚本能读取 Lead Pool。
2. 本地脚本能创建测试 Lead。
3. 本地脚本能更新 Lead Status。
4. 错误日志清晰。

---

### Day 4：线索清洗与评分

目标：

完成 AI 评分闭环。

任务：

1. 编写 `clean_leads.py`。
2. 编写 `dedupe_leads.py`。
3. 编写 `score_leads.py`。
4. 接入 Lead Scoring Prompt。
5. 校验 JSON 输出。
6. 写入 Lead Scoring 表。
7. 更新 Lead Pool 分数和优先级。

验收标准：

1. 10 条测试线索可以成功评分。
2. A/B/C/D 分类合理。
3. JSON 解析失败时不影响整体流程。
4. 飞书中能看到评分依据。

---

### Day 5：触达话术生成

目标：

完成业务员可审核的开发话术。

任务：

1. 编写 `generate_outreach.py`。
2. 接入 Email Prompt。
3. 接入 LinkedIn Prompt。
4. 接入 WhatsApp Prompt。
5. 写入 Outreach Task。
6. 默认状态为 Pending Review。

验收标准：

1. A 级客户自动生成开发信。
2. 话术必须个性化。
3. 不允许自动发送。
4. 业务员能在飞书中修改话术。

---

### Day 6：n8n 工作流搭建

目标：

把脚本和飞书串成自动化流程。

任务：

1. 创建 n8n workflow。
2. 配置定时触发。
3. 配置 HTTP Request 或 Execute Command。
4. 配置错误通知。
5. 配置飞书群日报推送。
6. 导出 workflow JSON 到仓库。

验收标准：

1. 每小时自动处理新线索。
2. 每天自动生成日报。
3. 错误会发到指定飞书群。
4. workflow JSON 已提交 GitHub。

---

### Day 7：业务员试运行

目标：

让真实团队开始用。

任务：

1. 导入第一批 100 条线索。
2. AI 评分。
3. 业务员只处理 A 级和部分 B 级。
4. 每个业务员每天联系 20 个客户。
5. 记录回复。
6. 生成日报。
7. 复盘评分和话术质量。

验收标准：

1. 至少 100 条线索进入系统。
2. 至少 20 条 A/B 级线索生成任务。
3. 至少 10 条由人工确认并发送。
4. 至少形成 1 份日报。
5. 发现 3 个需要优化的问题。

---

## 13. CLAUDE.md 内容

项目根目录创建 `CLAUDE.md`：

```text
# Claude Code Project Instructions

You are the system architect for ASG Lead Command Center.

Business context:
ASG Dropshipping provides China sourcing, dropshipping fulfillment, quality control, custom packaging, warehousing, Shopify order fulfillment, and logistics coordination for growing eCommerce sellers.

Project goal:
Build an internal AI-powered lead command center that helps ASG discover leads, score leads, generate outreach drafts, assign sales tasks, classify replies, generate daily reports, and convert sales conversations into content opportunities.

Important principles:
1. Do not build a full SaaS in V1.
2. Feishu Base is the data control center.
3. n8n is the workflow engine.
4. AI drafts must require human approval before sending.
5. Do not automate spam, mass messaging, or platform-violating behavior.
6. All AI outputs must be structured and auditable.
7. Keep the system simple, maintainable, and practical for the ASG team.

Development priorities:
1. Create clear documentation.
2. Build Feishu API integration.
3. Build lead cleaning and deduplication.
4. Build AI lead scoring.
5. Build outreach draft generation.
6. Build daily report generation.
7. Export n8n workflows.
8. Add tests for key logic.

When making changes:
- Update docs when logic changes.
- Keep prompts versioned.
- Use JSON output schemas for AI calls.
- Never hard-code secrets.
- Add comments for business logic.
```

---

## 14. CODEX_TASKS.md 内容

项目根目录创建 `CODEX_TASKS.md`：

```text
# Codex Task List

## Task 1: Feishu Client
Build scripts/feishu_client.py.

Requirements:
- Get tenant access token.
- Read records.
- Create records.
- Update records.
- Support pagination.
- Handle errors clearly.
- Use environment variables.

## Task 2: Lead Cleaner
Build scripts/clean_leads.py.

Requirements:
- Normalize URLs.
- Extract domains.
- Detect missing fields.
- Standardize country and platform values.
- Return structured JSON.

## Task 3: Lead Deduplication
Build scripts/dedupe_leads.py.

Requirements:
- Detect duplicate domains.
- Detect duplicate emails.
- Detect similar company names.
- Return duplicate type and master lead ID.

## Task 4: AI Lead Scoring
Build scripts/score_leads.py.

Requirements:
- Read new leads from Feishu.
- Load prompt from prompts/lead-scoring/lead-scoring-v1.md.
- Call AI API.
- Validate JSON.
- Write scoring result to Feishu.
- Update lead priority and status.

## Task 5: Outreach Draft Generator
Build scripts/generate_outreach.py.

Requirements:
- Read A/B leads with contact info.
- Select prompt by channel.
- Generate outreach draft.
- Write to Outreach Task.
- Set Approval Status = Pending Review.

## Task 6: Daily Report Generator
Build scripts/generate_daily_report.py.

Requirements:
- Collect daily metrics.
- Generate concise boss report.
- Write to Daily Report table.
- Output markdown summary.

## Task 7: Tests
Create tests for:
- URL normalization.
- Domain extraction.
- Deduplication.
- AI JSON validation.
- Score to priority mapping.
```

---

## 15. 运营 SOP

### 15.1 老板每天看什么

每天只看 6 个数字：

1. 今日新增线索。
2. 今日 A 级线索。
3. 今日已联系客户。
4. 今日回复客户。
5. 今日报价请求。
6. 今日成交或强意向。

再看 3 个问题：

1. 哪个渠道质量最高？
2. 哪类客户最容易回复？
3. 哪个业务员执行最好？

---

### 15.2 业务员每天做什么

业务员每天流程：

```text
9:00 查看自己的 A 级客户
9:30 审核 AI 生成话术
10:00 开始人工发送
14:00 回复客户
16:00 跟进昨天未回复客户
18:00 更新飞书状态
```

业务员每天最低动作：

```text
审核 20 条 A/B 线索
发送 10-20 条高质量触达
更新所有客户状态
把客户回复粘贴进 Conversation Log
```

---

### 15.3 内容负责人每天做什么

内容负责人每天流程：

```text
查看 Content Opportunity
挑选 3-5 个真实痛点
生成 SEO / LinkedIn / Reddit / Quora 草稿
人工审核后发布
把发布链接回填
```

内容原则：

1. 不发垃圾内容。
2. 不硬广。
3. 不假装用户。
4. 不批量刷屏。
5. 每条内容必须解决一个真实问题。

---

## 16. 安全与合规规则

### 16.1 禁止事项

系统禁止：

1. 自动群发未经审核的邮件。
2. 自动批量私信 LinkedIn / Facebook / Reddit / Quora 用户。
3. 绕过平台限制采集数据。
4. 采集非公开数据。
5. 假装客户、假装用户、假装第三方。
6. 编造客户痛点。
7. 编造成交案例。
8. 夸大物流时效。
9. 夸大服务能力。
10. 未经确认直接承诺价格和时效。

### 16.2 必须保留人工审核

以下动作必须人工确认：

1. 第一次触达客户。
2. 报价发送。
3. 对客户投诉的回复。
4. 对平台公开内容的发布。
5. 客户案例发布。
6. 涉及价格、时效、赔付、售后的承诺。

---

## 17. 核心 KPI

### 17.1 获客 KPI

| 指标       |     V1 目标 |
| -------- | --------: |
| 每天新增线索   |     100 条 |
| 每天 A 级线索 |   10-20 条 |
| 每天有效联系人  |   20-50 个 |
| 每天人工触达   |   10-30 个 |
| 回复率      |    5%-15% |
| 报价请求     | 每周 5-20 个 |
| 成交客户     |    每月逐步提高 |

### 17.2 内容 KPI

| 指标                     |   V1 目标 |
| ---------------------- | ------: |
| 每天内容机会                 |     5 个 |
| 每周 SEO 文章              |   3-5 篇 |
| 每周 LinkedIn 内容         |  5-10 条 |
| 每周 Reddit / Quora 回答草稿 | 10-20 条 |
| 每周短视频脚本                |  5-10 条 |

### 17.3 销售管理 KPI

| 指标         | V1 目标 |
| ---------- | ----: |
| 业务员任务完成率   |  80%+ |
| 客户状态更新率    |  95%+ |
| AI 评分人工认可率 |  70%+ |
| 话术可用率      |  70%+ |
| 日报生成率      |  100% |

---

## 18. V1 验收标准

项目 V1 完成必须满足：

1. GitHub 仓库结构完整。
2. 飞书多维表 8 张表创建完成。
3. 可以手动导入线索。
4. 可以自动清洗和去重。
5. 可以 AI 自动评分。
6. 可以自动生成触达草稿。
7. 所有触达草稿需要人工审核。
8. 可以记录客户回复。
9. 可以自动生成每日获客日报。
10. 可以把客户痛点转化成内容机会。
11. 业务员可以按任务执行。
12. 老板可以每天看日报判断获客质量。

---

## 19. V2 规划

V1 跑通后，再做 V2。

### V2 可以增加

1. 简单 Web Dashboard。
2. 邮件草稿自动创建。
3. Gmail / 企业邮箱收件分类。
4. Shopify 店铺数据增强。
5. 网站技术栈识别。
6. 联系人邮箱验证。
7. 多语言开发信。
8. 不同国家市场分层。
9. 业务员绩效看板。
10. 客户生命周期管理。
11. 自动生成报价准备清单。
12. 客户案例库。
13. SEO 内容自动发布前审核流。
14. LinkedIn 内容排期。
15. 线索来源 ROI 分析。

### V2 仍然不建议做

1. 自动刷屏。
2. 自动批量私信。
3. 自动冒充真人互动。
4. 自动承诺价格或物流时效。
5. 未审核自动发布客户案例。

---

## 20. 立即执行指令

### 给 Claude Code 的第一条指令

```text
请你读取当前项目，按照 docs/00-project-spec.md 的要求，先完成 ASG Lead Command Center 的项目骨架。

第一步只做：
1. 创建目录结构。
2. 创建 README.md。
3. 创建 CLAUDE.md。
4. 创建 CODEX_TASKS.md。
5. 创建 .env.example。
6. 创建 prompts 目录下的第一版 Prompt 文件。
7. 创建 scripts 目录下的空脚本文件，并写入函数说明。
8. 不要连接真实 API。
9. 不要做自动发送功能。

完成后，请输出：
- 已创建的文件列表
- 每个文件的作用
- 下一步建议
```

### 给 Codex 的第一批任务

```text
请你只执行 Task 1：Feishu Client。

目标：
实现 scripts/feishu_client.py。

要求：
1. 使用环境变量读取 FEISHU_APP_ID、FEISHU_APP_SECRET、FEISHU_BASE_APP_TOKEN。
2. 实现 get_tenant_access_token。
3. 实现 list_records。
4. 实现 create_record。
5. 实现 update_record。
6. 支持分页。
7. 不要写死任何表 ID。
8. 添加清晰错误处理。
9. 添加基础测试或示例用法。

完成后不要继续做其他任务。
```

---

## 21. 项目成功标准

这个项目不是为了“消耗 token”。

它的成功标准是：

```text
每天 ASG 能稳定发现更精准的客户，
业务员知道该联系谁，
AI 能提前准备好高质量话术，
老板每天能看到真实获客数据，
客户问题能反哺内容和 SOP，
最终让 ASG 在供应商切换、China fulfillment、custom packaging、dropshipping agent 这些场景里持续获得客户。
```

最终系统目标：

> **把 AI token 变成 ASG 的获客机器、销售助手、内容引擎和运营复盘系统。**
