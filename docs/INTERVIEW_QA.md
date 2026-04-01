# CostGuard AI — Interview Questions & Answers

## Project Overview Questions

### Q: Tell me about this project. What does it do?
**A:** CostGuard AI is a multi-tenant serverless SaaS platform I built on AWS that monitors AWS costs across multiple customer accounts. It runs daily, fetches billing data from Cost Explorer, compares yesterday's cost with the 7-day average to detect spikes, then uses Amazon Bedrock's Claude model to generate AI-powered explanations and optimization recommendations. If a cost spike exceeds 20%, it automatically sends an email alert via SES. Customers can self-onboard by creating a cross-account IAM role and registering through the dashboard UI.

### Q: Why did you build this?
**A:** Many organizations struggle with unexpected AWS cost increases. By the time they see the monthly bill, it's too late. I wanted to build a proactive solution that catches spikes daily, explains them using AI, and notifies the right people immediately — all as a self-service SaaS that multiple customers can use.

### Q: What's the tech stack?
**A:** Entirely serverless on AWS:
- Frontend: S3 + CloudFront (single-page app)
- Auth: Cognito (email-based signup/login)
- API: API Gateway + Lambda (Python 3.11)
- AI: Amazon Bedrock (Claude Sonnet)
- Data: DynamoDB (3 tables, PAY_PER_REQUEST)
- Scheduling: EventBridge (daily cron)
- Alerts: SES
- Monitoring: CloudWatch Alarms
- IaC: CloudFormation (single template, ~28 resources)

---

## Architecture Questions

### Q: Walk me through the data flow when a cost spike is detected.
**A:**
1. EventBridge triggers the CostAnalyzer Lambda at 6 AM UTC daily
2. Lambda scans the Customers DynamoDB table to get all registered accounts
3. For each customer, it assumes their cross-account IAM role via STS
4. Calls Cost Explorer API to get yesterday's cost and the past 7 days
5. Calculates the percentage change vs the 7-day average
6. Sends the cost data to Bedrock Claude for AI analysis
7. Stores the cost record + AI analysis in the DailyCosts DynamoDB table
8. If the change exceeds 20%, it writes an alert to the CostAlerts table
9. Sends an email notification via SES to the customer's registered email

### Q: How does multi-tenancy work?
**A:** Each customer registers with their email and a cross-account IAM role ARN. The role ARN points to a `CostGuardReadRole` in their AWS account that trusts our Lambda execution role. During the daily analysis, the Lambda iterates through all customers, assumes each role via STS AssumeRole, and fetches their Cost Explorer data independently. Data is partitioned in DynamoDB by `customerId` as the partition key, so each customer's data is isolated.

### Q: Why did you choose DynamoDB over RDS?
**A:**
- **Serverless fit**: DynamoDB with PAY_PER_REQUEST scales to zero — no idle costs
- **Access patterns are simple**: Key-value lookups and queries by customerId + date
- **No joins needed**: Each table is self-contained
- **Performance**: Single-digit millisecond latency at any scale
- **Operational overhead**: Zero — no patching, backups are automatic with PITR

### Q: Why CloudFront + S3 instead of hosting the frontend on EC2 or ECS?
**A:**
- Static SPA doesn't need a server — S3 is the cheapest option
- CloudFront provides global CDN, HTTPS, and caching
- Using OAC (Origin Access Control) keeps the S3 bucket fully private
- Zero server management, auto-scales to any traffic level
- Cost is essentially free for low-to-moderate traffic

### Q: How do you handle CORS?
**A:** Two layers:
1. **API Gateway**: Each resource has an OPTIONS method with MOCK integration that returns CORS headers (Allow-Origin: *, Allow-Headers, Allow-Methods)
2. **Lambda responses**: Every response from the Dashboard API Lambda includes CORS headers in the response object

This is necessary because the frontend (CloudFront domain) makes cross-origin requests to the API Gateway domain.

---

## Security Questions

