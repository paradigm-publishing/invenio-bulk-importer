# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""ONIX 3.0 codelist values this serializer reads.

Only the codes that carry meaning for us are named. Everything else is passed
through as the raw string, so a lookup table added later can interpret it
without the file having to be uploaded again.
"""

ONIX_NS = "http://ns.editeur.org/onix/3.0/reference"
"""Namespace of ONIX 3.0 reference-tag messages."""

NSMAP = {"onix": ONIX_NS}
"""Prefix map for the ``find``/``findall`` paths in :mod:`.reader`."""

# Codelist 5, ProductIDType.
PRODUCT_ID_PROPRIETARY = "01"
PRODUCT_ID_DOI = "06"
PRODUCT_ID_ISBN13 = "15"

# Codelist 43, TextItemIDType.
TEXT_ITEM_ID_DOI = "06"

# Codelist 42, TextItemType.
TEXT_ITEM_FRONT_MATTER = "02"
TEXT_ITEM_BODY_MATTER = "03"

# Codelist 153, TextType.
TEXT_TYPE_DESCRIPTION = "03"
TEXT_TYPE_REVIEW = "06"
TEXT_TYPE_BIOGRAPHICAL_NOTE = "12"

# Codelist 158, ResourceContentType.
RESOURCE_CONTENT_FRONT_COVER = "01"
RESOURCE_CONTENT_FULL = "28"

# Codelist 162, ResourceVersionFeatureType.
FEATURE_FILE_FORMAT = "01"
FEATURE_FILENAME = "04"
FEATURE_FILE_SIZE_BYTES = "07"

# Codelist 178, ResourceFileFormat.
FILE_FORMAT_PDF = "E107"

# Codelist 27, SubjectSchemeIdentifier.
SUBJECT_SCHEME_KEYWORDS = "20"
SUBJECT_SCHEME_PROPRIETARY = "23"

# Codelist 22, LanguageRole.
LANGUAGE_ROLE_TEXT = "01"

# Codelist 23, ExtentType: the page count the preprocessor emits.
EXTENT_TYPE_PAGES = "05"

# Codelist 149, TitleElementLevel.
TITLE_LEVEL_PRODUCT = "01"

# Codelist 45, PublishingRole.
PUBLISHING_ROLE_PUBLISHER = "01"

# Codelist 163, PublishingDateRole.
PUBLISHING_DATE_PUBLICATION = "01"

# Codelist 64, PublishingStatus.
PUBLISHING_STATUS_WITHDRAWN = "11"
"""Withdrawn from sale; the preprocessor emits it for a retracted title."""

FILE_ROLE_CONTENT = "content"
FILE_ROLE_COVER = "cover"
FILE_ROLE_OTHER = "other"
"""Roles :mod:`.reader` assigns to a supporting resource.

``other`` is kept in the source data for auditing but never reaches the record.
"""

CREATORS = "creators"
CONTRIBUTORS = "contributors"

DEFAULT_CONTRIBUTOR_ROLES = {
    # Codelist 17 -> (which RDM list, which role id).
    "A01": (CREATORS, "author"),
    "A02": (CREATORS, "co-author"),
    "A38": (CREATORS, "author"),
    "B01": (CONTRIBUTORS, "editor"),
    "B02": (CONTRIBUTORS, "editor"),
    "B09": (CONTRIBUTORS, "editor"),
    "B06": (CONTRIBUTORS, "translator"),
    # No illustrator, foreword or introduction role exists in the RDM
    # vocabulary, so these land on ``other`` rather than being dropped.
    "A12": (CONTRIBUTORS, "other"),
    "A23": (CONTRIBUTORS, "other"),
    "A24": (CONTRIBUTORS, "other"),
    "A32": (CONTRIBUTORS, "other"),
    "B25": (CONTRIBUTORS, "other"),
    "Z99": (CONTRIBUTORS, "other"),
}
"""Default reading of ONIX codelist 17.

Codelist 17 is a published standard rather than site policy, so this ships as a
default. A site overrides it through ``BULK_IMPORTER_ONIX3_SERIALIZER``.
"""

UNMAPPED_CONTRIBUTOR_ROLE = (CONTRIBUTORS, "other")
"""Where a contributor whose ONIX role we do not know ends up.

Never dropped: losing a person silently is the worst failure available here.
"""
