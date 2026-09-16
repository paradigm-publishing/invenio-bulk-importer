# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for grouping an ONIX message into books and their chapters."""

from io import BytesIO
from pathlib import Path

from invenio_bulk_importer.serializers.records.onix3 import ONIX3RDMRecordSerializer

DATA = Path(__file__).parent / "data" / "onix"

NS = "http://ns.editeur.org/onix/3.0/reference"


def _groups(name):
    """Group every product of a fixture file.

    :param name: Fixture file name under ``data/onix``.
    :return: The groups, as lists of entries.
    """
    with (DATA / name).open("rb") as stream:
        return list(ONIX3RDMRecordSerializer().load_groups(stream))


def test_group_is_book_then_chapters():
    """A product becomes its book followed by its chapters, in reading order."""
    (group,) = _groups("book_with_chapters.onix.xml")

    assert [(e.key, e.role, e.position) for e in group] == [
        ("book", "parent", 0),
        ("chapter:1", "child", 1),
        ("chapter:2", "child", 2),
        ("chapter:3", "child", 3),
    ]
    assert group[0].data["type"] == "book"
    assert all(e.data["type"] == "chapter" for e in group[1:])


def test_product_without_chapters_is_a_group_of_one():
    """A book with no chapters imports like a record from a flat format."""
    _, lone = _groups("two_books.onix.xml")

    (entry,) = lone
    assert (entry.key, entry.role, entry.position, entry.relations) == (
        None,
        None,
        0,
        [],
    )


def test_no_pending_relations_when_every_doi_is_present():
    """With DOIs on both sides, every link is written directly."""
    (group,) = _groups("book_with_chapters.onix.xml")

    assert all(entry.relations == [] for entry in group)


def test_relation_pending_when_a_chapter_doi_is_missing():
    """Only the link to the chapter without a DOI waits for the group import."""
    group, _ = _groups("two_books.onix.xml")

    book, with_doi, without_doi = group
    assert book.relations == [
        {
            "target_key": "chapter:2",
            "relation_type": {"id": "haspart"},
            "resource_type": {"id": "publication-book-chapter"},
        }
    ]
    # Both chapters can still link to the book, which has a DOI.
    assert with_doi.relations == []
    assert without_doi.relations == []


def test_relations_pending_when_the_book_doi_is_missing():
    """The two directions degrade independently."""
    stream = BytesIO(
        (
            "<?xml version='1.0' encoding='UTF-8'?>"
            f'<ONIXMessage xmlns="{NS}" release="3.0"><Header><Sender>'
            "<SenderName>t</SenderName></Sender>"
            "<SentDateTime>20260101</SentDateTime></Header>"
            "<Product><RecordReference>r</RecordReference><ContentDetail>"
            "<ContentItem><LevelSequenceNumber>1</LevelSequenceNumber>"
            "<TextItem><TextItemType>03</TextItemType><TextItemIdentifier>"
            "<TextItemIDType>06</TextItemIDType><IDValue>10.5555/c1</IDValue>"
            "</TextItemIdentifier></TextItem></ContentItem>"
            "</ContentDetail></Product></ONIXMessage>"
        ).encode("utf-8")
    )

    (group,) = list(ONIX3RDMRecordSerializer().load_groups(stream))

    book, chapter = group
    # The book links to its chapter through the chapter's DOI...
    assert book.relations == []
    # ...but the chapter cannot link back through a DOI the book lacks.
    assert chapter.relations == [
        {
            "target_key": "book",
            "relation_type": {"id": "ispartof"},
            "resource_type": {"id": "publication-book"},
        }
    ]


def test_load_yields_every_record():
    """The flat view carries the same records as the grouped one."""
    with (DATA / "two_books.onix.xml").open("rb") as stream:
        records = list(ONIX3RDMRecordSerializer().load(stream))

    assert [r["type"] for r in records] == ["book", "chapter", "chapter", "book"]


def test_stream_is_opened_as_bytes():
    """The task must hand the parser bytes, so the declared encoding is honoured."""
    assert ONIX3RDMRecordSerializer.stream_mode == "rb"