### Q: How did you implement least privilege IAM?
**A:** The Lambda execution role has 6 policy statements, each scoped to the minimum:
- **CloudWatch Logs**: Only `/aws/lambda/costguard-*` log groups
- **Cost Explorer**: `Resource: *` (CE doesn't support resource-level permissions, but only read actions)
- **Bedrock**: Scoped to the specific model ARN only
- **DynamoDB**: Only the 3 CostGuard table ARNs, no wildcard
- **SES**: Only the specific verified email identity ARN
- **STS**: Only `arn:aws:iam::*:role/CostGuardReadRole` — can only assume roles with that exact name

### Q: How is the S3 bucket secured?
**A:**
- All public access is blocked (BlockPublicAcls, BlockPublicPolicy, IgnorePublicAcls, RestrictPublicBuckets all set to true)
- CloudFront uses Origin Access Control (OAC) with SigV4 signing
- Bucket policy only allows `s3:GetObject` from the specific CloudFront distribution ARN
- No website hosting configuration on the bucket — CloudFront handles everything

### Q: How do you handle cross-account access securely?
**A:** Using the AWS STS AssumeRole pattern:
- Customer creates a role in their account with a trust policy that only allows our specific Lambda role ARN
- The role only has `ce:GetCostAndUsage` and `ce:GetCostForecast` — read-only billing access
- Our Lambda assumes the role, gets temporary credentials, and creates a scoped CE client
- Credentials are temporary (default 1 hour) and never stored

### Q: What about authentication?
**A:** Amazon Cognito handles user authentication:
- Email-based signup with verification code
- Password policy: min 8 chars, uppercase, lowercase, numbers
- USER_PASSWORD_AUTH flow returns JWT tokens (IdToken, AccessToken, RefreshToken)
- Frontend stores tokens in localStorage and sends as Bearer token
- Note: For production, I'd add a Cognito Authorizer to API Gateway to enforce auth server-side

---

## Serverless & Scaling Questions

### Q: How does this scale?
**A:** Every component auto-scales:
- **Lambda**: Concurrent executions scale automatically (up to 1000 default)
- **DynamoDB**: PAY_PER_REQUEST mode scales read/write capacity on demand
- **API Gateway**: Handles up to 10,000 requests/second by default
- **CloudFront**: Global CDN, handles any traffic level
- **EventBridge**: Managed service, no scaling concerns

### Q: What are the Lambda configurations and why?
**A:**
- **CostAnalyzer**: 512MB RAM, 5-minute timeout — needs more memory for Bedrock API calls and processing multiple customers. Longer timeout because it loops through all customers sequentially.
- **Dashboard API**: 256MB RAM, 30-second timeout — simple DynamoDB reads, doesn't need much resources. 30 seconds is generous for API responses.

### Q: What happens if the CostAnalyzer Lambda fails?
**A:**
- CloudWatch Alarm triggers on any Lambda error (threshold: ≥1 error in 5 minutes)
- Each customer is processed in a try/except block, so one customer's failure doesn't affect others
- The function logs errors to CloudWatch for debugging
- EventBridge will retry on the next daily run
- For production, I'd add a Dead Letter Queue (SQS) for failed events

---

## Database Questions

### Q: Explain your DynamoDB table design.
**A:**
- **Customers**: Simple key-value store. `customerId` as partition key. Stores email, roleArn, plan, createdAt. Low volume, mostly scans for the daily job.
- **DailyCosts**: `customerId` (PK) + `date` (SK). This allows efficient queries like "get all costs for customer X" or "get costs for customer X between dates". ScanIndexForward=False gives latest-first ordering.
- **CostAlerts**: `alertId` (PK) with format `{customerId}-spike-{date}`. This prevents duplicate alerts for the same customer on the same day (idempotent writes).

### Q: Why PAY_PER_REQUEST instead of provisioned capacity?
**A:** The access pattern is bursty — the CostAnalyzer runs once daily and writes a batch, then the API gets sporadic reads. Provisioned capacity would mean paying for idle capacity 23+ hours/day. PAY_PER_REQUEST is more cost-effective for this workload and eliminates capacity planning.

### Q: What about data protection?
**A:**
- **Encryption**: SSE enabled on all tables (AWS-managed keys)
- **Backups**: Point-in-Time Recovery (PITR) enabled on all tables
- **Deletion protection**: DeletionPolicy: Retain on all tables — stack deletion won't destroy data

---

## AI/Bedrock Questions

### Q: How do you use Amazon Bedrock?
**A:** I use the Bedrock Runtime API to invoke Claude 3 Sonnet. The Lambda sends a structured prompt with the customer's cost data (yesterday's cost, 7-day average, percentage change) and asks for brief insights and recommendations. The response is stored alongside the cost data in DynamoDB so the dashboard can display it.

