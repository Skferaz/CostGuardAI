# 🛡️ CostGuard AI

**AI-powered AWS cost intelligence platform** — Detects cost spikes, generates AI explanations using Amazon Bedrock, and sends automated alerts.

## Architecture

```
CloudFront → S3 (Dashboard)
API Gateway → Lambda (Dashboard API)
EventBridge → Lambda (Cost Analyzer) → Cost Explorer + Bedrock + SES
Cognito (Auth) → DynamoDB (Data)
```

## Features

- **Multi-tenant SaaS** — Monitor costs across multiple AWS accounts
- **AI Analysis** — Amazon Bedrock Claude generates cost insights and recommendations
- **Spike Detection** — Compares daily cost vs 7-day average, alerts on >20% increase
- **Email Alerts** — Automated SES notifications on cost spikes
- **Self-Service Onboarding** — Customers connect their AWS account via UI
- **Serverless** — Fully serverless, pay-per-use architecture
- **Razorpay Payments** — Subscription billing at ₹999/month with Standard Web Checkout
- **Model Gating** — AI model access controlled by subscription tier (Haiku / Sonnet / Opus)

## Stack

| Component | Service |
|-----------|---------|
| Frontend | S3 + CloudFront |
| Auth | Cognito |
| API | API Gateway + Lambda (Python 3.11) |
| AI | Amazon Bedrock (Claude Sonnet) |
| Data | DynamoDB (3 tables) |
| Scheduling | EventBridge (daily cron) |
| Alerts | SES |
| Monitoring | CloudWatch Alarms |
| IaC | CloudFormation |
| Payments | Razorpay Standard Web Checkout |

## Deploy

### Option 1: One-Click Setup (Recommended)

```bash
git clone https://github.com/Skferaz/CostGuardAI.git
cd CostGuardAI
./setup.sh
```

The script will:
1. Deploy all AWS infrastructure (CloudFormation)
2. Package and deploy Lambda code
3. Configure the frontend with your account's URLs
4. Set up monitoring (SNS alarms, X-Ray, DLQ)
5. Add health check endpoint
6. Enable Cognito authentication on all APIs
7. Verify your email for SES alerts

Takes ~5 minutes. You just need to enter your email.

### Option 2: Manual Deploy

```bash
aws cloudformation deploy \
  --template-file costguard-ai.json \
  --stack-name costguard-ai \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    BedrockModelId=anthropic.claude-3-sonnet-20240229-v1:0 \
    AlertEmailAddress=your@email.com
```

Then upload the frontend:

```bash
BUCKET=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' --output text)

aws s3 cp frontend/index.html s3://$BUCKET/index.html --content-type "text/html"
```

See `setup.sh` for the full list of post-deploy steps (Lambda code, auth, monitoring).

### Moving to a Different AWS Account

Just clone the repo and run `./setup.sh` in the new account — it handles everything automatically.

## Onboarding a Customer

1. Customer creates an IAM role in their account:
```bash
aws iam create-role --role-name CostGuardReadRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::<YOUR_ACCOUNT_ID>:role/costguard-lambda-role"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name CostGuardReadRole \
  --policy-name CostGuardReadAccess \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ce:GetCostAndUsage","ce:GetCostForecast","s3:ListAllMyBuckets","ec2:DescribeInstances","ec2:DescribeVolumes","lambda:ListFunctions","rds:DescribeDBInstances","dynamodb:ListTables","cloudfront:ListDistributions"],"Resource":"*"}]}'
```

2. Customer pastes their Role ARN in the **Add Account** page on the dashboard

## Subscription Tiers & Model Gating

| Plan | Price | Claude Model | Capability |
|------|-------|-------------|------------|
| **Free** | ₹0 | Claude 3 Haiku | Basic cost Q&A |
| **Pro** | ₹999/month | Claude 3 Sonnet | Advanced analysis |
| **Enterprise** | Custom | Claude 3 Opus | Maximum intelligence |

Plan is enforced **server-side** — the backend always selects the model based on the user's DynamoDB `plan` field. The frontend model selector is UI-only.

### Razorpay Payment Flow

1. Free user clicks a locked model (Sonnet/Opus) → upgrade modal appears
2. User clicks **Upgrade to Pro — ₹999/month**
3. Backend `POST /create-order` creates a Razorpay order (server-side, credentials never reach browser)
4. Razorpay Standard Checkout modal opens
5. On payment success, `razorpay_payment_id`, `razorpay_order_id`, `razorpay_signature` sent to `POST /verify-payment`
6. Backend verifies HMAC-SHA256 signature, upgrades `plan` to `pro` in DynamoDB
7. Frontend updates plan badge to **Pro**, Sonnet unlocks

### Testing Payments (Razorpay Test Mode)

Use Razorpay test card:
```
Card number : 4111 1111 1111 1111
Expiry      : Any future date
CVV         : Any 3 digits
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /health | None | Health check |
| GET | /dashboard | JWT | Cost data with AI analysis |
| GET | /alerts | JWT | Cost spike alerts |
| GET | /cost-summary | JWT | Aggregated spending summary |
| POST | /onboard | JWT | Register new customer account |
| GET | /customers | JWT (admin) | List connected accounts |
| POST | /customers/delete | JWT (admin) | Remove a customer |
| POST | /chat | JWT | AI chatbot with live AWS context |
| GET | /report | JWT | Monthly cost report |
| GET | /subscription-status | JWT | Current plan + next billing date |
| POST | /create-order | JWT | Create Razorpay payment order |
| POST | /verify-payment | JWT | Verify signature + upgrade plan |

## AI Chatbot

The built-in AI assistant has live access to your AWS account. Ask it:

- "What S3 buckets exist in my account?"
- "Which service is costing the most?"
- "How many Lambda functions are running?"
- "How can I reduce my AWS bill?"
- "What EC2 instances are running?"

It fetches real-time data from Cost Explorer + resource APIs (S3, EC2, Lambda, DynamoDB, RDS, CloudFront) and sends it to Bedrock Claude for intelligent answers.

## Project Structure

```
├── costguard-ai.json           # CloudFormation template (entire backend)
├── frontend/
│   └── index.html              # Single-page dashboard (Razorpay checkout + model selector)
├── lambda/
│   ├── cost_analyzer.py        # CostAnalyzer Lambda — daily cost analysis
│   └── dashboard_api.py        # Dashboard API: chat, payments, model gating
├── .env                        # Razorpay credentials (git-ignored)
├── docs/
│   ├── ARCHITECTURE.md         # Architecture deep dive
│   └── INTERVIEW_QA.md         # Interview questions & answers
└── README.md
```

## Environment Variables (Lambda)

| Variable | Description |
|----------|-------------|
| `CUSTOMERS_TABLE` | DynamoDB customers table name |
| `ALERTS_TABLE` | DynamoDB alerts table name |
| `COSTS_TABLE` | DynamoDB costs table name |
| `BEDROCK_MODEL_ID` | Fallback Bedrock model (overridden by plan gating) |
| `ADMIN_EMAIL` | Admin user email for elevated access |
| `RAZORPAY_KEY_ID` | Razorpay API key ID (test: `rzp_test_*`) |
| `RAZORPAY_KEY_SECRET` | Razorpay secret — **backend only, never in frontend** |

## License

MIT
