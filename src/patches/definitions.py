"""Declarative patch and build configuration, independent of the registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Patch


@dataclass(frozen=True)
class SourceRequirement:
    depot_id: int
    version: int
    blob_sha256: str
    dat_sha256: str
    origin: str  # selected_chain or catalog
    label: str


@dataclass(frozen=True)
class Resource:
    package: str  # path below src/patches, using forward slashes
    name: str
    native: bool = False


@dataclass(frozen=True)
class PatchDefinition:
    implementation: Patch
    default_selected: bool = True
    dependencies: frozenset[str] = frozenset()
    after: frozenset[str] = frozenset()
    requirements: frozenset[str] = frozenset()
    capabilities: frozenset[str] = frozenset()
    sources: tuple[SourceRequirement, ...] = ()
    resources: tuple[Resource, ...] = ()
    progress_range: tuple[float, float] = (0.88, 0.99)

    @property
    def id(self) -> str:
        return self.implementation.id

    @property
    def title(self) -> str:
        return self.implementation.display_name

    @property
    def description(self) -> str:
        return self.implementation.description


@dataclass(frozen=True)
class ChoiceGroup:
    patch_ids: tuple[str, ...]
    title: str
    description: str


@dataclass(frozen=True)
class BuildProfile:
    id: str
    target: tuple[int, int] | tuple[int, int, int] | None
    optional: frozenset[str]
    required: frozenset[str]
    groups: tuple[ChoiceGroup, ...] = ()
    first_run_audio: bool = False

    @property
    def all(self) -> frozenset[str]:
        return self.optional | self.required


@dataclass(frozen=True)
class ResolvedSelection:
    profile: BuildProfile
    definitions: tuple[PatchDefinition, ...]

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.definitions)

    @property
    def requirements(self) -> frozenset[str]:
        return frozenset(value for item in self.definitions for value in item.requirements)

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(value for item in self.definitions for value in item.capabilities)

    @property
    def sources(self) -> tuple[SourceRequirement, ...]:
        return tuple(dict.fromkeys(value for item in self.definitions for value in item.sources))
