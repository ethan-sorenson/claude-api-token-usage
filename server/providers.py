"""
Multi-provider API abstraction for chat completions.

Translates between provider-specific request/response formats and a
normalised Anthropic-like format so the front-end SSE parser works
unchanged regardless of which provider is used.

Supported providers: Anthropic, OpenAI, Google (Gemini), Mistral.
"""

import json
import logging
import requests

logger = logging.getLogger(__name__)

# Default pricing per million tokens – used when the AllowedModels table
# does not have per-model pricing configured.
DEFAULT_PRICING = {
    'anthropic': {'input': 3.00, 'output': 15.00},
    'openai':    {'input': 2.50, 'output': 10.00},
    'google':    {'input': 0.10, 'output': 0.40},
    'mistral':   {'input': 2.00, 'output': 6.00},
}


# ── Public helpers ──────────────────────────────────────────────────────

def get_provider(provider_name: str):
    """Return the provider handler for *provider_name* (case-insensitive)."""
    _providers = {
        'anthropic': AnthropicProvider(),
        'openai':    OpenAIProvider(),
        'google':    GoogleProvider(),
        'mistral':   MistralProvider(),
    }
    return _providers.get((provider_name or '').lower())


def get_pricing(provider: str, model: str = None, db=None):
    """Return ``(input_price_per_token, output_price_per_token)``.

    Checks the *AllowedModels* table first; falls back to
    ``DEFAULT_PRICING``.
    """
    if db and model:
        try:
            for m in db.list_allowed_models():
                if m['model_id'] == model:
                    ip = m.get('input_price')
                    op = m.get('output_price')
                    if ip is not None and op is not None:
                        return float(ip) / 1_000_000, float(op) / 1_000_000
        except Exception:
            pass

    defaults = DEFAULT_PRICING.get(provider, DEFAULT_PRICING['anthropic'])
    return defaults['input'] / 1_000_000, defaults['output'] / 1_000_000


# ── Helpers for message format conversion ───────────────────────────────

