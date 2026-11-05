"""List this key's Purdue models; optionally send one short JSON request, never a report."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values
from jsonschema import validate

from purdue_api import BASE_URL, CHAT_COMPLETIONS_ENDPOINT, account_models, client_for, request_parameters, settings

ROOT=Path(__file__).resolve().parent


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list-only',action='store_true',help='Only discover models; do not generate text')
    args=parser.parse_args(argv)
    key=(dotenv_values(ROOT/'.env').get('API_KEY') or '').strip()
    if not key or key=='paste-here': parser.error('Set API_KEY in .env; never paste it into logs.')
    config=settings()
    snapshot={'provider':'Purdue GenAI Studio','base_url':BASE_URL,'chat_endpoint':CHAT_COMPLETIONS_ENDPOINT,
              'checked_at':datetime.now(timezone.utc).isoformat(),'selected_model':config.model,
              'backend':config.backend,'model_request_sent':False}
    client=client_for(key)
    try:
        snapshot['available_models']=account_models(client)
        snapshot['selected_model_available']=config.model in snapshot['available_models']
        print('Models available to this API key:')
        for model in snapshot['available_models']: print('  '+model.replace(key,'[REDACTED]'))
        if not snapshot['selected_model_available']:
            raise RuntimeError('Configured model is not in the Purdue account model list.')
        if not args.list_only:
            schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
            packet={'task':'Return JSON with ok true.','context':{},'expected_output':{'ok':True}}
            body=request_parameters(config.model,'Return only the JSON object requested.',packet,schema)
            body['max_tokens']=256
            snapshot['model_request_sent']=True
            response=client.chat.completions.create(**body)
            if response is None or not response.choices or response.choices[0].finish_reason!='stop':
                raise RuntimeError('No complete Purdue reply.')
            reply=json.loads(response.choices[0].message.content)
            validate(reply,schema)
            if reply['ok'] is not True: raise RuntimeError('Short request returned an unexpected answer.')
            snapshot['short_request']={'success':True,'model':response.model,'response_id':response.id,
                                       'reply':reply,'finish_reason':response.choices[0].finish_reason}
            print('Short request succeeded using '+response.model+'.')
        snapshot['status']='passed'
    except Exception as exc:
        # Exception text/HTTP headers can contain credentials. Log only safe type/status.
        snapshot.update(status='failed',error_type=type(exc).__name__,http_status=getattr(exc,'status_code',None))
        print('Purdue connection check failed ('+type(exc).__name__+'); no provider fallback was attempted.')
    finally:
        client.close()
    folder=ROOT/'provider_checks'; folder.mkdir(exist_ok=True)
    path=folder/('purdue_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid4().hex[:8]+'.json')
    encoded=json.dumps(snapshot,indent=2).replace(key,'[REDACTED]')
    path.write_text(encoded+'\n')
    print('Check record: '+str(path))
    return 0 if snapshot['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
