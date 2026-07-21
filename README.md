# 🛡️ CostGuard AI

**Enterprise-grade, AI-powered AWS Cost Intelligence Platform** — Monitors costs across multiple AWS accounts, detects anomalies, generates AI savings recommendations, forecasts spend, and enables self-service subscription billing. Built to compete with Cloudability, CloudHealth, and Spot.io.

🔗 **Live Demo:** https://d3e1nh6uj1h44y.cloudfront.net

---

## What It Does

| Capability | Details |
|---|---|
| **Real-time Cost Monitoring** | Daily cost analysis per AWS account via Cost Explorer |
| **AI-Powered Chat** | Ask questions about your costs using Claude (Haiku 4.5 / Sonnet 4.6 / Opus 4.6) |
| **Security Scanning** | Live scan of AWS resources for misconfigurations (public S3, open security groups, unencrypted EBS/RDS, public RDS, IAM users without MFA) — each finding shows severity, the reason, and remediation steps, with one-click AI-generated fixes (CLI + Terraform) |
| **Anomaly Detection** | Spike detection: flags any day where cost exceeds 7-day avg by >20% |
| **Cost Forecasting** | 30-day spend projection with ±15% confidence band (client-side linear regression) |
| **Savings Recommendations** | AI generates 5 actionable savings opportunities from live resource inventory |
| **Budget Tracking** | Set monthly budgets per service, track actual vs budget with live progress bars |
| **Service Drill-down** | Click any service in reports → see resource-level cost breakdown |
| **Subscription Billing** | Razorpay Standard Checkout (₹999/mo Pro), server-side HMAC verification |
| **Model Gating** | Plan-based AI model access enforced server-side |
| **Verified Auth** | Cognito JWTs are cryptographically verified (RS256 against Cognito JWKS: signature, issuer, audience, expiry) inside the Lambda — not just base64-decoded — closing token-forgery/privilege-escalation. Security routes require authentication. |
| **Multi-tenant SaaS** | Multiple AWS accounts via cross-account IAM roles |
| **One-Click Onboarding** | CloudFormation quick-create link creates the IAM role automatically |
| **Light/Dark Mode** | Full theme toggle persisted to localStorage |

---

## Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                   AWS Account                        │
                    │                                                       │
  User Browser ────►│  CloudFront ──► S3 (index.html)                    │
                    │       │                                               │
                    │       ▼                                               │
                    │  API Gateway (11 routes)                             │
                    │       │                                               │
                    │       ▼                                               │
                    │  Lambda: dashboard_api.py  ──► DynamoDB (4 tables)  │
                    │       │                    ──► Bedrock (Claude AI)   │
                    │       │                    ──► STS (cross-account)   │
                    │       │                                               │
                    │  Cognito (Auth)                                       │
                    │                                                       │
                    │  EventBridge (6 AM UTC daily)                        │
                    │       │                                               │
                    │       ▼                                               │
                    │  Lambda: cost_analyzer.py  ──► Cost Explorer        │
                    │                            ──► Bedrock               │
                    │                            ──► SES (email alerts)   │
                    └─────────────────────────────────────────────────────┘
                                         │
                    Customer AWS Account  │ STS AssumeRole
                    ┌────────────────────▼────────────────┐
                    │  CostGuardReadRole (read-only)       │
                    │  Cost Explorer, EC2, S3, Lambda...   │
                    └──────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Frontend | Vanilla JS SPA, ApexCharts 3.x | Zero build step, CDN charts |
| Hosting | S3 + CloudFront (OAC) | Global CDN, private bucket, HTTPS |
| Auth | Amazon Cognito | Managed JWT, email verification |
| API | API Gateway + Lambda (Python 3.11) | Serverless, per-request billing |
| AI | Amazon Bedrock (Claude Haiku 4.5 / Sonnet 4.6 / Opus 4.6) | Multi-model with plan gating |
| Database | DynamoDB × 4 (PAY_PER_REQUEST) | Zero idle cost, single-ms latency |
| Scheduling | EventBridge (daily cron) | Native AWS scheduling |
| Alerts | SES | Managed transactional email |
| Payments | Razorpay Standard Web Checkout | HMAC-SHA256 verified, server-side only |
| IaC | CloudFormation (single template) | Entire backend in one deploy |

---

## Subscription Tiers

| Plan | Price | Claude Model | Features |
|---|---|---|---|
| **Free** | ₹0/mo | Claude Haiku 4.5 | Dashboard, alerts, basic chat |
| **Pro** | ₹999/mo | Claude Sonnet 4.6 | + Savings AI, advanced analysis |
| **Enterprise** | Custom | Claude Opus 4.6 | + Full access, priority support |

**Model selection is enforced server-side** — the Lambda reads the `plan` field from DynamoDB and picks the model. The frontend selector is UI-only; bypassing it changes nothing.

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| GET | `/dashboard` | JWT | Daily cost history + AI analysis |
| GET | `/alerts` | JWT | Cost spike alerts |
| GET | `/cost-summary` | JWT | Aggregated spend totals |
| POST | `/chat` | JWT | AI chatbot with live AWS context |
| GET | `/report` | JWT | Monthly cost + service breakdown |
| GET | `/service-breakdown` | JWT | 30-day service costs (donut chart) |
| GET | `/service-detail` | JWT | Resource-level cost drill-down |
| GET | `/recommendations` | JWT | AI savings recommendations |
| GET | `/security-scan` | JWT | Scans account for security misconfigurations (severity + reason + remediation) |
| POST | `/security-remediate` | JWT | AI-generated step-by-step fix for a finding (CLI + Terraform + verification) |
| GET | `/budgets` | JWT | Budgets + actuals + % used |
| POST | `/budgets` | JWT | Create/update a budget |
| GET | `/subscription-status` | JWT | Current plan + billing date |
| POST | `/create-order` | JWT | Create Razorpay order (server-side) |
| POST | `/verify-payment` | JWT | HMAC verify + upgrade plan in DB |
| POST | `/onboard` | JWT | Register new AWS account |
| GET | `/customers` | JWT (admin) | List all connected accounts |
| POST | `/customers/delete` | JWT (admin) | Remove customer + data |

