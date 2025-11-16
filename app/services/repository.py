"""Backwards-compatible import wrappers for task repositories."""

from task_state import RedisTaskRepository, TaskRepository

__all__ = ["TaskRepository", "RedisTaskRepository"]
