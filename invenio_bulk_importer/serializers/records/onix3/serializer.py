# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""ONIX 3.0 serializer for RDM records.

Reads the aggregated ONIX message produced by the publisher-delivery
preprocessor: one ``<Product>`` per book, its chapters as
``<ContentDetail>/<ContentItem>``, every file a ``gs://`` link. Each product
becomes a group (the book, then its chapters) imported together.
"""

from typing import IO, Iterator

from pydantic import ValidationError

from ...base import GroupEntry, Serializer
from ..utils import generate_error_messages
from .codes import FILE_ROLE_CONTENT, FILE_ROLE_COVER
from .linking import BOOK_KEY, sibling_links
from .reader import check_filenames, iter_products, parse_product
from .schema import (
    ONIXRecordSchema,
    build_book_payload,
    build_chapter_payload,
    get_settings,
)

ALLOWED_FILE_SCHEMES = ("gs://",)
"""Schemes a file link may use.

The preprocessor can emit ``file://`` links for local runs; those name paths on
whichever machine wrote the file, which the importer's workers cannot reach.
"""

WITHDRAWN = "11"

ATTACHED_ROLES = {
    "book": (FILE_ROLE_CONTENT, FILE_ROLE_COVER),
    "chapter": (FILE_ROLE_CONTENT,),
}
"""File roles each kind of record gets."""


class ONIX3RDMRecordSerializer(Serializer):
    """Serializer for ONIX 3.0 messages describing books and their chapters."""

    stream_mode = "rb"

    def load_groups(self, stream: IO, **kwargs) -> Iterator[list[GroupEntry]]:
        """Yield one group per ``<Product>``: the book, then its chapters.

        A book without chapters is a group of one, and so is imported exactly
        like a record from a one-record-per-entry format.

        :param stream: Binary stream over an ONIX 3.0 message.
        :return: Iterator of groups, the book first and chapters in reading
            order.
        """
        for product in iter_products(stream):
            book, chapters = parse_product(product)
            if not chapters:
                yield [GroupEntry(data=book)]
                continue
            _, book_intents = sibling_links(book)
            group = [
                GroupEntry(
                    data=book,
                    key=BOOK_KEY,
                    role="parent",
                    position=0,
                    relations=book_intents,
                )
            ]
            for position, chapter in enumerate(chapters, start=1):
                _, intents = sibling_links(chapter)
                group.append(
                    GroupEntry(
                        data=chapter,
                        key=chapter["key"],
                        role="child",
                        position=position,
                        relations=intents,
                    )
                )
            yield group

    def load(self, stream: IO, **kwargs) -> Iterator[dict]:
        """Yield every record's source data, books and chapters alike.

        :param stream: Binary stream over an ONIX 3.0 message.
        :return: Iterator of source data dicts.
        """
        for group in self.load_groups(stream, **kwargs):
            yield from (entry.data for entry in group)

    def _precheck(self, obj: dict) -> list[dict]:
        """Find problems that stop a record before its payload is built.

        :param obj: A book's or chapter's source data.
        :return: Error dicts, empty when the record may proceed.
        """
        errors = []
        status = (
            obj.get("publishing_status")
            if obj.get("type") == "book"
            else (obj.get("book") or {}).get("publishing_status")
        )
        if status == WITHDRAWN:
            errors.append(
                dict(
                    type="retracted_title",
                    loc="publishing_status",
                    msg="The title is withdrawn (PublishingStatus 11), so no "
                    "record is created for it.",
                )
            )
        # Only files that reach the record: a MARC record or other resource
        # that is never attached must not block the import.
        attached = [
            f
            for f in obj.get("files", [])
            if f["role"] in ATTACHED_ROLES.get(obj.get("type"), ())
        ]
        for entry in attached:
            if not entry["uri"].startswith(ALLOWED_FILE_SCHEMES):
                errors.append(
                    dict(
                        type="invalid_file_uri",
                        loc="files",
                        msg=f"File '{entry['uri']}' is not a gs:// link; ONIX "
                        "imports only accept files in Google Cloud Storage.",
                    )
                )
        for message in check_filenames(attached):
            errors.append(dict(type="file_name_mismatch", loc="files", msg=message))
        return errors

    def transform(
        self, obj: dict, mode: str = "import"
    ) -> tuple[dict | None, list[dict] | None]:
        """Transform a book's or chapter's source data into a record payload.

        :param obj: Source data produced by :meth:`load_groups`.
        :param mode: Only ``import`` is supported.
        :return: The payload and ``None``, or ``None`` and the errors found.
        """
        if mode != "import":
            # An error, not an exception: delete is selectable on the task, and
            # raising would bury the reason under a traceback on every record.
            return None, [
                dict(
                    type="unsupported_mode",
                    loc="mode",
                    msg="The ONIX 3 serializer only supports import mode.",
                )
            ]
        builders = {"book": build_book_payload, "chapter": build_chapter_payload}
        builder = builders.get(obj.get("type"))
        if builder is None:
            return None, [
                dict(
                    type="unknown_entry_type",
                    loc="type",
                    msg=f"Expected a book or chapter entry, got {obj.get('type')!r}.",
                )
            ]
        if errors := self._precheck(obj):
            return None, errors
        try:
            payload = builder(obj, get_settings())
            return ONIXRecordSchema(**payload).model_dump(exclude_none=True), None
        except ValidationError as e:
            return None, generate_error_messages(e.errors())
