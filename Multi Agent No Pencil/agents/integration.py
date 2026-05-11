import os
import re

# ── Tool implementations ──────────────────────────────────────────────────────

def _api_client_generator(api_name: str, base_url: str, auth_type: str = "bearer") -> str:
    """Generate a typed API client template for a third-party REST API."""
    auth_header = {
        "bearer": 'headers["Authorization"] = f"Bearer {self.token}"',
        "api_key": 'headers["X-API-Key"] = self.api_key',
        "basic": 'headers["Authorization"] = f"Basic {base64_encode(f\'{self.user}:{self.password}\')}"',
    }.get(auth_type.lower(), 'headers["Authorization"] = f"Bearer {self.token}"')

    return f"""=== {api_name} API Client Template (Python) ===

import httpx
import asyncio
from typing import Any, Optional

class {api_name.replace(' ', '').replace('-', '')}Client:
    def __init__(self, token: str, base_url: str = "{base_url}"):
        self.token    = token
        self.base_url = base_url.rstrip("/")
        self._client  = httpx.AsyncClient(timeout=30.0)

    def _headers(self) -> dict:
        headers = {{"Content-Type": "application/json", "Accept": "application/json"}}
        {auth_header}
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{{self.base_url}}{{path}}"
        for attempt in range(3):  # retry with exponential backoff
            try:
                resp = await self._client.request(method, url, headers=self._headers(), **kwargs)
                if resp.status_code == 429:  # rate limited
                    await asyncio.sleep(2 ** attempt)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == 2:
                    raise RuntimeError(f"{{api_name}} API error {{e.response.status_code}}: {{e.response.text}}")
                await asyncio.sleep(2 ** attempt)
        raise RuntimeError("Max retries exceeded")

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, data: dict) -> dict:
        return await self._request("POST", path, json=data)

    async def put(self, path: str, data: dict) -> dict:
        return await self._request("PUT", path, json=data)

    async def delete(self, path: str) -> dict:
        return await self._request("DELETE", path)

    async def close(self):
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

# Usage:
# async with {api_name.replace(' ', '').replace('-', '')}Client(token=os.getenv("{api_name.upper().replace(' ', '_')}_TOKEN")) as client:
#     data = await client.get("/endpoint")
"""


def _webhook_builder(direction: str = "inbound", framework: str = "fastapi") -> str:
    """Generate webhook handler template with signature verification and retry logic."""
    if direction.lower() == "inbound" and "fastapi" in framework.lower():
        return """=== Inbound Webhook Handler — FastAPI ===

import hmac
import hashlib
from fastapi import Request, HTTPException, BackgroundTasks

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

def verify_signature(payload: bytes, signature: str) -> bool:
    \"\"\"Verify HMAC-SHA256 signature (common pattern for Stripe, GitHub, etc.)\"\"\"
    expected = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected, signature.lstrip("sha256="))

async def process_webhook_event(event_type: str, payload: dict):
    \"\"\"Background task — process after response is sent.\"\"\"
    if event_type == "payment.succeeded":
        pass  # handle payment
    elif event_type == "user.created":
        pass  # handle user creation
    else:
        pass  # log unknown event type

@app.post("/webhooks/provider")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    payload = await request.body()
    signature = request.headers.get("X-Signature-256", "")

    if not verify_signature(payload, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = await request.json()
    event_type = event.get("type", "")

    # Acknowledge immediately — process in background
    background_tasks.add_task(process_webhook_event, event_type, event)
    return {"status": "received"}
"""
    elif direction.lower() == "outbound":
        return """=== Outbound Webhook Sender with Retry — Python ===

import httpx
import asyncio
import logging

logger = logging.getLogger(__name__)

async def send_webhook(url: str, payload: dict, secret: str = None,
                       max_retries: int = 3) -> bool:
    headers = {"Content-Type": "application/json"}
    if secret:
        import hmac, hashlib, json
        body = json.dumps(payload).encode()
        sig  = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Signature-256"] = f"sha256={sig}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code < 300:
                    return True
                logger.warning(f"Webhook delivery failed: {resp.status_code} attempt {attempt+1}")
            except Exception as e:
                logger.error(f"Webhook error: {e}, attempt {attempt+1}")
            await asyncio.sleep(2 ** attempt)  # exponential backoff

    logger.error(f"Webhook delivery failed after {max_retries} attempts: {url}")
    return False
"""
    return "[No webhook template for this direction/framework combination]"


