"""Exercise explicit parent/usage semantics and actual legacy HTTP envelopes."""
from types import SimpleNamespace

import httpx
import pytest

from interviewlens.tracing import LegacyClient, OTelClient, end_trace


def test_sdk4_end_updates_before_closing_and_children_keep_parent():
    calls = []
    class Span:
        def start_observation(self, **kwargs):
            calls.append(('child', self, kwargs))
            return Span()
        def update(self, **kwargs):
            calls.append(('update', self, kwargs))
        # Strict SDK 4 signature: kwargs such as output must not reach end().
        def end(self):
            calls.append(('end', self))
    root = Span()
    client = OTelClient(SimpleNamespace(start_observation=lambda **kwargs: root))
    trace = client.trace(name='answerer')
    generation = trace.generation(name='answer', model='test')
    generation.end(output='answer', usage={'prompt_tokens': 4, 'completion_tokens': 7})
    generation.end()
    end_trace(trace)
    assert calls[0][1] is root
    assert calls[1][2] == {'output': 'answer', 'usage_details': {'input': 4, 'output': 7, 'total': 11}}
    assert [c[0] for c in calls] == ['child', 'update', 'end', 'end']


def test_legacy_event_batch_has_parent_usage_times_and_survives_partial_error():
    requests = []
    def handler(request):
        import json
        requests.append(json.loads(request.content))
        return httpx.Response(207, json={'errors': [{'id': 'invalid'}] if len(requests) == 1 else [], 'successes': []})
    client = LegacyClient(host='https://langfuse.example', public_key='pk', secret_key='sk')
    client.http.close()
    client.http = httpx.Client(base_url='https://langfuse.example', transport=httpx.MockTransport(handler))
    trace = client.trace(name='answerer')
    span = trace.span(name='node')
    generation = span.generation(name='answer', model='model')
    generation.end(output='new answer', usage={'prompt_tokens': 10, 'completion_tokens': 20})
    span.end()
    end_trace(trace)
    with pytest.raises(RuntimeError, match='rejected'):
        client.flush()
    client.flush()
    assert requests[0] == requests[1]  # identical IDs make retry idempotent
    batch = requests[1]['batch']
    assert batch[2]['body']['parentObservationId'] == span.id
    assert batch[3]['body']['usage'] == {'input': 10, 'output': 20, 'unit': 'TOKENS'}
    assert batch[3]['body']['endTime'] >= batch[2]['body']['startTime']
    assert client.events == []


def test_legacy_generation_creation_maps_aggregate_usage():
    client = LegacyClient(host='https://langfuse.example', public_key='pk', secret_key='sk')
    trace = client.trace(name='aggregate')
    trace.generation(name='summary', usage={'prompt_tokens': 10, 'completion_tokens': 20}).end()
    assert client.events[1]['body']['usage'] == {'input': 10, 'output': 20, 'unit': 'TOKENS'}


def test_legacy_buffer_is_bounded():
    client = LegacyClient(host='https://langfuse.example', public_key='pk', secret_key='sk')
    for _ in range(1000):
        client.trace(name='test')
    with pytest.raises(RuntimeError, match='buffer full'):
        client.trace(name='overflow')
    assert len(client.events) == 1000
