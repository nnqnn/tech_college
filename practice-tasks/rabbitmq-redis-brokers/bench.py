import argparse
import csv
import os
import threading
import time
from pathlib import Path

import pika
import redis


def message_body(producer_id, seq, size):
    head = f"{producer_id}-{seq}|{time.time_ns()}|".encode()
    return head + (b"x" * max(0, size - len(head)))


def sent_at_ns(body):
    return int(body.split(b"|", 2)[1])


def retry(name, fn, attempts=40):
    last_error = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"{name} is not ready: {last_error}")


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.sent = 0
        self.processed = 0
        self.errors = 0
        self.latencies = []

    def mark_sent(self):
        with self.lock:
            self.sent += 1

    def mark_error(self):
        with self.lock:
            self.errors += 1

    def mark_processed(self, body):
        try:
            latency_ms = (time.time_ns() - sent_at_ns(body)) / 1_000_000
        except Exception:
            self.mark_error()
            return

        with self.lock:
            self.processed += 1
            self.latencies.append(latency_ms)

    def snapshot(self):
        with self.lock:
            latencies = list(self.latencies)
            sent = self.sent
            processed = self.processed
            errors = self.errors

        latencies.sort()
        p95 = latencies[int((len(latencies) - 1) * 0.95)] if latencies else 0
        avg = sum(latencies) / len(latencies) if latencies else 0
        max_latency = latencies[-1] if latencies else 0
        return sent, processed, errors, avg, p95, max_latency


class RabbitBroker:
    def __init__(self, host, queue):
        self.host = host
        self.queue = queue

    def connect(self):
        params = pika.ConnectionParameters(
            host=self.host,
            heartbeat=0,
            blocked_connection_timeout=5,
        )
        return pika.BlockingConnection(params)

    def setup(self):
        conn = retry("rabbitmq", self.connect)
        ch = conn.channel()
        ch.queue_declare(queue=self.queue, durable=False)
        ch.queue_purge(queue=self.queue)
        conn.close()

    def produce(self, producer_id, args, stats, end_at):
        conn = self.connect()
        ch = conn.channel()
        ch.queue_declare(queue=self.queue, durable=False)
        rate = args.rate / args.producers
        interval = 1 / rate if rate > 0 else 0
        next_at = time.perf_counter()
        seq = 0

        while time.perf_counter() < end_at:
            try:
                ch.basic_publish("", self.queue, message_body(producer_id, seq, args.payload_size))
                stats.mark_sent()
            except Exception:
                stats.mark_error()
            seq += 1
            next_at += interval
            delay = next_at - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

        conn.close()

    def consume(self, consumer_id, stop, stats):
        conn = self.connect()
        ch = conn.channel()
        ch.queue_declare(queue=self.queue, durable=False)
        ch.basic_qos(prefetch_count=1000)

        for method, _, body in ch.consume(self.queue, inactivity_timeout=0.2, auto_ack=True):
            if method:
                stats.mark_processed(body)
            if stop.is_set():
                break

        ch.cancel()
        conn.close()

    def backlog(self):
        conn = self.connect()
        ch = conn.channel()
        result = ch.queue_declare(queue=self.queue, passive=True)
        count = result.method.message_count
        conn.close()
        return count


class RedisBroker:
    def __init__(self, host, queue):
        self.host = host
        self.queue = queue

    def connect(self):
        return redis.Redis(host=self.host, port=6379, socket_timeout=3)

    def setup(self):
        def ready():
            client = self.connect()
            client.ping()
            return client

        client = retry("redis", ready)
        client.delete(self.queue)

    def produce(self, producer_id, args, stats, end_at):
        client = self.connect()
        rate = args.rate / args.producers
        interval = 1 / rate if rate > 0 else 0
        next_at = time.perf_counter()
        seq = 0

        while time.perf_counter() < end_at:
            try:
                client.rpush(self.queue, message_body(producer_id, seq, args.payload_size))
                stats.mark_sent()
            except Exception:
                stats.mark_error()
            seq += 1
            next_at += interval
            delay = next_at - time.perf_counter()
            if delay > 0:
                time.sleep(delay)

    def consume(self, consumer_id, stop, stats):
        client = self.connect()
        while not stop.is_set():
            item = client.blpop(self.queue, timeout=1)
            if item:
                stats.mark_processed(item[1])

    def backlog(self):
        return self.connect().llen(self.queue)


def build_broker(args):
    if args.broker == "rabbit":
        return RabbitBroker(args.rabbit_host, args.queue)
    return RedisBroker(args.redis_host, args.queue)


def write_csv(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys())
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def run(args):
    broker = build_broker(args)
    broker.setup()

    stats = Stats()
    stop = threading.Event()
    consumers = [
        threading.Thread(target=broker.consume, args=(i, stop, stats), daemon=True)
        for i in range(args.consumers)
    ]
    for thread in consumers:
        thread.start()

    time.sleep(0.5)
    started_at = time.perf_counter()
    end_at = started_at + args.duration
    producers = [
        threading.Thread(target=broker.produce, args=(i, args, stats, end_at), daemon=True)
        for i in range(args.producers)
    ]
    for thread in producers:
        thread.start()
    for thread in producers:
        thread.join()

    stop.set()
    for thread in consumers:
        thread.join(timeout=2)

    elapsed = time.perf_counter() - started_at
    backlog = broker.backlog()
    sent, processed, errors, avg_ms, p95_ms, max_ms = stats.snapshot()
    lost = max(0, sent - processed - backlog)

    row = {
        "broker": args.broker,
        "payload_size": args.payload_size,
        "target_rate": args.rate,
        "duration_sec": round(elapsed, 2),
        "producers": args.producers,
        "consumers": args.consumers,
        "sent": sent,
        "processed": processed,
        "backlog": backlog,
        "lost": lost,
        "errors": errors,
        "avg_ms": round(avg_ms, 2),
        "p95_ms": round(p95_ms, 2),
        "max_ms": round(max_ms, 2),
    }

    if args.csv:
        write_csv(args.csv, row)
    print(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", choices=["rabbit", "redis"], required=True)
    parser.add_argument("--payload-size", type=int, required=True)
    parser.add_argument("--rate", type=int, required=True)
    parser.add_argument("--duration", type=int, default=20)
    parser.add_argument("--producers", type=int, default=1)
    parser.add_argument("--consumers", type=int, default=1)
    parser.add_argument("--queue", default="broker_bench")
    parser.add_argument("--csv", default="")
    parser.add_argument("--rabbit-host", default=os.getenv("RABBIT_HOST", "localhost"))
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    run(parser.parse_args())


if __name__ == "__main__":
    main()