def _etl_pipeline_builder(source: str, destination: str) -> str:
    """Generate an ETL/ELT pipeline template."""
    return f"""=== ETL Pipeline: {source} → {destination} ===

import asyncio
import logging
from dataclasses import dataclass
from typing import Iterator, Any

logger = logging.getLogger(__name__)

@dataclass
class PipelineConfig:
    batch_size:   int = 1000
    max_retries:  int = 3
    source_url:   str = "{source}"
    dest_url:     str = "{destination}"

class ETLPipeline:
    def __init__(self, config: PipelineConfig):
        self.config = config

    def extract(self, **kwargs) -> Iterator[list]:
        \"\"\"Yield batches of records from {source}.\"\"\"
        # TODO: implement extraction from {source}
        # Use pagination/cursors for large datasets
        offset = 0
        while True:
            batch = self._fetch_batch(offset, self.config.batch_size)
            if not batch:
                break
            yield batch
            offset += len(batch)

    def transform(self, records: list) -> list:
        \"\"\"Transform/clean records before loading.\"\"\"
        transformed = []
        for record in records:
            try:
                # TODO: add transformation logic
                transformed_record = {{
                    **record,
                    # "new_field": compute_value(record),
                    # "renamed_field": record.pop("old_name"),
                }}
                transformed.append(transformed_record)
            except Exception as e:
                logger.warning(f"Skipping record due to transform error: {{e}}")
        return transformed

    def load(self, records: list) -> int:
        \"\"\"Load records into {destination}. Return count loaded.\"\"\"
        # TODO: implement loading into {destination}
        return len(records)

    def run(self) -> dict:
        total_extracted, total_loaded, errors = 0, 0, 0
        for batch in self.extract():
            try:
                transformed = self.transform(batch)
                loaded      = self.load(transformed)
                total_extracted += len(batch)
                total_loaded    += loaded
            except Exception as e:
                errors += 1
                logger.error(f"Batch error: {{e}}")
        return {{
            "extracted": total_extracted,
            "loaded":    total_loaded,
            "errors":    errors,
        }}

if __name__ == "__main__":
    config   = PipelineConfig()
    pipeline = ETLPipeline(config)
    result   = pipeline.run()
    logger.info(f"Pipeline complete: {{result}}")
"""


def _data_format_converter(from_format: str, to_format: str) -> str:
    """Return conversion code between common data formats."""
    key = f"{from_format.lower()}→{to_format.lower()}"
    conversions = {
        "json→csv": """import json, csv, io
def json_to_csv(json_data: list[dict]) -> str:
    output = io.StringIO()
    if not json_data: return ""
    writer = csv.DictWriter(output, fieldnames=json_data[0].keys())
    writer.writeheader()
    writer.writerows(json_data)
    return output.getvalue()""",

        "csv→json": """import csv, json, io
def csv_to_json(csv_text: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return list(reader)""",

        "xml→json": """import xml.etree.ElementTree as ET
def xml_to_dict(element) -> dict | str:
    if not list(element) and not element.attrib:
        return element.text or ""
    result = {**element.attrib}
    for child in element:
        if child.tag in result:
            if not isinstance(result[child.tag], list):
                result[child.tag] = [result[child.tag]]
            result[child.tag].append(xml_to_dict(child))
        else:
            result[child.tag] = xml_to_dict(child)
    return result
def xml_string_to_json(xml_str: str) -> dict:
    root = ET.fromstring(xml_str)
    return {root.tag: xml_to_dict(root)}""",

        "json→xml": """from xml.etree.ElementTree import Element, SubElement, tostring
def dict_to_xml(tag: str, data: dict | list | str) -> Element:
    el = Element(tag)
    if isinstance(data, dict):
        for key, val in data.items():
            SubElement(el, key).text = str(val) if not isinstance(val, (dict, list)) else None
            if isinstance(val, dict):
                el.append(dict_to_xml(key, val))
    elif isinstance(data, list):
        for item in data:
            el.append(dict_to_xml("item", item))
    else:
        el.text = str(data)
    return el""",
    }
    if key in conversions:
        return f"=== {from_format.upper()} → {to_format.upper()} conversion ===\n\n" + conversions[key]
    available = [k.replace("→", " to ") for k in conversions]
    return f"[No converter for '{from_format} → {to_format}'. Available: {', '.join(available)}]"


