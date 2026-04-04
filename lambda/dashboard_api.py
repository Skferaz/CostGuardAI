import json, boto3, os, uuid, re, time, hashlib
from decimal import Decimal
from datetime import datetime, timedelta
from boto3.dynamodb.conditions import Key

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

        elif path == '/customers':
            r = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()
            return resp(200, {'customers': r['Items'], 'total': r['Count']})

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
            admin_email = os.environ.get('ADMIN_EMAIL', '')
            if caller_email and caller_email == admin_email:
                is_admin = True
                customer_id = 'system'
            elif caller_email:
                try:
                    cust_table = dynamodb.Table(os.environ['CUSTOMERS_TABLE'])
                    cust_scan = cust_table.scan(FilterExpression=boto3.dynamodb.conditions.Attr('email').eq(caller_email))
                    if cust_scan['Items']:
                        customer_id = cust_scan['Items'][0]['customerId']
                        role_arn = cust_scan['Items'][0].get('roleArn', '')
                        if not role_arn: role_arn = None
                except: pass

            # Block unregistered users from seeing any account data
            if not customer_id:
                return resp(200, {'answer': 'Welcome to CostGuard AI! To use the chatbot, please connect your AWS account first.\n\nGo to the **Add Account** page in the sidebar and follow the 3 simple steps to connect your AWS account. Once connected, I can analyze your costs, list your resources, and provide optimization recommendations.', 'cost_data': {}})

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
            model_id = os.environ['BEDROCK_MODEL_ID']
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

        else:
            return resp(404, {'error': 'Not found'})

    except Exception as e:
        print('Error: ' + str(e))
        return resp(500, {'error': str(e)})
