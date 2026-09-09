# Importer flow

How an importer task goes from an uploaded metadata file to published Invenio
records. Everything below is the current CSV path, where **one row of the
metadata file becomes exactly one importer record**.

Two phases, each user-triggered and each run asynchronously by Celery:

* **validate** — parse the file, create one `ImporterRecord` per entry, and
  check that each entry could become a repository record.
* **import** — turn every validated importer record into a real RDM record.

## End-to-end lifecycle

```mermaid
flowchart TD
    subgraph http["HTTP — ImporterTaskResource"]
        A1["POST /importer-tasks<br/>create task<br/>(record_type, serializer, mode, options)"]
        A2["PUT /importer-tasks/:id/metadata-file<br/>upload metadata file"]
        A3["POST /importer-tasks/:id/validate"]
        A4["POST /importer-tasks/:id/load"]
    end

    subgraph svc["ImporterTaskService"]
        B1["create()"]
        B2["update_metadata_file() → _update_file()"]
        B3["start_validation()<br/>• guard: serializer + record_type set<br/>• guard: task not already running<br/>• component validation_start →<br/>&nbsp;&nbsp;_purge_importer_records()<br/>• status = validating"]
        B4["start_loading_records()<br/>• guard: status == validated<br/>• status = importing"]
    end

    subgraph celery["Celery — services/tasks.py"]
        C1["valid_importer_file_data(task_id)"]
        C2["validate_serialized_data(record_id, task_id)"]
        C3["run_transformed_records(task_id)"]
        C4["run_transformed_record(record_id, task_id)"]
        C5["finalize_importer_task(task_id, phase)"]
    end

    A1 --> B1
    A2 --> B2
    A3 --> B3
    A4 --> B4
    B3 -- "TaskOp, after commit" --> C1
    B4 -- "TaskOp, after commit" --> C3
    C1 -- "one .delay() per file entry" --> C2
    C1 --> C5
    C3 -- "one .delay() per record" --> C4
    C3 --> C5
    C5 -. "self.retry() while records pending" .-> C5
    C5 -. "max polls exceeded" .-> C6["_abandon_importer_task()<br/>status = damaged"]
```

## Validation phase

`valid_importer_file_data` is the **fan-out point**: it is the only place that
decides how many importer records a metadata file produces.

It reads the file a *group* at a time. A group is the set of records that have to
be imported together so identifiers can be resolved between them — a book and its
chapters, say. `Serializer.load_groups()` defaults to one group per object, so a
format describing one record per entry (CSV) yields groups of one and behaves
exactly as it always has. A group of one carries no `group_id`; where the records
of a task are grouped for import, `ImporterTask.get_record_groups()` falls back to
the record's own id, so each stays a group of its own.

```mermaid
flowchart TD
    S["valid_importer_file_data(task_id)"] --> T["_get_importer_task_classes()<br/>reads BULK_IMPORTER_RECORD_TYPES →<br/>(task, record_type_cls, serializer)"]
    T --> U["tasks_service.read_metadata_file()<br/>→ file stream"]
    U --> V["serializer.load_groups(stream)<br/>default: one group per object<br/>CSVSerializer: csv.DictReader<br/><b>yields one GroupEntry per row</b>"]
    V --> W["for each group:<br/>group_id = uuid4() if len(group) > 1 else None"]
    W --> W2["for each entry in the group:<br/>records_service.create(<br/>&nbsp;&nbsp;src_data=entry.data,<br/>&nbsp;&nbsp;group_id / group_key / group_role,<br/>&nbsp;&nbsp;group_position / group_relations,<br/>&nbsp;&nbsp;status=created, task_id=task.id)"]
    W2 --> X["validate_serialized_data.delay(record_id, task_id)"]
    V --> Y["finalize_importer_task.delay(task_id, 'validate')"]

    X --> V1["serializer.transform(src_data, mode)<br/>pydantic CSVRecordSchema / DeleteCSVRecordSchema<br/>→ (serializer_data, errors)"]
    V1 -- "errors" --> V2["status = serializer validation failed"]
    V1 -- "ok" --> V3["RDMRecord(serializer_data, bucket_id)<br/>__init__ pops id / communities / files<br/>off the serializer data"]
    V3 --> V4["RDMRecord.validate(mode)"]
    V4 --> V5["_verify_record_exists()"]
    V4 --> V6["_verify_files_accessible()<br/>local bucket / url / s3 / gs"]
    V4 --> V7["_verify_communities_exist()"]
    V4 --> V8["_validate_permissions()"]
    V4 --> V9["_verify_rdm_record_correctness()<br/>RDM marshmallow schema.load()"]
    V4 --> V10["_verify_pre_commit_correctness()<br/>RDMDraft extensions + relations,<br/>always rolled back"]
    V5 & V6 & V7 & V8 & V9 & V10 --> V11["records_service.update()<br/>status = validated | validation failed<br/>serializer_data, transformed_data,<br/>community_uuids, record_files,<br/>validated_record_files,<br/>existing_record_id, errors"]
```

## Import phase

```mermaid
flowchart TD
    R["run_transformed_records(task_id)"] --> R1["task.get_records()<br/>importer record ids for this task"]
    R1 --> R2["run_transformed_record.delay(record_id, task_id)"]
    R --> R3["finalize_importer_task.delay(task_id, 'import')"]

    R2 --> P0["RDMRecord((None, None), importer_record=record)"]
    P0 --> P1["RDMRecord.run(mode)<br/>guard: importer record status == validated<br/>single UnitOfWork, rolled back on failure"]
    P1 -- "mode=import" --> P2["_upsert_record()"]
    P1 -- "mode=delete" --> P3["_delete_record()"]
    P2 -- "no existing_record_id" --> P4["_create_record()<br/>rdm.create() → _doi_minting()"]
    P2 -- "existing_record_id" --> P5["_update_record()"]
    P5 -- "has files" --> P6["_update_new_version()<br/>new_version → update_draft →<br/>_add_files_to_record → publish"]
    P5 -- "metadata only" --> P7["_update_new_revision()<br/>edit → update_draft → publish"]
    P4 --> P8["_add_files_to_record()"]
    P8 --> P9["_publish_record()<br/>communities → _add_record_to_communities()<br/>else publish (if options.publish)"]
    P4 & P6 & P7 & P3 & P9 --> P10["records_service.update()<br/>status = success | import failed<br/>generated_record_id, errors"]
```

A single record can also be re-run on its own via
`POST /importer-records/:id/run` → `ImporterRecordService.start_run()` →
`run_transformed_record.delay()`, skipping the task-level fan-out.

## Status bookkeeping

`finalize_importer_task` is the only thing that moves the *task* status. It
re-reads the per-state record counts and recomputes the task state on every
pass, rescheduling itself while any record is still in a pending state for the
current phase.

```mermaid
stateDiagram-v2
    [*] --> created
    created --> validating: start_validation
    validating --> validated: all records validated
    validating --> validation_failed: any record failed
    validated --> importing: start_loading_records
    importing --> success: all records imported
    importing --> import_failed: any record failed
    validating --> damaged: poll limit exceeded
    importing --> damaged: poll limit exceeded
    validation_failed --> validating: re-validate
    validated --> validating: re-validate
```

Pending states per phase come from `PENDING_RECORD_STATES`: `created` during
validate, `validated` during import. Task state itself is derived from the
record counts by `TaskStateCalculator.calculate_task_state()`.
