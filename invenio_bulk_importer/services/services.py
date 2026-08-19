# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Bulk Importer Services."""

import os
from copy import deepcopy

from flask import current_app
from invenio_records_resources.services.records import RecordService
from invenio_records_resources.services.uow import (
    RecordCommitOp,
    TaskOp,
    unit_of_work,
)

from invenio_bulk_importer.errors import ImporterTaskNoReadyError
from invenio_bulk_importer.services.states import (
    ImporterTaskState,
    TaskStateCalculator,
)

from .tasks import (
    run_transformed_record,
    run_transformed_records,
    valid_importer_file_data,
)


class BulkImporterMixin:
    """Mixin for bulk importer services."""

    additional_keys = []

    def get_current_task_data(self, record):
        """Get the current data of the importer task."""
        keys = ["uuid", "version_id", "indexed_at"]
        keys.extend(self.additional_keys)

        update_data = deepcopy(record.dumps())
        for key in keys:
            update_data.pop(key)
        return update_data


class ImporterTaskService(BulkImporterMixin, RecordService):
    """Importer Task Service class."""

    additional_keys = ["started_by", "started_by_id"]

    def __init__(self, config, files_service=None):
        """Constructor for RecordService."""
        super().__init__(config)
        self._files = files_service

    @unit_of_work()
    def create(self, identity, data, uow=None, expand=False):
        """Create a record.

        Args:
            identity: Identity of user creating the record.
            data: Input data according to the data schema.
            task_id: The ID of the importer task.
            uow: Unit of work for database operations.
            expand: Whether to expand the record with additional fields.
        """
        if not data.get("options"):
            # Set default config options from selected record_type
            configs = self._get_record_type_config(data.get("record_type"))
            data["options"] = configs["options"]
        return self._create(self.record_cls, identity, data, uow=uow, expand=expand)

    def read_metadata_file(self, identity, id_):
        """Read the importer task metadata file."""
        return self._read_file(identity, "metadata", id_)

    @unit_of_work()
    def update_metadata_file(
        self, identity, id_, filename, stream, content_length=None, uow=None
    ):
        """Update the importer task metadata file."""
        self.require_permission(identity, "create")

        record = self.record_cls.pid.resolve(id_)

        self.run_components(
            "metadata_file_update",
            identity,
            id_=id_,
            record=record,
            filename=filename,
            stream=stream,
            content_length=content_length,
            uow=uow,
        )
        extension = self._get_file_extension(filename)
        return self._update_file(
            identity, record, stream, "metadata", extension, uow=uow
        )

    def get_record_types(self, identity):
        """Get the available record types for usage in importer task."""
        self.require_permission(identity, "create")
        record_types = current_app.config["BULK_IMPORTER_RECORD_TYPES"]
        return list(record_types.keys())

    def _get_record_type_config(self, record_type_str):
        record_types = current_app.config["BULK_IMPORTER_RECORD_TYPES"]
        record_type = record_types[record_type_str]
        return dict(
            serializers=list(record_type.get("serializers", {}).keys()),
            options=record_type.get("options", {}),
        )

    def get_record_type_config(self, identity, record_type_str):
        """Get the available serializers for a specific record type."""
        self.require_permission(identity, "create")
        return self._get_record_type_config(record_type_str)

    @unit_of_work()
    def delete_metadata_file(self, identity, id_, uow=None):
        """Delete the importer task metadata file."""
        self.require_permission(identity, "delete")
        record = self.record_cls.pid.resolve(id_)
        return self._delete_file(identity, record, "metadata", uow=uow)

    @unit_of_work()
    def start_validation(self, identity, id_, uow=None):
        """Load importer metadata for a record type using a specific serializer."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "create", record=record)
        if not record["serializer"] or not record["record_type"]:
            raise ImporterTaskNoReadyError(
                "Serializer and record_type must be set for validation."
            )
        self.run_components("validation_start", identity, record=record, uow=uow)

        task_data = self.get_current_task_data(record)
        task_data["status"] = ImporterTaskState.VALIDATING.value
        task_data.pop("records_status", None)
        self._update_task_metadata(identity, record, task_data, uow=uow)

        # Dispatch after commit, so the worker cannot observe the records this
        # transaction just deleted.
        uow.register(TaskOp(valid_importer_file_data, str(record.id)))

        return self.result_item(
            self,
            identity,
            record,
            links_tpl=self.links_item_tpl,
            expandable_fields=self.expandable_fields,
        )

    @unit_of_work()
    def options_update(self, identity, id_, data, uow=None):
        """Update the options of the importer task based on record_type options."""
        task = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "create", record=task)

        # Update the task with the total number of records processed
        task_data = self.get_current_task_data(task)
        task_data["options"] = data
        # Update the task metadata
        self._update_task_metadata(identity, task, task_data, uow=uow)
        return self.result_item(
            self,
            identity,
            task,
            links_tpl=self.links_item_tpl,
            expandable_fields=self.expandable_fields,
        )

    @unit_of_work()
    def status_update(self, identity, id_, uow=None):
        """Update the status of the importer task based on record status."""
        task = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "create", record=task)

        records_status = task.get_importer_record_info()
        # Update the task with the total number of records processed
        task_data = self.get_current_task_data(task)
        task_data["records_status"] = records_status
        # Determine Status update of task based on record statuses.
        task_status = TaskStateCalculator.calculate_task_state(records_status)
        task_data["status"] = task_status
        # Update the task metadata
        self._update_task_metadata(identity, task, task_data, uow=uow)

        return self.result_item(
            self,
            identity,
            task,
            links_tpl=self.links_item_tpl,
            expandable_fields=self.expandable_fields,
        )

    @unit_of_work()
    def start_loading_records(self, identity, id_, uow=None):
        """Start the load of the importer task to create a new invenio record."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "create", record=record)
        # Check task is ready to create records.
        if record["status"] != ImporterTaskState.VALIDATED.value:
            raise ImporterTaskNoReadyError("Importer Task in wrong status to proceed.")

        # Moving off `validated` also stops a second Load running concurrently.
        task_data = self.get_current_task_data(record)
        task_data["status"] = ImporterTaskState.IMPORTING.value
        self._update_task_metadata(identity, record, task_data, uow=uow)

        uow.register(TaskOp(run_transformed_records, str(record.id)))
        return self.result_item(
            self,
            identity,
            record,
            links_tpl=self.links_item_tpl,
            expandable_fields=self.expandable_fields,
        )

    #
    # Subservices
    #
    @property
    def files(self):
        """Record files service."""
        return self._files

    #
    # Private methods
    #
    def _update_task_metadata(self, identity, record, update_data, uow):
        """Update the importer task metadata, but not from form data."""
        data, _ = self.schema.load(
            update_data, context=dict(identity=identity, pid=record.pid, record=record)
        )
        # Run components
        self.run_components(
            "update",
            identity,
            data=data,
            record=record,
            uow=uow,
        )
        # Persist record (DB and index)
        uow.register(RecordCommitOp(record, self.indexer))

    def _get_file_extension(self, filename):
        """Get the file extension from the filename."""
        extension = None
        if filename:
            _, extension = os.path.splitext(filename)
        return extension

    def _find_file_in_record(self, file_name, record):
        """Find the file in the record."""
        full_file_name = None
        for key in record.files.keys():
            prefix_to_check = f"{file_name}."
            if key.startswith(prefix_to_check):
                full_file_name = key
                break
        return full_file_name

    def _read_file(self, identity, file_name, id_):
        """Read the importer task's file."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "read", record=record)
        full_file_name = self._find_file_in_record(file_name, record)
        record_file = record.files.get(full_file_name)
        if record_file is None:
            raise FileNotFoundError()
        return self.files.file_result_item(
            self.files,
            identity,
            record_file,
            record,
            links_tpl=self.files.file_links_item_tpl(id_),
        )

    @unit_of_work()
    def _update_file(
        self, identity, record, stream, file_name, file_extension, uow=None
    ):
        """Update a importer task's file."""
        self.require_permission(identity, "update", record=record)

        full_file_name = f"{file_name}{file_extension}" if file_extension else file_name
        if (
            record.files
            and full_file_name not in record.files
            and self._find_file_in_record(file_name, record)
        ):
            # Delete the old file of a different extension
            self._delete_file(identity, record, file_name, uow=uow)
        record.files[full_file_name] = stream
        uow.register(RecordCommitOp(record))

        return self.files.file_result_item(
            self.files,
            identity,
            record.files[full_file_name],
            record,
            links_tpl=self.files.file_links_item_tpl(record.id),
        )

    def _delete_file(self, identity, record, file_name, uow=None):
        """Delete a importer task's file."""
        # update permission on community is required to be able to remove file.
        self.require_permission(identity, "update", record=record)

        full_file_name = self._find_file_in_record(file_name, record)
        deleted_file = record.files.pop(full_file_name, None)
        if deleted_file is None:
            raise FileNotFoundError()

        deleted_file.delete(force=True)

        uow.register(RecordCommitOp(record))

        return self.files.file_result_item(
            self.files,
            identity,
            deleted_file,
            record,
            links_tpl=self.files.file_links_item_tpl(record.id),
        )


