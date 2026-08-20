from io import BytesIO
from uuid import uuid4

import pytest
from celery.exceptions import Retry

from invenio_bulk_importer.errors import ImporterTaskNoReadyError
from invenio_bulk_importer.proxies import (
    current_importer_records_service as records_service,
)
from invenio_bulk_importer.proxies import (
    current_importer_tasks_service as tasks_service,
)
from invenio_bulk_importer.records.api import ImporterRecord, ImporterTask
from invenio_bulk_importer.records.models import ImporterRecordModel, ImporterTaskModel
from invenio_bulk_importer.services.tasks import (
    _mark_record_failed,
    finalize_importer_task,
    validate_serialized_data,
)


def test_create_importer_task(
    app, db, user_admin, minimal_importer_task, location, search_clear
):
    """Test creating an importer task with minimal data."""

    task = tasks_service.create(user_admin.identity, data=minimal_importer_task)
    task_data = task.data
    assert task_data["title"] == minimal_importer_task["title"]
    assert task_data["description"] == minimal_importer_task["description"]
    assert task_data["mode"] == minimal_importer_task["mode"]
    assert task_data["status"] == minimal_importer_task["status"]
    assert task_data["record_type"] == minimal_importer_task["record_type"]
    assert task_data["serializer"] == minimal_importer_task["serializer"]
    assert task_data["options"] == {
        "doi_minting": False,
        "publish": True,
    }
    # Check start_by_id is set from component running.
    task_model_instance = db.session.get(ImporterTaskModel, task.id)
    assert task_model_instance.started_by_id == int(user_admin.id)

    ImporterTask.index.refresh()

    # try to search for the profile
    all_tasks = tasks_service.search(user_admin.identity)
    assert all_tasks.total == 1
    hits = list(all_tasks.hits)
    assert hits[0] == task.data

    # Add metadata file to importer task.
    stream = BytesIO(b"csvdata")
    metadata_file_item = tasks_service.update_metadata_file(
        user_admin.identity,
        task.id,
        "new.csv",
        stream,
        content_length=stream.getbuffer().nbytes,
    )
    file_output = tasks_service.read_metadata_file(user_admin.identity, task.id)
    assert file_output
    file_deleted = tasks_service.delete_metadata_file(user_admin.identity, task.id)
    pytest.raises(
        FileNotFoundError,
        tasks_service.read_metadata_file,
        user_admin.identity,
        task.id,
    )


def test_starting_validation(app, db, user_admin, task, community, search_clear):
    """Test starting validation of an importer task."""
    # Start validation. The result item is built before the unit of work
    # commits, so it shows the status the run just moved into.
    task_result = tasks_service.start_validation(user_admin.identity, task.id)
    assert task_result.data["status"] == "validating"

    record_model_instances = (
        db.session.query(ImporterRecordModel)
        .filter(ImporterRecordModel.task_id == task.id)
        .all()
    )
    assert len(record_model_instances) == 3

    ImporterTask.index.refresh()
    ImporterRecord.index.refresh()

    # Assertions - there will be 3 records, one valid, the others fail at serializer or at record type validation.
    all_records = records_service.search(user_admin.identity)
    assert all_records.total == 3
    hits = list(all_records.hits)
    serializer_validation_failure_hits = [
        hit for hit in hits if hit["status"] == "serializer validation failed"
    ]
    invenio_validation_failure_hits = [
        hit for hit in hits if hit["status"] == "validation failed"
    ]
    validated_hits = [hit for hit in hits if hit["status"] == "validated"]
    assert len(serializer_validation_failure_hits) == 1
    assert len(invenio_validation_failure_hits) == 1
    assert len(validated_hits) == 1
    serializer_validation_failure = serializer_validation_failure_hits[0]
    assert serializer_validation_failure["src_data"]
    assert "serializer_data" not in serializer_validation_failure
    assert "transformed_data" not in serializer_validation_failure
    assert len(serializer_validation_failure["errors"]) == 3
    invenio_validation_failure = invenio_validation_failure_hits[0]
    assert invenio_validation_failure["src_data"]
    assert invenio_validation_failure["serializer_data"]
    assert "transformed_data" not in invenio_validation_failure
    assert len(invenio_validation_failure["errors"]) == 12

    invenio_validated = validated_hits[0]
    assert invenio_validated["src_data"]
    assert invenio_validated["serializer_data"]
    assert invenio_validated["transformed_data"]
    assert "errors" not in invenio_validated
    # Check update to task metadata has occurred.
    all_tasks = tasks_service.search(user_admin.identity)
    assert all_tasks.total == 1
    hits = list(all_tasks.hits)
    assert hits[0]["status"] == "validated with failures"
    assert hits[0]["records_status"] == {
        "serializer validation failed": 1,
        "total_records": 3,
        "validated": 1,
        "validation failed": 1,
    }


def test_revalidating_replaces_records(
    app, db, user_admin, task, community, search_clear
):
    """Validating twice must replace the importer records, not duplicate them."""
    tasks_service.start_validation(user_admin.identity, task.id)
    ImporterTask.index.refresh()
    ImporterRecord.index.refresh()

    first_run = tasks_service.read(user_admin.identity, task.id).data
    assert first_run["records_status"]["total_records"] == 3

    tasks_service.start_validation(user_admin.identity, task.id)
    ImporterTask.index.refresh()
    ImporterRecord.index.refresh()

    live_records = (
        db.session.query(ImporterRecordModel)
        .filter(
            ImporterRecordModel.task_id == task.id,
            ImporterRecordModel.is_deleted.is_(False),
        )
        .all()
    )
    assert len(live_records) == 3

    # The records purged by the second run are soft-deleted, so they are still
    # rows in the table; they must not be counted.
    second_run = tasks_service.read(user_admin.identity, task.id).data
    assert second_run["records_status"]["total_records"] == 3
    assert second_run["status"] == "validated with failures"


