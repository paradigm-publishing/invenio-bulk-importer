# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Bulk creation, import, and/or edittion of record and files for Invenio.."""

from invenio_i18n import lazy_gettext as _

from invenio_bulk_importer.record_types.rdm import RDMRecord
from invenio_bulk_importer.serializers.records.csv import CSVRDMRecordSerializer

BULK_IMPORTER_DEFAULT_VALUE = "foobar"
"""Default value for the application."""

BULK_IMPORTER_BASE_TEMPLATE = "invenio_bulk_importer/base.html"
"""Default base template for the demo page."""

BULK_IMPORTER_CUSTOM_FIELDS = {}
"""Custom fields wiring for the importer's serializers.

Maps a serializer key (e.g. ``"csv_rdm_record_serializer"``) to a list of
custom-field entries. Each entry describes how one custom field is built
from CSV columns on import and, optionally, how it is written back out
when exporting a record to CSV.

Each entry is a dict with the following keys:

:``field``: Dotted custom-field name as registered in the instance
    (``"<namespace>:<name>"``, e.g. ``"imprint:imprint"``). This is the
    key the value will be stored under in ``custom_fields`` on the
    record.
:``transformer``: Dotted import path to a callable that receives the raw
    CSV row (``dict[str, str]``) and returns the value to store under
    ``field``. Returning a falsy value skips the field for that row.
:``exporter``: Optional. Dotted import path to a callable that receives
    the record's value for ``field`` and returns a ``dict[str, str]`` of
    CSV columns to emit when exporting. Pair with ``export_field`` so
    the exported CSV round-trips back through the importer.
:``export_field``: Optional. Column-name prefix used for the exported
    columns (e.g. ``"imprint"`` produces ``imprint.isbn``,
    ``imprint.pages``, ...). Must match the prefix the ``transformer``
    expects on import.

Example::

    BULK_IMPORTER_CUSTOM_FIELDS = {
        "csv_rdm_record_serializer": [
            {
                "field": "imprint:imprint",
                "transformer": "invenio_bulk_importer.serializers.records.contrib.transformers.imprint_transform",
                "exporter": "invenio_bulk_importer.serializers.records.contrib.transformers.imprint_export",
                "export_field": "imprint",
            }
        ]
    }
"""

BULK_IMPORTER_FINALIZE_POLL_SECONDS = 15
"""Seconds between task status refreshes while records are still processing.

``finalize_importer_task`` reschedules itself at this interval until every
record has been processed, rewriting the task status on each pass. It doubles
as the progress cadence, so keep it short enough to look responsive.
"""

BULK_IMPORTER_FINALIZE_MAX_POLLS = 480
"""How many times ``finalize_importer_task`` may reschedule itself.

Together with ``BULK_IMPORTER_FINALIZE_POLL_SECONDS`` this bounds how long a
run may take before the task stops being followed. Beyond it, the last status
written stands. The default allows two hours for slow imports with downloads.
"""

BULK_IMPORTER_RECORD_TYPES = {
    "record": {
        "class": RDMRecord,
        "options": {
            "doi_minting": False,
            "publish": True,
        },
        "serializers": {"csv": CSVRDMRecordSerializer},
    }
}
"""List of options and serializers to be used by the importer."""


#
# Importer tasks Search configuration
#
BULK_IMPORTER_TASKS_FACETS = {}

BULK_IMPORTER_TASKS_SORT_OPTIONS = {
    "bestmatch": dict(
        title=_("Best match"),
        fields=["_score"],  # ES defaults to desc on `_score` field
    ),
    "newest": dict(
        title=_("Newest"),
        fields=["-created"],
    ),
    "oldest": dict(
        title=_("Oldest"),
        fields=["created"],
    ),
}

BULK_IMPORTER_TASKS_SEARCH = {
    "facets": [],
    "sort": ["bestmatch", "newest", "oldest"],
}


#
# Importer records Search configuration
#
BULK_IMPORTER_RECORDS_FACETS = {}

BULK_IMPORTER_RECORDS_SORT_OPTIONS = {
    "bestmatch": dict(
        title=_("Best match"),
        fields=["_score"],  # ES defaults to desc on `_score` field
    ),
    "newest": dict(
        title=_("Newest"),
        fields=["-created"],
    ),
    "oldest": dict(
        title=_("Oldest"),
        fields=["created"],
    ),
}

BULK_IMPORTER_RECORDS_SEARCH = {
    "facets": [],
    "sort": ["bestmatch", "newest", "oldest"],
}
