# 🛡️ CostGuard AI

**Enterprise-grade, AI-powered AWS Cost Intelligence Platform** — Monitors costs across multiple AWS accounts, detects anomalies, generates AI savings recommendations, forecasts spend, and enables self-service subscription billing. Built to compete with Cloudability, CloudHealth, and Spot.io.

🔗 **Live Demo:** https://d3e1nh6uj1h44y.cloudfront.net

---

## What It Does

| Capability | Details |
|---|---|
| **Real-time Cost Monitoring** | Daily cost analysis per AWS account via Cost Explorer |
| **AI-Powered Chat** | Ask questions about your costs using Claude (Haiku 4.5 / Sonnet 4.5 / Opus 4.6) |
| **Anomaly Detection** | Spike detection: flags any day where cost exceeds 7-day avg by >20% |
| **Cost Forecasting** | 30-day spend projection with ±15% confidence band (client-side linear regression) |
| **Savings Recommendations** | AI generates 5 actionable savings opportunities from live resource inventory |
| **Budget Tracking** | Set monthly budgets per service, track actual vs budget with live progress bars |
| **Service Drill-down** | Click any service in reports → see resource-level cost breakdown |
| **Subscription Billing** | Razorpay Standard Checkout (₹999/mo Pro), server-side HMAC verification |
| **Model Gating** | Plan-based AI model access enforced server-side |
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
| AI | Amazon Bedrock (Claude Haiku 4.5 / Sonnet 4.5 / Opus 4.6) | Multi-model with plan gating |
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
| **Pro** | ₹999/mo | Claude Sonnet 4.5 | + Savings AI, advanced analysis |
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
├── costguard-ai.json              # CloudFormation — entire backend (28+ resources)
├── costguard-role-template.json   # CF template for customer IAM role (one-click onboard)
├── frontend/
│   └── index.html                 # SPA: dashboard, charts, chat, billing, forecast, budgets
├── lambda/
│   ├── dashboard_api.py           # Main API Lambda (17 routes, payments, AI, model gating)
│   └── cost_analyzer.py           # Daily cron Lambda (CE → Bedrock → DynamoDB → SES)
├── .env                           # Razorpay credentials (git-ignored)
├── docs/
│   ├── ARCHITECTURE.md            # Deep-dive architecture decisions
│   └── INTERVIEW_QA.md            # Interview prep Q&A
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

```bash
# 1. Deploy infrastructure
aws cloudformation deploy \
  --template-file costguard-ai.json \
  --stack-name costguard-ai \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides AlertEmailAddress=your@email.com

# 2. Deploy Lambda code
zip lambda.zip lambda/dashboard_api.py
aws lambda update-function-code \
  --function-name costguard-dashboard-api \
  --zip-file fileb://lambda.zip

# 3. Upload frontend
aws s3 cp frontend/index.html s3://YOUR-BUCKET/index.html \
  --content-type text/html --cache-control no-cache

# 4. Invalidate CloudFront
aws cloudfront create-invalidation \
  --distribution-id YOUR-DIST-ID --paths "/*"
```

---

## License

MIT — built by Feraz Shaikh
