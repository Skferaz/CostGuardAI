"""
CostGuard AI - Dashboard API Lambda (with AI Chat)
Handles all REST API requests from the frontend via API Gateway.

Endpoints:
  GET  /dashboard?customerId=xxx  - Cost data with AI analysis
  GET  /alerts                    - Cost spike alerts
  GET  /cost-summary?customerId=x - Aggregated spending summary
  POST /onboard                   - Register new customer account
  GET  /customers                 - List all connected accounts
  POST /chat                      - AI chatbot with live resource + cost context
"""
import json
import boto3
import os
import uuid
from decimal import Decimal
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key


HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
}


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def get_cost_context():
    """Fetch 7-day cost breakdown by service from Cost Explorer."""
    ce = boto3.client('ce')
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

    svc = ce.get_cost_and_usage(
        TimePeriod={'Start': start, 'End': end},
        Granularity='DAILY',
        Metrics=['UnblendedCost'],
        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
    )

    svc_costs = {}
    for day in svc['ResultsByTime']:
        for g in day['Groups']:
            name = g['Keys'][0]
            cost = float(g['Metrics']['UnblendedCost']['Amount'])
            svc_costs[name] = svc_costs.get(name, 0) + cost

    svc_sorted = sorted(svc_costs.items(), key=lambda x: x[1], reverse=True)[:15]

    ctx = 'AWS Cost Breakdown (Last 7 Days):\n'
    for name, cost in svc_sorted:
        ctx += f'  {name}: ${cost:.2f}\n'

    return ctx, dict(svc_sorted)


def get_resource_inventory():
    """Fetch live inventory of AWS resources in the account."""
    ctx = '\nAWS Resources Inventory:\n'

    # S3 Buckets
    try:
        buckets = boto3.client('s3').list_buckets().get('Buckets', [])
        ctx += f'S3 Buckets ({len(buckets)}):\n'
        for b in buckets:
            ctx += f'  - {b.get("Name", "")}\n'
    except Exception:
        pass

    # EC2 Instances
    try:
        reservations = boto3.client('ec2').describe_instances()['Reservations']
        instances = []
        for r in reservations:
            for i in r['Instances']:
                name = 'No Name'
                for tag in i.get('Tags', []):
                    if tag.get('Key') == 'Name':
                        name = tag.get('Value', '')
                instances.append(
                    f'  - {i.get("InstanceId", "")} '
                    f'({i.get("InstanceType", "")}, '
                    f'{i.get("State", {}).get("Name", "")}, '
                    f'Name: {name})'
                )
        ctx += f'EC2 Instances ({len(instances)}):\n' + '\n'.join(instances) + '\n'
    except Exception:
        pass

    # Lambda Functions
    try:
        fns = boto3.client('lambda').list_functions()['Functions']
        ctx += f'Lambda Functions ({len(fns)}):\n'
        for fn in fns:
            ctx += (
                f'  - {fn.get("FunctionName", "")} '
                f'({fn.get("Runtime", "N/A")}, '
                f'{fn.get("MemorySize", "")}MB)\n'
            )
    except Exception:
        pass

    # DynamoDB Tables
    try:
        tables = boto3.client('dynamodb').list_tables()['TableNames']
        ctx += f'DynamoDB Tables ({len(tables)}):\n'
        for t in tables:
            ctx += f'  - {t}\n'
    except Exception:
        pass

    # RDS Instances
    try:
        dbs = boto3.client('rds').describe_db_instances()['DBInstances']
        ctx += f'RDS Instances ({len(dbs)}):\n'
        for db in dbs:
            ctx += (
                f'  - {db.get("DBInstanceIdentifier", "")} '
                f'({db.get("DBInstanceClass", "")}, '
                f'{db.get("Engine", "")})\n'
            )
    except Exception:
        pass

    # CloudFront Distributions
    try:
        dists = boto3.client('cloudfront').list_distributions() \
            .get('DistributionList', {}).get('Items', [])
        ctx += f'CloudFront Distributions ({len(dists)}):\n'
        for d in dists:
            ctx += f'  - {d.get("Id", "")} ({d.get("DomainName", "")})\n'
    except Exception:
        pass

    return ctx


