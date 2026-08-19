# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Importer task service components."""

from invenio_records_resources.services.records.components import ServiceComponent

from ..proxies import current_importer_records_service


class ImporterTaskServiceComponent(ServiceComponent):
    """Importer Task Service Component."""

    # store user identity only on create, ignore later
    def create(self, identity, *, record, **kwargs):
        """Create a new importer task."""
        record.update_start_by_id(identity.user.id)

    def _purge_importer_records(self, identity, record):
        """Delete the importer records currently attached to the task."""
        for importer_record_id in record.get_records():
            current_importer_records_service.delete(
                identity, id_=importer_record_id, uow=self.uow
            )

    def metadata_file_update(self, identity, *, id_, record, **kwargs):
        """Clean previous tasks to avoid duplicates after uploading a metadata file."""
        self._purge_importer_records(identity, record)

    def validation_start(self, identity, *, record, **kwargs):
        """Clean previous records so re-validating replaces them, not duplicates them."""
        self._purge_importer_records(identity, record)


class ImporterRecordServiceComponent(ServiceComponent):
    """Importer Task Service Component."""

    # store user identity only on create, ignore later
    def create(self, identity, *, record, task_id, **kwargs):
        """Create a new importer task."""
        record.update_task_id(task_id)