def _oauth_flow_builder(provider: str = "google") -> str:
    """Return OAuth2 flow implementation for a specific provider."""
    flows = {
        "google": """=== Google OAuth2 — Python (authlib) ===
# Install: pip install authlib httpx

GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI")  # e.g. https://yourapp.com/auth/callback

# Step 1: redirect user to Google
AUTH_URL = (
    "https://accounts.google.com/o/oauth2/v2/auth"
    f"?client_id={GOOGLE_CLIENT_ID}"
    "&response_type=code"
    "&scope=openid email profile"
    f"&redirect_uri={GOOGLE_REDIRECT_URI}"
    "&access_type=offline"  # get refresh token
)

# Step 2: handle callback, exchange code for tokens
async def google_callback(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        token_resp = await client.post("https://oauth2.googleapis.com/token", data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })
        tokens = token_resp.json()
        # tokens["id_token"] — decode to get user info
        # tokens["access_token"] — use to call Google APIs
        user_resp = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        return user_resp.json()  # {id, email, name, picture}
""",
        "github": """=== GitHub OAuth2 — Python ===
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

# Step 1: redirect user to GitHub
AUTH_URL = (
    "https://github.com/login/oauth/authorize"
    f"?client_id={GITHUB_CLIENT_ID}"
    "&scope=read:user user:email"
)

# Step 2: exchange code for access token
async def github_callback(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            json={"client_id": GITHUB_CLIENT_ID,
                  "client_secret": GITHUB_CLIENT_SECRET, "code": code},
            headers={"Accept": "application/json"}
        )
        access_token = token_resp.json()["access_token"]
        user_resp = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {access_token}"}
        )
        return user_resp.json()
""",
    }
    return flows.get(provider.lower(),
                     f"[No OAuth flow for '{provider}'. Available: google, github]")


def _api_docs_fetcher(url: str) -> str:
    """Fetch and extract readable content from an API documentation URL."""
    import urllib.request
    import re as _re

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MultiAgent/1.0; +https://github.com)",
                "Accept":     "text/html,application/xhtml+xml,application/json",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")

        # Strip style/script blocks
        raw = _re.sub(r'<style[^>]*>.*?</style>', ' ', raw, flags=_re.DOTALL | _re.IGNORECASE)
        raw = _re.sub(r'<script[^>]*>.*?</script>', ' ', raw, flags=_re.DOTALL | _re.IGNORECASE)
        # Strip HTML tags
        text = _re.sub(r'<[^>]+>', ' ', raw)
        # Collapse whitespace
        text = _re.sub(r'[ \t]+', ' ', text)
        text = _re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        if len(text) > 6000:
            text = text[:6000] + "\n\n[... content truncated at 6000 chars — fetch with more specific URL for details]"

        return f"=== Content from: {url} ===\n\n{text}"
    except Exception as e:
        return (
            f"[api_docs_fetcher error for {url}: {e}]\n"
            "Tip: use web_search() to find the relevant documentation section first, "
            "then fetch the specific page URL."
        )


