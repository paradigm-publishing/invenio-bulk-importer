# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for reading ONIX 3.0 messages into source data."""

from io import BytesIO
from pathlib import Path

import pytest

from invenio_bulk_importer.serializers.records.onix3.reader import (
    ONIXReadError,
    check_filenames,
    iter_products,
    parse_product,
)

DATA = Path(__file__).parent / "data" / "onix"

NS = "http://ns.editeur.org/onix/3.0/reference"


def _parse(name):
    """Parse every product of a fixture file.

    :param name: Fixture file name under ``data/onix``.
    :return: A ``(book, chapters)`` pair per product.
    """
    with (DATA / name).open("rb") as stream:
        return [parse_product(product) for product in iter_products(stream)]


def _message(products_xml):
    """Wrap product markup in a namespaced ONIX message.

    :param products_xml: One or more ``<Product>`` elements, as markup.
    :return: A binary stream over the message.
    """
    return BytesIO(
        (
            "<?xml version='1.0' encoding='UTF-8'?>"
            f'<ONIXMessage xmlns="{NS}" release="3.0">'
            "<Header><Sender><SenderName>t</SenderName></Sender>"
            "<SentDateTime>20260101</SentDateTime></Header>"
            f"{products_xml}</ONIXMessage>"
        ).encode("utf-8")
    )


def test_iter_products_yields_every_product():
    """A message holding two books yields two products, in order."""
    parsed = _parse("two_books.onix.xml")

    assert [book["title"] for book, _ in parsed] == [
        "A Book With Chapters",
        "A Book Without Chapters Or A DOI",
    ]


def test_iter_products_frees_consumed_products():
    """Products already consumed are dropped, so memory stays bounded.

    lxml parses ahead in chunks, so products *after* the current one may
    already be in the tree, bounded by the chunk size. What must not
    accumulate is what came *before*: at most the previous product, emptied.
    """
    stream = _message(
        "".join(
            f"<Product><RecordReference>r{n}</RecordReference></Product>"
            for n in range(5)
        )
    )

    for product in iter_products(stream):
        retained = product.getparent().findall(f"{{{NS}}}Product")
        before = retained[: retained.index(product)]
        assert len(before) <= 1
        assert all(len(p) == 0 for p in before)


def test_reader_rejects_root_without_namespace():
    """A namespace-less file says why it yields nothing."""
    stream = BytesIO(b"<ONIXMessage release='3.0'><Product/></ONIXMessage>")

    with pytest.raises(ONIXReadError, match="carries no namespace"):
        list(iter_products(stream))


def test_reader_rejects_short_tag_message():
    """A short-tag message is not silently read as an empty one."""
    stream = BytesIO(b"<ONIXmessage release='3.0'><product/></ONIXmessage>")

    with pytest.raises(ONIXReadError):
        list(iter_products(stream))


def test_reader_rejects_bare_product():
    """A lone product, rather than a full message, is rejected with a reason."""
    stream = BytesIO(
        f'<Product xmlns="{NS}"><RecordReference>x</RecordReference></Product>'.encode()
    )

    # The bare product *is* yielded by tag match, so reading succeeds. But a
    # document whose root is not a message and holds no product is refused.
    empty = BytesIO(f'<Header xmlns="{NS}"/>'.encode())
    with pytest.raises(ONIXReadError, match="Expected an <ONIXMessage> root"):
        list(iter_products(empty))
    assert len(list(iter_products(stream))) == 1


def test_reader_does_not_resolve_external_entities(tmp_path):
    """An external entity is left unexpanded rather than read off the disk.

    :param tmp_path: Pytest temporary directory.
    """
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    stream = BytesIO(
        (
            "<?xml version='1.0' encoding='UTF-8'?>"
            f'<!DOCTYPE ONIXMessage [<!ENTITY leak SYSTEM "file://{secret}">]>'
            f'<ONIXMessage xmlns="{NS}" release="3.0"><Product>'
            "<RecordReference>r</RecordReference><DescriptiveDetail><TitleDetail>"
            "<TitleType>01</TitleType><TitleElement>"
            "<TitleElementLevel>01</TitleElementLevel>"
            "<TitleText>&leak;</TitleText>"
            "</TitleElement></TitleDetail></DescriptiveDetail>"
            "</Product></ONIXMessage>"
        ).encode("utf-8")
    )

    ((book, _),) = [parse_product(p) for p in iter_products(stream)]

    assert "TOP-SECRET" not in (book["title"] or "")


