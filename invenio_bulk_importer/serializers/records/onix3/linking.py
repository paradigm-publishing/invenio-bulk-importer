# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Links between a book and its chapters.

The one place the linking rule lives. It is applied twice, in different tasks at
different times. Once when the file is read, to record what cannot be linked
yet, and once when each record is transformed, to write what can, so both
halves are derived here from the same source data and cannot drift apart.

The rule: a link is written as a DOI when the record at the other end has one.
DOIs are what the preprocessor supplies for books and chapters alike, and
``doi`` is among the schemes RDM's DataCite serializer keeps
(``RELATED_IDENTIFIER_SCHEMES``, a hardcoded set), so these links reach
DataCite. Do not swap them for a bespoke local-record scheme: that set would
silently drop it on export.

When the other end has no DOI the link cannot be written yet. Its intent is
recorded instead, for the group import to resolve once every record of the group
has a PID. The two directions degrade independently: a book links to a chapter
through the *chapter's* DOI, a chapter to its book through the *book's*.
"""

BOOK_KEY = "book"
"""Group key of the book entry; chapters use ``chapter:<sequence>``."""

RESOURCE_TYPE_BOOK = "publication-book"
RESOURCE_TYPE_CHAPTER = "publication-book-chapter"

RELATION_HAS_PART = "haspart"
RELATION_IS_PART_OF = "ispartof"


def _link(target_key, doi, relation, resource_type):
    """Build one link, resolved when a DOI is known and pending otherwise.

    :param target_key: Group key of the record at the other end.
    :param doi: DOI of the record at the other end, when it has one.
    :param relation: RDM relation type id.
    :param resource_type: RDM resource type id of the record at the other end.
    :return: ``(related_identifier, None)`` or ``(None, intent)``.
    """
    relation_type = {"id": relation}
    resource = {"id": resource_type}
    if doi:
        return (
            {
                "identifier": doi,
                "scheme": "doi",
                "relation_type": relation_type,
                "resource_type": resource,
            },
            None,
        )
    return (
        None,
        {
            "target_key": target_key,
            "relation_type": relation_type,
            "resource_type": resource,
        },
    )


def sibling_links(src: dict) -> tuple[list[dict], list[dict]]:
    """Split an entry's links to its siblings into resolvable and pending.

    :param src: Source data of a book or a chapter, as produced by the reader.
    :return: ``(related_identifiers, intents)``: the links that can be written
        into ``metadata.related_identifiers`` now, and the ones to record for
        the group import.
    """
    if src.get("type") == "book":
        candidates = [
            _link(
                chapter["key"],
                chapter.get("doi"),
                RELATION_HAS_PART,
                RESOURCE_TYPE_CHAPTER,
            )
            for chapter in src.get("chapters", [])
        ]
    else:
        book = src.get("book") or {}
        candidates = [
            _link(BOOK_KEY, book.get("doi"), RELATION_IS_PART_OF, RESOURCE_TYPE_BOOK)
        ]
    resolved = [link for link, _ in candidates if link]
    pending = [intent for _, intent in candidates if intent]
    return resolved, pending
