# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Celery tasks for the Invenio Bulk Importer."""

import traceback
import uuid
from copy import deepcopy

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError
from flask import current_app
from invenio_base.utils import obj_or_import_string
from invenio_records_resources.tasks import system_identity

from invenio_bulk_importer.services.states import (
    ImporterRecordState,
    TaskStateCalculator,
)

from ..proxies import current_importer_records_service as records_service
from ..proxies import current_importer_tasks_service as tasks_service

VALIDATE_PHASE = "validate"
"""Follow the validation run."""

IMPORT_PHASE = "import"
"""Follow the record creation run."""

PENDING_RECORD_STATES = {
    VALIDATE_PHASE: [ImporterRecordState.CREATED.value],
    IMPORT_PHASE: [ImporterRecordState.VALIDATED.value],
}
"""Record states still awaiting work, per phase."""

DEFAULT_IMPORER_RECORD_DICT = dict(
    status=ImporterRecordState.CREATED.value,
    errors=[],
    message=None,
    src_data=None,
    serializer_data=None,
    transformed_data=None,
)
"""Default importer record dictionary schema."""


def _get_record_from_uuid_str(id_str, service):
    """Get a record from a UUID string."""
    if not id_str:
        return None
    try:
        record_id = uuid.UUID(id_str)
        return service.record_cls.pid.resolve(record_id)
    except Exception as e:
        print(f"Error resolving record from UUID {id_str}: {e}")
        return None


def _get_importer_task_classes(task_id_str: str):
    """Get record type class, serializer and record instance for a given task ID."""
    task = _get_record_from_uuid_str(task_id_str, tasks_service)
    # Get Record Type
    record_type_details = current_app.config.get("BULK_IMPORTER_RECORD_TYPES", {}).get(
        task.get("record_type"), {}
    )
    record_type_cls = obj_or_import_string(record_type_details.get("class"))
    # Get Serializer
    serializer_cls = obj_or_import_string(
        record_type_details.get("serializers", {}).get(task.get("serializer"))
    )
    return task, record_type_cls, serializer_cls()


@shared_task(ignore_result=True)
def run_transformed_record(record_id_str: str, task_id_str: str):
    """Run the transformed importer record for a given record ID and task ID to create a new record."""
    try:
        record = _get_record_from_uuid_str(record_id_str, records_service)
        importer_record_dict = records_service.get_current_task_data(record)
        task, record_type_cls, _ = _get_importer_task_classes(task_id_str)
        rdm_record = record_type_cls(
            (None, None),
            importer_record=record,
        )
        record_item = rdm_record.run(mode=task.get("mode"))
        importer_record_dict["status"] = (
            ImporterRecordState.IMPORTED.value
            if rdm_record.is_successful
            else ImporterRecordState.IMPORT_FAILED.value
        )
        importer_record_dict["errors"] = rdm_record.errors
        importer_record_dict["generated_record_id"] = (
            record_item.id if record_item else None
        )
        # Update the importer record with the validation results
        records_service.update(
            system_identity, data=importer_record_dict, id_=record.id
        )
    except Exception as e:
        traceback.print_exc()
        print(
            f"Error run_transformed_record for record/task: {record_id_str}/{task_id_str}:- {e}"
        )
        # Handle error appropriately, e.g., log it or update task status
        raise e


@shared_task(ignore_result=True)
def run_transformed_records(task_id_str: str):
    """Load importer metadata for a record type using a specific serializer."""
    try:
        task, _, _ = _get_importer_task_classes(task_id_str)
        # Validate entries from the metadata file
        for record_id_str in task.get_records():
            run_transformed_record.delay(
                record_id_str=record_id_str,
                task_id_str=task_id_str,
            )
        # Follow the run, refreshing the task status until every record is done.
        finalize_importer_task.delay(task_id_str, phase=IMPORT_PHASE)
    except Exception as e:
        traceback.print_exc()
        print(f"Error run_transformed_records for task: {task_id_str}:- {e}")
        # Handle error appropriately, e.g., log it or update task status
        raise e