class ImporterRecordService(BulkImporterMixin, RecordService):
    """Importer Task Service class."""

    additional_keys = ["task_id"]

    @unit_of_work()
    def create(self, identity, data, task_id, uow=None, expand=False):
        """Create a record.

        Args:
            identity: Identity of user creating the record.
            data: Input data according to the data schema.
            task_id: The ID of the importer task.
            uow: Unit of work for database operations.
            expand: Whether to expand the record with additional fields.
        """
        return self._create(
            self.record_cls, identity, data, task_id, uow=uow, expand=expand
        )

    @unit_of_work()
    def _create(
        self,
        record_cls,
        identity,
        data,
        task_id,
        raise_errors=True,
        uow=None,
        expand=False,
    ):
        """Create a record.

        :param identity: Identity of user creating the record.
        :param dict data: Input data according to the data schema.
        :param bool raise_errors: raise schema ValidationError or not.
        """
        self.require_permission(identity, "create")

        # Validate data and create record with pid
        data, errors = self.schema.load(
            data,
            context={"identity": identity},
            raise_errors=raise_errors,  # if False, flow is continued with data
            # only containing valid data, but errors
            # are reported (as warnings)
        )

        # It's the components who saves the actual data in the record.
        record = record_cls.create({})

        # Run components
        self.run_components(
            "create",
            identity,
            data=data,
            record=record,
            errors=errors,
            uow=uow,
            task_id=task_id,
        )

        # Persist record (DB and index)
        uow.register(RecordCommitOp(record, self.indexer))

        return self.result_item(
            self,
            identity,
            record,
            links_tpl=self.links_item_tpl,
            nested_links_item=getattr(self.config, "nested_links_item", None),
            errors=errors,
            expandable_fields=self.expandable_fields,
            expand=expand,
        )

    @unit_of_work()
    def start_run(self, identity, id_, uow=None):
        """Start the run of the importer record to create a new invenio record."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "read", record=record)
        # TODO: Validate Metadata file exists - throw error

        # Load the importer records with the specified serializer data.
        run_transformed_record.delay(str(record.id), str(record.task_id))

        return self.result_item(
            self,
            identity,
            record,
            links_tpl=self.links_item_tpl,
            expandable_fields=self.expandable_fields,
        )
