# CostGuard AI — Architecture Deep Dive

## Problem Statement

Organizations using AWS often struggle with:
- Unexpected cost spikes that go unnoticed until the monthly bill
- Lack of real-time cost visibility across multiple AWS accounts
- No automated analysis explaining WHY costs increased
- Manual effort required to monitor and optimize spending

CostGuard AI solves this by providing automated, AI-powered cost monitoring as a multi-tenant SaaS platform.

---

## High-Level Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  CloudFront  │────▶│   S3 Bucket   │     │   EventBridge    │
│  (CDN/HTTPS) │     │  (Frontend)   │     │  (Daily Cron)    │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
┌─────────────┐     ┌──────────────┐     ┌────────▼────────┐
│   Cognito    │     │ API Gateway  │────▶│  Lambda Functions │
│  (Auth)      │     │  (REST API)  │     │                   │
└─────────────┘     └──────────────┘     │ ┌───────────────┐ │
                                          │ │Cost Analyzer   │ │
                                          │ │  - Cost Explorer│ │
                                          │ │  - Bedrock AI   │ │
                                          │ │  - SES Alerts   │ │
                                          │ └───────────────┘ │
                                          │ ┌───────────────┐ │
                                          │ │Dashboard API   │ │
                                          │ │  - CRUD Ops    │ │
                                          │ │  - Onboarding  │ │
                                          │ └───────────────┘ │
                                          └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │    DynamoDB       │
                                          │  ┌─────────────┐ │
                                          │  │ Customers    │ │
                                          │  │ DailyCosts   │ │
                                          │  │ CostAlerts   │ │
                                          │  └─────────────┘ │
                                          └─────────────────┘