def _content_blocks_to_text(content):
    """Convert Anthropic-style content blocks ``[{type, text}, …]`` to a
    plain string suitable for OpenAI / Mistral / Google messages."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get('type') == 'text':
                    parts.append(c.get('text', ''))
                elif c.get('type') == 'thinking':
                    parts.append(c.get('thinking', ''))
            elif isinstance(c, str):
                parts.append(c)
        return '\n'.join(parts) if parts else ''
    return str(content)


def _convert_to_openai_messages(messages):
    """Anthropic → OpenAI/Mistral message list."""
    converted = []
    for msg in messages:
        role = msg.get('role', 'user')
        content = _content_blocks_to_text(msg.get('content', ''))
        converted.append({'role': role, 'content': content})
    return converted


def _convert_to_gemini(messages):
    """Anthropic → Gemini ``contents`` + optional ``systemInstruction``."""
    system_text = None
    contents = []

    for msg in messages:
        role = msg.get('role', '')
        raw = msg.get('content', '')

        if role == 'system':
            system_text = _content_blocks_to_text(raw)
            continue

        gemini_role = 'model' if role == 'assistant' else 'user'
        text = _content_blocks_to_text(raw)
        contents.append({'role': gemini_role, 'parts': [{'text': text}]})

    return contents, system_text


# ═══════════════════════════════════════════════════════════════════════
# Provider implementations
# ═══════════════════════════════════════════════════════════════════════

class BaseProvider:
    """Abstract base for all AI chat providers."""

    name = 'base'
    default_model = ''

    # -- request building ------------------------------------------------

    def build_headers(self, api_key, **kwargs):
        raise NotImplementedError

    def build_url(self, **kwargs):
        raise NotImplementedError

    def build_payload(self, model, messages, max_tokens, stream=False, **kwargs):
        raise NotImplementedError

    # -- response parsing ------------------------------------------------

    def parse_response(self, resp_json):
        """Parse a non-streaming JSON response into normalised format."""
        raise NotImplementedError

    def parse_stream_events(self, response):
        """Yield normalised SSE JSON strings from a streaming ``Response``."""
        raise NotImplementedError

    def parse_error(self, resp):
        """Return a dict ``{error: str}`` from a failed ``Response``."""
        try:
            body = resp.json()
        except Exception:
            return {'error': f'API request failed with status {resp.status_code}'}
        err = body.get('error', body)
        if isinstance(err, dict):
            msg = err.get('message', str(err))
        else:
            msg = str(err)
        return {'error': msg}

    # -- credit / key validation ----------------------------------------

    def check_credit(self, api_key):
        raise NotImplementedError

    # -- usage normalisation --------------------------------------------

    def normalize_usage(self, usage_data):
        """Return ``{input_tokens, output_tokens, …}``."""
        raise NotImplementedError


# ── Anthropic ───────────────────────────────────────────────────────────

class AnthropicProvider(BaseProvider):
    name = 'anthropic'
    default_model = 'claude-sonnet-4-20250514'
    api_url = 'https://api.anthropic.com/v1/messages'
    api_version = '2023-06-01'

    def build_headers(self, api_key, **kwargs):
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': self.api_version,
        }
        if kwargs.get('use_mcp'):
            headers['anthropic-beta'] = 'mcp-client-2025-11-20'
        return headers

    def build_url(self, **kwargs):
        return self.api_url

    def build_payload(self, model, messages, max_tokens, stream=False, **kwargs):
        payload = {
            'model': model or self.default_model,
            'max_tokens': max_tokens,
            'messages': messages,
        }
        if stream:
            payload['stream'] = True
        if kwargs.get('mcp_servers'):
            payload['mcp_servers'] = kwargs['mcp_servers']
        if kwargs.get('tools'):
            payload['tools'] = kwargs['tools']
        if kwargs.get('temperature') is not None:
            payload['temperature'] = min(float(kwargs['temperature']), 1.0)
        if kwargs.get('top_p') is not None:
            payload['top_p'] = float(kwargs['top_p'])
        if kwargs.get('stop_sequences'):
            payload['stop_sequences'] = list(kwargs['stop_sequences'])
        return payload

    # Anthropic responses are already in the target format.
    def parse_response(self, resp_json):
        return resp_json

    def parse_stream_events(self, response):
        """Pass-through: Anthropic's SSE *is* the normalised format."""
        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode('utf-8')
            if not text.startswith('data: '):
                continue
            data_str = text[6:]
            if data_str.strip() == '[DONE]':
                continue
            yield data_str

    def check_credit(self, api_key):
        headers = {
            'x-api-key': api_key,
            'anthropic-version': self.api_version,
            'content-type': 'application/json',
        }
        resp = requests.get(
            'https://api.anthropic.com/v1/models?limit=1',
            headers=headers, timeout=15,
        )
        if resp.status_code == 401:
            return {'error': 'Invalid API key', 'valid': False, 'status': 401}
        if resp.status_code == 403:
            return {'error': 'API key does not have permission', 'valid': False, 'status': 403}
        if resp.status_code == 402:
            return {
                'valid': True, 'credit_status': 'exhausted',
                'message': 'Your API credit has been exhausted. '
                           'Please add more credit at console.anthropic.com.',
                'status': 200,
            }
        if resp.status_code != 200:
            try:
                msg = resp.json().get('error', {}).get('message',
                      f'API returned status {resp.status_code}')
            except Exception:
                msg = f'API returned status {resp.status_code}'
            return {'error': msg, 'status': resp.status_code}

        h = resp.headers
        return {
            'valid': True,
            'credit_status': 'active',
            'rate_limits': {k: v for k, v in {
                'requests_limit': h.get('anthropic-ratelimit-requests-limit'),
                'requests_remaining': h.get('anthropic-ratelimit-requests-remaining'),
                'requests_reset': h.get('anthropic-ratelimit-requests-reset'),
                'tokens_limit': h.get('anthropic-ratelimit-tokens-limit'),
                'tokens_remaining': h.get('anthropic-ratelimit-tokens-remaining'),
                'tokens_reset': h.get('anthropic-ratelimit-tokens-reset'),
                'input_tokens_limit': h.get('anthropic-ratelimit-input-tokens-limit'),
                'input_tokens_remaining': h.get('anthropic-ratelimit-input-tokens-remaining'),
                'output_tokens_limit': h.get('anthropic-ratelimit-output-tokens-limit'),
                'output_tokens_remaining': h.get('anthropic-ratelimit-output-tokens-remaining'),
            }.items() if v is not None},
            'status': 200,
        }

    def normalize_usage(self, usage):
        return {
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'cache_creation_input_tokens': usage.get('cache_creation_input_tokens', 0),
            'cache_read_input_tokens': usage.get('cache_read_input_tokens', 0),
        }


