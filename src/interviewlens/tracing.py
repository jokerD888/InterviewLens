"""Keep explicit parent traces across SDK versions and self-hosted v2.

SDK 4 removed trace()/generation() and end(output=..., usage=...). The small
adapter below keeps our explicit-parent protocol without implicit thread-local
context. Legacy ingestion is opt-in for a v2 server; new servers use OTel.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx


def _usage(values: dict) -> dict:
    values = dict(values)
    usage = values.pop("usage", None)
    if usage:
        values["usage_details"] = {
            "input": usage.get("prompt_tokens", 0),
            "output": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)),
        }
    return values


def _legacy_fields(values: dict) -> dict:
    values = dict(values)
    if "status_message" in values:
        values["statusMessage"] = values.pop("status_message")
    usage = values.pop("usage", None)
    if usage:
        values["usage"] = {"input": usage.get("prompt_tokens", 0), "output": usage.get("completion_tokens", 0), "unit": "TOKENS"}
    return values


class Observation:
    def __init__(self, observation):
        self.observation = observation
        self.ended = False

    def generation(self, **values):
        return Observation(self.observation.start_observation(as_type="generation", **_usage(values)))

    def span(self, **values):
        return Observation(self.observation.start_observation(as_type="span", **values))

    def update(self, **values):
        self.observation.update(**_usage(values))

    def end(self, **values):
        if not self.ended:
            if values:
                self.update(**values)
            self.observation.end()
            self.ended = True


class OTelClient:
    def __init__(self, client):
        self.client = client

    def trace(self, **values):
        return Observation(self.client.start_observation(as_type="span", **values))

    def flush(self):
        self.client.flush()


class LegacyClient:
    """Bounded, synchronous exporter for an existing v2 installation.

    Call flush in a worker thread. Keep failed batches for a later attempt, with
    stable event IDs for server deduplication. No unbounded retry or disk queue.
    """
    def __init__(self, *, host: str, public_key: str, secret_key: str):
        self.http = httpx.Client(base_url=host.rstrip("/"), auth=(public_key, secret_key), timeout=5)
        self.events: list[dict] = []
        self.lock = threading.Lock()
        self.flush_lock = threading.Lock()

    def emit(self, event_type: str, body: dict):
        event = {"id": uuid.uuid4().hex, "timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, "body": body}
        with self.lock:
            if len(self.events) >= 1000:
                raise RuntimeError("Langfuse pending event buffer full")
            self.events.append(event)

    def trace(self, **values):
        trace = LegacyObservation(self, "trace", uuid.uuid4().hex)
        self.emit("trace-create", {"id": trace.id, **values})
        return trace

    def flush(self):
        with self.flush_lock:
            with self.lock:
                batch = self.events[:100]
            while batch:
                response = self.http.post("/api/public/ingestion", json={"batch": batch})
                response.raise_for_status()
                # Ingestion reports event-level validation failures with HTTP 207.
                if response.json().get("errors"):
                    raise RuntimeError("Langfuse rejected ingestion events")
                with self.lock:
                    del self.events[:len(batch)]
                    batch = self.events[:100]


class LegacyObservation:
    def __init__(self, client: LegacyClient, kind: str, trace_id: str, parent: str | None = None):
        self.client, self.kind, self.trace_id, self.parent = client, kind, trace_id, parent
        self.id = trace_id if kind == "trace" else uuid.uuid4().hex
        self.ended = False

    def _child(self, kind: str, values: dict):
        child = LegacyObservation(self.client, kind, self.trace_id, None if self.kind == "trace" else self.id)
        body = {"id": child.id, "traceId": self.trace_id, "startTime": datetime.now(timezone.utc).isoformat(), **_legacy_fields(values)}
        if child.parent:
            body["parentObservationId"] = child.parent
        self.client.emit(f"{kind}-create", body)
        return child

    def generation(self, **values):
        return self._child("generation", values)

    def span(self, **values):
        return self._child("span", values)

    def update(self, **values):
        self.client.emit("trace-create" if self.kind == "trace" else f"{self.kind}-update", {"id": self.id, **_legacy_fields(values)})

    def end(self, **values):
        if not self.ended:
            if self.kind != "trace":
                values["endTime"] = datetime.now(timezone.utc).isoformat()
            if values:
                self.update(**values)
            self.ended = True


def end_trace(trace: Any | None) -> None:
    # SDK 2 root traces have no end(); modern root observations must be ended.
    end = getattr(trace, "end", None)
    if callable(end):
        end()