@shared_task(ignore_result=True)
def validate_serialized_data(record_id_str: str, task_id_str: str):
    """Validate serialized data for a record type using a specific serializer data."""
    try:
        record = _get_record_from_uuid_str(record_id_str, records_service)
        importer_record_dict = records_service.get_current_task_data(record)
        task, record_type_cls, serializer = _get_importer_task_classes(task_id_str)
        mode = task.get("mode")
        serializer_data, serializer_errors = serializer.transform(
            importer_record_dict["src_data"], mode=mode
        )
        rdm_record = record_type_cls(
            (
                serializer_data,
                serializer_errors,
            ),
            task.bucket_id,
        )
        importer_record_dict["serializer_data"] = None
        importer_record_dict["transformed_data"] = None
        if serializer_errors:
            importer_record_dict["status"] = (
                ImporterRecordState.SERIALIZER_VALIDATION_FAILED.value
            )
            importer_record_dict["errors"] = serializer_errors
        else:
            importer_record_dict["serializer_data"] = serializer_data
            importer_record_dict["status"] = (
                ImporterRecordState.VALIDATED.value
                if rdm_record.validate(mode=mode)
                else ImporterRecordState.VALIDATION_FAILED.value
            )
            importer_record_dict["transformed_data"] = rdm_record.validated_record_dict
            importer_record_dict["errors"] = rdm_record.errors
            importer_record_dict["community_uuids"] = rdm_record.community_uuids_dict
            importer_record_dict["record_files"] = rdm_record.record_file_list
            importer_record_dict["validated_record_files"] = (
                rdm_record.validated_record_file_list
            )
            # Exisitng Record ID
            importer_record_dict["existing_record_id"] = rdm_record.id
        # Update the importer record with the validation results
        records_service.update(
            system_identity, data=importer_record_dict, id_=record.id
        )
    except Exception as e:
        traceback.print_exc()
        print(
            f"Error validate_serialized_data for record/task: {record_id_str}/{task_id_str}:- {e}"
        )
        # Handle error appropriately, e.g., log it or update task status
        raise e


@shared_task(ignore_result=True)
def valid_importer_file_data(task_id_str: str):
    """Load importer metadata for a record type using a specific serializer."""
    try:
        task, _, serializer = _get_importer_task_classes(task_id_str)
        # Get Metadata File
        metadata_file = tasks_service.read_metadata_file(system_identity, task.id)
        # Validate entries from the metadata file
        for serializer_record_data in serializer.load(metadata_file.get_stream("r")):
            importer_record_dict = deepcopy(DEFAULT_IMPORER_RECORD_DICT)
            importer_record_dict["src_data"] = serializer_record_data
            # Create Basic Importer Record
            importer_record = records_service.create(
                system_identity,
                data=importer_record_dict,
                task_id=task.id,
            )
            validate_serialized_data.delay(
                record_id_str=str(importer_record.id),
                task_id_str=task_id_str,
            )
        # Follow the run, refreshing the task status until every record is done.
        finalize_importer_task.delay(task_id_str, phase=VALIDATE_PHASE)
    except Exception as e:
        traceback.print_exc()
        print(f"Error loading importer file for task: {task_id_str}:- {e}")
        # Handle error appropriately, e.g., log it or update task status
        raise e


@shared_task(bind=True, ignore_result=True)
def finalize_importer_task(self, task_id_str: str, phase: str = VALIDATE_PHASE):
    """Refresh the importer task status, and follow the run until it is done.

    Runs on every pass rather than only at the end: the status and record
    counts are rewritten each time, so a long import reports progress instead
    of sitting on its starting status. While records are still pending the
    task reschedules itself, which is what makes it correct under real workers
    -- it used to be queued alongside the per-record tasks and so ran before
    any of them had finished.

    :param task_id_str: Importer task id.
    :param phase: Which run to follow, ``validate`` or ``import``.
    """
    try:
        task, _, _ = _get_importer_task_classes(task_id_str)
        # Get all records for this task
        records_status = task.get_importer_record_info()
        # Update the task with the total number of records processed
        task_data = tasks_service.get_current_task_data(task)
        task_data["records_status"] = records_status
        # Calculate the task state based on the records status
        task_data["status"] = TaskStateCalculator.calculate_task_state(records_status)
        tasks_service.update(system_identity, data=task_data, id_=task.id)
        pending = any(
            records_status.get(state) for state in PENDING_RECORD_STATES[phase]
        )
    except Exception as e:
        traceback.print_exc()
        print(f"Error finalizing importer task: {e}")
        raise e

    if not pending or self.request.is_eager:
        # Under eager execution the per-record tasks have already run inline,
        # so anything still pending is stuck; retrying would just spin.
        return
    # Raised outside the block above: `Retry` is an `Exception`, so catching it
    # there would turn a normal reschedule into a reported failure.
    try:
        raise self.retry(
            countdown=current_app.config["BULK_IMPORTER_FINALIZE_POLL_SECONDS"],
            max_retries=current_app.config["BULK_IMPORTER_FINALIZE_MAX_POLLS"],
        )
    except MaxRetriesExceededError:
        # Stop following the run. The status just written stands.
        print(
            f"Giving up following importer task {task_id_str}, records still pending."
        )