# ── OpenAI ──────────────────────────────────────────────────────────────

class OpenAIProvider(BaseProvider):
    name = 'openai'
    default_model = 'gpt-4o'
    api_url = 'https://api.openai.com/v1/chat/completions'

    def build_headers(self, api_key, **kwargs):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }

    def build_url(self, **kwargs):
        return self.api_url

    def build_payload(self, model, messages, max_tokens, stream=False, **kwargs):
        payload = {
            'model': model or self.default_model,
            'max_tokens': max_tokens,
            'messages': _convert_to_openai_messages(messages),
        }
        if stream:
            payload['stream'] = True
            payload['stream_options'] = {'include_usage': True}
        if kwargs.get('tools'):
            payload['tools'] = kwargs['tools']
        if kwargs.get('temperature') is not None:
            payload['temperature'] = float(kwargs['temperature'])
        if kwargs.get('top_p') is not None:
            payload['top_p'] = float(kwargs['top_p'])
        if kwargs.get('stop_sequences'):
            payload['stop'] = list(kwargs['stop_sequences'])
        return payload

    def parse_response(self, resp_json):
        choices = resp_json.get('choices', [])
        content = []
        stop_reason = None
        if choices:
            msg = choices[0].get('message', {})
            if msg.get('content'):
                content = [{'type': 'text', 'text': msg['content']}]
            stop_reason = choices[0].get('finish_reason')

        return {
            'id': resp_json.get('id'),
            'model': resp_json.get('model'),
            'content': content,
            'stop_reason': stop_reason,
            'usage': self.normalize_usage(resp_json.get('usage', {})),
            'provider': 'openai',
        }

    def extract_tool_calls(self, resp_json):
        """Return tool calls from an OpenAI response, or empty list."""
        choices = resp_json.get('choices', [])
        if not choices:
            return []
        msg = choices[0].get('message', {})
        raw_calls = msg.get('tool_calls', [])
        result = []
        for tc in raw_calls:
            fn = tc.get('function', {})
            try:
                args = json.loads(fn.get('arguments', '{}'))
            except (json.JSONDecodeError, TypeError):
                args = {}
            result.append({
                'id': tc.get('id', ''),
                'name': fn.get('name', ''),
                'arguments': args,
            })
        return result

    def append_tool_results(self, payload, resp_json, tool_results):
        """Append assistant tool-call msg + tool results to payload."""
        choices = resp_json.get('choices', [])
        if choices:
            payload['messages'].append(choices[0].get('message', {}))
        for tr in tool_results:
            content = tr['result']
            if not isinstance(content, str):
                content = json.dumps(content)
            payload['messages'].append({
                'role': 'tool',
                'tool_call_id': tr['id'],
                'content': content,
            })

    _FINISH_REASON_MAP = {
        'stop': 'end_turn',
        'length': 'max_tokens',
        'tool_calls': 'tool_use',
        'content_filter': 'content_filter',
    }

    def parse_stream_events(self, response):
        sent_start = False
        _stop_reason = 'end_turn'

        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode('utf-8')
            if not text.startswith('data: '):
                continue
            data_str = text[6:]
            if data_str.strip() == '[DONE]':
                continue

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            # Emit message_start on first chunk
            if not sent_start:
                sent_start = True
                yield json.dumps({
                    'type': 'message_start',
                    'message': {
                        'id': event.get('id', ''),
                        'model': event.get('model', ''),
                        'usage': {'input_tokens': 0, 'output_tokens': 0},
                    },
                })
                yield json.dumps({
                    'type': 'content_block_start',
                    'index': 0,
                    'content_block': {'type': 'text', 'text': ''},
                })

            choices = event.get('choices', [])
            if choices:
                delta = choices[0].get('delta', {})
                chunk = delta.get('content', '')
                if chunk:
                    yield json.dumps({
                        'type': 'content_block_delta',
                        'index': 0,
                        'delta': {'type': 'text_delta', 'text': chunk},
                    })
                finish = choices[0].get('finish_reason')
                if finish:
                    _stop_reason = self._FINISH_REASON_MAP.get(finish, finish)
                    yield json.dumps({'type': 'content_block_stop', 'index': 0})

            # OpenAI sends usage in the final chunk when include_usage=true
            if event.get('usage'):
                yield json.dumps({
                    'type': 'message_delta',
                    'delta': {'stop_reason': _stop_reason},
                    'usage': self.normalize_usage(event['usage']),
                })

    def check_credit(self, api_key):
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        resp = requests.get(
            'https://api.openai.com/v1/models',
            headers=headers, timeout=15,
        )
        if resp.status_code == 401:
            return {'error': 'Invalid API key', 'valid': False, 'status': 401}
        if resp.status_code == 403:
            return {'error': 'API key does not have permission', 'valid': False, 'status': 403}
        if resp.status_code != 200:
            return {'error': f'API returned status {resp.status_code}', 'status': resp.status_code}

        return {
            'valid': True,
            'credit_status': 'active',
            'message': 'OpenAI API key is valid.',
            'status': 200,
        }

    def normalize_usage(self, usage):
        return {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
        }


