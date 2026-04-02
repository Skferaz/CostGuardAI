#!/bin/bash
# ============================================================
# CostGuard AI - One-Click Setup Script
# Run this in any AWS account to deploy the entire platform
# ============================================================

set -e

echo "🛡️  CostGuard AI - Setup Starting..."
echo ""

# Check AWS credentials
echo "Checking AWS credentials..."
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)
if [ -z "$ACCOUNT_ID" ]; then
    echo "❌ AWS credentials not configured. Run 'aws configure' first."
    exit 1
fi
REGION=$(aws configure get region 2>/dev/null || echo "us-east-1")
echo "✅ Account: $ACCOUNT_ID | Region: $REGION"
echo ""

# Get user inputs
read -p "📧 Enter your email for alerts (e.g. you@gmail.com): " ALERT_EMAIL
if [ -z "$ALERT_EMAIL" ]; then echo "❌ Email required"; exit 1; fi

BEDROCK_MODEL="anthropic.claude-3-sonnet-20240229-v1:0"
echo ""

# Step 1: Deploy CloudFormation
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1/7: Deploying infrastructure..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
aws cloudformation deploy \
    --template-file costguard-ai.json \
    --stack-name costguard-ai \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        BedrockModelId=$BEDROCK_MODEL \
        AlertEmailAddress=$ALERT_EMAIL \
    --no-fail-on-empty-changeset
echo "✅ Infrastructure deployed"
echo ""

# Get stack outputs
API_ID=$(aws apigateway get-rest-apis --query 'items[?name==`costguard-api`].id' --output text)
API_URL="https://${API_ID}.execute-api.${REGION}.amazonaws.com/prod"
BUCKET=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`CustomersTableName`].OutputValue' --output text | sed 's/costguard-customers/costguard-dashboard-'$ACCOUNT_ID'/')
BUCKET="costguard-dashboard-${ACCOUNT_ID}"
CF_DOMAIN=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`DashboardURL`].OutputValue' --output text)
POOL_ID=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
CLIENT_ID=$(aws cloudformation describe-stacks --stack-name costguard-ai --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text)

echo "API: $API_URL"
echo "Dashboard: $CF_DOMAIN"
echo "Pool: $POOL_ID"
echo "Client: $CLIENT_ID"
echo ""

# Step 2: Deploy Lambda code
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2/7: Deploying Lambda code..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cd lambda
zip -j /tmp/dashboard_api.zip dashboard_api.py
zip -j /tmp/cost_analyzer.zip cost_analyzer.py
aws lambda update-function-code --function-name costguard-dashboard-api --zip-file fileb:///tmp/dashboard_api.zip > /dev/null
aws lambda update-function-code --function-name costguard-cost-analyzer --zip-file fileb:///tmp/cost_analyzer.zip > /dev/null
sleep 5
aws lambda update-function-configuration --function-name costguard-dashboard-api \
    --handler dashboard_api.handler \
    --timeout 60 --memory-size 512 \
    --environment "Variables={CUSTOMERS_TABLE=costguard-customers,ALERTS_TABLE=costguard-alerts,COSTS_TABLE=costguard-costs,BEDROCK_MODEL_ID=$BEDROCK_MODEL,ALLOWED_ORIGIN=$CF_DOMAIN}" > /dev/null
aws lambda update-function-configuration --function-name costguard-cost-analyzer \
    --handler cost_analyzer.handler > /dev/null
cd ..
echo "✅ Lambda code deployed"
echo ""

# Step 3: Upload frontend
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3/7: Configuring frontend..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
# Update frontend config with new values
sed "s|API:'[^']*'|API:'${API_URL}'|g; s|CLIENT_ID:'[^']*'|CLIENT_ID:'${CLIENT_ID}'|g; s|REGION:'[^']*'|REGION:'${REGION}'|g" frontend/index.html > /tmp/index.html
# Update onboarding instructions with new account ID
sed -i "s/651592873649/${ACCOUNT_ID}/g" /tmp/index.html
aws s3 cp /tmp/index.html s3://$BUCKET/index.html --content-type "text/html"
CF_DIST_ID=$(aws cloudfront list-distributions --query 'DistributionList.Items[?Comment==`costguard Dashboard CDN`].Id' --output text)
aws cloudfront create-invalidation --distribution-id $CF_DIST_ID --paths "/*" > /dev/null
echo "✅ Frontend uploaded"
echo ""

# Step 4: Production features - SNS, DLQ, X-Ray
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 4/7: Setting up monitoring..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
SNS_ARN=$(aws sns create-topic --name costguard-alarms --query 'TopicArn' --output text)
aws sns subscribe --topic-arn $SNS_ARN --protocol email --notification-endpoint $ALERT_EMAIL > /dev/null

for ALARM in costguard-cost-analyzer-errors costguard-cost-analyzer-throttles costguard-dashboard-api-errors costguard-dashboard-api-throttles; do
    FUNC=$(echo $ALARM | sed 's/-errors//' | sed 's/-throttles//')
    METRIC=$(echo $ALARM | grep -q "errors" && echo "Errors" || echo "Throttles")
    aws cloudwatch put-metric-alarm --alarm-name $ALARM --alarm-actions $SNS_ARN \
        --metric-name $METRIC --namespace AWS/Lambda --statistic Sum \
        --period 300 --evaluation-periods 1 --threshold 1 \
        --comparison-operator GreaterThanOrEqualToThreshold \
        --dimensions Name=FunctionName,Value=$FUNC > /dev/null