def test_book_entry_shape():
    """The book-level fields are read from where ONIX puts them."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    assert book["type"] == "book"
    assert book["doi"] == "10.3138/9781442617650"
    assert book["isbn"] == "9781442617650"
    assert book["private_identifiers"] == {"edition_id": "524020"}
    assert book["title"] == "Collected Works of Erasmus"
    assert book["subtitle"] == "Prolegomena to the Adages"
    assert book["edition"] == "2nd edition"
    assert book["series"] == {
        "title": "Erasmus Studies",
        "code": "UTPERST-B",
        "volume": "30",
    }
    assert book["languages"] == ["eng"]
    assert book["page_count"] == "856"
    assert book["subject_codes"] == ["SC-LT-01"]
    assert book["publisher"] == "University of Toronto Press"
    assert book["publication_date"] == "20190219"
    assert book["copyright_year"] == "2017"
    assert book["copyright_owner"] == "University of Toronto Press"
    assert book["license"] == {
        "name": "CC BY 4.0",
        "link": "https://creativecommons.org/licenses/by/4.0/",
    }
    assert book["description"] == "The English description."
    assert book["reviews"] == "A glowing review."
    assert book["biographical_note"] == "Erasmus: a Dutch humanist."
    assert [c["onix_role"] for c in book["contributors"]] == ["A01", "B01"]
    assert book["contributors"][0]["family_name"] == "Erasmus"
    assert book["contributors"][0]["given_names"] == "Desiderius"


def test_values_are_left_as_onix_wrote_them():
    """Codes and dates are not mapped at read time, so a table fix needs no re-upload."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    assert book["publication_date"] == "20190219"
    assert book["contributors"][1]["onix_role"] == "B01"
    assert book["audience_scheme"] == "degruyter-audience"


def test_licence_absent_when_not_openly_licensed():
    """No ``<EpubLicense>`` reads as no licence, which is what marks a closed title."""
    ((book, _),) = _parse("file_uri.onix.xml")

    assert book["license"] is None


def test_book_file_roles():
    """Cover, content and the MARC record each get the role that decides their fate."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    roles = {f["filename"]: f["role"] for f in book["files"]}
    assert roles == {
        "coverImage.9781442617650.jpg": "cover",
        "9781442617650.pdf": "content",
        "marcRecord.9781442617650.mrc": "other",
    }


def test_marc_record_is_not_content():
    """The MARC record shares a content type with the PDF but is not content."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    (marc,) = [f for f in book["files"] if f["filename"].endswith(".mrc")]
    assert marc["role"] == "other"
    assert marc["format"] is None


def test_file_size_and_uri_are_read():
    """The byte size and link ride along with each file."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    (pdf,) = [f for f in book["files"] if f["role"] == "content"]
    assert pdf["uri"] == (
        "gs://bulk-importer-test/extracted/9781442617650/9781442617650.pdf"
    )
    assert pdf["size"] == 13


def test_keywords_and_audiences_are_split():
    """Delimited keyword and audience values become separate entries."""
    stream = _message(
        "<Product><RecordReference>r</RecordReference><DescriptiveDetail>"
        "<Subject><SubjectSchemeIdentifier>20</SubjectSchemeIdentifier>"
        "<SubjectHeadingText>one; two;three</SubjectHeadingText></Subject>"
        "<Audience><AudienceCodeType>02</AudienceCodeType>"
        "<AudienceCodeValue>College/higher education;Professional and scholarly;"
        "</AudienceCodeValue></Audience>"
        "</DescriptiveDetail></Product>"
    )

    ((book, _),) = [parse_product(p) for p in iter_products(stream)]

    assert book["keywords"] == ["one", "two", "three"]
    assert book["audiences"] == [
        "College/higher education",
        "Professional and scholarly",
    ]


def test_chapters_carry_book_context():
    """A chapter holds what it inherits, since it is transformed without its book."""
    ((_, chapters),) = _parse("book_with_chapters.onix.xml")

    context = chapters[0]["book"]
    assert context["doi"] == "10.3138/9781442617650"
    assert context["isbn"] == "9781442617650"
    assert context["title"] == "Collected Works of Erasmus"
    assert context["publisher"] == "University of Toronto Press"
    assert context["publication_date"] == "20190219"
    assert context["languages"] == ["eng"]


def test_book_carries_chapter_summaries():
    """The book knows its chapters' keys and DOIs, to link to them."""
    ((book, _),) = _parse("book_with_chapters.onix.xml")

    assert book["chapters"] == [
        {"key": "chapter:1", "doi": "10.3138/9781442617650-fm", "title": "Frontmatter"},
        {
            "key": "chapter:2",
            "doi": "10.3138/9781442617650-001",
            "title": "Erasmus' Preface",
        },
        {
            "key": "chapter:3",
            "doi": "10.3138/9781442617650-002",
            "title": "Greek Index",
        },
    ]


