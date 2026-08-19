# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Fixtures for Invenio Bulk Importer tests."""

import csv
import os
from copy import deepcopy
from io import BytesIO, StringIO

import pytest
from flask_security import login_user
from invenio_accounts.testutils import login_user_via_session

from invenio_bulk_importer.proxies import (
    current_importer_tasks_service as importer_tasks_service,
)
from invenio_bulk_importer.records.api import ImporterTask


@pytest.fixture()
def headers():
    """Default headers for making requests."""
    return {
        "content-type": "application/json",
        "accept": "application/json",
    }


@pytest.fixture()
def admin_client(client, user_admin, app, db):
    """Log in a user to the client."""
    user = user_admin.user
    # login_user(user)
    login_user_via_session(client, email=user.email)
    return client


def _create_task_with_csv_updates(
    csv_file_path: str,
    task_data: dict,
    csv_updates: dict,  # Dictionary of column: value pairs to update
    identity,
    delete: bool = False,
):
    """Helper function to create task with CSV updates."""
    task = importer_tasks_service.create(identity, data=task_data)

    with open(csv_file_path, "r", newline="", encoding="utf-8") as file:
        csv_reader = csv.DictReader(file)
        fieldnames = csv_reader.fieldnames
        updated_rows = []
        for row in csv_reader:
            updated_row = dict(row)
            if (
                not delete
                and csv_updates
                and updated_row["resource_type.id"] == "dataset"
            ):
                # Apply all updates
                updated_row.update(csv_updates)
            if delete:
                updated_row.update(csv_updates)
            updated_rows.append(updated_row)
    # Create and upload updated CSV
    output = StringIO()
    csv_writer = csv.DictWriter(output, fieldnames=fieldnames)
    csv_writer.writeheader()
    csv_writer.writerows(updated_rows)
    csv_stream = BytesIO(output.getvalue().encode("utf-8"))
    csv_stream.seek(0)
    importer_tasks_service.update_metadata_file(
        identity,
        task.id,
        "rdm_records.csv",
        csv_stream,
        content_length=csv_stream.getbuffer().nbytes,
    )
    # Add other files needed for records to be created
    content = BytesIO(b"test file content")
    result = importer_tasks_service._update_file(
        identity, task._record, content, "article", ".txt"
    )
    assert result.to_dict()["key"] == "article.txt"
    ImporterTask.index.refresh()
    return task


@pytest.fixture()
def edit_version_task(
    running_app,
    db,
    user_admin,
    minimal_importer_task,
    record,
):
    """Create an importer taskwith a record to be version updated."""
    version_task_data = deepcopy(minimal_importer_task)
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "rdm_records.csv"
    )
    return _create_task_with_csv_updates(
        csv_file_path=file_path,
        task_data=version_task_data,
        csv_updates={"id": str(record.id), "doi": "10.5281/zenodo.105727344"},
        identity=user_admin.identity,
    )


@pytest.fixture()
def edit_revision_task(
    running_app,
    db,
    user_admin,
    minimal_importer_task,
    record,
):
    """Create an importer task with a record to be revision updated."""
    version_task_data = deepcopy(minimal_importer_task)
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "rdm_records.csv"
    )
    return _create_task_with_csv_updates(
        csv_file_path=file_path,
        task_data=version_task_data,
        csv_updates={"id": str(record.id), "filenames": ""},
        identity=user_admin.identity,
    )


@pytest.fixture()
def delete_task(
    running_app,
    db,
    user_admin,
    minimal_importer_task,
    record,
):
    """Create an importer task for deletion of an exisiting record."""
    version_task_data = deepcopy(minimal_importer_task)
    version_task_data.update({"mode": "delete"})
    file_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "rdm_records_delete.csv"
    )
    return _create_task_with_csv_updates(
        csv_file_path=file_path,
        task_data=version_task_data,
        csv_updates={"id": record.id},
        identity=user_admin.identity,
        delete=True,
    )


@pytest.fixture()
def plain_user_client(client, users, app, db):
    """Log in a user who holds no administration role."""
    login_user_via_session(client, email=users["user_moderator"].user.email)
    return client
