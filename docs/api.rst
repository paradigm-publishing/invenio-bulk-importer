..
    Copyright (C) 2025 Ubiquity Press.

    Invenio-Bulk-Importer is free software; you can redistribute it and/or
    modify it under the terms of the MIT License; see LICENSE file for more
    details.


API Docs
========

Extension
---------

.. automodule:: invenio_bulk_importer.ext
   :members:


CSV serializers
---------------

Input schema and serializer used to read CSV files into RDM records.

.. automodule:: invenio_bulk_importer.serializers.records.csv
   :members:
   :show-inheritance:

Export serializer used to flatten RDM records back into CSV.

.. automodule:: invenio_bulk_importer.serializers.records.csv_export
   :members:
   :show-inheritance:

Shared helpers for parsing grouped and discriminator columns.

.. automodule:: invenio_bulk_importer.serializers.records.utils
   :members:


ONIX 3.0 serializer
-------------------

Defaults for :py:data:`~invenio_bulk_importer.config.BULK_IMPORTER_ONIX3_SERIALIZER`.
Import them from ``invenio_bulk_importer.serializers.records.onix3``.

.. autodata:: invenio_bulk_importer.serializers.records.onix3.schema.DEFAULT_SETTINGS

.. autodata:: invenio_bulk_importer.serializers.records.onix3.codes.DEFAULT_CONTRIBUTOR_ROLES