def test_chapter_entry_shape():
    """A body-matter chapter reads its own title, DOI, pages, abstract and authors."""
    ((_, chapters),) = _parse("book_with_chapters.onix.xml")

    chapter = chapters[1]
    assert chapter["type"] == "chapter"
    assert chapter["text_item_type"] == "03"
    assert chapter["doi"] == "10.3138/9781442617650-001"
    assert chapter["title"] == "Erasmus' Preface"
    assert chapter["abstract"] == "<p>A short abstract.</p>"
    assert chapter["keywords"] == ["adages"]
    assert [c["family_name"] for c in chapter["contributors"]] == ["Grant"]
    assert [f["role"] for f in chapter["files"]] == ["content"]


def test_front_matter_is_read_as_a_chapter():
    """Front matter carries a DOI and a PDF, so it is read like any chapter."""
    ((_, chapters),) = _parse("book_with_chapters.onix.xml")

    assert chapters[0]["text_item_type"] == "02"
    assert chapters[0]["doi"] == "10.3138/9781442617650-fm"


def test_roman_page_run_is_preserved():
    """Front-matter page numbers stay as written, not coerced to integers."""
    ((_, chapters),) = _parse("book_with_chapters.onix.xml")

    assert (chapters[0]["first_page"], chapters[0]["last_page"]) == ("i", "vi")


def test_chapters_ordered_by_level_sequence_number():
    """Stated sequence wins over document order."""
    items = "".join(
        "<ContentItem>"
        f"<LevelSequenceNumber>{n}</LevelSequenceNumber>"
        "<TextItem><TextItemType>03</TextItemType></TextItem>"
        "<TitleDetail><TitleType>01</TitleType><TitleElement>"
        f"<TitleElementLevel>01</TitleElementLevel><TitleText>Ch {n}</TitleText>"
        "</TitleElement></TitleDetail></ContentItem>"
        for n in (3, 1, 2)
    )
    stream = _message(
        "<Product><RecordReference>r</RecordReference>"
        f"<ContentDetail>{items}</ContentDetail></Product>"
    )

    ((_, chapters),) = [parse_product(p) for p in iter_products(stream)]

    assert [c["title"] for c in chapters] == ["Ch 1", "Ch 2", "Ch 3"]
    assert [c["key"] for c in chapters] == ["chapter:1", "chapter:2", "chapter:3"]


def test_product_without_content_detail_has_no_chapters():
    """A book with no content items reads as a book with no chapters."""
    parsed = _parse("two_books.onix.xml")

    book, chapters = parsed[1]
    assert chapters == []
    assert book["chapters"] == []
    assert book["doi"] is None


def test_chapter_without_doi_is_still_read():
    """A missing chapter DOI leaves the chapter in place with no DOI."""
    (_, chapters), _ = _parse("two_books.onix.xml")

    assert [c["doi"] for c in chapters] == ["10.5555/complete-book-001", None]


def test_check_filenames_accepts_matching_uris():
    """Every fixture URI ends in its declared filename."""
    ((book, chapters),) = _parse("book_with_chapters.onix.xml")

    assert check_filenames(book["files"]) == []
    assert all(check_filenames(c["files"]) == [] for c in chapters)


def test_check_filenames_reports_a_mismatch():
    """A URI that disagrees with the declared filename is reported."""
    files = [{"uri": "gs://b/path/other.pdf", "filename": "declared.pdf"}]

    (problem,) = check_filenames(files)

    assert "declared.pdf" in problem
