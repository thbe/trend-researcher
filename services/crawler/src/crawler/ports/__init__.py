"""Crawler ports — protocols implemented by I/O adapters."""

from crawler.ports.source_port import SourcePort
from crawler.ports.topic_repository_port import TopicCandidate, TopicRepositoryPort

__all__ = ["SourcePort", "TopicCandidate", "TopicRepositoryPort"]