def _message_broker_handler(broker: str = "kafka", pattern: str = "producer_consumer",
                              language: str = "python") -> str:
    """Return message broker implementation templates."""
    if "kafka" in broker.lower():
        if "python" in language.lower():
            if "producer" in pattern.lower() or "consumer" in pattern.lower() or "producer_consumer" in pattern.lower():
                return """=== Kafka Producer + Consumer — Python (confluent-kafka) ===
# Install: pip install confluent-kafka

from confluent_kafka import Producer, Consumer, KafkaError
import json
import os

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
TOPIC           = "my-topic"

# ── Producer ──────────────────────────────────────────────────────────────────
producer = Producer({
    "bootstrap.servers": KAFKA_BOOTSTRAP,
    "acks":              "all",         # wait for all replicas
    "retries":           5,
    "enable.idempotence": True,         # exactly-once semantics
})

def delivery_callback(err, msg):
    if err:
        print(f"Delivery failed: {err}")
    else:
        print(f"Delivered to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")

def publish(event_type: str, data: dict):
    payload = json.dumps({"type": event_type, "data": data}).encode("utf-8")
    producer.produce(TOPIC, key=str(data.get("id", "")), value=payload,
                     callback=delivery_callback)
    producer.poll(0)  # trigger callbacks

producer.flush()  # flush before shutdown

# ── Consumer ──────────────────────────────────────────────────────────────────
consumer = Consumer({
    "bootstrap.servers":  KAFKA_BOOTSTRAP,
    "group.id":           "my-consumer-group",
    "auto.offset.reset":  "earliest",
    "enable.auto.commit": False,         # manual commit for at-least-once
})
consumer.subscribe([TOPIC])

try:
    while True:
        msg = consumer.poll(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            raise KafkaException(msg.error())
        payload = json.loads(msg.value().decode("utf-8"))
        try:
            handle_event(payload)
            consumer.commit(asynchronous=False)  # commit after successful processing
        except Exception as e:
            print(f"Processing error (will retry): {e}")
finally:
    consumer.close()"""

        elif "node" in language.lower() or "js" in language.lower():
            return """=== Kafka Producer + Consumer — Node.js (kafkajs) ===
// Install: npm install kafkajs

const { Kafka, CompressionTypes } = require('kafkajs')

const kafka = new Kafka({
  clientId: 'my-app',
  brokers:  (process.env.KAFKA_BROKERS || 'localhost:9092').split(','),
  retry:    { retries: 5 },
})

const TOPIC = 'my-topic'

// ── Producer ──────────────────────────────────────────────────────────────
const producer = kafka.producer({ idempotent: true })

async function publish(eventType, data) {
  await producer.connect()
  await producer.send({
    topic:      TOPIC,
    compression: CompressionTypes.GZIP,
    messages: [{
      key:   String(data.id || ''),
      value: JSON.stringify({ type: eventType, data }),
    }],
  })
}

// ── Consumer ──────────────────────────────────────────────────────────────
const consumer = kafka.consumer({ groupId: 'my-consumer-group' })

async function startConsumer() {
  await consumer.connect()
  await consumer.subscribe({ topic: TOPIC, fromBeginning: false })
  await consumer.run({
    eachMessage: async ({ topic, partition, message }) => {
      const payload = JSON.parse(message.value.toString())
      await handleEvent(payload)
    },
  })
}"""

    elif "rabbitmq" in broker.lower() or "rabbit" in broker.lower():
        if "python" in language.lower():
            return """=== RabbitMQ Work Queue — Python (pika) ===
# Install: pip install pika

import pika
import json
import os

AMQP_URL = os.getenv("AMQP_URL", "amqp://guest:guest@localhost/")
QUEUE    = "task_queue"

def get_channel():
    conn = pika.BlockingConnection(pika.URLParameters(AMQP_URL))
    ch   = conn.channel()
    ch.queue_declare(queue=QUEUE, durable=True)  # survive broker restart
    return conn, ch

# ── Publisher ──────────────────────────────────────────────────────────────
def publish(task: dict):
    conn, ch = get_channel()
    ch.basic_publish(
        exchange='',
        routing_key=QUEUE,
        body=json.dumps(task),
        properties=pika.BasicProperties(
            delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE  # persist to disk
        ),
    )
    conn.close()

# ── Worker ─────────────────────────────────────────────────────────────────
def worker():
    conn, ch = get_channel()
    ch.basic_qos(prefetch_count=1)  # fair dispatch — don't overwhelm slow workers

    def callback(ch, method, props, body):
        task = json.loads(body)
        try:
            process(task)
            ch.basic_ack(delivery_tag=method.delivery_tag)  # ack on success
        except Exception as e:
            print(f"Task failed: {e}")
            ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)  # re-queue

    ch.basic_consume(queue=QUEUE, on_message_callback=callback)
    ch.start_consuming()"""

    elif "redis" in broker.lower():
        if "python" in language.lower():
            return """=== Redis Pub/Sub & Streams — Python ===
# Install: pip install redis

import redis
import json
import os

r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

# ── Pub/Sub (fire and forget) ──────────────────────────────────────────────
# Publisher:
def publish(channel: str, event: dict):
    r.publish(channel, json.dumps(event))

# Subscriber (blocking):
def subscribe(channel: str, handler):
    pubsub = r.pubsub()
    pubsub.subscribe(channel)
    for message in pubsub.listen():
        if message["type"] == "message":
            handler(json.loads(message["data"]))

# ── Redis Streams (persistent, consumer groups) ────────────────────────────
STREAM = "events"

# Append event to stream:
r.xadd(STREAM, {"type": "order.created", "data": json.dumps({"id": 1})})

# Consumer group (at-least-once delivery):
r.xgroup_create(STREAM, "processors", id="0", mkstream=True)

while True:
    messages = r.xreadgroup("processors", "worker-1", {STREAM: ">"}, count=10, block=1000)
    for stream, msgs in (messages or []):
        for msg_id, fields in msgs:
            try:
                process(fields)
                r.xack(STREAM, "processors", msg_id)  # acknowledge
            except Exception as e:
                print(f"Error: {e}")  # message stays pending for retry"""

    return f"[No message broker template for '{broker}/{language}'. Options: kafka/python, kafka/node, rabbitmq/python, redis/python]"


