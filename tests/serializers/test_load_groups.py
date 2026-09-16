# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for the default grouping behaviour of serializers."""

from io import StringIO

from invenio_bulk_importer.serializers.base import GroupEntry
from invenio_bulk_importer.serializers.records.csv import CSVRDMRecordSerializer

CSV_CONTENT = "id,title\r\n1,First\r\n2,Second\r\n3,Third\r\n"


def test_load_groups_yields_one_entry_per_object():
    """A format with one record per entry yields a group per object."""
    serializer = CSVRDMRecordSerializer()

    groups = list(serializer.load_groups(StringIO(CSV_CONTENT)))

    assert len(groups) == 3
    for group in groups:
        assert len(group) == 1
        assert isinstance(group[0], GroupEntry)


def test_load_groups_carries_the_same_data_as_load():
    """Grouping does not change what is read out of the stream."""
    serializer = CSVRDMRecordSerializer()

    loaded = list(serializer.load(StringIO(CSV_CONTENT)))
    grouped = [
        entry.data
        for group in serializer.load_groups(StringIO(CSV_CONTENT))
        for entry in group
    ]

    assert grouped == loaded


def test_load_groups_defaults_for_a_group_of_one():
    """A lone entry carries no key, role or relations of its own."""
    serializer = CSVRDMRecordSerializer()

    entry = next(iter(serializer.load_groups(StringIO(CSV_CONTENT))))[0]

    assert entry.key is None
    assert entry.role is None
    assert entry.position == 0
    assert entry.relations == []
