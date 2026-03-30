#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Iterable

from redis import Redis


@dataclass(frozen=True)
class CheckResult:
    user_id: str
    services: list[str]
    user_index_count: int
    service_union_count: int
    missing_in_user_index: list[str]
    extra_in_user_index: list[str]



def _decode_members(values: Iterable[bytes | str]) -> set[str]:
    decoded: set[str] = set()
    for value in values:
        if isinstance(value, bytes):
            decoded.add(value.decode("utf-8"))
        else:
            decoded.add(str(value))
    return decoded



def _collect_services(redis: Redis, user_id: str, service: str | None) -> list[str]:
    if service:
        return [service]

    pattern = f"index:service:*:user:{user_id}"
    services: set[str] = set()
    for key in redis.scan_iter(match=pattern):
        raw = key.decode("utf-8") if isinstance(key, bytes) else str(key)
        parts = raw.split(":")
        # index:service:{service}:user:{user_id}
        if len(parts) >= 5 and parts[0] == "index" and parts[1] == "service" and parts[-2] == "user":
            services.add(parts[2])
    return sorted(services)



def run_check(redis: Redis, user_id: str, service: str | None) -> CheckResult:
    services = _collect_services(redis, user_id, service)

    user_index_key = f"index:user:{user_id}"
    user_index_ids = _decode_members(redis.smembers(user_index_key))

    service_union: set[str] = set()
    for svc in services:
        key = f"index:service:{svc}:user:{user_id}"
        service_union.update(_decode_members(redis.smembers(key)))

    missing = sorted(service_union - user_index_ids, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))
    extra = sorted(user_index_ids - service_union, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))

    return CheckResult(
        user_id=user_id,
        services=services,
        user_index_count=len(user_index_ids),
        service_union_count=len(service_union),
        missing_in_user_index=missing,
        extra_in_user_index=extra,
    )



def apply_repair(redis: Redis, result: CheckResult, ttl_seconds: int) -> dict[str, int]:
    user_index_key = f"index:user:{result.user_id}"
    added = 0
    removed = 0

    if result.missing_in_user_index:
        added = int(redis.sadd(user_index_key, *result.missing_in_user_index))
    if result.extra_in_user_index:
        removed = int(redis.srem(user_index_key, *result.extra_in_user_index))

    redis.expire(user_index_key, ttl_seconds)
    return {"added": added, "removed": removed}



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check and optionally repair Redis index consistency for one user.",
    )
    parser.add_argument("--user-id", required=True, help="Target user_id to audit.")
    parser.add_argument(
        "--service",
        help="Optional single service scope. When omitted, script scans all service-user indexes for the user.",
    )
    parser.add_argument(
        "--redis-url",
        default=os.getenv("DMS_REDIS_WRITE_URL", "redis://localhost:6379/0"),
        help="Redis URL (default: DMS_REDIS_WRITE_URL or redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=int(os.getenv("DMS_REDIS_TASK_TTL_SECONDS", str(90 * 24 * 60 * 60))),
        help="TTL applied to index:user:<user_id> after repair.",
    )
    parser.add_argument(
        "--repair",
        action="store_true",
        help="Apply repair: add missing IDs to index:user and remove extra IDs.",
    )
    return parser



def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        redis = Redis.from_url(args.redis_url, decode_responses=False)
        redis.ping()
    except Exception as exc:  # pragma: no cover
        print(f"Failed to connect Redis: {exc}", file=sys.stderr)
        return 1

    result = run_check(redis, user_id=args.user_id, service=args.service)
    report = {
        "user_id": result.user_id,
        "services": result.services,
        "user_index_count": result.user_index_count,
        "service_union_count": result.service_union_count,
        "missing_in_user_index_count": len(result.missing_in_user_index),
        "extra_in_user_index_count": len(result.extra_in_user_index),
        "missing_in_user_index": result.missing_in_user_index,
        "extra_in_user_index": result.extra_in_user_index,
    }

    if args.repair:
        report["repair"] = apply_repair(redis, result, ttl_seconds=args.ttl_seconds)

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
