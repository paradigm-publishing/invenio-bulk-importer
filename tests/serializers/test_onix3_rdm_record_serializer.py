# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Tests for transforming ONIX source data into RDM record payloads."""

from copy import deepcopy
from pathlib import Path

from invenio_bulk_importer.serializers.records.onix3 import ONIX3RDMRecordSerializer
from invenio_bulk_importer.serializers.records.onix3.schema import (
    DEFAULT_SETTINGS,
    build_book_payload,
    format_date,
    license_id,
)

DATA = Path(__file__).parent / "data" / "onix"


def _entries(name):
    """Read the source data of every record in a fixture file.

    :param name: Fixture file name under ``data/onix``.
    :return: Source data dicts, books and chapters in file order.
    """
    with (DATA / name).open("rb") as stream:
        return list(ONIX3RDMRecordSerializer().load(stream))


def _transform(src, mode="import"):
    """Transform one record's source data.

    :param src: Source data dict.
    :param mode: Task mode.
    :return: ``(payload, errors)``.
    """
    return ONIX3RDMRecordSerializer().transform(deepcopy(src), mode=mode)


def test_book_transform(running_app):
    """A book's payload carries its identity, people, files and links."""
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, errors = _transform(book)

    assert errors is None
    assert payload["pids"] == {
        "doi": {"identifier": "10.3138/9781442617650", "provider": "external"}
    }
    metadata = payload["metadata"]
    assert metadata["resource_type"] == {"id": "publication-book"}
    assert metadata["title"] == "Collected Works of Erasmus"
    assert metadata["additional_titles"] == [
        {"title": "Prolegomena to the Adages", "type": {"id": "subtitle"}}
    ]
    assert metadata["publication_date"] == "2019-02-19"
    assert metadata["publisher"] == "University of Toronto Press"
    assert metadata["languages"] == [{"id": "eng"}]
    assert [c["person_or_org"]["family_name"] for c in metadata["creators"]] == [
        "Erasmus"
    ]
    assert metadata["contributors"][0]["role"] == {"id": "editor"}
    assert metadata["identifiers"] == [
        {"scheme": "isbn", "identifier": "9781442617650"}
    ]
    assert metadata["sizes"] == ["856 pages"]
    assert metadata["subjects"] == [{"subject": "adages"}, {"subject": "proverbs"}]
    assert metadata["copyright"] == "© 2017 University of Toronto Press"
    assert payload["custom_fields"]["imprint:imprint"] == {
        "isbn": "9781442617650",
        "series_name": "Erasmus Studies",
        "volume": "30",
        "edition": "2nd edition",
    }


def test_book_links_to_every_chapter(running_app):
    """The book gets one ``haspart`` per chapter, by DOI."""
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(book)

    assert [
        (r["identifier"], r["scheme"], r["relation_type"]["id"])
        for r in payload["metadata"]["related_identifiers"]
    ] == [
        ("10.3138/9781442617650-fm", "doi", "haspart"),
        ("10.3138/9781442617650-001", "doi", "haspart"),
        ("10.3138/9781442617650-002", "doi", "haspart"),
    ]


def test_chapter_transform_inherits_from_its_book(running_app):
    """A chapter takes publisher, date and languages from its book."""
    _, _, chapter, _ = _entries("book_with_chapters.onix.xml")

    payload, errors = _transform(chapter)

    assert errors is None
    metadata = payload["metadata"]
    assert metadata["resource_type"] == {"id": "publication-book-chapter"}
    assert metadata["title"] == "Erasmus' Preface"
    assert metadata["description"] == "<p>A short abstract.</p>"
    assert metadata["publisher"] == "University of Toronto Press"
    assert metadata["publication_date"] == "2019-02-19"
    assert metadata["languages"] == [{"id": "eng"}]
    assert payload["pids"]["doi"]["identifier"] == "10.3138/9781442617650-001"
    assert payload["custom_fields"]["imprint:imprint"] == {
        "title": "Collected Works of Erasmus",
        "isbn": "9781442617650",
        "pages": "ix-x",
    }


def test_chapter_links_back_to_its_book(running_app):
    """A chapter gets one ``ispartof`` back to its book, by DOI."""
    _, _, chapter, _ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(chapter)

    assert payload["metadata"]["related_identifiers"] == [
        {
            "identifier": "10.3138/9781442617650",
            "scheme": "doi",
            "relation_type": {"id": "ispartof"},
            "resource_type": {"id": "publication-book"},
        }
    ]


def test_chapter_authors_are_its_creators(running_app):
    """Everyone credited on a chapter authored it."""
    _, _, chapter, _ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(chapter)

    assert [
        c["person_or_org"]["family_name"] for c in payload["metadata"]["creators"]
    ] == ["Grant"]
    assert payload["metadata"]["contributors"] == []


def test_front_matter_falls_back_to_book_creators(running_app):
    """Front matter credits nobody, so it borrows the book's authors."""
    _, front_matter, _, _ = _entries("book_with_chapters.onix.xml")

    payload, errors = _transform(front_matter)

    assert errors is None
    assert [
        c["person_or_org"]["family_name"] for c in payload["metadata"]["creators"]
    ] == ["Erasmus"]


def test_edited_volume_promotes_editors_to_creators(running_app):
    """A book credited only to editors still gets creators."""
    *_, edited = _entries("two_books.onix.xml")

    payload, errors = _transform(edited)

    assert errors is None
    (creator,) = payload["metadata"]["creators"]
    assert creator["person_or_org"]["family_name"] == "Hopper"
    assert creator["role"] == {"id": "editor"}


