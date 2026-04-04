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

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /dashboard | Cost data with AI analysis |
| GET | /alerts | Cost spike alerts |
| GET | /cost-summary | Aggregated spending summary |
| POST | /onboard | Register new customer account |
| GET | /customers | List connected accounts |
| POST | /chat | AI chatbot — ask about costs & resources |

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
│   └── index.html              # Single-page dashboard app (mobile responsive)
├── lambda/
│   ├── cost_analyzer.py        # CostAnalyzer Lambda (readable version)
│   └── dashboard_api.py        # Dashboard API + Chat Lambda (readable version)
├── docs/
│   ├── ARCHITECTURE.md         # Architecture deep dive
│   └── INTERVIEW_QA.md         # Interview questions & answers
└── README.md
```

## License

MIT