def _finalize_outside_eager_mode(task_id, phase, **request):
    """Run ``finalize_importer_task`` as a worker would, not inline.

    Eager mode short-circuits the reschedule, because inline execution means
    the per-record tasks have already finished, so the polling path needs a
    non-eager request pushed by hand. ``called_directly`` defaults to True,
    which makes ``retry()`` raise straight away instead of queueing a real
    message; pass ``called_directly=False`` to reach the max-retries branch.
    """
    finalize_importer_task.push_request(is_eager=False, **request)
    try:
        return finalize_importer_task.run(str(task_id), phase=phase)
    finally:
        finalize_importer_task.pop_request()


def test_finalize_reports_progress_and_keeps_polling(
    app, db, user_admin, task, community, search_clear
):
    """While records are pending, finalize writes progress then reschedules."""
    tasks_service.start_validation(user_admin.identity, task.id)
    # Put one record back to `created`, as if its worker had not run yet.
    pending_id = task._record.get_records()[0]
    pending = records_service.read(user_admin.identity, pending_id)
    data = records_service.get_current_task_data(pending._record)
    data["status"] = "created"
    records_service.update(user_admin.identity, data=data, id_=pending_id)
    ImporterRecord.index.refresh()

    with pytest.raises(Retry):
        _finalize_outside_eager_mode(task.id, "validate")

    # Progress was written before rescheduling, rather than staying silent.
    refreshed = tasks_service.read(user_admin.identity, task.id).data
    assert refreshed["status"] == "validating"
    assert refreshed["records_status"]["created"] == 1
    assert refreshed["records_status"]["total_records"] == 3


def test_finalize_stops_once_nothing_is_pending(
    app, db, user_admin, task, community, search_clear
):
    """With every record processed, finalize writes the state and stops."""
    tasks_service.start_validation(user_admin.identity, task.id)
    ImporterRecord.index.refresh()

    # No exception: nothing left to wait for.
    _finalize_outside_eager_mode(task.id, "validate")

    refreshed = tasks_service.read(user_admin.identity, task.id).data
    assert refreshed["status"] == "validated with failures"
    assert "created" not in refreshed["records_status"]


def test_finalize_gives_up_after_max_polls(
    app, db, user_admin, task, community, search_clear
):
    """A run that never completes ends on a terminal status, not mid-flight.

    Records still pending this long mean the workers holding them are gone.
    Leaving the calculated ``validating`` would read as "still working"
    forever, so the task is marked damaged instead.
    """
    tasks_service.start_validation(user_admin.identity, task.id)
    pending_id = task._record.get_records()[0]
    pending = records_service.read(user_admin.identity, pending_id)
    data = records_service.get_current_task_data(pending._record)
    data["status"] = "created"
    records_service.update(user_admin.identity, data=data, id_=pending_id)
    ImporterRecord.index.refresh()

    # Exhausted retries must not surface as a task failure.
    _finalize_outside_eager_mode(
        task.id,
        "validate",
        called_directly=False,
        retries=app.config["BULK_IMPORTER_FINALIZE_MAX_POLLS"] + 1,
    )

    refreshed = tasks_service.read(user_admin.identity, task.id).data
    assert refreshed["status"] == "damaged"
    assert refreshed["records_status"]["created"] == 1


def test_worker_failure_leaves_the_record_in_a_terminal_state(
    app, db, user_admin, task, community, search_clear
):
    """A record task that raises must not leave its record looking pending.

    The finaliser reads `created` as "still working", so a crashing worker
    used to keep the whole task being followed until the poll limit.
    """
    tasks_service.start_validation(user_admin.identity, task.id)
    record_id = task._record.get_records()[0]
    data = records_service.get_current_task_data(
        records_service.read(user_admin.identity, record_id)._record
    )
    data["status"] = "created"
    records_service.update(user_admin.identity, data=data, id_=record_id)

    # Run the real task against a task id that cannot be resolved, so it
    # raises where a crashing worker would, rather than calling the helper.
    with pytest.raises(Exception):
        validate_serialized_data(record_id_str=record_id, task_id_str=str(uuid4()))
    ImporterRecord.index.refresh()

    refreshed = records_service.read(user_admin.identity, record_id).data
    assert refreshed["status"] == "validation failed"
    assert refreshed["errors"][-1]["type"] == "unexpected_error"
    assert refreshed["errors"][-1]["loc"] == "validate"


def test_marking_a_record_failed_never_raises(app, db, user_admin, search_clear):
    """Recording a failure runs while an exception is already in flight."""
    # Nothing must escape, even when the record cannot be found at all.
    _mark_record_failed(str(uuid4()), "import", RuntimeError("worker died"))


def test_cannot_revalidate_while_a_run_is_in_progress(
    app, db, user_admin, task, community, search_clear
):
    """Validating clears the task's records, so it must not run concurrently.

    During an import that would purge records whose workers may already have
    created repository records, leaving those with no importer trail.
    """
    tasks_service.start_validation(user_admin.identity, task.id)
    for status in ("validating", "importing"):
        data = tasks_service.get_current_task_data(task._record)
        data["status"] = status
        tasks_service.update(user_admin.identity, data=data, id_=task.id)

        with pytest.raises(ImporterTaskNoReadyError):
            tasks_service.start_validation(user_admin.identity, task.id)

    # The records of the run in progress were left alone.
    assert len(task._record.get_records()) == 3
