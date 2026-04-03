import json, boto3, os, time
from datetime import datetime, timedelta

def retry(fn, retries=3, delay=1):
    for i in range(retries):
        try: return fn()
        except Exception as e:
            if i == retries - 1: raise
            time.sleep(delay * (2 ** i))

def get_ce_client(role_arn=None):
    if role_arn:
        creds = retry(lambda: boto3.client('sts').assume_role(RoleArn=role_arn, RoleSessionName='CostGuard')['Credentials'])
        return boto3.client('ce', aws_access_key_id=creds['AccessKeyId'], aws_secret_access_key=creds['SecretAccessKey'], aws_session_token=creds['SessionToken'])
    return boto3.client('ce')

def analyze_customer(cid, role_arn, email, dynamodb, bedrock, ses):
    ce = get_ce_client(role_arn)
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    wstart = (datetime.now() - timedelta(days=8)).strftime('%Y-%m-%d')
    r = retry(lambda: ce.get_cost_and_usage(TimePeriod={'Start':start,'End':end},Granularity='DAILY',Metrics=['UnblendedCost']))
    ycost = float(r['ResultsByTime'][0]['Total']['UnblendedCost']['Amount']) if r['ResultsByTime'] else 0
    wr = retry(lambda: ce.get_cost_and_usage(TimePeriod={'Start':wstart,'End':start},Granularity='DAILY',Metrics=['UnblendedCost']))
    wc = [float(d['Total']['UnblendedCost']['Amount']) for d in wr['ResultsByTime']]
    avg = sum(wc)/len(wc) if wc else 0
    pct = ((ycost-avg)/avg*100) if avg>0 else 0
    ai = ''
    try:
        model_id = os.environ['BEDROCK_MODEL_ID']
        if 'nova' in model_id:
            br = retry(lambda: bedrock.invoke_model(modelId=model_id,body=json.dumps({'schemaVersion':'messages-v1','system':[{'text':'You are an AWS cost analyst. Provide brief cost insights and recommendations.'}],'messages':[{'role':'user','content':[{'text':'Analyze AWS cost for '+cid+': Yesterday $'+str(round(ycost,2))+', 7-day avg $'+str(round(avg,2))+', change '+str(round(pct,1))+'%. Brief insights.'}]}],'inferenceConfig':{'max_new_tokens':200}})))
            ai = json.loads(br['body'].read())['output']['message']['content'][0]['text']
        else:
            br = retry(lambda: bedrock.invoke_model(modelId=model_id,body=json.dumps({'anthropic_version':'bedrock-2023-05-31','max_tokens':200,'messages':[{'role':'user','content':'Analyze AWS cost for '+cid+': Yesterday $'+str(round(ycost,2))+', 7-day avg $'+str(round(avg,2))+', change '+str(round(pct,1))+'%. Brief insights.'}]})))
            ai = json.loads(br['body'].read())['content'][0]['text']
    except: ai = 'AI analysis unavailable'
    dynamodb.Table(os.environ['COSTS_TABLE']).put_item(Item={'customerId':cid,'date':start,'cost':str(ycost),'avg_cost':str(avg),'percent_change':str(pct),'ai_analysis':ai,'timestamp':datetime.now().isoformat()})
    if pct > 20:
        dynamodb.Table(os.environ['ALERTS_TABLE']).put_item(Item={'alertId':cid+'-spike-'+start,'customerId':cid,'service':'AWS','percentChange':str(pct),'aiExplanation':ai,'timestamp':datetime.now().isoformat()})
        if email:
            try: ses.send_email(Source=os.environ['ALERT_EMAIL'],Destination={'ToAddresses':[email]},Message={'Subject':{'Data':'CostGuard: '+str(round(pct,1))+'% Spike'},'Body':{'Text':{'Data':'Spike for '+cid+': $'+str(round(ycost,2))+' vs $'+str(round(avg,2))+' avg\n\nAI: '+ai}}})
            except: pass
    return {'customer_id':cid,'cost':ycost,'avg':avg,'pct':pct,'alert':pct>20}

def handler(event, context):
    dynamodb = boto3.resource('dynamodb')
    bedrock = boto3.client('bedrock-runtime')
    ses = boto3.client('ses')
    results = []
    # SQS fan-out: process single customer from SQS message
    if 'Records' in event:
        for record in event['Records']:
            c = json.loads(record['body'])
            try: results.append(analyze_customer(c['customerId'],c.get('roleArn'),c.get('email'),dynamodb,bedrock,ses))
            except Exception as e: print('Error for '+c['customerId']+': '+str(e)); raise
        return {'processed': len(results)}
    # Direct invocation: enqueue all customers to SQS or process directly
    try:
        sqs_url = os.environ.get('SQS_QUEUE_URL')
        results.append(analyze_customer('system',None,os.environ['ALERT_EMAIL'],dynamodb,bedrock,ses))
        customers = dynamodb.Table(os.environ['CUSTOMERS_TABLE']).scan()['Items']
        if sqs_url and customers:
            sqs = boto3.client('sqs')
            for c in customers:
                sqs.send_message(QueueUrl=sqs_url, MessageBody=json.dumps({'customerId':c['customerId'],'roleArn':c.get('roleArn',''),'email':c.get('email','')}))
            return {'statusCode':200,'body':json.dumps({'status':'success','system_processed':True,'customers_queued':len(customers)})}
        else:
            for c in customers:
                try: results.append(analyze_customer(c['customerId'],c.get('roleArn'),c.get('email'),dynamodb,bedrock,ses))
                except Exception as e: results.append({'customer_id':c['customerId'],'error':str(e)})
        return {'statusCode':200,'body':json.dumps({'status':'success','processed':len(results)})}
    except Exception as e:
        print('Error: '+str(e))
        return {'statusCode':500,'body':json.dumps({'error':str(e)})}
