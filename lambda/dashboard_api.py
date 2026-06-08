import json, boto3, os, uuid, re, time, hashlib, hmac, base64, urllib.request
from decimal import Decimal
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key

PLAN_MODELS = {
    'free':       'us.anthropic.claude-haiku-4-5-20251001-v1:0',      # Claude Haiku 4.5
    'pro':        'us.anthropic.claude-sonnet-4-5-20250929-v1:0',     # Claude Sonnet 4.5
    'enterprise': 'us.anthropic.claude-opus-4-6-v1',                  # Claude Opus 4.6
}

def get_model_for_plan(plan):
    return PLAN_MODELS.get(plan, PLAN_MODELS['free'])

def get_customer_by_email(dynamodb, email):
    tbl = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
    result = tbl.scan(FilterExpression=boto3.dynamodb.conditions.Attr('email').eq(email))
    return result['Items'][0] if result['Items'] else None

HEADERS = {'Access-Control-Allow-Origin': os.environ.get('ALLOWED_ORIGIN','*'), 'Access-Control-Allow-Headers': 'Content-Type,Authorization', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS'}
_cache = {}

def dd(obj):
    if isinstance(obj, Decimal): return float(obj)
    raise TypeError

def cached(key, ttl, fn):
    now = time.time()
    if key in _cache and now - _cache[key]['t'] < ttl: return _cache[key]['v']
    v = fn()
    _cache[key] = {'v': v, 't': now}
    return v

def resp(code, body):
    return {'statusCode': code, 'headers': HEADERS, 'body': json.dumps(body, default=dd)}

def validate_arn(arn):
    return bool(re.match(r'^arn:aws:iam::\d{12}:role/.+$', arn))

def get_resource_inventory(role_arn=None):
    ctx = ''
    if role_arn:
        try:
            sts = boto3.client('sts')
            creds = sts.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardResources')['Credentials']
            session = boto3.Session(aws_access_key_id=creds['AccessKeyId'], aws_secret_access_key=creds['SecretAccessKey'], aws_session_token=creds['SessionToken'])
        except:
            return 'Resource inventory: Unable to access customer account\n'
    else:
        session = boto3.Session()
    try:
        bkts = session.client('s3').list_buckets().get('Buckets', [])
        ctx += 'S3 Buckets ('+str(len(bkts))+'):\n'
        for b in bkts: ctx += '  - '+b.get('Name','')+'\n'
    except: pass
    try:
        ec2r = session.client('ec2').describe_instances()['Reservations']
        il = []
        for rv in ec2r:
            for inst in rv['Instances']:
                nm = 'No Name'
                for tg in inst.get('Tags', []):
                    if tg.get('Key') == 'Name': nm = tg.get('Value', '')
                il.append('  - '+inst.get('InstanceId','')+' ('+inst.get('InstanceType','')+', '+inst.get('State',{}).get('Name','')+', Name: '+nm+')')
        ctx += 'EC2 Instances ('+str(len(il))+'):\n'+'\n'.join(il)+'\n'
    except: pass
    try:
        fns = session.client('lambda').list_functions()['Functions']
        ctx += 'Lambda Functions ('+str(len(fns))+'):\n'
        for fn in fns: ctx += '  - '+fn.get('FunctionName','')+' ('+fn.get('Runtime','N/A')+', '+str(fn.get('MemorySize',''))+'MB)\n'
    except: pass
    try:
        tbs = session.client('dynamodb').list_tables()['TableNames']
        ctx += 'DynamoDB Tables ('+str(len(tbs))+'):\n'
        for tb in tbs: ctx += '  - '+tb+'\n'
    except: pass
    try:
        rdsl = session.client('rds').describe_db_instances()['DBInstances']
        ctx += 'RDS Instances ('+str(len(rdsl))+'):\n'
        for db in rdsl: ctx += '  - '+db.get('DBInstanceIdentifier','')+' ('+db.get('DBInstanceClass','')+', '+db.get('Engine','')+')\n'
    except: pass
    try:
        cfl = session.client('cloudfront').list_distributions().get('DistributionList',{}).get('Items',[])
        ctx += 'CloudFront Distributions ('+str(len(cfl))+'):\n'
        for cf2 in cfl: ctx += '  - '+cf2.get('Id','')+' ('+cf2.get('DomainName','')+')\n'
    except: pass
    return ctx

def handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    path = event.get('path', '')
    method = event.get('httpMethod', 'GET')
    params = event.get('queryStringParameters') or {}

    try:
        # Extract caller email from JWT
        caller_email = ''
        try:
            claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
            caller_email = claims.get('email', '')
            if not caller_email:
                auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header else ''
                if token and '.' in token:
                    import base64
                    payload = token.split('.')[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = json.loads(base64.b64decode(payload))
                    caller_email = decoded.get('email', '')
        except: pass

        admin_email = os.environ.get('ADMIN_EMAIL', '')
        is_admin = caller_email and caller_email == admin_email

        # For data endpoints, check if user is admin or registered customer
        protected_paths = ['/dashboard', '/alerts', '/cost-summary', '/report']
        if path in protected_paths and not is_admin:
            cust_scan = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan(FilterExpression=boto3.dynamodb.conditions.Attr('email').eq(caller_email)) if caller_email else {'Items': []}
            if not cust_scan['Items']:
                return resp(200, {'costs': [], 'alerts': [], 'total_items': 0, 'total_cost': 0, 'average_daily_cost': 0, 'days_tracked': 0, 'message': 'Connect your AWS account to see your cost data. Go to Add Account page.'})

        if path == '/health':
            return resp(200, {'status': 'healthy', 'timestamp': datetime.now().isoformat()})

        if method == 'OPTIONS':
            return resp(200, {'message': 'ok'})

        elif path == '/dashboard':
            cid = params.get('customerId', 'system')
            limit = min(int(params.get('limit', '30')), 100)
            kwargs = {'KeyConditionExpression': Key('customerId').eq(cid), 'ScanIndexForward': False, 'Limit': limit}
            if params.get('nextKey'): kwargs['ExclusiveStartKey'] = json.loads(params['nextKey'])
            r = dynamodb.Table(os.environ['COSTS_TABLE']).query(**kwargs)
            body = {'costs': r['Items'], 'total_items': r['Count']}
            if 'LastEvaluatedKey' in r: body['nextKey'] = json.dumps(r['LastEvaluatedKey'], default=dd)
            return resp(200, body)

        elif path == '/alerts':
            limit = min(int(params.get('limit', '50')), 100)
            kwargs = {'Limit': limit}
            if params.get('nextKey'): kwargs['ExclusiveStartKey'] = json.loads(params['nextKey'])
            r = dynamodb.Table(os.environ['ALERTS_TABLE']).scan(**kwargs)
            body = {'alerts': r['Items'], 'total_items': r['Count']}
            if 'LastEvaluatedKey' in r: body['nextKey'] = json.dumps(r['LastEvaluatedKey'], default=dd)
            return resp(200, body)

        elif path == '/cost-summary':
            cid = params.get('customerId', 'system')
            r = dynamodb.Table(os.environ['COSTS_TABLE']).query(KeyConditionExpression=Key('customerId').eq(cid))
            items = r['Items']
            tc = sum(float(i.get('cost', 0)) for i in items)
            ac = tc / len(items) if items else 0
            return resp(200, {'total_cost': tc, 'average_daily_cost': ac, 'days_tracked': len(items)})

        elif path == '/onboard' and method == 'POST':
            body = json.loads(event.get('body', '{}'))
            email = body.get('email', '').strip()
            role_arn = body.get('roleArn', '').strip()
            plan = body.get('plan', 'free')
            if not email or not role_arn: return resp(400, {'error': 'email and roleArn required'})
            if not re.match(r'^[^@]+@[^@]+\.[^@]+$', email): return resp(400, {'error': 'Invalid email format'})
            if not validate_arn(role_arn): return resp(400, {'error': 'Invalid IAM role ARN format. Expected: arn:aws:iam::<account-id>:role/<role-name>'})
            if plan not in ('free', 'pro', 'enterprise'): return resp(400, {'error': 'Invalid plan. Must be free, pro, or enterprise'})
            cid = 'cust-' + str(uuid.uuid4())[:8]
            dynamodb.Table(os.environ['CUSTOMERS_TABLE']).put_item(Item={'customerId': cid, 'email': email, 'roleArn': role_arn, 'plan': plan, 'createdAt': datetime.now().isoformat()})
            return resp(200, {'message': 'Onboarded', 'customerId': cid})

        elif path == '/customers' and method == 'GET':
            # Admin only
            caller_email = ''
            try:
                claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
                caller_email = claims.get('email', '')
                if not caller_email:
                    auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header else ''
                    if token and '.' in token:
                        import base64
                        payload = token.split('.')[1]
                        payload += '=' * (4 - len(payload) % 4)
                        caller_email = json.loads(base64.b64decode(payload)).get('email', '')
            except: pass
            if caller_email != os.environ.get('ADMIN_EMAIL', ''):
                return resp(403, {'error': 'Admin access only'})
            r = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()
            return resp(200, {'customers': r['Items'], 'total': r['Count']})

        elif path == '/customers/delete' and method == 'POST':
            # Admin only - delete customer and their data
            caller_email = ''
            try:
                claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
                caller_email = claims.get('email', '')
                if not caller_email:
                    auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header else ''
                    if token and '.' in token:
                        import base64
                        payload = token.split('.')[1]
                        payload += '=' * (4 - len(payload) % 4)
                        caller_email = json.loads(base64.b64decode(payload)).get('email', '')
            except: pass
            if caller_email != os.environ.get('ADMIN_EMAIL', ''):
                return resp(403, {'error': 'Admin access only'})
            body = json.loads(event.get('body', '{}'))
            cid = body.get('customerId', '')
            if not cid: return resp(400, {'error': 'customerId required'})
            dynamodb.Table(os.environ['CUSTOMERS_TABLE']).delete_item(Key={'customerId': cid})
            # Delete customer's cost data
            costs_table = dynamodb.Table(os.environ['COSTS_TABLE'])
            cost_items = costs_table.query(KeyConditionExpression=boto3.dynamodb.conditions.Key('customerId').eq(cid))['Items']
            for item in cost_items:
                costs_table.delete_item(Key={'customerId': cid, 'date': item['date']})
            # Delete customer's alerts
            alerts_table = dynamodb.Table(os.environ['ALERTS_TABLE'])
            alert_items = alerts_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('customerId').eq(cid))['Items']
            for item in alert_items:
                alerts_table.delete_item(Key={'alertId': item['alertId']})
            return resp(200, {'message': 'Customer ' + cid + ' removed successfully'})

        elif path == '/chat' and method == 'POST':
            body = json.loads(event.get('body', '{}'))
            question = body.get('question', '').strip()
            if not question: return resp(400, {'error': 'question is required'})
            if len(question) > 1000: return resp(400, {'error': 'Question too long (max 1000 chars)'})

            # Identify user from Cognito token
            caller_email = ''
            role_arn = None
            try:
                claims = event.get('requestContext', {}).get('authorizer', {}).get('claims', {})
                caller_email = claims.get('email', '')
                if not caller_email:
                    auth_header = event.get('headers', {}).get('Authorization', '') or event.get('headers', {}).get('authorization', '')
                    token = auth_header.replace('Bearer ', '')
                    if token:
                        import base64
                        payload = token.split('.')[1]
                        payload += '=' * (4 - len(payload) % 4)
                        decoded = json.loads(base64.b64decode(payload))
                        caller_email = decoded.get('email', '')
            except: pass

            # Look up customer record
            customer_id = None
            is_admin = False
            customer_plan = 'free'
            admin_email = os.environ.get('ADMIN_EMAIL', '')
            if caller_email and caller_email == admin_email:
                is_admin = True
                customer_id = 'system'
                customer_plan = 'enterprise'
            elif caller_email:
                try:
                    cust_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
                    cust_scan = cust_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('email').eq(caller_email))
                    if cust_scan['Items']:
                        customer_id = cust_scan['Items'][0]['customerId']
                        role_arn = cust_scan['Items'][0].get('roleArn', '')
                        customer_plan = cust_scan['Items'][0].get('plan', 'free')
                        if not role_arn: role_arn = None
                except: pass

            # Block unregistered users from seeing any account data
            if not customer_id:
                return resp(200, {'answer': 'Welcome to CostGuard AI! To use the chatbot, please connect your AWS account first.\n\nGo to the **Add Account** page in the sidebar and follow the 3 simple steps to connect your AWS account. Once connected, I can analyze your costs, list your resources, and provide optimization recommendations.', 'cost_data': {}})

            # For customers with roleArn, verify the role works
            if role_arn and not is_admin:
                try:
                    sts_test = boto3.client('sts')
                    sts_test.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardTest')['Credentials']
                except:
                    return resp(200, {'answer': 'Your AWS account is registered but I cannot access it yet. Please verify:\n\n1. The IAM role **CostGuardReadRole** exists in your AWS account\n2. The trust policy allows **arn:aws:iam::717279732828:role/costguard-lambda-role**\n3. The role has the required permissions (S3, EC2, Lambda, DynamoDB, RDS, CloudFront, Cost Explorer)\n\nGo to **Add Account** page for the exact commands to run.', 'cost_data': {}})

            ctx = ''
            svc_sorted = []
            # Fetch cost data (from customer's account if they have a role)
            try:
                if role_arn:
                    import boto3 as b3
                    sts = b3.client('sts')
                    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardChat')['Credentials']
                    ce = b3.client('ce', aws_access_key_id=creds['AccessKeyId'], aws_secret_access_key=creds['SecretAccessKey'], aws_session_token=creds['SessionToken'])
                else:
                    ce = boto3.client('ce')
                end = datetime.now().strftime('%Y-%m-%d')
                start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                svc = ce.get_cost_and_usage(TimePeriod={'Start':start,'End':end},Granularity='DAILY',Metrics=['UnblendedCost'],GroupBy=[{'Type':'DIMENSION','Key':'SERVICE'}])
                svc_costs = {}
                for day in svc['ResultsByTime']:
                    for g in day['Groups']:
                        sn = g['Keys'][0]; cv = float(g['Metrics']['UnblendedCost']['Amount'])
                        svc_costs[sn] = svc_costs.get(sn, 0) + cv
                svc_sorted = sorted(svc_costs.items(), key=lambda x: x[1], reverse=True)[:15]
                ctx = 'AWS Cost Breakdown (Last 7 Days) for ' + customer_id + ':\n'
                for sn, cv in svc_sorted: ctx += '  ' + sn + ': $' + str(round(cv, 2)) + '\n'
            except:
                ctx = 'AWS Cost data: Not available\n'

            # Fetch resources (from customer's account if they have a role, otherwise host account)
            cache_key = 'resources_' + customer_id
            ctx += '\n' + cached(cache_key, 300, lambda: get_resource_inventory(role_arn))

            bedrock = boto3.client('bedrock-runtime')
            model_id = get_model_for_plan(customer_plan)
            if 'nova' in model_id:
                br = bedrock.invoke_model(modelId=model_id, body=json.dumps({'schemaVersion': 'messages-v1', 'system': [{'text': 'You are CostGuard AI, an AWS cost optimization assistant. You have access to real AWS cost data AND a live inventory of AWS resources for customer ' + customer_id + '. Answer with specific resource names and IDs. Be concise and actionable.'}], 'messages': [{'role': 'user', 'content': [{'text': ctx + '\nUser Question: ' + question}]}], 'inferenceConfig': {'max_new_tokens': 500}}))
                answer = json.loads(br['body'].read())['output']['message']['content'][0]['text']
            elif 'titan' in model_id:
                br = bedrock.invoke_model(modelId=model_id, body=json.dumps({'inputText': ctx + '\nUser Question: ' + question, 'textGenerationConfig': {'maxTokenCount': 500, 'temperature': 0.7}}))
                answer = json.loads(br['body'].read())['results'][0]['outputText']
            else:
                br = bedrock.invoke_model(modelId=model_id, body=json.dumps({'anthropic_version':'bedrock-2023-05-31','max_tokens':500,'system':'You are CostGuard AI, an AWS cost optimization assistant. You have access to real AWS cost data AND a live inventory of AWS resources for customer ' + customer_id + '. Answer with specific resource names and IDs. Be concise and actionable.','messages':[{'role':'user','content':ctx+'\nUser Question: '+question}]}))
                answer = json.loads(br['body'].read())['content'][0]['text']
            return resp(200, {'answer': answer, 'cost_data': dict(svc_sorted)})

        elif path == '/report':
            import calendar
            month = params.get('month', '')
            if not month or not re.match(r'^\d{4}-\d{2}$', month): return resp(400, {'error': 'month param required (YYYY-MM)'})
            try:
                yr, mn = int(month.split('-')[0]), int(month.split('-')[1])
                last_day = calendar.monthrange(yr, mn)[1]
                ms = month + '-01'; me = month + '-' + str(last_day)
                today = datetime.now().strftime('%Y-%m-%d')
                if me > today: me = today
                ce = boto3.client('ce')
                daily = ce.get_cost_and_usage(TimePeriod={'Start':ms,'End':me},Granularity='DAILY',Metrics=['UnblendedCost'])
                daily_data = [{'date':d['TimePeriod']['Start'],'cost':round(float(d['Total']['UnblendedCost']['Amount']),4)} for d in daily['ResultsByTime']]
                svc = ce.get_cost_and_usage(TimePeriod={'Start':ms,'End':me},Granularity='MONTHLY',Metrics=['UnblendedCost'],GroupBy=[{'Type':'DIMENSION','Key':'SERVICE'}])
                svc_data = []
                for g in (svc['ResultsByTime'][0]['Groups'] if svc['ResultsByTime'] else []):
                    c = round(float(g['Metrics']['UnblendedCost']['Amount']), 4)
                    if c > 0: svc_data.append({'service':g['Keys'][0],'cost':c})
                svc_data.sort(key=lambda x: x['cost'], reverse=True)
                total = sum(d['cost'] for d in daily_data)
                avg = total / len(daily_data) if daily_data else 0
                peak = max(daily_data, key=lambda x: x['cost']) if daily_data else {'date':'N/A','cost':0}
                return resp(200, {'month':month,'total_cost':round(total,2),'avg_daily':round(avg,2),'peak_day':peak,'days':len(daily_data),'daily_costs':daily_data,'service_breakdown':svc_data})
            except Exception as e:
                return resp(500, {'error': 'Cost Explorer may not be enabled. Enable it at https://console.aws.amazon.com/cost-management/home#/cost-explorer. Error: ' + str(e)})

        elif path == '/subscription-status' and method == 'GET':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            # Admin always gets enterprise — no DynamoDB record needed
            if is_admin:
                return resp(200, {'plan': 'enterprise', 'nextBillingDate': None, 'email': caller_email, 'isAdmin': True})
            cust = get_customer_by_email(dynamodb, caller_email)
            if not cust:
                return resp(200, {'plan': 'free', 'nextBillingDate': None, 'email': caller_email})
            return resp(200, {'plan': cust.get('plan', 'free'), 'nextBillingDate': cust.get('nextBillingDate', None), 'email': caller_email})

        elif path == '/create-order' and method == 'POST':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            key_id = os.environ.get('RAZORPAY_KEY_ID', '')
            key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
            if not key_id or not key_secret:
                return resp(500, {'error': 'Payment not configured'})
            amount = 99900  # ₹999 in paise
            credentials = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
            order_payload = json.dumps({
                'amount': amount, 'currency': 'INR',
                'receipt': f'rcpt_{int(time.time())}',
                'notes': {'email': caller_email, 'plan': 'pro'}
            }).encode()
            req = urllib.request.Request(
                'https://api.razorpay.com/v1/orders', data=order_payload,
                headers={'Authorization': f'Basic {credentials}', 'Content-Type': 'application/json'},
                method='POST'
            )
            with urllib.request.urlopen(req) as r:
                order = json.loads(r.read())
            return resp(200, {'orderId': order['id'], 'amount': amount, 'currency': 'INR', 'keyId': key_id})

        elif path == '/verify-payment' and method == 'POST':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            body = json.loads(event.get('body', '{}'))
            order_id   = body.get('razorpay_order_id', '')
            payment_id = body.get('razorpay_payment_id', '')
            signature  = body.get('razorpay_signature', '')
            key_secret = os.environ.get('RAZORPAY_KEY_SECRET', '')
            expected = hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return resp(400, {'error': 'Payment verification failed'})
            cust = get_customer_by_email(dynamodb, caller_email)
            if not cust:
                return resp(404, {'error': 'Customer not found'})
            next_billing = (datetime.now() + timedelta(days=30)).isoformat()
            dynamodb.Table(os.environ['CUSTOMERS_TABLE']).update_item(
                Key={'customerId': cust['customerId']},
                UpdateExpression='SET #p = :p, nextBillingDate = :nb, paymentId = :pid',
                ExpressionAttributeNames={'#p': 'plan'},
                ExpressionAttributeValues={':p': 'pro', ':nb': next_billing, ':pid': payment_id}
            )
            return resp(200, {'message': 'Upgraded to Pro', 'plan': 'pro', 'nextBillingDate': next_billing})

        elif path == '/recommendations' and method == 'GET':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})

            # Get customer info
            customer_plan = 'enterprise' if is_admin else 'free'
            role_arn = None
            if not is_admin:
                cust = get_customer_by_email(dynamodb, caller_email)
                if not cust:
                    return resp(200, {'recommendations': [], 'message': 'Connect your AWS account first'})
                role_arn = cust.get('roleArn')
                customer_plan = cust.get('plan', 'free')

            # Fetch cost data
            try:
                if role_arn:
                    sts = boto3.client('sts')
                    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardRecs')['Credentials']
                    ce = boto3.client('ce', aws_access_key_id=creds['AccessKeyId'],
                                     aws_secret_access_key=creds['SecretAccessKey'],
                                     aws_session_token=creds['SessionToken'])
                else:
                    ce = boto3.client('ce')

                end = datetime.now().strftime('%Y-%m-%d')
                start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
                svc = ce.get_cost_and_usage(
                    TimePeriod={'Start': start, 'End': end},
                    Granularity='MONTHLY', Metrics=['UnblendedCost'],
                    GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
                )
                svc_costs = {}
                for g in (svc['ResultsByTime'][0]['Groups'] if svc['ResultsByTime'] else []):
                    cost = float(g['Metrics']['UnblendedCost']['Amount'])
                    if cost > 0:
                        svc_costs[g['Keys'][0]] = round(cost, 2)
                cost_ctx = 'AWS 30-Day Costs by Service:\n' + '\n'.join(
                    f'  {k}: ${v}' for k, v in sorted(svc_costs.items(), key=lambda x: x[1], reverse=True)[:10]
                )
            except Exception as e:
                cost_ctx = f'Cost data unavailable: {str(e)[:100]}'

            resource_ctx = get_resource_inventory(role_arn)

            prompt = f"""You are an AWS cost optimization expert. Analyze this data and provide exactly 5 actionable savings recommendations.

{cost_ctx}

{resource_ctx}

Return ONLY a valid JSON array (no other text, no markdown) with exactly 5 objects, each having:
- "action": string (specific action to take)
- "saving": number (estimated monthly USD saving, realistic estimate)
- "effort": "Easy" or "Medium" or "Hard"
- "resource": string (specific service, resource name, or "General")
- "reason": string (one sentence explanation)

Example format: [{{"action":"...", "saving":50, "effort":"Easy", "resource":"Amazon EC2", "reason":"..."}}]"""

            try:
                bedrock = boto3.client('bedrock-runtime')
                model_id = get_model_for_plan(customer_plan)
                br = bedrock.invoke_model(
                    modelId=model_id,
                    body=json.dumps({
                        'anthropic_version': 'bedrock-2023-05-31',
                        'max_tokens': 1500,
                        'messages': [{'role': 'user', 'content': prompt}]
                    })
                )
                raw = json.loads(br['body'].read())['content'][0]['text'].strip()
                # Extract JSON array
                match = re.search(r'\[[\s\S]*\]', raw)
                recs = json.loads(match.group()) if match else []
                # Validate and sanitize
                clean_recs = []
                for r in recs[:5]:
                    clean_recs.append({
                        'action': str(r.get('action', ''))[:200],
                        'saving': float(r.get('saving', 0)),
                        'effort': r.get('effort', 'Medium') if r.get('effort') in ['Easy','Medium','Hard'] else 'Medium',
                        'resource': str(r.get('resource', 'General'))[:100],
                        'reason': str(r.get('reason', ''))[:300]
                    })
                return resp(200, {'recommendations': clean_recs, 'generated_at': datetime.now().isoformat()})
            except Exception as e:
                return resp(500, {'error': f'Recommendations failed: {str(e)[:200]}'})

        elif path == '/budgets' and method == 'GET':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            cust = get_customer_by_email(dynamodb, caller_email) if not is_admin else None
            customer_id = 'system' if is_admin else (cust['customerId'] if cust else None)
            if not customer_id:
                return resp(200, {'budgets': []})

            budgets_table = dynamodb.Table(os.environ.get('BUDGETS_TABLE', 'costguard-budgets'))
            try:
                result = budgets_table.query(
                    KeyConditionExpression=boto3.dynamodb.conditions.Key('customerId').eq(customer_id)
                )
                budgets = result['Items']

                # Get actual costs for current month
                now = datetime.now()
                period = params.get('period', now.strftime('%Y-%m'))
                import calendar
                yr, mn = int(period.split('-')[0]), int(period.split('-')[1])
                ms = f'{period}-01'
                last_day = calendar.monthrange(yr, mn)[1]
                me = f'{period}-{last_day:02d}'
                today = now.strftime('%Y-%m-%d')
                if me > today: me = today

                # Fetch actual costs
                role_arn = None if is_admin else (cust.get('roleArn') if cust else None)
                try:
                    if role_arn:
                        sts = boto3.client('sts')
                        creds = sts.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardBudgets')['Credentials']
                        ce = boto3.client('ce', aws_access_key_id=creds['AccessKeyId'],
                                         aws_secret_access_key=creds['SecretAccessKey'],
                                         aws_session_token=creds['SessionToken'])
                    else:
                        ce = boto3.client('ce')
                    svc_data = ce.get_cost_and_usage(
                        TimePeriod={'Start': ms, 'End': me},
                        Granularity='MONTHLY', Metrics=['UnblendedCost'],
                        GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
                    )
                    actuals = {}
                    for g in (svc_data['ResultsByTime'][0]['Groups'] if svc_data['ResultsByTime'] else []):
                        actuals[g['Keys'][0]] = float(g['Metrics']['UnblendedCost']['Amount'])
                except:
                    actuals = {}

                enriched = []
                for b in budgets:
                    budget_amt = float(b.get('budget_amount', 0))
                    actual = actuals.get(b.get('service', ''), 0.0)
                    pct = (actual / budget_amt * 100) if budget_amt > 0 else 0
                    enriched.append({
                        'service': b.get('service', ''),
                        'budget_amount': budget_amt,
                        'actual_cost': round(actual, 2),
                        'period': b.get('period', period),
                        'pct_used': round(pct, 1)
                    })
                return resp(200, {'budgets': enriched, 'period': period})
            except Exception as e:
                return resp(500, {'error': str(e)})

        elif path == '/budgets' and method == 'POST':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            body = json.loads(event.get('body', '{}'))
            service = body.get('service', '').strip()
            budget_amount = float(body.get('budget_amount', 0))
            period = body.get('period', datetime.now().strftime('%Y-%m'))

            if not service or budget_amount <= 0:
                return resp(400, {'error': 'service and budget_amount (>0) required'})

            cust = get_customer_by_email(dynamodb, caller_email) if not is_admin else None
            customer_id = 'system' if is_admin else (cust['customerId'] if cust else None)
            if not customer_id:
                return resp(404, {'error': 'Customer not found. Connect your AWS account first.'})

            budgets_table = dynamodb.Table(os.environ.get('BUDGETS_TABLE', 'costguard-budgets'))
            try:
                budgets_table.put_item(Item={
                    'customerId': customer_id,
                    'service': service,
                    'budget_amount': str(budget_amount),
                    'period': period,
                    'createdAt': datetime.now().isoformat()
                })
                return resp(200, {'message': 'Budget saved', 'service': service, 'budget_amount': budget_amount, 'period': period})
            except Exception as e:
                return resp(500, {'error': str(e)})

        elif path == '/service-detail' and method == 'GET':
            if not caller_email:
                return resp(401, {'error': 'Authentication required'})
            service = params.get('service', '').strip()
            month = params.get('month', '')
            if not service or not month or not re.match(r'^\d{4}-\d{2}$', month):
                return resp(400, {'error': 'service and month (YYYY-MM) required'})

            import calendar
            yr, mn = int(month.split('-')[0]), int(month.split('-')[1])
            ms = f'{month}-01'
            last_day = calendar.monthrange(yr, mn)[1]
            me = f'{month}-{last_day:02d}'
            today = datetime.now().strftime('%Y-%m-%d')
            if me > today: me = today

            cust = get_customer_by_email(dynamodb, caller_email) if not is_admin else None
            role_arn = None if is_admin else (cust.get('roleArn') if cust else None)

            try:
                if role_arn:
                    sts = boto3.client('sts')
                    creds = sts.assume_role(RoleArn=role_arn, RoleSessionName='CostGuardDetail')['Credentials']
                    ce = boto3.client('ce', aws_access_key_id=creds['AccessKeyId'],
                                     aws_secret_access_key=creds['SecretAccessKey'],
                                     aws_session_token=creds['SessionToken'])
                else:
                    ce = boto3.client('ce')

                result = ce.get_cost_and_usage(
                    TimePeriod={'Start': ms, 'End': me},
                    Granularity='MONTHLY', Metrics=['UnblendedCost'],
                    GroupBy=[{'Type': 'DIMENSION', 'Key': 'RESOURCE_ID'}],
                    Filter={'Dimensions': {'Key': 'SERVICE', 'Values': [service]}}
                )
                resources = []
                for g in (result['ResultsByTime'][0]['Groups'] if result['ResultsByTime'] else []):
                    cost = float(g['Metrics']['UnblendedCost']['Amount'])
                    if cost > 0.001:
                        resources.append({'resource_id': g['Keys'][0], 'cost': round(cost, 4)})
                resources.sort(key=lambda x: x['cost'], reverse=True)
                return resp(200, {'service': service, 'month': month, 'resources': resources[:50]})
            except Exception as e:
                return resp(500, {'error': f'Service detail failed: {str(e)[:200]}'})

        else:
            return resp(404, {'error': 'Not found'})

    except Exception as e:
        print('Error: ' + str(e))
        return resp(500, {'error': str(e)})
