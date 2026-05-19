from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    content: bytes
    content_type: str


class ObjectStorage(Protocol):
    def put_object(self, key: str, content: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get_object(self, key: str) -> StoredObject:
        raise NotImplementedError

    def delete_object(self, key: str) -> None:
        raise NotImplementedError


class ObjectNotFoundError(Exception):
    pass


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self._objects: dict[str, StoredObject] = {}
        self._lock = Lock()

    def put_object(self, key: str, content: bytes, content_type: str) -> None:
        with self._lock:
            self._objects[key] = StoredObject(content=content, content_type=content_type)

    def get_object(self, key: str) -> StoredObject:
        with self._lock:
            stored = self._objects.get(key)
            if stored is None:
                raise ObjectNotFoundError(f"Object with key={key} not found")
            return stored

    def delete_object(self, key: str) -> None:
        with self._lock:
            self._objects.pop(key, None)


class S3ObjectStorage:
    def __init__(
        self,
        *,
        endpoint_url: str | None,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        region_name: str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._bucket_name = bucket_name
        self._region_name = region_name
        self._client = None
        self._bucket_checked = False
        self._lock = Lock()

    def put_object(self, key: str, content: bytes, content_type: str) -> None:
        self._ensure_bucket()
        self.client.put_object(
            Bucket=self._bucket_name,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    def get_object(self, key: str) -> StoredObject:
        try:
            response = self.client.get_object(Bucket=self._bucket_name, Key=key)
        except Exception as error:
            if _is_missing_object_error(error):
                raise ObjectNotFoundError(f"Object with key={key} not found") from error
            raise

        return StoredObject(
            content=response["Body"].read(),
            content_type=response.get("ContentType") or "application/octet-stream",
        )

    def delete_object(self, key: str) -> None:
        self.client.delete_object(Bucket=self._bucket_name, Key=key)

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self._endpoint_url or None,
                aws_access_key_id=self._access_key_id,
                aws_secret_access_key=self._secret_access_key,
                region_name=self._region_name,
            )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_checked:
            return

        with self._lock:
            if self._bucket_checked:
                return
            try:
                self.client.head_bucket(Bucket=self._bucket_name)
            except Exception:
                self.client.create_bucket(Bucket=self._bucket_name)
            self._bucket_checked = True


def _is_missing_object_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False

    error_data = response.get("Error") or {}
    return str(error_data.get("Code")) in {"NoSuchKey", "404", "NotFound"}