def handle_chat(event):
    """AI chatbot: fetches live cost + resource data, sends to Bedrock with user question."""
    body = json.loads(event.get('body', '{}'))
    question = body.get('question', '')

    if not question:
        return {
            'statusCode': 400,
            'headers': HEADERS,
            'body': json.dumps({'error': 'question is required'})
        }

    cost_ctx, cost_data = get_cost_context()
    resource_ctx = get_resource_inventory()

    bedrock = boto3.client('bedrock-runtime')
    response = bedrock.invoke_model(
        modelId=os.environ['BEDROCK_MODEL_ID'],
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 500,
            'system': (
                'You are CostGuard AI, an AWS cost optimization assistant. '
                'You have access to real AWS cost data AND a live inventory '
                'of AWS resources in this account. Answer questions about '
                'costs and resources with specific names, IDs, and types. '
                'Be concise and actionable.'
            ),
            'messages': [{
                'role': 'user',
                'content': cost_ctx + resource_ctx + '\nUser Question: ' + question
            }]
        })
    )

    answer = json.loads(response['body'].read())['content'][0]['text']

    return {
        'statusCode': 200,
        'headers': HEADERS,
        'body': json.dumps({
            'answer': answer,
            'cost_data': cost_data
        })
    }


def handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    path = event.get('path', '')
    method = event.get('httpMethod', 'GET')

    try:
        if path == '/dashboard':
            params = event.get('queryStringParameters') or {}
            cid = params.get('customerId', 'system')
            r = dynamodb.Table(os.environ['COSTS_TABLE']).query(
                KeyConditionExpression=Key('customerId').eq(cid),
                ScanIndexForward=False, Limit=30
            )
            return {
                'statusCode': 200, 'headers': HEADERS,
                'body': json.dumps({
                    'costs': r['Items'], 'total_items': r['Count']
                }, default=decimal_default)
            }

        elif path == '/alerts':
            r = dynamodb.Table(os.environ['ALERTS_TABLE']).scan(Limit=50)
            return {
                'statusCode': 200, 'headers': HEADERS,
                'body': json.dumps({
                    'alerts': r['Items'], 'total_items': r['Count']
                }, default=decimal_default)
            }

        elif path == '/cost-summary':
            params = event.get('queryStringParameters') or {}
            cid = params.get('customerId', 'system')
            r = dynamodb.Table(os.environ['COSTS_TABLE']).query(
                KeyConditionExpression=Key('customerId').eq(cid)
            )
            items = r['Items']
            tc = sum(float(i.get('cost', 0)) for i in items)
            ac = tc / len(items) if items else 0
            return {
                'statusCode': 200, 'headers': HEADERS,
                'body': json.dumps({
                    'total_cost': tc,
                    'average_daily_cost': ac,
                    'days_tracked': len(items)
                })
            }

        elif path == '/onboard' and method == 'POST':
            body = json.loads(event.get('body', '{}'))
            email = body.get('email', '')
            role_arn = body.get('roleArn', '')
            plan = body.get('plan', 'free')
            if not email or not role_arn:
                return {
                    'statusCode': 400, 'headers': HEADERS,
                    'body': json.dumps({'error': 'email and roleArn required'})
                }
            cid = 'cust-' + str(uuid.uuid4())[:8]
            dynamodb.Table(os.environ['CUSTOMERS_TABLE']).put_item(Item={
                'customerId': cid, 'email': email, 'roleArn': role_arn,
                'plan': plan, 'createdAt': datetime.now().isoformat()
            })
            return {
                'statusCode': 200, 'headers': HEADERS,
                'body': json.dumps({'message': 'Onboarded', 'customerId': cid})
            }

        elif path == '/customers':
            r = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()
            return {
                'statusCode': 200, 'headers': HEADERS,
                'body': json.dumps({
                    'customers': r['Items'], 'total': r['Count']
                }, default=decimal_default)
            }

        elif path == '/chat' and method == 'POST':
            return handle_chat(event)

        else:
            return {
                'statusCode': 404, 'headers': HEADERS,
                'body': json.dumps({'error': 'Not found'})
            }

    except Exception as e:
        return {
            'statusCode': 500, 'headers': HEADERS,
            'body': json.dumps({'error': str(e)})
        }
