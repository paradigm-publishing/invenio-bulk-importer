# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Permissions for the importer task and record services.

Importer tasks and records hold the source data and the fully transformed
metadata of records that are not published yet, so reading them is limited
to administrators, matching who is allowed to create them.
"""

from invenio_administration.generators import Administration
from invenio_records_permissions import RecordPermissionPolicy
from invenio_records_permissions.generators import SystemProcess
from invenio_records_resources.services.files.generators import IfTransferType
from invenio_records_resources.services.files.transfer import LOCAL_TRANSFER_TYPE


class ImporterTaskPermissionPolicy(RecordPermissionPolicy):
    """Importer Task Permission Policy class."""

    can_search = [Administration(), SystemProcess()]
    can_create = [Administration(), SystemProcess()]
    can_update = [Administration(), SystemProcess()]
    can_delete = [Administration(), SystemProcess()]
    can_read = [Administration(), SystemProcess()]
    can_create_files = [Administration(), SystemProcess()]
    can_set_content_files = [Administration(), SystemProcess()]
    can_get_content_files = [
        IfTransferType(LOCAL_TRANSFER_TYPE, Administration()),
        SystemProcess(),
    ]
    can_commit_files = [Administration(), SystemProcess()]
    can_read_files = [Administration(), SystemProcess()]
    can_update_files = [Administration(), SystemProcess()]
    can_delete_files = [Administration(), SystemProcess()]
    can_search_records = [Administration(), SystemProcess()]


class ImporterRecordPermissionPolicy(RecordPermissionPolicy):
    """Importer Record Permission Policy class."""

    can_search = [Administration(), SystemProcess()]
    can_create = [Administration(), SystemProcess()]
    can_update = [Administration(), SystemProcess()]
    can_delete = [Administration(), SystemProcess()]
    can_read = [Administration(), SystemProcess()]
    can_create_files = [Administration(), SystemProcess()]
    can_set_content_files = [Administration(), SystemProcess()]
    can_get_content_files = [
        IfTransferType(LOCAL_TRANSFER_TYPE, Administration()),
        SystemProcess(),
    ]
    can_commit_files = [Administration(), SystemProcess()]
    can_read_files = [Administration(), SystemProcess()]
    can_update_files = [Administration(), SystemProcess()]
    can_delete_files = [Administration(), SystemProcess()]
    can_search_records = [Administration(), SystemProcess()]
