# CostGuard AI — Interview Questions & Answers

> Complete interview prep for this project. Covers architecture, security, AI, payments, scaling, and behavioral questions.

---

## 1. Project Overview

### Q: Tell me about this project in 60 seconds.
**A:** CostGuard AI is a multi-tenant SaaS platform I built from scratch that competes with enterprise tools like Cloudability and CloudHealth. It monitors AWS costs across multiple customer accounts, detects anomalies, generates AI-powered savings recommendations using Amazon Bedrock, forecasts spend using linear regression, and has a full subscription billing system via Razorpay. Everything is serverless on AWS — Lambda, DynamoDB, API Gateway, CloudFront — deployed via CloudFormation. It has a real-time chat interface powered by Claude Haiku/Sonnet/Opus, a budget tracker, service-level cost drill-downs, and a one-click CloudFormation onboarding flow. Paying customers get access to more powerful Claude models — enforced server-side.

### Q: Why did you build this?
**A:** Three reasons. First, existing tools like Cloudability cost thousands of dollars per month — there's a gap for SMBs. Second, I wanted to explore the full stack: serverless infrastructure, AI integration, payments, multi-tenancy, and UX all in one project. Third, AWS cost management is genuinely hard — most teams discover problems on their monthly bill, not daily. This catches spikes within 24 hours.

### Q: What's the tech stack?
**A:**
- **Frontend**: Vanilla JS SPA with ApexCharts — no build step, served from S3 + CloudFront
- **Auth**: Amazon Cognito (JWT tokens, email verification)
- **API**: API Gateway + Lambda (Python 3.11) — 17 routes
- **AI**: Amazon Bedrock (Claude Haiku 4.5 / Sonnet 4.5 / Opus 4.6) — model selected by subscription plan
- **Database**: DynamoDB × 4 tables (PAY_PER_REQUEST)
- **Scheduling**: EventBridge daily cron → CostAnalyzer Lambda
- **Payments**: Razorpay Standard Web Checkout (HMAC-SHA256 signature verification)
- **IaC**: CloudFormation single template (~30 resources)

---

## 2. Architecture

### Q: Walk me through the data flow when a cost spike is detected.
**A:**
1. EventBridge triggers `cost_analyzer` Lambda at 6 AM UTC
2. Lambda scans `costguard-customers` DynamoDB table — gets all registered accounts
3. For each customer: assumes their cross-account IAM role via STS
4. Calls Cost Explorer — gets yesterday's cost and 7-day breakdown
5. Calculates % change vs 7-day average
6. Invokes Bedrock Claude with cost context — gets AI-generated insights
7. Writes cost record + AI analysis to `costguard-costs` DynamoDB table
8. If change > 20%: writes to `costguard-alerts` table + sends SES email
9. Admin dashboard shows the alert in real-time on next page load

### Q: How does multi-tenancy work?
**A:** Two layers:
- **Data isolation**: All DynamoDB tables use `customerId` as the partition key. One customer can never read another's data.
- **AWS access isolation**: Each customer creates a `CostGuardReadRole` in their own AWS account with a trust policy that only allows our Lambda role ARN. We assume this role via STS for each API call — credentials are temporary (1 hour TTL), never stored.

The result: we touch each customer's account only when needed, with minimum permissions, using credentials that auto-expire.

### Q: How does the AI chatbot work?
**A:**
1. User asks a question (e.g., "Which service is costing the most?")
2. Lambda assumes the customer's cross-account role
3. Fetches 7-day cost breakdown by service from Cost Explorer
4. Fetches live resource inventory: S3 buckets, EC2 instances, Lambda functions, DynamoDB tables, RDS, CloudFront
5. Combines all data into a context string (real account IDs and resource names)
6. Sends `context + question` to Bedrock Claude with system prompt: "You have access to real AWS data, answer with specific resource names and IDs"
7. Returns the AI response — specific, not generic