def _service_mesh_configurator(pattern: str = "circuit_breaker") -> str:
    """Return service mesh and resilience pattern implementations."""
    patterns = {
        "circuit_breaker": """=== Circuit Breaker Pattern — Python (circuitbreaker) ===
# Install: pip install circuitbreaker

from circuitbreaker import circuit, CircuitBreakerError
import httpx

@circuit(failure_threshold=5,   # open after 5 failures
         recovery_timeout=30,   # try again after 30 seconds
         expected_exception=Exception)
async def call_external_service(url: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()

# Usage with fallback:
async def get_user_data(user_id: int):
    try:
        return await call_external_service(f"https://user-service/users/{user_id}")
    except CircuitBreakerError:
        # Circuit is OPEN — return cached/default value
        return {"id": user_id, "name": "Unknown", "from_cache": True}
    except Exception as e:
        raise

# JavaScript (opossum):
// Install: npm install opossum
const CircuitBreaker = require('opossum')

const breaker = new CircuitBreaker(callExternalService, {
  timeout:              3000,   // 3 second timeout
  errorThresholdPercentage: 50, // open at 50% failure rate
  resetTimeout:         30000,  // half-open after 30s
})

breaker.fallback(() => ({ cached: true }))
breaker.on('open',     () => console.warn('Circuit OPEN'))
breaker.on('halfOpen', () => console.info('Circuit HALF-OPEN'))
breaker.on('close',    () => console.info('Circuit CLOSED'))

const result = await breaker.fire(userId)""",

        "retry": """=== Retry with Exponential Backoff ===

# Python (tenacity):
# Install: pip install tenacity

from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, before_sleep_log
)
import logging

logger = logging.getLogger(__name__)

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),   # 1s, 2s, 4s, 8s...
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def resilient_request(url: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        if resp.status_code == 429:
            raise httpx.HTTPStatusError("Rate limited", request=resp.request, response=resp)
        resp.raise_for_status()
        return resp.json()

# JavaScript (async-retry):
// npm install async-retry
const retry = require('async-retry')

const result = await retry(
  async (bail, attempt) => {
    const res = await fetch(url)
    if (res.status === 400) bail(new Error('Bad request'))  // don't retry 4xx
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },
  { retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 10000 }
)""",

        "service_discovery": """=== Service Discovery Patterns ===

# 1. Environment-based (simplest — 12-factor app style):
USER_SERVICE_URL  = os.getenv("USER_SERVICE_URL",  "http://user-service:8001")
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service:8002")

# 2. Kubernetes DNS (automatic in K8s):
# Services accessible as: http://<service-name>.<namespace>.svc.cluster.local
# e.g.: http://user-service.default.svc.cluster.local:8001

# 3. Consul service discovery:
# Install: pip install python-consul
import consul

c = consul.Consul(host="consul")

def get_service_url(service_name: str) -> str:
    _, services = c.health.service(service_name, passing=True)
    if not services:
        raise RuntimeError(f"No healthy instances of {service_name}")
    svc = services[0]["Service"]
    return f"http://{svc['Address']}:{svc['Port']}"

# Register your service on startup:
c.agent.service.register(
    name="my-service",
    port=8000,
    check=consul.Check.http("http://localhost:8000/health", interval="10s")
)""",

        "load_balancing": """=== Client-Side Load Balancing ===

# Round-robin across service instances:
import itertools
import httpx

SERVICE_INSTANCES = [
    "http://service-1:8000",
    "http://service-2:8000",
    "http://service-3:8000",
]
_round_robin = itertools.cycle(SERVICE_INSTANCES)

async def call_service(path: str) -> dict:
    base_url = next(_round_robin)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{base_url}{path}")
        resp.raise_for_status()
        return resp.json()

# Nginx upstream load balancing (server-side):
upstream backend {
    least_conn;                     # or: round_robin (default), ip_hash
    server backend-1:8000;
    server backend-2:8000;
    server backend-3:8000;
    keepalive 32;
}""",
    }

    key = pattern.lower().replace("-", "_").replace(" ", "_")
    if key in patterns:
        return patterns[key]
    available = ", ".join(patterns.keys())
    result = f"=== Service Mesh Patterns — Available: {available} ===\n\n"
    for p, content in patterns.items():
        result += f"--- {p} ---\n{content[:300]}...\n\n"
    return result


