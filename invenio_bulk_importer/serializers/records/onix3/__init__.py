# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""ONIX 3.0 serializer."""

from .codes import DEFAULT_CONTRIBUTOR_ROLES
from .schema import DEFAULT_SETTINGS
from .serializer import ONIX3RDMRecordSerializer

__all__ = (
    "DEFAULT_CONTRIBUTOR_ROLES",
    "DEFAULT_SETTINGS",
    "ONIX3RDMRecordSerializer",
)
