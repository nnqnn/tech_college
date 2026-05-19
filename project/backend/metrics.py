from __future__ import annotations

from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "dating_http_requests_total",
    "Total backend HTTP requests.",
    ("method", "path", "status"),
)
HTTP_LATENCY = Histogram(
    "dating_http_request_duration_seconds",
    "Backend HTTP request latency.",
    ("method", "path"),
)
FEED_REQUESTS = Counter(
    "dating_feed_requests_total",
    "Feed requests grouped by source.",
    ("source",),
)
CACHE_HITS = Counter(
    "dating_candidate_cache_hits_total",
    "Candidate cache hits.",
)
CACHE_MISSES = Counter(
    "dating_candidate_cache_misses_total",
    "Candidate cache misses.",
)
INTERACTIONS = Counter(
    "dating_interactions_total",
    "Profile interactions.",
    ("is_like",),
)
MATCHES = Counter(
    "dating_matches_total",
    "Mutual likes.",
)
PHOTO_UPLOADS = Counter(
    "dating_photo_uploads_total",
    "Uploaded profile photos.",
)
PHOTO_DELETES = Counter(
    "dating_photo_deletes_total",
    "Deleted profile photos.",
)
RATING_TASKS_ENQUEUED = Counter(
    "dating_rating_tasks_enqueued_total",
    "Rating refresh tasks enqueued to Celery.",
    ("task",),
)
RATING_TASK_FALLBACKS = Counter(
    "dating_rating_task_fallbacks_total",
    "Rating refresh tasks executed synchronously after Celery was unavailable.",
    ("task",),
)
