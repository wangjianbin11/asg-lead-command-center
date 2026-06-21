# Feishu Base Schema

Base name: `ASG Lead Command Center`.

## Lead Pool

Stores every potential customer lead.

Required fields:
- `Lead ID`
- `Company / Store Name`
- `Website URL`
- `Platform`
- `Country / Region`
- `Category`
- `Source Channel`
- `Source URL`
- `Pain Signal`
- `Evidence Text`
- `Estimated Stage`
- `Estimated Order Volume`
- `Current Supplier Guess`
- `ASG Fit Score`
- `Priority`
- `Status`
- `Owner`
- `Created Time`
- `Last Updated`
- `Notes`

## Contact Table

Stores contact-level data linked to Lead Pool.

Required fields:
- `Contact ID`
- `Lead ID`
- `Name`
- `Role`
- `Email`
- `Email Confidence`
- `LinkedIn URL`
- `WhatsApp`
- `Facebook URL`
- `Instagram URL`
- `Contact Form URL`
- `Preferred Channel`
- `Contact Status`
- `Notes`

## Lead Scoring

Stores scoring details and reasoning so the total score is auditable.

Required fields:
- `Score ID`
- `Lead ID`
- `Total Score`
- `Sourcing Need Score`
- `Fulfillment Pain Score`
- `Custom Packaging Score`
- `Store Maturity Score`
- `Contactability Score`
- `ASG Service Fit Score`
- `Reasoning Summary`
- `Main Pain Point`
- `Recommended Offer`
- `Risk`
- `Review Needed`

## Outreach Task

Stores salesperson tasks and AI drafts. Drafts are never sent automatically.

Required fields:
- `Task ID`
- `Lead ID`
- `Contact ID`
- `Owner`
- `Channel`
- `Message Type`
- `AI Draft`
- `Human Edited Version`
- `Approval Status`
- `Send Status`
- `Send Date`
- `Next Follow-up Date`
- `Result`
- `Notes`

## Conversation Log

Stores inbound and outbound customer conversation history.

Required fields:
- `Conversation ID`
- `Lead ID`
- `Contact ID`
- `Channel`
- `Direction`
- `Message Content`
- `AI Summary`
- `Intent`
- `Urgency`
- `Next Action`
- `Owner`
- `Created Time`

## Content Opportunity

Turns real customer pain points into content ideas.

Required fields:
- `Content ID`
- `Source Lead ID`
- `Source Conversation ID`
- `Pain Point`
- `Topic`
- `Search Intent`
- `Recommended Format`
- `Draft Brief`
- `Priority`
- `Status`
- `Owner`

## Daily Report

Stores daily boss-readable acquisition performance.

Required fields:
- `Report Date`
- `New Leads`
- `A Leads`
- `B Leads`
- `Contacts Found`
- `Outreach Drafts Generated`
- `Messages Sent`
- `Replies`
- `Quote Requests`
- `Meetings`
- `Won Deals`
- `Lost Deals`
- `Main Findings`
- `Problems`
- `Tomorrow Actions`

## Prompt Version

Stores active and deprecated prompt versions.

Required fields:
- `Prompt ID`
- `Prompt Name`
- `Version`
- `Use Case`
- `Prompt Content`
- `Output Schema`
- `Status`
- `Owner`
- `Last Updated`
- `Test Result`