# ── Google (Gemini) ─────────────────────────────────────────────────────

class GoogleProvider(BaseProvider):
    name = 'google'
    default_model = 'gemini-2.0-flash'

    def build_headers(self, api_key, **kwargs):
        # Google uses the key as a query parameter, not a header.
        return {'Content-Type': 'application/json'}

    def build_url(self, model=None, stream=False, api_key=None, **kwargs):
        model = model or self.default_model
        base = f'https://generativelanguage.googleapis.com/v1beta/models/{model}'
        if stream:
            return f'{base}:streamGenerateContent?alt=sse&key={api_key}'
        return f'{base}:generateContent?key={api_key}'

    def build_payload(self, model, messages, max_tokens, stream=False, **kwargs):
        contents, system_text = _convert_to_gemini(messages)
        payload = {
            'contents': contents,
            'generationConfig': {'maxOutputTokens': max_tokens},
        }
        if system_text:
            payload['systemInstruction'] = {'parts': [{'text': system_text}]}
        if kwargs.get('tools'):
            payload['tools'] = kwargs['tools']
        return payload

    def parse_response(self, resp_json):
        candidates = resp_json.get('candidates', [])
        content = []
        stop_reason = None

        if candidates:
            for p in candidates[0].get('content', {}).get('parts', []):
                if 'text' in p:
                    content.append({'type': 'text', 'text': p['text']})
            finish = candidates[0].get('finishReason', '')
            stop_reason = 'end_turn' if finish == 'STOP' else (finish.lower() or None)

        usage_meta = resp_json.get('usageMetadata', {})
        return {
            'model': resp_json.get('modelVersion', ''),
            'content': content,
            'stop_reason': stop_reason,
            'usage': self.normalize_usage(usage_meta),
            'provider': 'google',
        }

    def extract_tool_calls(self, resp_json):
        """Return tool calls from a Gemini response, or empty list."""
        candidates = resp_json.get('candidates', [])
        if not candidates:
            return []
        parts = candidates[0].get('content', {}).get('parts', [])
        result = []
        for i, p in enumerate(parts):
            if 'functionCall' in p:
                fc = p['functionCall']
                result.append({
                    'id': f"call_{i}",
                    'name': fc.get('name', ''),
                    'arguments': fc.get('args', {}),
                })
        return result

    def append_tool_results(self, payload, resp_json, tool_results):
        """Append model functionCall + user functionResponse to contents."""
        candidates = resp_json.get('candidates', [])
        if candidates:
            model_content = candidates[0].get('content', {})
            payload['contents'].append(model_content)
        response_parts = []
        for tr in tool_results:
            res = tr['result']
            if not isinstance(res, dict):
                res = {'result': res}
            response_parts.append({
                'functionResponse': {
                    'name': tr['name'],
                    'response': res,
                }
            })
        if response_parts:
            payload['contents'].append({'role': 'user', 'parts': response_parts})

    def parse_stream_events(self, response):
        sent_start = False
        last_usage = {}

        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode('utf-8')
            if not text.startswith('data: '):
                continue
            data_str = text[6:]

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if not sent_start:
                sent_start = True
                yield json.dumps({
                    'type': 'message_start',
                    'message': {
                        'id': '',
                        'model': event.get('modelVersion', ''),
                        'usage': {'input_tokens': 0, 'output_tokens': 0},
                    },
                })
                yield json.dumps({
                    'type': 'content_block_start',
                    'index': 0,
                    'content_block': {'type': 'text', 'text': ''},
                })

            candidates = event.get('candidates', [])
            if candidates:
                for p in candidates[0].get('content', {}).get('parts', []):
                    if 'text' in p:
                        yield json.dumps({
                            'type': 'content_block_delta',
                            'index': 0,
                            'delta': {'type': 'text_delta', 'text': p['text']},
                        })
                if candidates[0].get('finishReason'):
                    yield json.dumps({'type': 'content_block_stop', 'index': 0})

            if event.get('usageMetadata'):
                last_usage = event['usageMetadata']

        # Emit final usage after all chunks
        if last_usage:
            yield json.dumps({
                'type': 'message_delta',
                'delta': {'stop_reason': 'end_turn'},
                'usage': self.normalize_usage(last_usage),
            })

    def parse_error(self, resp):
        try:
            body = resp.json()
        except Exception:
            return {'error': f'Google API returned status {resp.status_code}'}
        err = body.get('error', {})
        if isinstance(err, dict):
            return {'error': err.get('message', f'Google API returned status {resp.status_code}')}
        return {'error': str(err)}

    def check_credit(self, api_key):
        resp = requests.get(
            f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=1',
            timeout=15,
        )
        if resp.status_code == 400:
            try:
                body = resp.json()
            except Exception:
                body = {}
            if 'API_KEY_INVALID' in str(body):
                return {'error': 'Invalid API key', 'valid': False, 'status': 401}
            return {'error': str(body.get('error', {}).get('message', 'Bad request')),
                    'valid': False, 'status': 400}
        if resp.status_code == 403:
            return {'error': 'API key does not have permission', 'valid': False, 'status': 403}
        if resp.status_code != 200:
            return {'error': f'API returned status {resp.status_code}', 'status': resp.status_code}

        return {
            'valid': True,
            'credit_status': 'active',
            'message': 'Google API key is valid.',
            'status': 200,
        }

    def normalize_usage(self, usage):
        return {
            'input_tokens': usage.get('promptTokenCount', 0),
            'output_tokens': usage.get('candidatesTokenCount', 0),
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
        }


