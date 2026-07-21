# SPDX-License-Identifier: Apache-2.0
"""Checked atomic destination writes and per-path generation coordination."""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path


class SupersededWriteError(RuntimeError):
    """A newer write reservation exists for the same destination."""


def canonical_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def atomic_write(
    path: str,
    writer: Callable[[str], object],
    *,
    before_commit: Callable[[], object] | None = None,
    durable: bool = False,
) -> str:
    """Write via a same-directory temporary and replace only after success."""
    destination = os.path.abspath(path)
    directory = os.path.dirname(destination) or os.curdir
    suffix = f".tmp{Path(destination).suffix}"
    fd, temporary = tempfile.mkstemp(
        prefix=f".{Path(destination).name}.", suffix=suffix, dir=directory
    )
    os.close(fd)
    try:
        writer(temporary)
        if not os.path.isfile(temporary):
            raise OSError(f"Writer did not produce a file: {destination}")
        with open(temporary, "rb") as handle:
            if durable:
                os.fsync(handle.fileno())
        if before_commit is not None:
            before_commit()
        os.replace(temporary, destination)
        if durable and os.name != "nt":
            directory_fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        return destination
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def atomic_bytes(
    path: str,
    data: bytes,
    *,
    before_commit: Callable[[], object] | None = None,
    durable: bool = False,
) -> str:
    def write(temporary: str) -> None:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()

    return atomic_write(path, write, before_commit=before_commit, durable=durable)


@dataclass
class _PathState:
    generation: int
    lock: threading.Lock


class WriteTicket:
    def __init__(
        self, coordinator: WriteCoordinator, path: str, state: _PathState, generation: int
    ) -> None:
        self._coordinator = coordinator
        self.path = path
        self._state = state
        self.generation = generation

    def is_current(self) -> bool:
        with self._coordinator._lock:
            return self._state.generation == self.generation

    def write(
        self,
        writer: Callable[[str], object],
        *,
        before_commit: Callable[[], object] | None = None,
        durable: bool = False,
    ) -> str:
        def validate() -> None:
            if before_commit is not None:
                before_commit()
            if not self.is_current():
                raise SupersededWriteError(f"A newer write superseded {self.path}")

        with self._state.lock:
            return atomic_write(self.path, writer, before_commit=validate, durable=durable)


class WriteCoordinator:
    """Issue generations and serialize commits for canonical destinations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._paths: dict[str, _PathState] = {}

    def reserve(self, path: str) -> WriteTicket:
        canonical = canonical_path(path)
        with self._lock:
            state = self._paths.get(canonical)
            if state is None:
                state = _PathState(0, threading.Lock())
                self._paths[canonical] = state
            state.generation += 1
            return WriteTicket(self, os.path.abspath(path), state, state.generation)


write_coordinator = WriteCoordinator()