### Q: Why Claude Sonnet specifically?
**A:** It's a good balance of quality and cost. Sonnet is cheaper than Opus but still produces high-quality analysis. For cost monitoring, we don't need the most powerful model — we need concise, accurate insights. I also limit max_tokens to 200 to keep responses focused and costs low.

### Q: How much does the AI cost?
**A:** Roughly $0.003 per input 1K tokens and $0.015 per output 1K tokens for Claude 3 Sonnet. Each analysis uses ~100 input tokens and ~150 output tokens, so about $0.003 per customer per day. For 100 customers, that's ~$9/month.

---

## DevOps & IaC Questions

### Q: Why CloudFormation instead of Terraform or CDK?
**A:** CloudFormation is native to AWS — no external state management, no additional tools to install. For a pure-AWS project, it's the simplest choice. The entire infrastructure is in a single JSON template that can be deployed with one command. For a larger project, I'd consider CDK for better abstraction.

### Q: How do you deploy updates?
**A:**
```bash
# Backend (CloudFormation)
aws cloudformation deploy --template-file costguard-ai.json \
  --stack-name costguard-ai --capabilities CAPABILITY_NAMED_IAM

# Frontend (S3 + CloudFront invalidation)
aws s3 cp frontend/index.html s3://$BUCKET/index.html
aws cloudfront create-invalidation --distribution-id $DIST_ID --paths "/*"

# Force API Gateway redeployment (if needed)
aws apigateway create-deployment --rest-api-id $API_ID --stage-name prod
```

### Q: What would you improve for production?
**A:**
1. **Add Cognito Authorizer** to API Gateway (currently auth is frontend-only)
2. **Add WAF** to API Gateway and CloudFront
3. **Add DLQ** (SQS) for failed Lambda invocations
4. **Add X-Ray tracing** for distributed tracing
5. **Use CI/CD pipeline** (CodePipeline or GitHub Actions)
6. **Add custom domain** with Route 53 + ACM certificate
7. **Add rate limiting** on API Gateway
8. **Separate IAM roles** for each Lambda (currently shared)
9. **Add SNS topic** for CloudWatch alarm notifications
10. **Move Lambda code** out of inline ZipFile to S3 packages

---

## Behavioral / Design Decision Questions

### Q: What was the hardest part of building this?
**A:** Getting CORS right between CloudFront and API Gateway. The browser sends a preflight OPTIONS request before the actual GET/POST, and API Gateway needs to respond with the correct CORS headers. I had to add MOCK integration OPTIONS methods on every resource. The Lambda also needs to return CORS headers in every response.

### Q: How would you handle 10,000 customers?
**A:**
- The current sequential loop in CostAnalyzer would be too slow
- I'd switch to a fan-out pattern: EventBridge → Step Functions → parallel Lambda invocations (one per customer)
- Or use SQS: EventBridge → Lambda (enqueue all customers) → SQS → Lambda (process one customer per message)
- DynamoDB would handle the scale fine with PAY_PER_REQUEST

### Q: How would you add cost forecasting?
**A:** AWS Cost Explorer already has a `GetCostForecast` API (which I've already granted permission for). I'd add a `/forecast` endpoint that calls this API and combines it with Bedrock analysis to provide AI-powered spending predictions.

### Q: If you had to rebuild this, what would you do differently?
**A:**
- Use AWS SAM or CDK instead of raw CloudFormation — better developer experience
- Use Lambda Layers for shared code between the two functions
- Implement proper API versioning (/v1/dashboard)
- Add unit tests and integration tests from the start
- Use a proper frontend framework (React/Vue) instead of vanilla JS
- Implement WebSocket for real-time dashboard updates