# ── Mistral ─────────────────────────────────────────────────────────────

class MistralProvider(BaseProvider):
    name = 'mistral'
    default_model = 'mistral-large-latest'
    api_url = 'https://api.mistral.ai/v1/chat/completions'

    def build_headers(self, api_key, **kwargs):
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }

    def build_url(self, **kwargs):
        return self.api_url

    def build_payload(self, model, messages, max_tokens, stream=False, **kwargs):
        payload = {
            'model': model or self.default_model,
            'max_tokens': max_tokens,
            'messages': _convert_to_openai_messages(messages),
        }
        if stream:
            payload['stream'] = True
        if kwargs.get('tools'):
            payload['tools'] = kwargs['tools']
        if kwargs.get('temperature') is not None:
            payload['temperature'] = min(float(kwargs['temperature']), 1.0)
        if kwargs.get('top_p') is not None:
            payload['top_p'] = float(kwargs['top_p'])
        if kwargs.get('stop_sequences'):
            payload['stop'] = list(kwargs['stop_sequences'])
        return payload

    def parse_response(self, resp_json):
        choices = resp_json.get('choices', [])
        content = []
        stop_reason = None
        if choices:
            msg = choices[0].get('message', {})
            if msg.get('content'):
                content = [{'type': 'text', 'text': msg['content']}]
            stop_reason = choices[0].get('finish_reason')

        return {
            'id': resp_json.get('id'),
            'model': resp_json.get('model'),
            'content': content,
            'stop_reason': stop_reason,
            'usage': self.normalize_usage(resp_json.get('usage', {})),
            'provider': 'mistral',
        }

    def extract_tool_calls(self, resp_json):
        """Return tool calls from a Mistral response, or empty list."""
        choices = resp_json.get('choices', [])
        if not choices:
            return []
        msg = choices[0].get('message', {})
        raw_calls = msg.get('tool_calls', [])
        result = []
        for tc in raw_calls:
            fn = tc.get('function', {})
            try:
                args = json.loads(fn.get('arguments', '{}'))
            except (json.JSONDecodeError, TypeError):
                args = {}
            result.append({
                'id': tc.get('id', ''),
                'name': fn.get('name', ''),
                'arguments': args,
            })
        return result

    def append_tool_results(self, payload, resp_json, tool_results):
        """Append assistant tool-call msg + tool results to payload."""
        choices = resp_json.get('choices', [])
        if choices:
            payload['messages'].append(choices[0].get('message', {}))
        for tr in tool_results:
            content = tr['result']
            if not isinstance(content, str):
                content = json.dumps(content)
            payload['messages'].append({
                'role': 'tool',
                'tool_call_id': tr['id'],
                'content': content,
            })

    _FINISH_REASON_MAP = {
        'stop': 'end_turn',
        'length': 'max_tokens',
        'tool_calls': 'tool_use',
    }

    def parse_stream_events(self, response):
        sent_start = False
        _stop_reason = 'end_turn'

        for line in response.iter_lines():
            if not line:
                continue
            text = line.decode('utf-8')
            if not text.startswith('data: '):
                continue
            data_str = text[6:]
            if data_str.strip() == '[DONE]':
                continue

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if not sent_start:
                sent_start = True
                yield json.dumps({
                    'type': 'message_start',
                    'message': {
                        'id': event.get('id', ''),
                        'model': event.get('model', ''),
                        'usage': {'input_tokens': 0, 'output_tokens': 0},
                    },
                })
                yield json.dumps({
                    'type': 'content_block_start',
                    'index': 0,
                    'content_block': {'type': 'text', 'text': ''},
                })

            choices = event.get('choices', [])
            if choices:
                delta = choices[0].get('delta', {})
                chunk = delta.get('content', '')
                if chunk:
                    yield json.dumps({
                        'type': 'content_block_delta',
                        'index': 0,
                        'delta': {'type': 'text_delta', 'text': chunk},
                    })
                finish = choices[0].get('finish_reason')
                if finish:
                    _stop_reason = self._FINISH_REASON_MAP.get(finish, finish)
                    yield json.dumps({'type': 'content_block_stop', 'index': 0})

            if event.get('usage'):
                yield json.dumps({
                    'type': 'message_delta',
                    'delta': {'stop_reason': _stop_reason},
                    'usage': self.normalize_usage(event['usage']),
                })

    def check_credit(self, api_key):
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        resp = requests.get(
            'https://api.mistral.ai/v1/models',
            headers=headers, timeout=15,
        )
        if resp.status_code == 401:
            return {'error': 'Invalid API key', 'valid': False, 'status': 401}
        if resp.status_code == 403:
            return {'error': 'API key does not have permission', 'valid': False, 'status': 403}
        if resp.status_code != 200:
            return {'error': f'API returned status {resp.status_code}', 'status': resp.status_code}

        return {
            'valid': True,
            'credit_status': 'active',
            'message': 'Mistral API key is valid.',
            'status': 200,
        }

    def normalize_usage(self, usage):
        return {
            'input_tokens': usage.get('prompt_tokens', 0),
            'output_tokens': usage.get('completion_tokens', 0),
            'cache_creation_input_tokens': 0,
            'cache_read_input_tokens': 0,
        }
