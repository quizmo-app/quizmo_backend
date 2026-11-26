"""Immutable records returned by the course repository."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CourseRecord:
    """A course owned by one teacher."""

    id: int
    title: str
    owner_ldap: str
    is_archived: bool
    created_at: str


@dataclass(frozen=True)
class VersionRecord:
    """One PDF version of a course."""

    id: int
    course_id: int
    version_number: int
    page_count: int
    is_active: bool
    page_fingerprints: tuple[str, ...]


@dataclass(frozen=True)
class InsertionRecord:
    """A quiz or a leaderboard placed after a page of one version."""

    id: int
    course_id: int
    version_id: int
    item_type: str
    item_id: int
    title: str
    after_page: int
    ordre: int
    page_fingerprint: str
