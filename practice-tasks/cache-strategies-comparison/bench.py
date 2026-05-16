import argparse
import csv
import os
import random
import statistics
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
import redis


WORKLOADS = {
    "read-heavy": 80,
    "balanced": 50,
    "write-heavy": 20,
}


def wait_for(name, fn, attempts=40):
    last_error = None
    for _ in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"{name} is not ready: {last_error}")


@dataclass
class Metrics:
    requests: int = 0
    reads: int = 0
    writes: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    db_reads: int = 0
    db_writes: int = 0
    errors: int = 0
    max_pending: int = 0


class App:
    def __init__(self, args, strategy):
        self.args = args
        self.strategy = strategy
        self.redis = redis.Redis(host=args.redis_host, port=6379, decode_responses=True)
        self.db = psycopg.connect(
            host=args.db_host,
            dbname=args.db_name,
            user=args.db_user,
            password=args.db_password,
            autocommit=True,
        )
        self.metrics = Metrics()
        self.db_lock = threading.Lock()
        self.stop_flush = threading.Event()
        self.flush_thread = None

    def setup(self):
        self.redis.ping()
        with self.db_lock, self.db.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INT PRIMARY KEY,
                    value INT NOT NULL
                )
                """
            )
            cur.execute("TRUNCATE items")
            rows = [(i, 1000 + i) for i in range(1, self.args.items + 1)]
            cur.executemany("INSERT INTO items (id, value) VALUES (%s, %s)", rows)
        self.redis.flushdb()

    def cache_key(self, item_id):
        return f"item:{item_id}"

    def read(self, item_id):
        cached = self.redis.get(self.cache_key(item_id))
        self.metrics.reads += 1
        if cached is not None:
            self.metrics.cache_hits += 1
            return int(cached)

        self.metrics.cache_misses += 1
        self.metrics.db_reads += 1
        with self.db_lock, self.db.cursor() as cur:
            cur.execute("SELECT value FROM items WHERE id = %s", (item_id,))
            value = cur.fetchone()[0]
        self.redis.set(self.cache_key(item_id), value)
        return value

    def write(self, item_id, value):
        self.metrics.writes += 1
        key = self.cache_key(item_id)

        if self.strategy == "cache-aside":
            self.metrics.db_writes += 1
            with self.db_lock, self.db.cursor() as cur:
                cur.execute("UPDATE items SET value = %s WHERE id = %s", (value, item_id))
            self.redis.delete(key)
            return

        if self.strategy == "write-through":
            self.redis.set(key, value)
            self.metrics.db_writes += 1
            with self.db_lock, self.db.cursor() as cur:
                cur.execute("UPDATE items SET value = %s WHERE id = %s", (value, item_id))
            return

        self.redis.set(key, value)
        self.redis.sadd("dirty_items", item_id)

    def start_write_back(self):
        if self.strategy != "write-back":
            return
        self.flush_thread = threading.Thread(target=self.flush_loop, daemon=True)
        self.flush_thread.start()

    def stop_write_back(self):
        if self.strategy != "write-back":
            return 0
        self.stop_flush.set()
        if self.flush_thread:
            self.flush_thread.join()
        pending = self.redis.scard("dirty_items")
        self.flush_all(count_metrics=False)
        return pending

    def flush_loop(self):
        while not self.stop_flush.wait(self.args.flush_interval):
            self.flush_batch(count_metrics=True)

    def flush_batch(self, count_metrics):
        ids = self.redis.spop("dirty_items", self.args.flush_batch)
        if not ids:
            return 0

        rows = []
        for item_id in ids:
            value = self.redis.get(self.cache_key(item_id))
            if value is not None:
                rows.append((int(value), int(item_id)))

        if rows:
            with self.db_lock, self.db.cursor() as cur:
                cur.executemany("UPDATE items SET value = %s WHERE id = %s", rows)
            if count_metrics:
                self.metrics.db_writes += len(rows)
        return len(rows)

    def flush_all(self, count_metrics):
        total = 0
        while self.redis.scard("dirty_items"):
            total += self.flush_batch(count_metrics=count_metrics)
        return total

    def update_pending_metric(self):
        if self.strategy == "write-back":
            pending = self.redis.scard("dirty_items")
            self.metrics.max_pending = max(self.metrics.max_pending, pending)

    def close(self):
        self.db.close()


def db_ready(args):
    conn = psycopg.connect(
        host=args.db_host,
        dbname=args.db_name,
        user=args.db_user,
        password=args.db_password,
        autocommit=True,
    )
    conn.close()


def redis_ready(args):
    redis.Redis(host=args.redis_host, port=6379).ping()


def percentile(values, ratio):
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[int((len(ordered) - 1) * ratio)]


def run_case(args, strategy, workload):
    wait_for("postgres", lambda: db_ready(args))
    wait_for("redis", lambda: redis_ready(args))

    app = App(args, strategy)
    app.setup()
    app.start_write_back()

    rng = random.Random(args.seed)
    read_percent = WORKLOADS[workload]
    latencies = []
    started = time.perf_counter()

    for index in range(args.requests):
        due = started + (index * args.duration / args.requests)
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

        item_id = rng.randint(1, args.items)
        value = rng.randint(1, 1_000_000)
        request_start = time.perf_counter()

        try:
            if rng.randint(1, 100) <= read_percent:
                app.read(item_id)
            else:
                app.write(item_id, value)
        except Exception:
            app.metrics.errors += 1

        app.metrics.requests += 1
        latencies.append((time.perf_counter() - request_start) * 1000)
        app.update_pending_metric()

    elapsed = time.perf_counter() - started
    pending_before_final_flush = app.stop_write_back()

    db_calls = app.metrics.db_reads + app.metrics.db_writes
    hit_base = app.metrics.cache_hits + app.metrics.cache_misses
    hit_rate = app.metrics.cache_hits / hit_base if hit_base else 0
    row = {
        "strategy": strategy,
        "workload": workload,
        "read_percent": read_percent,
        "write_percent": 100 - read_percent,
        "requests": app.metrics.requests,
        "elapsed_sec": round(elapsed, 2),
        "throughput_rps": round(app.metrics.requests / elapsed, 2),
        "avg_ms": round(statistics.mean(latencies), 2),
        "p95_ms": round(percentile(latencies, 0.95), 2),
        "db_reads": app.metrics.db_reads,
        "db_writes": app.metrics.db_writes,
        "db_calls": db_calls,
        "cache_hits": app.metrics.cache_hits,
        "cache_misses": app.metrics.cache_misses,
        "hit_rate": round(hit_rate, 4),
        "pending_writes": pending_before_final_flush,
        "max_pending_writes": app.metrics.max_pending,
        "errors": app.metrics.errors,
    }
    app.close()
    return row


def write_row(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=row.keys())
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=["cache-aside", "write-through", "write-back"])
    parser.add_argument("--workload", choices=WORKLOADS.keys())
    parser.add_argument("--requests", type=int, default=12000)
    parser.add_argument("--duration", type=int, default=15)
    parser.add_argument("--items", type=int, default=1000)
    parser.add_argument("--flush-interval", type=float, default=5)
    parser.add_argument("--flush-batch", type=int, default=50)
    parser.add_argument("--csv", default="results/results.csv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--db-host", default=os.getenv("DB_HOST", "localhost"))
    parser.add_argument("--db-name", default=os.getenv("DB_NAME", "cache_lab"))
    parser.add_argument("--db-user", default=os.getenv("DB_USER", "cache_user"))
    parser.add_argument("--db-password", default=os.getenv("DB_PASSWORD", "cache_pass"))
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    args = parser.parse_args()

    if args.strategy and args.workload:
        row = run_case(args, args.strategy, args.workload)
        write_row(args.csv, row)
        print(row)
        return

    for strategy in ["cache-aside", "write-through", "write-back"]:
        for workload in WORKLOADS:
            row = run_case(args, strategy, workload)
            write_row(args.csv, row)
            print(row)


if __name__ == "__main__":
    main()
