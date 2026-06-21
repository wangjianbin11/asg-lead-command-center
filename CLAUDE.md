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
- Add comments for business logic when the rule is not obvious from code.

