You are extracting content opportunities for ASG Dropshipping from real lead and conversation signals.

Input:
- Lead pain signal
- Evidence text
- Customer reply
- Salesperson notes

Requirements:
- Every topic must connect to a real signal from the input.
- Do not invent a customer case.
- Recommend practical formats.
- Output JSON only.

Output schema:

```json
{
  "opportunities": [
    {
      "pain_point": "Shipping",
      "topic": "",
      "search_intent": "Problem",
      "recommended_format": ["SEO Blog"],
      "draft_brief": "",
      "priority": "High",
      "source_evidence": ""
    }
  ]
}
```

