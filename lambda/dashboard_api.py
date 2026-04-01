"""
CostGuard AI - Dashboard API Lambda
Handles all REST API requests from the frontend via API Gateway.

Endpoints:
  GET  /dashboard?customerId=xxx  - Cost data with AI analysis
  GET  /alerts                    - Cost spike alerts
  GET  /cost-summary?customerId=x - Aggregated spending summary
  POST /onboard                   - Register new customer account
  GET  /customers                 - List all connected accounts
"""
import json
import boto3
import os
import uuid
from decimal import Decimal
from datetime import datetime
from boto3.dynamodb.conditions import Key


# CORS headers - required for browser requests from CloudFront domain
HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Content-Type,Authorization',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'
}


def decimal_default(obj):
    """JSON serializer for DynamoDB Decimal types."""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError


def handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    path = event.get('path', '')
    method = event.get('httpMethod', 'GET')

    try:
        # GET /dashboard - Returns cost records with AI analysis
        if path == '/dashboard':
            params = event.get('queryStringParameters') or {}
            cid = params.get('customerId', 'system')
            r = dynamodb.Table(os.environ['COSTS_TABLE']).query(
                KeyConditionExpression=Key('customerId').eq(cid),
                ScanIndexForward=False,
                Limit=30
            )
            return {
                'statusCode': 200,
                'headers': HEADERS,
                'body': json.dumps({
                    'costs': r['Items'],
                    'total_items': r['Count']
                }, default=decimal_default)
            }

        # GET /alerts - Returns all cost spike alerts
        elif path == '/alerts':
            r = dynamodb.Table(os.environ['ALERTS_TABLE']).scan(Limit=50)
            return {
                'statusCode': 200,
                'headers': HEADERS,
                'body': json.dumps({
                    'alerts': r['Items'],
                    'total_items': r['Count']
                }, default=decimal_default)
            }

        # GET /cost-summary - Aggregated cost statistics
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
                'statusCode': 200,
                'headers': HEADERS,
                'body': json.dumps({
                    'total_cost': tc,
                    'average_daily_cost': ac,
                    'days_tracked': len(items)
                })
            }

        # POST /onboard - Register a new customer's AWS account
        elif path == '/onboard' and method == 'POST':
            body = json.loads(event.get('body', '{}'))
            email = body.get('email', '')
            role_arn = body.get('roleArn', '')
            plan = body.get('plan', 'free')

            if not email or not role_arn:
                return {
                    'statusCode': 400,
                    'headers': HEADERS,
                    'body': json.dumps({'error': 'email and roleArn required'})
                }

            cid = 'cust-' + str(uuid.uuid4())[:8]
            dynamodb.Table(os.environ['CUSTOMERS_TABLE']).put_item(
                Item={
                    'customerId': cid,
                    'email': email,
                    'roleArn': role_arn,
                    'plan': plan,
                    'createdAt': datetime.now().isoformat()
                }
            )
            return {
                'statusCode': 200,
                'headers': HEADERS,
                'body': json.dumps({
                    'message': 'Onboarded',
                    'customerId': cid
                })
            }

        # GET /customers - List all registered customer accounts
        elif path == '/customers':
            r = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()
            return {
                'statusCode': 200,
                'headers': HEADERS,
                'body': json.dumps({
                    'customers': r['Items'],
                    'total': r['Count']
                }, default=decimal_default)
            }

        else:
            return {
                'statusCode': 404,
                'headers': HEADERS,
                'body': json.dumps({'error': 'Not found'})
            }

    except Exception as e:
        return {
            'statusCode': 500,
            'headers': HEADERS,
            'body': json.dumps({'error': str(e)})
        }
