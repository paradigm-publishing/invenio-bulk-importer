# -*- coding: utf-8 -*-
#
# Copyright (C) 2024 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Base serializer."""

import csv
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import IO, Iterator


@dataclass
class GroupEntry:
    """One record's worth of source data, plus its place in its group.

    A group is the set of records that have to be imported together, so that
    identifiers can be resolved between them. Formats that describe a single
    record per entry produce groups of one, which is why every field but
    ``data`` has a default.
    """

    data: dict
    """The source data for one record, as it came out of the file."""

    key: str | None = None
    """Identifies the entry within its group, for siblings to refer to."""

    role: str | None = None
    """``parent``, ``child``, or ``None`` for a group of one."""

    position: int = 0
    """Order of the entry within its group."""

    relations: list[dict] = field(default_factory=list)
    """Links to siblings, resolved once every record in the group has a PID."""


class Serializer(ABC):
    """Base serializer class."""

    @abstractmethod
    def load(self, stream: IO, **kwargs) -> Iterator[dict]:
        """Load the stream object by object.

        :param stream: IO
        """

    def load_groups(self, stream: IO, **kwargs) -> Iterator[list[GroupEntry]]:
        """Load the stream group by group.

        The records of a group are imported together. By default every object
        is its own group, which is what formats describing one record per entry
        need; override this to yield real groups.

        :param stream: IO
        :return: An iterator of groups, each a list of entries.
        """
        for obj in self.load(stream, **kwargs):
            yield [GroupEntry(data=obj)]

    @abstractmethod
    def transform(self, obj: dict) -> tuple[dict | None, list[dict] | None]:
        """Transform a given object into dict Invenio understands."""


class CSVSerializer(Serializer):
    """Base class for all CSV serializers."""

    def _clean_row(self, row):
        """Remove empty strings replacing them wit `None` values."""
        return {k: v for k, v in row.items() if v != ""}

    def load(self, stream: IO, **kwargs) -> Iterator[dict]:
        """Load the content of the stream using ``DictReader``."""
        for row in csv.DictReader(stream, **kwargs):
            yield self._clean_row(row)
