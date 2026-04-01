"""
CostGuard AI - Cost Analyzer Lambda
Triggered daily by EventBridge at 6 AM UTC.
Analyzes AWS costs for all registered customers using Cost Explorer,
generates AI insights via Amazon Bedrock, and sends SES alerts on spikes.
"""
import json
import boto3
import os
from datetime import datetime, timedelta


def get_ce_client(role_arn=None):
    """Get Cost Explorer client - uses STS AssumeRole for cross-account access."""
    if role_arn:
        sts = boto3.client('sts')
        creds = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName='CostGuard'
        )['Credentials']
        return boto3.client(
            'ce',
            aws_access_key_id=creds['AccessKeyId'],
            aws_secret_access_key=creds['SecretAccessKey'],
            aws_session_token=creds['SessionToken']
        )
    return boto3.client('ce')


def analyze_customer(cid, role_arn, email, dynamodb, bedrock, ses):
    """
    Analyze a single customer's AWS costs:
    1. Fetch yesterday's cost from Cost Explorer
    2. Fetch 7-day historical costs for average
    3. Calculate percentage change (spike detection)
    4. Send cost data to Bedrock Claude for AI analysis
    5. Store results in DynamoDB
    6. If spike >20%, store alert and send email via SES
    """
    ce = get_ce_client(role_arn)

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    wstart = (datetime.now() - timedelta(days=8)).strftime('%Y-%m-%d')

    # Get yesterday's cost
    r = ce.get_cost_and_usage(
        TimePeriod={'Start': start, 'End': end},
        Granularity='DAILY',
        Metrics=['UnblendedCost']
    )
    ycost = float(r['ResultsByTime'][0]['Total']['UnblendedCost']['Amount']) if r['ResultsByTime'] else 0

    # Get 7-day costs for average
    wr = ce.get_cost_and_usage(
        TimePeriod={'Start': wstart, 'End': start},
        Granularity='DAILY',
        Metrics=['UnblendedCost']
    )
    wc = [float(d['Total']['UnblendedCost']['Amount']) for d in wr['ResultsByTime']]
    avg = sum(wc) / len(wc) if wc else 0

    # Calculate percentage change
    pct = ((ycost - avg) / avg * 100) if avg > 0 else 0

    # AI Analysis via Bedrock Claude
    br = bedrock.invoke_model(
        modelId=os.environ['BEDROCK_MODEL_ID'],
        body=json.dumps({
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': 200,
            'messages': [{
                'role': 'user',
                'content': f'Analyze AWS cost for {cid}: Yesterday ${ycost:.2f}, '
                           f'7-day avg ${avg:.2f}, change {pct:.1f}%. '
                           f'Brief insights and recommendations.'
            }]
        })
    )
    ai = json.loads(br['body'].read())['content'][0]['text']

    # Store cost data in DynamoDB
    dynamodb.Table(os.environ['COSTS_TABLE']).put_item(
        Item={
            'customerId': cid,
            'date': start,
            'cost': str(ycost),
            'avg_cost': str(avg),
            'percent_change': str(pct),
            'ai_analysis': ai,
            'timestamp': datetime.now().isoformat()
        }
    )

    # Spike detection: >20% increase triggers alert
    if pct > 20:
        dynamodb.Table(os.environ['ALERTS_TABLE']).put_item(
            Item={
                'alertId': f'{cid}-spike-{start}',
                'customerId': cid,
                'service': 'AWS',
                'percentChange': str(pct),
                'aiExplanation': ai,
                'timestamp': datetime.now().isoformat()
            }
        )
        if email:
            try:
                ses.send_email(
                    Source=os.environ['ALERT_EMAIL'],
                    Destination={'ToAddresses': [email]},
                    Message={
                        'Subject': {'Data': f'CostGuard: {pct:.1f}% Spike'},
                        'Body': {'Text': {'Data': (
                            f'Spike for {cid}: ${ycost:.2f} vs ${avg:.2f} avg '
                            f'({pct:.1f}%)\n\nAI: {ai}'
                        )}}
                    }
                )
            except Exception:
                pass

    return {
        'customer_id': cid,
        'cost': ycost,
        'avg': avg,
        'pct': pct,
        'alert': pct > 20
    }


def handler(event, context):
    """
    Main handler - processes all customers:
    1. Analyze the host account (system)
    2. Scan Customers DynamoDB table
    3. For each customer, assume their cross-account role and analyze
    """
    dynamodb = boto3.resource('dynamodb')
    bedrock = boto3.client('bedrock-runtime')
    ses = boto3.client('ses')
    results = []

    try:
        # Analyze host account
        results.append(analyze_customer(
            'system', None, os.environ['ALERT_EMAIL'],
            dynamodb, bedrock, ses
        ))

        # Analyze all registered customers
        customers = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()['Items']
        for c in customers:
            try:
                results.append(analyze_customer(
                    c['customerId'], c.get('roleArn'), c.get('email'),
                    dynamodb, bedrock, ses
                ))
            except Exception as e:
                results.append({
                    'customer_id': c['customerId'],
                    'error': str(e)
                })

        return {
            'statusCode': 200,
            'body': json.dumps({
                'status': 'success',
                'processed': len(results),
                'results': results
            })
        }
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