```

---

## Data Flow

### Daily Cost Analysis (Automated)
```
EventBridge (6 AM UTC)
  → CostAnalyzer Lambda
    → Scan Customers table (get all registered accounts)
    → For each customer:
      → STS AssumeRole (cross-account access)
      → Cost Explorer API (yesterday's cost + 7-day history)
      → Calculate % change vs 7-day average
      → Bedrock Claude API (AI analysis of cost pattern)
      → DynamoDB put_item (store cost + AI analysis)
      → If spike >20%:
        → DynamoDB put_item (store alert)
        → SES send_email (notify customer)
```

### User Request Flow
```
Browser (CloudFront)
  → Cognito (authenticate)
  → API Gateway (route request)
    → DashboardApi Lambda
      → DynamoDB query/scan
      → Return JSON response
  → Browser renders data
```

### Customer Onboarding Flow
```
Customer's AWS Account:
  → Create IAM Role (CostGuardReadRole)
  → Trust policy allows CostGuard's Lambda role to assume it
  → Attach ce:GetCostAndUsage permission

CostGuard Dashboard:
  → POST /onboard { email, roleArn, plan }
  → Lambda stores in Customers DynamoDB table
  → Next daily run picks up new customer automatically
```

---

## DynamoDB Table Design

### Customers Table
```
Partition Key: customerId (String)
Attributes:
  - email (String) — customer's email for alerts
  - roleArn (String) — cross-account IAM role ARN
  - plan (String) — free/pro/enterprise
  - createdAt (String) — ISO timestamp
```

### DailyCosts Table
```
Partition Key: customerId (String)
Sort Key: date (String, YYYY-MM-DD)
Attributes:
  - cost (String) — yesterday's cost
  - avg_cost (String) — 7-day average
  - percent_change (String) — % change
  - ai_analysis (String) — Bedrock Claude's explanation
  - timestamp (String) — ISO timestamp

Access Patterns:
  - Query by customerId (get all costs for a customer)
  - Query by customerId + date range (recent costs)
  - ScanIndexForward=False for latest-first ordering
```

### CostAlerts Table
```
Partition Key: alertId (String, format: {customerId}-spike-{date})
Attributes:
  - customerId (String)
  - service (String)
  - percentChange (String)
  - aiExplanation (String)
  - timestamp (String)
```

---

## IAM Security Model (Least Privilege)

### Lambda Execution Role
```
Permissions:
  ✅ logs:CreateLogGroup, CreateLogStream, PutLogEvents
     → Scoped to: /aws/lambda/costguard-*

  ✅ ce:GetCostAndUsage, ce:GetCostForecast
     → Resource: * (Cost Explorer doesn't support resource-level permissions)

  ✅ bedrock:InvokeModel
     → Scoped to: specific model ARN only

  ✅ dynamodb:PutItem, GetItem, UpdateItem, DeleteItem, Query, Scan
     → Scoped to: only the 3 CostGuard tables

  ✅ ses:SendEmail, SendRawEmail
     → Scoped to: specific verified email identity

  ✅ sts:AssumeRole
     → Scoped to: arn:aws:iam::*:role/CostGuardReadRole
```

### Cross-Account Customer Role
```
Trust Policy:
  → Only CostGuard's Lambda role can assume it

Permissions:
  ✅ ce:GetCostAndUsage, ce:GetCostForecast
  ❌ No write permissions
  ❌ No access to any other service
```

---

## API Design

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /dashboard?customerId=xxx | None* | Cost data with AI analysis |
| GET | /alerts | None* | All cost spike alerts |
| GET | /cost-summary?customerId=xxx | None* | Aggregated spending |
| POST | /onboard | None* | Register customer account |
| GET | /customers | None* | List connected accounts |

| POST | /chat | None* | AI chatbot with live resource context |

*Note: Cognito auth is implemented on the frontend. For production, add a Cognito Authorizer to API Gateway.

### AI Chatbot Data Flow
```
User asks question in chat UI
  → POST /chat { question }
  → DashboardApi Lambda:
    1. Cost Explorer API → 7-day cost breakdown by service
    2. S3 ListBuckets → all bucket names
    3. EC2 DescribeInstances → instance IDs, types, state, names
    4. Lambda ListFunctions → function names, runtimes, memory
    5. DynamoDB ListTables → table names
    6. RDS DescribeDBInstances → DB IDs, classes, engines
    7. CloudFront ListDistributions → distribution IDs, domains
    8. Combine all data into context string
    9. Bedrock Claude API (context + question) → AI answer
  → Return { answer, cost_data }
```

### CORS Configuration
Each endpoint has an OPTIONS method with MOCK integration returning:
- Access-Control-Allow-Origin: *
- Access-Control-Allow-Headers: Content-Type,Authorization
- Access-Control-Allow-Methods: GET,POST,OPTIONS

---

## AI Integration (Amazon Bedrock)

### Model: Claude 3 Sonnet
- Used for generating natural language explanations of cost patterns
- Prompt includes: yesterday's cost, 7-day average, percentage change
- Response: brief insights and optimization recommendations
- Max tokens: 200 (keeps responses concise)

### Example Prompt:
```
Analyze AWS cost for customer cust-abc123:
Yesterday $45.67, 7-day avg $32.10, change +42.3%.
Brief insights and recommendations.
```

### Example Response:
```
Your AWS costs increased 42.3% yesterday ($45.67 vs $32.10 average).
This could indicate:
1. New EC2 instances or scaling events
2. Increased data transfer
3. New service provisioning

Recommendations:
- Review CloudTrail for recent resource changes
- Check for unused/idle resources
- Consider Reserved Instances for steady workloads
```

---

## Monitoring & Alerting

### CloudWatch Alarms (4 total)
| Alarm | Metric | Threshold | Description |
|-------|--------|-----------|-------------|
| cost-analyzer-errors | Lambda Errors | ≥1 in 5min | CostAnalyzer failures |
| cost-analyzer-throttles | Lambda Throttles | ≥1 in 5min | CostAnalyzer throttling |
| dashboard-api-errors | Lambda Errors | ≥1 in 5min | API failures |
| dashboard-api-throttles | Lambda Throttles | ≥1 in 5min | API throttling |

### CloudWatch Log Groups
- `/aws/lambda/costguard-cost-analyzer` (14-day retention)
- `/aws/lambda/costguard-dashboard-api` (14-day retention)

---

## Frontend Architecture

Single-page application (SPA) served from S3 via CloudFront:

- **Auth**: Direct Cognito API calls (SignUp, ConfirmSignUp, InitiateAuth)
- **Session**: JWT tokens stored in localStorage
- **API calls**: Fetch with Bearer token authorization
- **Pages**: Dashboard, Alerts, Cost Summary, Add Account, Customers
- **Responsive**: Works on desktop and mobile

### Security
- S3 bucket is fully private (all public access blocked)
- CloudFront uses Origin Access Control (OAC) with SigV4
- Bucket policy only allows CloudFront distribution
- HTTPS enforced via ViewerProtocolPolicy: redirect-to-https

---

## Infrastructure as Code

Everything deployed via a single CloudFormation template:

### Resources Created (28 total)
- 3 DynamoDB tables (with PITR, SSE, Retain policy)
- 1 IAM Role (least privilege)
- 2 Lambda functions (with log groups)
- 1 EventBridge rule + permission
- 1 API Gateway REST API
- 5 API resources + 5 GET/POST methods + 5 OPTIONS methods
- 1 API deployment
- 1 Lambda permission for API Gateway
- 1 Cognito User Pool + Client
- 1 S3 bucket + bucket policy
- 1 CloudFront distribution + OAC
- 4 CloudWatch alarms

### Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| ProjectName | costguard | Prefix for all resource names |
| BedrockModelId | claude-3-sonnet | AI model for analysis |
| AlertEmailAddress | admin@example.com | SES sender/recipient |

---

## Cost of Running This Platform

All serverless = pay only for what you use:

| Service | Pricing Model | Estimated Monthly (low traffic) |
|---------|--------------|-------------------------------|
| DynamoDB | Per request | ~$0.00 (free tier) |
| Lambda | Per invocation + duration | ~$0.00 (free tier) |
| API Gateway | Per request | ~$0.00 (free tier) |
| CloudFront | Per request + data transfer | ~$0.00 (free tier) |
| S3 | Storage + requests | ~$0.01 |
| Bedrock | Per token | ~$0.50/day (1 analysis) |
| SES | Per email | ~$0.00 |
| EventBridge | Per rule | Free |
| **Total** | | **~$15-20/month** |
