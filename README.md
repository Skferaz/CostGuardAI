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
# Get bucket name from stack outputs
BUCKET=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`S3BucketName`].OutputValue' --output text)

aws s3 cp frontend/index.html s3://$BUCKET/index.html --content-type "text/html"
```

## Onboarding a Customer

1. Customer creates an IAM role in their account:
```bash
aws iam create-role --role-name CostGuardReadRole \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::<YOUR_ACCOUNT_ID>:role/costguard-lambda-role"},"Action":"sts:AssumeRole"}]}'

aws iam put-role-policy --role-name CostGuardReadRole \
  --policy-name CostExplorerRead \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["ce:GetCostAndUsage","ce:GetCostForecast"],"Resource":"*"}]}'
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

## Project Structure

```
├── costguard-ai.json      # CloudFormation template (entire backend)
├── frontend/
│   └── index.html          # Single-page dashboard app
└── README.md
```

## License

MIT
