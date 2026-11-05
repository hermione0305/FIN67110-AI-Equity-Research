"""Purdue-only OpenAI-compatible Chat Completions transport. No paid fallback."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from functools import lru_cache
from pathlib import Path

BASE_URL = 'https://genai.rcac.purdue.edu/api'
CHAT_COMPLETIONS_ENDPOINT = BASE_URL + '/chat/completions'
MODELS_ENDPOINT = BASE_URL + '/models'
CONFIG_PATH = Path(__file__).resolve().with_name('purdue_genai.json')


@dataclass(frozen=True)
class Settings:
    model: str
    backend: str
    max_tokens: int
    timeout_seconds: int
    context_window: int = 65536
    context_margin: int = 2048


def settings():
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    if (config.get('base_url') != BASE_URL
            or config.get('chat_completions_endpoint') != CHAT_COMPLETIONS_ENDPOINT
            or config.get('models_endpoint') != MODELS_ENDPOINT
            or config.get('fallback_provider') is not None):
        raise ValueError('Only the documented Purdue GenAI Studio endpoints are allowed; no provider fallback.')
    if not isinstance(config.get('model'),str) or not config['model'].strip():
        raise ValueError('Configure an exact model ID returned by Purdue /api/models.')
    if config.get('backend') not in {'vllm','ollama'}:
        raise ValueError('Purdue backend must be vllm or ollama.')
    if not isinstance(config.get('max_tokens'),int) or not 1 <= config['max_tokens'] <= 32000:
        raise ValueError('Invalid Purdue output token limit.')
    window=config.get('context_window',16384 if config['model']=='llama4:latest' else 65536)
    margin=config.get('context_margin',2048)
    if not isinstance(window,int) or not isinstance(margin,int) or margin<512 or window<=config['max_tokens']+margin:
        raise ValueError('Invalid Purdue context window or safety margin.')
    return Settings(config['model'],config['backend'],config['max_tokens'],config.get('timeout_seconds',240),window,margin)


def client_for(key):
    from openai import OpenAI
    import httpx
    # Request/response headers must never enter debug logs, including when a
    # caller has OPENAI_LOG=debug in their shell. Audit logs are handled separately.
    for name in ('openai','openai._base_client','httpx','httpcore'):
        logging.getLogger(name).setLevel(logging.WARNING)
    return OpenAI(api_key=key,base_url=BASE_URL,max_retries=0,timeout=settings().timeout_seconds,
                  http_client=httpx.Client(follow_redirects=False))


def check_client_origin(client):
    url = getattr(client,'base_url',None)
    if url is not None and str(url).rstrip('/') != BASE_URL:
        raise ValueError('Model client must target Purdue GenAI Studio; paid-provider fallback is disabled.')


def account_models(client):
    check_client_origin(client)
    listing = client.models.list()
    if listing is None or not isinstance(getattr(listing,'data',None),list):
        raise RuntimeError('Purdue did not return a valid model list; do not guess a model ID.')
    return sorted({row.id for row in listing.data if isinstance(getattr(row,'id',None),str)})


def request_parameters(model, instructions, packet, schema):
    config = settings()
    kwargs = {'model':model,'messages':[{'role':'system','content':instructions},
                                      {'role':'user','content':json.dumps(packet,ensure_ascii=False,separators=(',',':'))}],
              'max_tokens':config.max_tokens,'stream':False}
    if config.backend == 'vllm':
        kwargs['response_format'] = {'type':'json_schema','json_schema':{
            'name':'node_output','schema':schema}}
    else:
        # The OpenAI-compatible SDK passes Purdue's Ollama-specific field through.
        kwargs['extra_body'] = {'format':schema}
    return kwargs


@lru_cache(maxsize=1)
def local_encoder():
    import tiktoken
    return tiktoken.get_encoding('o200k_harmony')


def request_budget(body):
    """Conservative local budget, including schema, output allowance and margin.

    The server's exact chat template can differ. Its deployed context window is
    authoritative; never assume an upstream model's larger advertised capacity.
    """
    config=settings(); encoder=local_encoder()
    messages=sum(len(encoder.encode(row['content'],disallowed_special=())) for row in body['messages'])
    schema=body.get('response_format') or body.get('extra_body',{})
    schema_tokens=len(encoder.encode(json.dumps(schema,separators=(',',':')),disallowed_special=()))
    estimated=messages+schema_tokens+512
    output=body.get('max_tokens',config.max_tokens)
    return {'estimated_input_tokens':estimated,'requested_output_tokens':output,
            'safety_margin_tokens':config.context_margin,'context_window':config.context_window,
            'fits':estimated+output+config.context_margin<=config.context_window,
            'tokenizer':'o200k_harmony','schema_tokens_included':True}
