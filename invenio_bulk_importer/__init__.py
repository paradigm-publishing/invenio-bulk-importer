# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Bulk creation, import, and/or edittion of record and files for Invenio."""

from .ext import InvenioBulkImporter

__version__ = "0.1.2"

__all__ = ("__version__", "InvenioBulkImporter")