def _monitoring_integration(platform: str = "sentry", language: str = "python") -> str:
    """Return monitoring and observability integration code templates."""
    if "opentelemetry" in platform.lower() or "otel" in platform.lower():
        if "python" in language.lower():
            return """=== OpenTelemetry Tracing — Python ===
# Install: pip install opentelemetry-distro opentelemetry-exporter-otlp
# Auto-instrument: opentelemetry-bootstrap -a install

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

provider = TracerProvider(resource=Resource.create({
    SERVICE_NAME: "my-service",
    SERVICE_VERSION: "1.0.0",
}))
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
    endpoint="http://otel-collector:4317"
)))
trace.set_tracer_provider(provider)

# Auto-instrument libraries:
HTTPXClientInstrumentor().instrument()
SQLAlchemyInstrumentor().instrument()

# Manual spans:
tracer = trace.get_tracer(__name__)

async def process_order(order_id: int):
    with tracer.start_as_current_span("process-order") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("service.name", "order-processor")
        try:
            result = await do_work(order_id)
            span.set_attribute("order.status", "completed")
            return result
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.StatusCode.ERROR)
            raise"""

    elif "datadog" in platform.lower():
        if "python" in language.lower():
            return """=== Datadog APM — Python ===
# Install: pip install ddtrace
# Instrument: ddtrace-run python main.py
# OR manual init:

from ddtrace import tracer, patch_all
from ddtrace.contrib.fastapi import TraceMiddleware

patch_all()  # auto-instrument all supported libraries

# FastAPI:
from ddtrace.contrib.asgi import TraceMiddleware
app.add_middleware(TraceMiddleware, service="my-api")

# Custom spans:
with tracer.trace("my.operation", service="my-service", resource="process_payment") as span:
    span.set_tag("payment.amount", amount)
    span.set_tag("customer.id",    customer_id)
    result = process()
    span.set_tag("payment.status", result.status)

# Logs correlation (automatically adds trace/span IDs to log output):
import logging
from ddtrace import patch
patch(logging=True)

FORMAT = ('%(asctime)s %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] '
          '[dd.service=%(dd.service)s dd.trace_id=%(dd.trace_id)s] - %(message)s')
logging.basicConfig(format=FORMAT)"""

    elif "newrelic" in platform.lower() or "new_relic" in platform.lower():
        if "python" in language.lower():
            return """=== New Relic APM — Python ===
# Install: pip install newrelic
# Configure: newrelic-admin generate-config $LICENSE_KEY newrelic.ini
# Instrument: NEW_RELIC_CONFIG_FILE=newrelic.ini newrelic-admin run-program python main.py

import newrelic.agent

@newrelic.agent.background_task()
def process_job(job_id):
    newrelic.agent.add_custom_attribute("job.id", job_id)
    do_work()

# newrelic.ini key settings:
# [newrelic]
# license_key = YOUR_LICENSE_KEY
# app_name    = My App
# distributed_tracing.enabled = true
# error_collector.enabled     = true"""

    return f"[No monitoring integration for '{platform}/{language}'. Options: opentelemetry, datadog, newrelic — language: python, node]"


