# -*- coding: utf-8 -*-
#
# Copyright (C) 2026 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for grouping importer records of a task."""

from copy import deepcopy

from invenio_bulk_importer.proxies import (
    current_importer_records_service as records_service,
)
from invenio_bulk_importer.records.api import ImporterTask


def _create(identity, task, data, **overrides):
    """Create an importer record for a task, overriding its group fields."""
    record_data = deepcopy(data)
    record_data.update(overrides)
    return records_service.create(identity, data=record_data, task_id=task.id)


def test_record_groups_without_group_id_stay_separate(
    app, db, user_admin, task, minimal_importer_record, location, search_clear
):
    """Records carrying no group id must not collapse into a single group."""
    first = _create(user_admin.identity, task, minimal_importer_record)
    second = _create(user_admin.identity, task, minimal_importer_record)

    groups = ImporterTask.pid.resolve(task.id).get_record_groups()

    assert len(groups) == 2
    assert groups[str(first.id)] == [str(first.id)]
    assert groups[str(second.id)] == [str(second.id)]


def test_record_groups_collects_members_in_position_order(
    app, db, user_admin, task, minimal_importer_record, location, search_clear
):
    """Records sharing a group id come back together, ordered by position."""
    book = _create(
        user_admin.identity,
        task,
        minimal_importer_record,
        group_id="group-1",
        group_role="parent",
        group_position=0,
    )
    second_chapter = _create(
        user_admin.identity,
        task,
        minimal_importer_record,
        group_id="group-1",
        group_role="child",
        group_position=2,
    )
    first_chapter = _create(
        user_admin.identity,
        task,
        minimal_importer_record,
        group_id="group-1",
        group_role="child",
        group_position=1,
    )

    groups = ImporterTask.pid.resolve(task.id).get_record_groups()

    assert list(groups) == ["group-1"]
    assert groups["group-1"] == [
        str(book.id),
        str(first_chapter.id),
        str(second_chapter.id),
    ]


def test_record_groups_ignores_deleted_records(
    app, db, user_admin, task, minimal_importer_record, location, search_clear
):
    """A deleted record leaves its group, like it leaves the record list."""
    kept = _create(user_admin.identity, task, minimal_importer_record)
    removed = _create(user_admin.identity, task, minimal_importer_record)
    records_service.delete(user_admin.identity, id_=str(removed.id))

    groups = ImporterTask.pid.resolve(task.id).get_record_groups()

    assert groups == {str(kept.id): [str(kept.id)]}