done

aws lambda update-function-configuration --function-name costguard-cost-analyzer --tracing-config Mode=Active > /dev/null
aws lambda update-function-configuration --function-name costguard-dashboard-api --tracing-config Mode=Active > /dev/null
echo "✅ SNS alarms + X-Ray tracing enabled"
echo ""

# Step 5: DLQ
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 5/7: Setting up Dead Letter Queue..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
DLQ_URL=$(aws sqs create-queue --queue-name costguard-dlq --query 'QueueUrl' --output text)
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url $DLQ_URL --attribute-names QueueArn --query 'Attributes.QueueArn' --output text)
aws iam put-role-policy --role-name costguard-lambda-role --policy-name SQSAccess \
    --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"sqs:SendMessage\",\"sqs:ReceiveMessage\",\"sqs:DeleteMessage\",\"sqs:GetQueueAttributes\"],\"Resource\":\"arn:aws:sqs:${REGION}:${ACCOUNT_ID}:costguard-*\"}]}"
aws iam put-role-policy --role-name costguard-lambda-role --policy-name XRayAccess \
    --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":["xray:PutTraceSegments","xray:PutTelemetryRecords"],"Resource":"*"}]}'
sleep 10
aws lambda update-function-configuration --function-name costguard-cost-analyzer --dead-letter-config TargetArn=$DLQ_ARN > /dev/null
echo "✅ DLQ configured"
echo ""

# Step 6: Health endpoint
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 6/7: Adding health check endpoint..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
ROOT_ID=$(aws apigateway get-resources --rest-api-id $API_ID --query 'items[?path==`/`].id' --output text)
HEALTH_ID=$(aws apigateway create-resource --rest-api-id $API_ID --parent-id $ROOT_ID --path-part health --query 'id' --output text 2>/dev/null || aws apigateway get-resources --rest-api-id $API_ID --query 'items[?path==`/health`].id' --output text)
aws apigateway put-method --rest-api-id $API_ID --resource-id $HEALTH_ID --http-method GET --authorization-type NONE > /dev/null 2>&1 || true
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:costguard-dashboard-api"
aws apigateway put-integration --rest-api-id $API_ID --resource-id $HEALTH_ID --http-method GET --type AWS_PROXY --integration-http-method POST --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" > /dev/null 2>&1 || true
aws lambda add-permission --function-name costguard-dashboard-api --statement-id health-api --action lambda:InvokeFunction --principal apigateway.amazonaws.com --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/GET/health" > /dev/null 2>&1 || true
echo "✅ Health endpoint added"
echo ""

# Step 7: Cognito Authorizer
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 7/7: Setting up Cognito Authorizer..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
POOL_ARN="arn:aws:cognito-idp:${REGION}:${ACCOUNT_ID}:userpool/${POOL_ID}"
AUTH_ID=$(aws apigateway create-authorizer --rest-api-id $API_ID --name CognitoAuth --type COGNITO_USER_POOLS --provider-arns $POOL_ARN --identity-source method.request.header.Authorization --query 'id' --output text 2>/dev/null || aws apigateway get-authorizers --rest-api-id $API_ID --query 'items[?name==`CognitoAuth`].id' --output text)

RESOURCES=$(aws apigateway get-resources --rest-api-id $API_ID --query 'items[*].[id,path,resourceMethods]' --output json)
for RES_ID in $(aws apigateway get-resources --rest-api-id $API_ID --query 'items[?path!=`/` && path!=`/health`].id' --output text); do
    for METHOD in GET POST; do
        aws apigateway update-method --rest-api-id $API_ID --resource-id $RES_ID --http-method $METHOD \
            --patch-operations op=replace,path=/authorizationType,value=COGNITO_USER_POOLS op=replace,path=/authorizerId,value=$AUTH_ID > /dev/null 2>&1 || true
    done
done

aws apigateway create-deployment --rest-api-id $API_ID --stage-name prod > /dev/null
sleep 3
aws apigateway update-stage --rest-api-id $API_ID --stage-name prod --patch-operations op=replace,path=/deploymentId,value=$(aws apigateway get-deployments --rest-api-id $API_ID --query 'items[0].id' --output text) > /dev/null

# SES verification
aws ses verify-email-identity --email-address $ALERT_EMAIL > /dev/null 2>&1 || true

echo "✅ Cognito Authorizer enabled"
echo ""

# Done!
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 CostGuard AI is LIVE!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Dashboard:  $CF_DOMAIN"
echo "API:        $API_URL"
echo "Health:     $API_URL/health"
echo ""
echo "📋 Next steps:"
echo "  1. Check your email ($ALERT_EMAIL) and confirm:"
echo "     - SNS subscription (for alarm notifications)"
echo "     - SES verification (for cost spike alerts)"
echo "  2. Open $CF_DOMAIN in your browser"
echo "  3. Sign up with your email and start monitoring!"
echo ""