def test_book_files_are_content_then_cover(running_app):
    """The PDF comes first, so it is what the record previews, and MARC is left out."""
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(book)

    assert payload["files"] == [
        "gs://bulk-importer-test/extracted/9781442617650/9781442617650.pdf",
        "gs://bulk-importer-test/extracted/9781442617650/coverImage.9781442617650.jpg",
    ]


def test_chapter_gets_only_its_own_pdf(running_app):
    """A chapter carries its own PDF and nothing of the book's."""
    _, _, chapter, _ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(chapter)

    assert payload["files"] == [
        "gs://bulk-importer-test/extracted/9781442617650/9781442617650-001.pdf"
    ]


def test_openly_licensed_title_gets_public_files(running_app):
    """An ``<EpubLicense>`` opens the files, for the book and its chapters."""
    book, chapter, *_ = _entries("book_with_chapters.onix.xml")

    for src in (book, chapter):
        payload, _ = _transform(src)
        assert payload["access"] == {"record": "public", "files": "public"}


def test_title_without_licence_keeps_files_restricted(running_app):
    """No licence means not openly licensed, so the files stay restricted."""
    book, *_ = _entries("two_books.onix.xml")

    payload, errors = _transform(book)

    assert errors is None
    assert payload["access"] == {"record": "public", "files": "restricted"}


def test_licence_driven_access_can_be_turned_off(running_app):
    """A site can keep every title's files restricted regardless of licence."""
    book, *_ = _entries("book_with_chapters.onix.xml")
    settings = {**DEFAULT_SETTINGS, "use_license_for_access": False}

    payload = build_book_payload(book, settings)

    assert payload["access"] == {"record": "public", "files": "restricted"}


def test_creative_commons_licence_link_resolves(running_app):
    """A Creative Commons link needs no lookup table."""
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, _ = _transform(book)

    assert payload["metadata"]["rights"] == [{"id": "cc-by-4.0"}]


def test_licence_name_resolves_through_the_mapping(running_app):
    """A licence known only by name needs the ``licenses`` setting."""
    licence = {"name": "Publisher Open Licence", "link": None}

    assert license_id(licence, {}) is None
    assert license_id(licence, {"Publisher Open Licence": "pol-1"}) == "pol-1"


def test_non_gs_file_uri_is_rejected(running_app):
    """A ``file://`` link names a path the workers cannot reach."""
    book, *_ = _entries("file_uri.onix.xml")

    payload, errors = _transform(book)

    assert payload is None
    assert {e["type"] for e in errors} == {"invalid_file_uri"}
    assert all("gs://" in e["msg"] for e in errors)


def test_unattached_file_does_not_block_the_record(running_app):
    """A bad link on a file that is never attached is not an error."""
    book, *_ = _entries("book_with_chapters.onix.xml")
    for entry in book["files"]:
        if entry["role"] == "other":
            entry["uri"] = "file:///nowhere/" + entry["filename"]

    payload, errors = _transform(book)

    assert errors is None
    assert payload is not None


def test_retracted_title_is_rejected(running_app):
    """A withdrawn title fails, book and chapters alike."""
    book, chapter, *_ = _entries("retracted.onix.xml")

    for src in (book, chapter):
        payload, errors = _transform(src)
        assert payload is None
        assert [e["type"] for e in errors] == ["retracted_title"]


def test_delete_mode_is_unsupported(running_app):
    """Delete mode reports why instead of raising."""
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, errors = _transform(book, mode="delete")

    assert payload is None
    assert [e["type"] for e in errors] == ["unsupported_mode"]


def test_unmapped_contributor_role_is_kept_as_other(running_app):
    """A contributor with an unknown role is recorded, never dropped."""
    book, *_ = _entries("book_with_chapters.onix.xml")
    book["contributors"].append(
        {
            "sequence": 3,
            "onix_role": "Q42",
            "person_name": "Ann Other",
            "given_names": "Ann",
            "family_name": "Other",
            "corporate_name": None,
        }
    )

    payload, _ = _transform(book)

    other = payload["metadata"]["contributors"][-1]
    assert other["person_or_org"]["family_name"] == "Other"
    assert other["role"] == {"id": "other"}


def test_missing_title_is_a_validation_error(running_app):
    """A payload RDM would reject is reported with a readable location."""
    book, *_ = _entries("book_with_chapters.onix.xml")
    book["title"] = None

    payload, errors = _transform(book)

    assert payload is None
    assert any(e["loc"] == "metadata.title" for e in errors)


def test_format_date():
    """ONIX dates become EDTF at the precision they were given."""
    assert format_date("20190219") == "2019-02-19"
    assert format_date("201902") == "2019-02"
    assert format_date("2019") == "2019"
    assert format_date(None) is None


def _stub_imprint(values):
    """Stand-in transformer returning a recognisable imprint.

    :param values: One record's source data.
    :return: An imprint naming the record's ISBN.
    """
    return {"isbn": f"configured-{values.get('isbn')}"}


def test_configured_transformer_overrides_native_imprint(
    running_app, set_app_config_fn_scoped
):
    """A site transformer for a field wins over the imprint built natively."""
    set_app_config_fn_scoped(
        {
            "BULK_IMPORTER_CUSTOM_FIELDS": {
                "onix3_rdm_record_serializer": [
                    {"field": "imprint:imprint", "transformer": _stub_imprint}
                ]
            }
        }
    )
    book, *_ = _entries("book_with_chapters.onix.xml")

    payload, errors = _transform(book)

    assert errors is None
    assert payload["custom_fields"]["imprint:imprint"] == {
        "isbn": "configured-9781442617650"
    }
