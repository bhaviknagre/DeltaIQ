
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from src.canonical.model import CanonicalDocument


class FormatAdapter(ABC):
    format_name: str

    @classmethod
    @abstractmethod
    def sniff(cls, path: Path) -> bool:
        """Return True if this adapter can handle the file at `path`.

        Sniffing is content-based where practical (magic bytes / text-layer
        presence), not just extension matching, since a ".pdf" may be native
        or scanned and that distinction is exactly what routing depends on.
        """

    @abstractmethod
    def parse(self, path: Path, pid: str, revision_label: str | None = None) -> CanonicalDocument:
        """Parse the file into the canonical representation."""


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: list[type[FormatAdapter]] = []

    def register(self, adapter_cls: type[FormatAdapter]) -> None:
        self._adapters.append(adapter_cls)

    def resolve(self, path: Path) -> type[FormatAdapter]:
        for adapter_cls in self._adapters:
            if adapter_cls.sniff(path):
                return adapter_cls
        raise ValueError(f"No registered adapter can handle: {path}")


registry = AdapterRegistry()