---

## Payment Flow

```
Free user clicks locked model
         ↓
Upgrade modal (₹999/month)
         ↓
POST /create-order → Razorpay API → returns order_id
         ↓
Razorpay checkout.js modal opens
         ↓
User pays → razorpay_payment_id + razorpay_order_id + razorpay_signature
         ↓
POST /verify-payment
  HMAC-SHA256(order_id|payment_id, KEY_SECRET) == razorpay_signature ?
         ↓ yes
DynamoDB update: plan = 'pro'
         ↓
Frontend badge: Free → Pro ✦, Sonnet unlocks
```

**KEY_SECRET never touches the frontend** — returned only via `/create-order` response as `keyId` (public key only).

---

## Project Structure

```
CostGuardAI/
├── costguard-ai.json              # CloudFormation — entire backend (S3-based Lambda code, all routes, 4 tables)
├── costguard-role-template.json   # CF template for customer IAM role (one-click onboard)
├── frontend/
│   └── index.html                 # SPA: dashboard, charts, chat, billing, forecast, budgets
├── lambda/
│   ├── dashboard_api.py           # Main API Lambda (payments, AI chat, savings, security scanning, model gating)
│   └── cost_analyzer.py           # Daily cron Lambda (CE → Bedrock → DynamoDB → SES)
├── .env                           # Razorpay credentials (git-ignored)
├── docs/
│   └── ARCHITECTURE.md            # Deep-dive architecture decisions
│   # (docs/INTERVIEW_QA.md exists locally but is git-ignored — not published)
└── README.md
```

---

## Environment Variables (Lambda)

| Variable | Description |
|---|---|
| `CUSTOMERS_TABLE` | DynamoDB customers table |
| `ALERTS_TABLE` | DynamoDB alerts table |
| `COSTS_TABLE` | DynamoDB daily costs table |
| `BUDGETS_TABLE` | DynamoDB budgets table |
| `BEDROCK_MODEL_ID` | Fallback model ID (overridden by plan gating) |
| `ADMIN_EMAIL` | Admin email — gets enterprise plan + all features |
| `RAZORPAY_KEY_ID` | Razorpay public key (returned to frontend) |
| `RAZORPAY_KEY_SECRET` | Razorpay secret — **server-side only, never in frontend** |

---

## Deploy

The CloudFormation template (`costguard-ai.json`) is the single source of truth for the **entire** backend — all DynamoDB tables (4), every API Gateway route (including `/security-scan` and `/security-remediate`), both Lambdas, IAM, Cognito, CloudFront/S3, and the daily EventBridge job. Lambda code is loaded from S3 (not inline), so package the functions first.

```bash
# 1. Package + upload Lambda code to your artifact bucket
cd lambda && zip dashboard_api.zip dashboard_api.py && zip cost_analyzer.zip cost_analyzer.py && cd ..
aws s3 cp lambda/dashboard_api.zip s3://YOUR-CODE-BUCKET/lambda/dashboard_api.zip
aws s3 cp lambda/cost_analyzer.zip  s3://YOUR-CODE-BUCKET/lambda/cost_analyzer.zip

# 2. Deploy the full stack (creates/updates everything)
aws cloudformation deploy \
  --template-file costguard-ai.json \
  --stack-name costguard-ai \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      AlertEmailAddress=your@email.com \
      LambdaCodeBucket=YOUR-CODE-BUCKET

# 3. Push a code-only update later (no stack change needed)
aws lambda update-function-code --function-name costguard-dashboard-api \
  --s3-bucket YOUR-CODE-BUCKET --s3-key lambda/dashboard_api.zip

# 4. Upload frontend + invalidate CloudFront
aws s3 cp frontend/index.html s3://YOUR-WEB-BUCKET/index.html \
  --content-type text/html --cache-control no-cache
aws cloudfront create-invalidation --distribution-id YOUR-DIST-ID --paths "/*"
```

**Parameters:** `AlertEmailAddress` (SES alerts), `ProjectName` (resource name prefix, default `costguard`), `BedrockModelId` (cost-analyzer model, default Haiku 4.5), `LambdaCodeBucket` (**required** — S3 bucket with the zips), `DashboardApiS3Key` / `CostAnalyzerS3Key` (default `lambda/*.zip`).

> **Adopting onto an already-running stack:** the live production stack was originally created with fewer routes/tables and later extended out-of-band, so several resources now exist outside CloudFormation's record. A plain in-place `deploy` onto it would collide on those names. To make CFN authoritative again, either (a) stand up a **fresh** stack from this template and cut over, or (b) use `aws cloudformation` **resource import** to adopt the out-of-band resources first. A clean first-time deploy from this template needs neither.

---

## License

MIT — built by Shaikh Feraz