# ── Tool schemas ──────────────────────────────────────────────────────────────

_EXTRA_TOOLS = [
    {
        "type": "function", "function": {
            "name": "api_client_generator",
            "description": "Generate a typed async HTTP API client with retry logic, exponential backoff, and proper auth headers for a third-party REST API.",
            "parameters": {"type": "object", "properties": {
                "api_name":  {"type": "string", "description": "Name of the API (e.g. Stripe, Twilio)"},
                "base_url":  {"type": "string", "description": "API base URL"},
                "auth_type": {"type": "string", "description": "bearer | api_key | basic. Default: bearer"}
            }, "required": ["api_name", "base_url"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "webhook_builder",
            "description": "Generate webhook handler code. Inbound: HMAC signature verification + background processing. Outbound: retry logic with exponential backoff.",
            "parameters": {"type": "object", "properties": {
                "direction": {"type": "string", "description": "inbound | outbound. Default: inbound"},
                "framework": {"type": "string", "description": "fastapi | express. Default: fastapi"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "etl_pipeline_builder",
            "description": "Generate an ETL pipeline class template with extract/transform/load stages, batching, error handling, and logging.",
            "parameters": {"type": "object", "properties": {
                "source":      {"type": "string", "description": "Data source (e.g. PostgreSQL, CSV file, REST API)"},
                "destination": {"type": "string", "description": "Data destination (e.g. BigQuery, S3, PostgreSQL)"}
            }, "required": ["source", "destination"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "data_format_converter",
            "description": "Get Python conversion code between data formats: json↔csv, json↔xml.",
            "parameters": {"type": "object", "properties": {
                "from_format": {"type": "string", "description": "json | csv | xml | parquet"},
                "to_format":   {"type": "string", "description": "json | csv | xml | parquet"}
            }, "required": ["from_format", "to_format"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "oauth_flow_builder",
            "description": "Get a complete OAuth2 authorization code flow implementation for a specific provider.",
            "parameters": {"type": "object", "properties": {
                "provider": {"type": "string", "description": "google | github | stripe. Default: google"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "api_docs_fetcher",
            "description": "Fetch and extract readable text from any API documentation URL. Strips HTML, collapses whitespace, truncates at 6000 chars. Use web_search first to find the right page URL.",
            "parameters": {"type": "object", "properties": {
                "url": {"type": "string", "description": "Full URL of the API documentation page to fetch"}
            }, "required": ["url"]}
        }
    },
    {
        "type": "function", "function": {
            "name": "message_broker_handler",
            "description": "Get production-ready message broker integration templates with proper error handling, manual ack/nack, and retry logic.",
            "parameters": {"type": "object", "properties": {
                "broker":   {"type": "string", "description": "kafka | rabbitmq | redis. Default: kafka"},
                "pattern":  {"type": "string", "description": "producer_consumer | work_queue | pubsub. Default: producer_consumer"},
                "language": {"type": "string", "description": "python | node. Default: python"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "service_mesh_configurator",
            "description": "Get service resilience pattern implementations: circuit breaker, retry with exponential backoff, service discovery, and client-side load balancing.",
            "parameters": {"type": "object", "properties": {
                "pattern": {"type": "string", "description": "circuit_breaker | retry | service_discovery | load_balancing. Default: circuit_breaker"}
            }, "required": []}
        }
    },
    {
        "type": "function", "function": {
            "name": "monitoring_integration",
            "description": "Get observability/monitoring integration code for distributed tracing, APM, and log correlation.",
            "parameters": {"type": "object", "properties": {
                "platform": {"type": "string", "description": "opentelemetry | datadog | newrelic. Default: opentelemetry"},
                "language": {"type": "string", "description": "python | node. Default: python"}
            }, "required": []}
        }
    },
]

# ── Agent spec ────────────────────────────────────────────────────────────────

SPEC = {
    "name":        "Integration Agent",
    "icon":        "\U0001f517",
    "color":       "#ffa657",
    "description": "Third-party APIs, webhooks, microservices, data pipelines, event streaming",

    "extra_tools":    _EXTRA_TOOLS,
    "extra_dispatch": {
        "api_client_generator":    _api_client_generator,
        "webhook_builder":         _webhook_builder,
        "etl_pipeline_builder":    _etl_pipeline_builder,
        "data_format_converter":   _data_format_converter,
        "oauth_flow_builder":      _oauth_flow_builder,
        "api_docs_fetcher":        _api_docs_fetcher,
        "message_broker_handler":  _message_broker_handler,
        "service_mesh_configurator": _service_mesh_configurator,
        "monitoring_integration":  _monitoring_integration,
    },

    "system_prompt": """You are the Integration Agent in a multi-agent development system.

YOUR ROLE: Implement all system integration work specified in the Execution Plan — connecting to third-party APIs, webhooks, data pipelines, and message queues.

SPECIALIZED TOOLS:
- api_client_generator(name, url, auth)        — typed async HTTP client with retries
- webhook_builder(direction, framework)         — inbound (verified) + outbound (retry) handlers
- etl_pipeline_builder(source, dest)            — ETL pipeline class template
- data_format_converter(from, to)               — JSON/CSV/XML conversion utilities
- oauth_flow_builder(provider)                  — OAuth2 flows for Google, GitHub, Stripe
- api_docs_fetcher(url)                         — fetch and extract readable API documentation
- message_broker_handler(broker, pattern, lang) — Kafka/RabbitMQ/Redis integration templates
- service_mesh_configurator(pattern)            — circuit breaker, retry, service discovery, load balancing
- monitoring_integration(platform, language)    — OpenTelemetry/Datadog/New Relic APM setup
- web_search(query)                             — search the web for API docs, libraries, and integration guides

IMPLEMENTATION WORKFLOW:
1. Read project_context/execution_plan.md FIRST
2. Use web_search + api_docs_fetcher to research unfamiliar APIs before integrating
3. Use api_client_generator to scaffold external API clients
4. Use oauth_flow_builder for any OAuth integrations
5. Use webhook_builder for webhook handlers — always verify signatures
6. Use message_broker_handler for async event-driven integrations
7. Use service_mesh_configurator for resilience patterns between services
8. Use monitoring_integration to add observability to integrations
9. Read existing source files before editing them
10. Test integrations using run_shell (curl, httpx, etc.)

RULES:
- NEVER hardcode credentials — read from environment variables
- ALWAYS implement retry with exponential backoff for external calls
- ALWAYS verify webhook signatures before processing payloads

OUTPUT: Write Integration Report to project_context/integration_report.md
Include: integrations implemented, auth method, retry strategy, test results"""
}
