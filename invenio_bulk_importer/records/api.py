# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2015-2020 CERN.
# Copyright (C) 2024-2025 Ubiquity Press.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Importer task records API."""

from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_records.dumpers import SearchDumper
from invenio_records.dumpers.indexedat import IndexedAtDumperExt
from invenio_records.dumpers.relations import RelationDumperExt
from invenio_records.systemfields import (
    ModelField,
    ModelRelation,
    RelationsField,
    SystemField,
)
from invenio_records_resources.records.api import (
    FileRecord,
    PersistentIdentifierWrapper,
    Record,
)
from invenio_records_resources.records.systemfields import FilesField, IndexField
from invenio_users_resources.records.api import UserAggregate
from sqlalchemy import func
from sqlalchemy.exc import NoResultFound, StatementError

from .models import ImporterRecordModel, ImporterTaskFileModel, ImporterTaskModel


class GetRecordResolver(object):
    """Resolver that simply uses get record."""

    def __init__(self, record_cls):
        """Initialize resolver."""
        self._record_cls = record_cls

    def resolve(self, pid_value, registered_only=False):
        """Simply get the record."""
        _ = registered_only
        try:
            return self._record_cls.get_record(pid_value)
        except (NoResultFound, StatementError):
            raise PIDDoesNotExistError("pid", pid_value)


class DirectIdPID(SystemField):
    """Helper emulate a PID field."""

    def __init__(self, id_field="id"):
        """Constructor."""
        self._id_field = id_field

    def obj(self, record):
        """Get the access object."""
        pid_value = getattr(record, self._id_field)
        if pid_value is None:
            return None
        return PersistentIdentifierWrapper(str(pid_value))

    def __get__(self, record, owner=None):
        """Evaluate the property."""
        if record is None:
            return GetRecordResolver(owner)
        return self.obj(record)


class ImporterTaskFile(FileRecord):
    """Importer Task File record."""

    model_cls = ImporterTaskFileModel

    record_cls = None  # is defined inside the parent record


class ImporterTask(Record):
    """Importer Task record."""

    model_cls = ImporterTaskModel
    child_record_model_cls = ImporterRecordModel
    dumper = SearchDumper(
        extensions=[
            RelationDumperExt("relations"),
            IndexedAtDumperExt(),
        ]
    )

    # Systemfields
    index = IndexField(
        "importertasks-importertask-v1.0.0",
        search_alias="importertasks",
    )

    pid = DirectIdPID()

    # Importer Task File related fields
    files = FilesField(file_cls=ImporterTaskFile, store=False)
    bucket_id = ModelField(dump=False)
    bucket = ModelField(dump=False)

    started_by_id = ModelField("started_by_id")
    """The data-layer id of the user who started task (or None)."""

    relations = RelationsField(
        started_by=ModelRelation(
            UserAggregate,
            "started_by_id",
            "started_by",
            attrs=[
                "email",
                "username",
            ],
        ),
    )

    def update_start_by_id(self, user_id):
        """Update start by id fk."""
        if not self.model:
            raise NoResultFound(f"ImporterTask with id {self.id} not found.")
        self.model.started_by_id = user_id

    def get_importer_record_info(self) -> dict:
        """Get information about the importer records related to this task.

        Soft-deleted records are excluded: deleting one nulls its ``json``, so
        counting them would add a ``None`` status bucket and inflate
        ``total_records``.
        """
        record_model_class = self.child_record_model_cls
        records_info = (
            db.session.query(
                record_model_class.json["status"].label("status"),
                func.count(record_model_class.id).label("count"),
            )
            .filter(
                record_model_class.task_id == self.id,
                record_model_class.is_deleted.is_(False),
            )
            .group_by(record_model_class.json["status"])
            .all()
        )
        records_info = dict(records_info)
        records_info["total_records"] = sum(records_info.values())
        return records_info

    def get_records(self) -> list[str]:
        """Get all importer records ids related to this task.

        Returns:
            list[str]: List of record ids as strings.
        """
        record_model_class = self.child_record_model_cls
        query = db.session.query(record_model_class.id).filter(
            record_model_class.task_id == str(self.id),
            record_model_class.is_deleted.is_(False),
        )
        return [str(id) for (id,) in query.all()]


class ImporterRecord(Record):
    """Importer Record record."""

    model_cls = ImporterRecordModel

    dumper = SearchDumper(
        extensions=[
            RelationDumperExt("relations"),
            IndexedAtDumperExt(),
        ]
    )

    # Systemfields
    index = IndexField(
        "importerrecords-importerrecord-v1.0.0",
        search_alias="importerrecords",
    )

    pid = DirectIdPID()

    task_id = ModelField("task_id")
    """The data-layer id of the importer task that generated record."""

    relations = RelationsField(
        task=ModelRelation(
            ImporterTask,
            "task_id",
            "task",
            attrs=[
                "id",
            ],
        ),
    )

    def update_task_id(self, task_id):
        """Update task id fk."""
        if not self.model:
            raise NoResultFound(f"ImporterRecord with id {self.id} not found.")
        self.model.task_id = task_id


ImporterTaskFile.record_cls = ImporterTask
