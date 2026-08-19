# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Rdm specific record resources."""

from flask import current_app
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_records_resources.services.uow import UnitOfWork
from invenio_records_resources.tasks import system_identity
from invenio_requests.proxies import current_requests_service
from marshmallow.exceptions import ValidationError as MarshmallowValidationError

from invenio_bulk_importer.record_types.base import (
    CommunityMixin,
    FileMixin,
    InvenioRecordMixin,
    PermissionsMixin,
    RecordType,
)

from ..proxies import current_importer_tasks_service as tasks_service
from ..records.api import ImporterRecord


class RDMRecord(
    PermissionsMixin, CommunityMixin, FileMixin, InvenioRecordMixin, RecordType
):
    """RDM Record validation and loading class."""

    def __init__(
        self,
        serializer_data: tuple[dict | None, dict | None],
        bucket_id: str = None,
        importer_record: ImporterRecord = None,
        **kwargs,
    ):
        """Initialize the rdm record resource.

        Args:
            serializer_data (tuple[dict | None, dict | None]): Data from the serializer [serialized record dict, errors].
            bucket_id (str): Identifier for the invenio bucket of the Bulk Importer process.
            **kwargs: Additional keyword arguments.
        """
        # Initialize the serializer data and errors

        self._add_community_vars(serializer_data)
        self._add_file_vars(serializer_data, bucket_id)
        super().__init__(serializer_data)
        self._importer_record = importer_record
        self.options = {}
        # get task options for creating record.
        if self._importer_record:
            self.options = tasks_service.record_cls.pid.resolve(
                self._importer_record.task_id
            )["options"]
        self.kwargs = kwargs

    def _verify_rdm_record_correctness(self, serializer_data):
        """Verify that the RDM record is correct."""
        schema = current_rdm_records_service.schema
        # Setup to be metadata only or with files.
        serializer_data["files"] = (
            dict(enabled=True) if self._files else dict(enabled=False)
        )
        try:
            self._record, _ = schema.load(
                serializer_data,
                context={"identity": system_identity},
                raise_errors=True,
            )
        except MarshmallowValidationError as e:
            self._process_validation_errors(e.messages, prefix="")

    def _process_validation_errors(self, errors, prefix=""):
        """Process validation errors recursively.

        Args:
            errors: The validation errors dict or list
            prefix: The current field path prefix
        """
        if isinstance(errors, dict):
            # Handle dictionary of errors (field_name -> error_message)
            for field, error in errors.items():
                field_path = f"{prefix}.{field}" if prefix else field

                if isinstance(error, (dict, list)):
                    # Recursively process nested errors
                    self._process_validation_errors(error, field_path)
                else:
                    # Handle string or list of string errors
                    if isinstance(error, list):
                        for err_msg in error:
                            self._add_error(
                                dict(
                                    type="validation_error", loc=prefix, msg=str(error)
                                )
                            )
                    else:
                        self._add_error(
                            dict(type="validation_error", loc=prefix, msg=str(error))
                        )
        elif isinstance(errors, list):
            # Handle list of errors
            if all(isinstance(item, (dict, list)) for item in errors):
                # List of nested structures
                for i, error in enumerate(errors):
                    self._process_validation_errors(error, f"{prefix}[{i}]")
            else:
                # List of string error messages
                for error in errors:
                    self._add_error(
                        dict(type="validation_error", loc=prefix, msg=str(error))
                    )

    def validate(self, mode: str) -> bool:
        """Validate the serializer object can be loaded into Invenio.

        Returns True if the validation is successful, otherwise False.
        """
        if not self._serializer_record_data:
            self._add_error(
                dict(
                    type="serialized_record_not_provided",
                    loc="serialized_record",
                    msg="Existing serialized errors, cannot progress any further.",
                )
            )
            return False
        self._verify_record_exists(self.id, required=(mode == "delete"))
        if mode == "import":  # Only validate further if we are importing records.
            self._verify_files_accessible(self._files)
            self._verify_communities_exist(self._serializer_communities)
            self._validate_permissions(self._serializer_record_data)
            self._verify_rdm_record_correctness(self._serializer_record_data)
            self._verify_pre_commit_correctness(self._record)
        elif mode == "delete":
            self._record = self._serializer_record_data
        return self.is_successful

    def run(self, mode: str = "import") -> dict | None:
        """Run the record creation/edit or delete process.

        At this point a importer record must be validated to continue.

        The whole run is one unit of work: on failure it is rolled back, so a
        partially imported record (created, but missing its files or never
        published) is never left behind. Errors are reported on
        :attr:`errors` instead, for the caller to persist.

        :param mode: Either ``import`` or ``delete``.
        :return: The created, updated or deleted record, or ``None`` when the
            run did not complete.
        """
        if not self._importer_record or self._importer_record["status"] != "validated":
            # Cannot run record creation as not in correct status.
            return
        # Run create, edit or delete
        try:
            # NOTE: not the `unit_of_work()` decorator, as that commits
            # whatever was done so far whenever an exception is swallowed
            # rather than re-raised. Exiting the context manager with an
            # exception in flight rolls back instead.
            with UnitOfWork(db.session) as uow:
                if mode == "import":  # Create the RDM record using the validated data.
                    record_item = self._upsert_record(self._importer_record, uow)
                else:  # Delete record.
                    record_item = self._delete_record(self._importer_record, uow)
                uow.commit()
            return record_item
        except Exception:
            if not self.errors:
                # If no errors were added, log the traceback as an error.
                self._add_error(
                    dict(
                        type="unexpected_error",
                        loc="run",
                        msg="An unexpected error occurred",
                    )
                )
            current_app.logger.exception("Unexcepted error.")
        return

    def _create_record(self, importer_record, uow):
        """Create a new Invenio record."""
        try:
            data = importer_record["transformed_data"]
            record_item = current_rdm_records_service.create(
                system_identity,
                data=data,
                uow=uow,
            )
            self._doi_minting(record_item, data, uow)

        except Exception as e:
            self._add_error(
                dict(
                    type="record_creation_error",
                    loc="record",
                    msg=f"Error creating record: {str(e)}",
                )
            )
            current_app.logger.exception("Error creating a new record.")
            raise
        self._add_files_to_record(self._importer_record, record_item, uow)
        self._publish_record(record_item, uow)
        return record_item

    def _doi_minting(self, record_item, data, uow):
        """Check if DOI minting and pid required then get doi from provider."""
        if not current_app.config["DATACITE_ENABLED"]:
            # If the datacite is not enabled, skip DOI minting.
            return
        # Check doi setup
        if current_app.config["RDM_PERSISTENT_IDENTIFIERS"]["doi"]["required"]:
            # Will automatically create a DOI if required.
            return

        if self.options.get("doi_minting") and "doi" not in data.get("pids", {}):
            # if pids doesn't have an external doi and minted config is set to True
            current_rdm_records_service.pids.create(
                system_identity,
                record_item.id,
                "doi",
                provider="datacite",
                uow=uow,
            )

    def _delete_record(self, importer_record, uow):
        """Delete an existing Invenio record."""
        existing_record_id = importer_record.get("existing_record_id")
        try:
            data = importer_record["transformed_data"]
            tombstone_info = dict(note=data.get("reason", "deleted by bulk importer."))
            record_item = current_rdm_records_service.delete_record(
                system_identity, existing_record_id, tombstone_info, uow=uow
            )
        except Exception as e:
            self._add_error(
                dict(
                    type="record_deletion_error",
                    loc="record",
                    msg=f"Error deleting record ({existing_record_id}): {str(e)}",
                )
            )
            current_app.logger.exception("Error deleting a record.")
            raise
        return record_item

    def _update_record(self, existing_record_id, importer_record, uow):
        """Update an existing Invenio record is required, determine what type of update."""
        record_item = None
        if importer_record.get("validated_record_files", []):
            # If files are being added, create a new version.
            record_item = self._update_new_version(
                existing_record_id, importer_record, uow
            )
        else:  # Revision update as just metadata
            record_item = self._update_new_revision(
                existing_record_id, importer_record, uow
            )
        return record_item

    def _update_new_revision(self, existing_record_id, importer_record, uow):
        """Update an existing Invenio record by creating a new version - no files."""
        try:
            data = importer_record.get("transformed_data", {})
            record_item = current_rdm_records_service.edit(
                system_identity,
                existing_record_id,
                uow=uow,
            )
            record_item = current_rdm_records_service.update_draft(
                system_identity,
                record_item.id,
                data=data,
                uow=uow,
            )
            current_rdm_records_service.publish(
                system_identity,
                record_item.id,
                uow=uow,
            )
        except Exception as e:
            self._add_error(
                dict(
                    type="record_update_error",
                    loc="record",
                    msg=f"Error updating record ({existing_record_id}): {str(e)}",
                )
            )
            current_app.logger.exception("Error creating new revision.")
            raise
        return record_item

    def _update_new_version(self, existing_record_id, importer_record, uow):
        """Update an existing Invenio record by creating a new version because it has files."""
        try:
            data = importer_record.get("transformed_data", {})
            record_item = current_rdm_records_service.new_version(
                system_identity,
                existing_record_id,
                uow=uow,
            )
            #  Update the draft with the new metadata.
            current_rdm_records_service.update_draft(
                system_identity,
                record_item.id,
                data=data,
                uow=uow,
            )
            # Add files to the draft.
            self._add_files_to_record(importer_record, record_item, uow)
            # Publish the new version. even if in a community.
            # It appears you cannot change the community of a record via edit.
            current_rdm_records_service.publish(
                system_identity,
                record_item.id,
                uow=uow,
            )
        except Exception as e:
            self._add_error(
                dict(
                    type="record_update_error",
                    loc="record",
                    msg=f"Error creating new version of record ({existing_record_id}): {str(e)}",
                )
            )
            current_app.logger.exception("Error creating a new version.")
            raise
        return record_item

    def _upsert_record(self, importer_record, uow):
        """Record to be updated or created based on if exisiting record id is present."""
        if existing_record_id := importer_record.get("existing_record_id"):
            return self._update_record(existing_record_id, importer_record, uow)
        return self._create_record(importer_record, uow)

    def _add_files_to_record(self, importer_record, record_item, uow=None) -> None:
        """Add the file to the specified record."""
        # TODO: Consider large files, will they timeout the celery task this is run in?
        # TODO: Consider timeout of file streams from url or cloud buckets
        # TODO: Consider moving files from IMporter task bucket to RDM record bucket rather than copy.
        files = importer_record.get("validated_record_files", [])
        if not files:
            return
        file_service = current_rdm_records_service.draft_files
        try:
            file_service.init_files(
                system_identity,
                record_item.id,
                [{"key": f["key"]} for f in files],
                uow=uow,
            )
        except Exception as e:
            self._add_error(
                dict(
                    type="file_add_error",
                    loc="files",
                    msg=f"Error initializing file for '{record_item.id}': {str(e)}",
                )
            )
            current_app.logger.exception("Error adding files to the record.")
            raise
        for file in files:
            file_key = file["key"]
            try:
                file_service.set_file_content(
                    system_identity,
                    record_item.id,
                    file_key,
                    self._get_stream_for_file_content(file),
                    file["size"],
                    uow=uow,
                )
                # Commit the file to the record
                file_service.commit_file(
                    system_identity, record_item.id, file_key, uow=uow
                )
            except Exception as e:
                self._add_error(
                    dict(
                        type="file_add_error",
                        loc="files",
                        msg=f"Error uploading and commiting '{file_key}' to record '{record_item.id}': {str(e)}",
                    )
                )
                current_app.logger.exception("Error adding a file to the record.")
                raise

    def _add_record_to_communities(self, community_uuids: dict, record, uow) -> None:
        """Add the record to the specified community.

        If community_uuids is empty then the record will be published.

        Args:
            community_uuids (dict): Dictionary containing community UUIDs.
            record (RDMRecord): The record to be added to the community.
            uow: Unit of Work for database operations.
        """
        for community_id in community_uuids["ids"]:
            try:
                data = {
                    "type": "community-submission",
                    "receiver": {"community": community_id},
                }
                # Update record parent with community relationships request.
                request = current_rdm_records_service.review.update(
                    system_identity,
                    record.id,
                    data,
                    uow=uow,
                )
                if self.options.get("publish", True):
                    # Submit record to community to be accepted.
                    current_requests_service.execute_action(
                        system_identity, id_=request.id, action="submit", uow=uow
                    )
                    # Accept Record into the community.
                    current_requests_service.execute_action(
                        system_identity,
                        id_=request.id,
                        action="accept",
                        data={
                            "payload": {
                                "content": "This record is accepted automatically using the bulk importer.",
                                "format": "html",
                            }
                        },
                        send_notification=False,
                        uow=uow,
                    )
            except Exception as e:
                self._add_error(
                    dict(
                        type="record_add_error",
                        loc="communities.record",
                        msg=f"Error adding record '{record.id}' to community '{community_id}': {str(e)}",
                    )
                )
                current_app.logger.exception("Error publishing record.")
                raise

    def _publish_record(self, record_item, uow):
        """Publish the record in community or globally."""
        # # Add the record to the communities if specified.
        community_uuids = self._importer_record.get("community_uuids", {})
        if community_uuids:
            self._add_record_to_communities(community_uuids, record_item, uow)
        else:
            if self.options.get("publish", True):
                # If no communities specified, publish globally.
                current_rdm_records_service.publish(
                    system_identity,
                    record_item.id,
                    uow=uow,
                )