The model used (Haiku/Sonnet/Opus) is selected based on the user's subscription plan — enforced in Python before the Bedrock API call.

### Q: Explain the cost forecasting feature.
**A:** Pure client-side linear regression — no new backend endpoint needed.
1. Fetch last 60 days of daily cost data (2 months of `/report` responses)
2. Map each day to an index (x=0,1,2...) and daily cost (y=$)
3. Run linear regression: calculate slope and intercept from sumX, sumY, sumXY, sumX²
4. Project 30 days forward using the regression line
5. Add ±15% confidence band as a `rangeArea` series in ApexCharts
6. Show "Projected Monthly: $X" KPI card

This gives a real forecast without a data science pipeline or ML service — just math.

### Q: Why ApexCharts instead of Chart.js or D3?
**A:** ApexCharts won on three specific features I needed:
- Built-in `annotations.points` for spike markers on the trend chart — no plugin needed
- Native `rangeArea` series type for the confidence band on the forecast chart
- `theme: { mode: 'dark'/'light' }` option that maps directly to our light/dark toggle
Chart.js requires separate annotation plugins with breaking API changes. D3 is too low-level for a project where I wasn't building a data viz product.

---

## 3. Security

### Q: How did you implement least-privilege IAM?
**A:** The Lambda execution role has 6 policy statements:
- **CloudWatch Logs**: Only `arn:aws:logs:*:*:log-group:/aws/lambda/costguard-*`
- **DynamoDB**: Only the 4 specific table ARNs — no wildcard
- **Cost Explorer**: `Resource: *` (CE doesn't support resource-level permissions, but only `ce:GetCostAndUsage` and `ce:GetCostForecast` actions)
- **Bedrock**: Scoped to `arn:aws:bedrock:*::foundation-model/*` — all models allowed because model ID varies by plan
- **SES**: Only the verified email identity ARN
- **STS**: Only `arn:aws:iam::*:role/CostGuardReadRole` — can only assume that exact role name in any account

### Q: How is the Razorpay integration secured?
**A:** Four-layer security:
1. **KEY_SECRET never reaches the browser** — it lives only in Lambda env vars
2. **Orders created server-side** — `POST /create-order` calls Razorpay API with Basic auth; the frontend only receives the order ID and public key
3. **Signature verified server-side** — `POST /verify-payment` computes `HMAC-SHA256(order_id|payment_id, KEY_SECRET)` and compares using `hmac.compare_digest` (constant-time, prevents timing attacks)
4. **Plan upgraded only on verified payment** — DynamoDB update happens only after successful HMAC verification. A tampered signature returns HTTP 400, no plan upgrade.

### Q: How is the S3 bucket secured?
**A:**
- All public access blocked (all 4 `BlockPublicAcls`/`BlockPublicPolicy` flags)
- CloudFront uses Origin Access Control (OAC) with SigV4 signing
- Bucket policy allows `s3:GetObject` only from our specific CloudFront distribution ARN
- No S3 website hosting — CloudFront handles routing and HTTPS

### Q: How does the one-click onboarding work securely?
**A:** The customer's CloudFormation stack creates an IAM role in their account with:
- A trust policy that only allows our Lambda role ARN (`arn:aws:iam::717279732828:role/costguard-lambda-role`) to assume it
- Read-only permissions: `ce:GetCostAndUsage`, `ce:GetCostForecast`, `s3:ListAllMyBuckets`, `ec2:DescribeInstances`, etc. — no write actions
- The role ARN is copied from CloudFormation output and pasted into our UI

Our Lambda never gets IAM permissions in the customer's account — it can only `AssumeRole` to get temporary credentials for the specific `CostGuardReadRole`.

---

## 4. Payments & Monetization

### Q: Walk me through the full payment flow.
**A:**
1. Free user clicks a locked model button (Sonnet/Opus) → upgrade modal appears
2. User clicks "Upgrade to Pro — ₹999/month"
3. Frontend calls `POST /create-order` (no amount in request — amount is hardcoded server-side)
4. Lambda creates a Razorpay order via `urllib.request` (stdlib, no pip install needed) using Basic auth with KEY_ID:KEY_SECRET
5. Returns `{orderId, amount: 99900, currency: 'INR', keyId}` to frontend
6. Frontend opens `new Razorpay({key: keyId, order_id: orderId, handler: ...})` checkout modal
7. User completes payment → Razorpay calls `handler({razorpay_payment_id, razorpay_order_id, razorpay_signature})`
8. Frontend sends all three to `POST /verify-payment`
9. Lambda: `HMAC-SHA256(order_id + "|" + payment_id, KEY_SECRET)` — must match `razorpay_signature`
10. Match → DynamoDB update: `plan = 'pro'`, `nextBillingDate = now + 30 days`, `paymentId = payment_id`
11. Returns `{plan: 'pro', nextBillingDate}`
12. Frontend updates badge (Free → Pro ✦), unlocks Sonnet model button, closes modal

### Q: Why did you choose Razorpay over Stripe?
**A:** India-first integration. Razorpay is the leading payment gateway in India with better UPI/net banking support, lower fees for INR transactions, and simpler onboarding for Indian businesses. The Standard Checkout SDK is also lighter than Stripe's Elements. For a global product I'd add Stripe alongside it.

### Q: How do you handle subscription renewals?
**A:** Currently simplified — we set `nextBillingDate = now + 30 days` in DynamoDB at payment time. A production system would use Razorpay webhooks: when a subscription renews, Razorpay sends a `payment.captured` webhook → Lambda verifies and extends the billing date. For now, the `nextBillingDate` field is stored and returned by `/subscription-status` for display.

---

## 5. AI & Bedrock

### Q: How does the savings recommendation feature work?
**A:**
1. `GET /recommendations` is called when the user navigates to the Savings page
2. Lambda fetches: 30-day cost breakdown by service (Cost Explorer) + live resource inventory
3. Builds a structured prompt: "You are an AWS cost optimization expert. Here is cost and resource data: [data]. Return EXACTLY 5 recommendations as a JSON array with fields: action, saving, effort (Easy/Medium/Hard), resource, reason."
4. Invokes Bedrock Claude — the model selected matches the user's plan
5. Parses the JSON response (regex fallback to extract array if model wraps in prose)
6. Returns 5 typed recommendation objects to the frontend
7. Frontend renders cards with effort color badges and "Implement with AI" button that pre-fills the chat input

The prompt uses structured output (JSON array) so the backend can validate and sanitize each field before returning it.

### Q: How does model gating work technically?
**A:** In `dashboard_api.py`, at module level:
```python
PLAN_MODELS = {
    'free':       'us.anthropic.claude-haiku-4-5-20251001-v1:0',
    'pro':        'us.anthropic.claude-sonnet-4-5-20250929-v1:0',
    'enterprise': 'us.anthropic.claude-opus-4-6-v1',
}
```
For every AI endpoint (`/chat`, `/recommendations`), before the Bedrock call:
1. Look up the customer's `plan` field in DynamoDB
2. Call `get_model_for_plan(plan)` → gets the model ID
3. Pass that model ID to `bedrock.invoke_model()`

The frontend model selector is purely UI — clicking it has zero effect on which model actually runs. A user can't get Sonnet by modifying the request; the model is always determined by the DynamoDB plan field.

### Q: Why use cross-region inference profiles (us. prefix) for Claude 4.x?
**A:** Claude 4 models don't support on-demand invocation with a direct model ID — you get a `ValidationException: on-demand throughput isn't supported`. Cross-region inference profiles (prefixed with `us.`) route requests across AWS regions for better availability and are required for Claude 4.x models. Claude 3.x still works with direct IDs in regions where they're enabled. We discovered this by probing all 32 model ID variants in the account.

---

## 6. Database Design

### Q: Explain your DynamoDB schema.
**A:** Four tables with different access patterns:

| Table | PK | SK | Purpose |
|---|---|---|---|
| `costguard-customers` | customerId | — | Customer registry with roleArn, plan, email |
| `costguard-costs` | customerId | date | Daily cost records + AI analysis |
| `costguard-alerts` | alertId | — | Spike alerts (ID format prevents duplicates) |
| `costguard-budgets` | customerId | service | Budget amounts per service |

The `costguard-costs` table uses a composite key: `customerId` (PK) + `date` (SK). This enables efficient range queries — "get all costs for customer X in the last 30 days" — and `ScanIndexForward=False` gives latest-first ordering without a GSI.

The `alertId` format is `{customerId}-spike-{date}`. DynamoDB's `put_item` is idempotent — if the alert already exists (same customer, same day), the write overwrites with the same data. No duplicate alerts.

### Q: Why PAY_PER_REQUEST instead of provisioned capacity?
**A:** The access pattern is extremely bursty. The CostAnalyzer runs once daily and writes a batch of records, then the API gets sporadic reads throughout the day. Provisioned capacity would mean paying for 95%+ idle capacity. PAY_PER_REQUEST eliminates that waste entirely. For a workload like this, it also removes capacity planning — if we suddenly get 1,000 customers instead of 10, DynamoDB scales automatically.

---

## 7. Frontend Architecture

### Q: Why vanilla JS instead of React?
**A:** Deliberate constraint for this project — I wanted to ship without a build pipeline, npm, node_modules, or a bundler. The entire frontend is one HTML file that can be opened directly or served from S3. ApexCharts is loaded via CDN. In hindsight, the JS grew to ~500 lines and component reuse suffers — for v2 I'd use React with Vite and proper component decomposition. The constraint did force disciplined state management (explicit global variables rather than implicit framework magic).

### Q: How does light/dark mode work?
**A:** CSS custom properties (`--bg-base`, `--text-primary`, etc.) defined at `:root` (dark) and overridden in `[data-theme="light"]`. Toggle sets `document.documentElement.setAttribute('data-theme', t)` and saves to `localStorage`. ApexCharts has a native `theme: { mode: 'dark'/'light' }` prop that we update via `chart.updateOptions()` when the toggle fires — no chart re-render needed.

### Q: How did you implement the one-click AWS onboarding?
**A:** CloudFormation Quick Create. I wrote a CF template (`costguard-role-template.json`) that creates the `CostGuardReadRole` with the correct trust policy and permissions, uploaded it to S3 (served via CloudFront), and generated a console deep-link:
```
https://console.aws.amazon.com/cloudformation/home#/stacks/quickcreate
  ?templateURL=https://d3e1nh6uj1h44y.cloudfront.net/costguard-role-template.json
  &stackName=CostGuardAccess
```
The customer clicks one button → AWS Console opens with everything pre-filled → they click "Create Stack" → IAM role exists in 30 seconds. They then type their 12-digit Account ID in the UI and the Role ARN is auto-constructed (`arn:aws:iam::{accountId}:role/CostGuardReadRole`). This is the same pattern Datadog, New Relic, and Spot.io use for AWS integration.

---

## 8. Scaling & Production Readiness

### Q: How does this scale?
**A:** Every component auto-scales:
- **Lambda**: Up to 1,000 concurrent executions by default, 10,000 with a quota increase
- **DynamoDB PAY_PER_REQUEST**: Handles any read/write rate without pre-provisioning
- **API Gateway**: 10,000 requests/second per region by default
- **CloudFront**: Global CDN, no scaling limit
- **Bedrock**: Subject to per-model token limits (can request quota increases)

The one scaling bottleneck is the CostAnalyzer Lambda — it processes customers sequentially. For 10,000+ customers, I'd switch to a fan-out pattern: EventBridge → Lambda sends all customer IDs to SQS → a second Lambda processes one customer per message in parallel.

### Q: What would you add for production?
**A:** Ten specific things:
1. **Cognito Authorizer on API Gateway** — currently auth is frontend-only; a crafted request can hit any endpoint
2. **WAF** on API Gateway and CloudFront — rate limiting, SQLi/XSS protection
3. **Razorpay webhooks** — proper subscription lifecycle management (renewals, failures, cancellations)
4. **SQS Dead Letter Queue** on CostAnalyzer — catch and retry failed customer analyses
5. **GitHub Actions CI/CD** — automated deploy on push to main
6. **Custom domain** with Route 53 + ACM (currently using CloudFront default domain)
7. **Lambda Layers** — share common code between the two Lambda functions
8. **API versioning** — `/v1/dashboard` instead of `/dashboard` for backward compatibility
9. **X-Ray tracing** — distributed tracing across API Gateway → Lambda → DynamoDB → Bedrock
10. **Per-customer API keys** — API Gateway usage plans for rate limiting per customer

### Q: What about observability?
**A:** Currently: CloudWatch Logs (all Lambda invocations), CloudWatch Alarms (Lambda error rate ≥ 1), CloudWatch metrics for DynamoDB, Lambda duration, and API Gateway 5xx rates. For production I'd add: X-Ray traces end-to-end, custom CloudWatch metrics (cost-per-customer, AI tokens consumed), a CloudWatch Dashboard, and PagerDuty/SNS integration for alarm notifications.

---

## 9. Behavioral

### Q: What was the hardest technical problem you solved?
**A:** The Bedrock model compatibility issue. I assumed model IDs from `list-foundation-models` were all directly invocable. After deploying, every AI call returned either `ResourceNotFoundException: end of life` (Claude 3 Opus — deprecated) or `ValidationException: on-demand throughput isn't supported` (Claude Sonnet 4 — requires cross-region inference profiles). I wrote a Python script that probed all 32 model ID variants (direct IDs + `us.` prefixed inference profile IDs) across 4 model families and found that only 6 were actually callable. The fix was switching to `us.` prefixed IDs for Claude 4.x models. The lesson: always probe the actual API, not just the documentation.

### Q: Tell me about a time you had to debug something unexpected.
**A:** The service breakdown donut chart was always empty in production. Local testing showed Cost Explorer returning data fine. The root cause: the dashboard called `/report?month=YYYY-MM` which queries Cost Explorer on the *platform* AWS account (717279732828). That account's own costs — Lambda, DynamoDB, API Gateway — total about $2/month and CE rounds them to $0.00 in grouped queries. The real customer cost data lives in their accounts, accessed via cross-account STS. I added a new `/service-breakdown` endpoint that uses the customer's assumed role to query CE — exactly like `/chat` does. Now the donut shows real customer data.

### Q: How would you monetize this beyond the current subscription?
**A:**
- **Per-account pricing** — charge per connected AWS account instead of flat ₹999
- **Usage-based AI** — charge per chat message or recommendation generated
- **Enterprise tier** — custom model fine-tuning, SSO, audit logs, SLA
- **Marketplace listing** — publish on AWS Marketplace for simplified billing
- **White-label** — sell to MSPs who want a branded cost tool for their customers
- **Forecasting alerts** — premium feature: alert when projected spend will exceed budget before month-end

### Q: If you had to rebuild from scratch, what would you do differently?
**A:**
1. **CDK instead of raw CloudFormation** — typed constructs, better reuse, built-in L2 defaults
2. **React + Vite frontend** — component reuse, proper state management, easier testing
3. **API Gateway HTTP API instead of REST API** — 70% cheaper, simpler CORS, JWT authorizer built-in
4. **Lambda Powertools** — structured logging, tracing, parameter store integration from day one
5. **Event-driven architecture** — EventBridge for all internal events (new customer registered, payment succeeded) instead of direct Lambda calls
6. **Proper CI/CD from day one** — GitHub Actions + environments (dev/staging/prod) before writing any code
7. **Test-driven** — pytest for Lambda handlers with mocked boto3, Playwright for frontend E2E
