# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Read an ONIX 3.0 message into plain dictionaries.

Deliberately free of Flask, pydantic and Invenio imports: this is the fiddliest
part of the serializer and it is worth being able to test it with nothing
running.

What comes out is *structurally* normalized -- nesting turned into named keys,
text flattened, delimited strings split, items ordered. Values are left as ONIX
wrote them: a contributor role stays ``"A01"``, a date stays ``"20190219"``, a
subject code stays ``"SC-LT-01"``. The mapping from those to repository
vocabularies happens later, at transform time, so that correcting a lookup
table and re-validating picks the correction up without the file being
uploaded again.
"""

from typing import IO, Iterator

from lxml import etree

from .codes import (
    EXTENT_TYPE_PAGES,
    FEATURE_FILE_FORMAT,
    FEATURE_FILE_SIZE_BYTES,
    FEATURE_FILENAME,
    FILE_FORMAT_PDF,
    FILE_ROLE_CONTENT,
    FILE_ROLE_COVER,
    FILE_ROLE_OTHER,
    LANGUAGE_ROLE_TEXT,
    NSMAP,
    ONIX_NS,
    PRODUCT_ID_DOI,
    PRODUCT_ID_ISBN13,
    PRODUCT_ID_PROPRIETARY,
    PUBLISHING_DATE_PUBLICATION,
    PUBLISHING_ROLE_PUBLISHER,
    RESOURCE_CONTENT_FRONT_COVER,
    SUBJECT_SCHEME_KEYWORDS,
    SUBJECT_SCHEME_PROPRIETARY,
    TEXT_ITEM_ID_DOI,
    TEXT_TYPE_BIOGRAPHICAL_NOTE,
    TEXT_TYPE_DESCRIPTION,
    TEXT_TYPE_REVIEW,
    TITLE_LEVEL_PRODUCT,
)

ZERO_WIDTH = "​﻿"
"""Characters that ride along in publisher text and break exact comparisons."""


class ONIXReadError(ValueError):
    """The stream is not an ONIX 3.0 reference-tag message we can read."""


def _clean(value: str | None) -> str | None:
    """Collapse whitespace and drop zero-width characters.

    :param value: Raw text from the document.
    :return: The cleaned text, or ``None`` when nothing is left.
    """
    if value is None:
        return None
    for char in ZERO_WIDTH:
        value = value.replace(char, "")
    value = " ".join(value.split())
    return value or None


def _text(element, path: str) -> str | None:
    """Return the flattened text of the first match of ``path``.

    :param element: Element to search from.
    :param path: ElementPath expression using the ``onix`` prefix.
    :return: The cleaned text, or ``None`` when there is no match.
    """
    found = element.find(path, NSMAP)
    if found is None:
        return None
    return _clean("".join(found.itertext()))


def _texts(element, path: str) -> list[str]:
    """Return the flattened text of every match of ``path``.

    :param element: Element to search from.
    :param path: ElementPath expression using the ``onix`` prefix.
    :return: The cleaned texts, empty ones dropped.
    """
    out = []
    for found in element.findall(path, NSMAP):
        if value := _clean("".join(found.itertext())):
            out.append(value)
    return out


def _split_list(values: list[str]) -> list[str]:
    """Split semicolon-delimited values into individual entries.

    ONIX packs several keywords or audience terms into one element, and there
    is no normative separator -- the preprocessor uses ``;``.

    :param values: Raw element texts.
    :return: The individual entries, in order, without duplicates.
    """
    out = []
    for value in values:
        for part in value.split(";"):
            if (part := _clean(part)) and part not in out:
                out.append(part)
    return out


def _int_or_none(value: str | None) -> int | None:
    """Read an integer that ONIX may not have supplied.

    :param value: The raw text.
    :return: The integer, or ``None`` when absent or not a number.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iter_products(stream: IO) -> Iterator[etree._Element]:
    """Yield each ``<Product>`` of an ONIX message, freeing it once consumed.

    The stream must be binary. An ONIX file carries an encoding declaration,
    and a parser handed already-decoded text cannot honour it.

    External entities and network access are off: the file arrives from a user
    upload and is parsed inside a worker, which is exactly the setting where an
    entity expansion or an external DTD reference would do damage.

    :param stream: Binary stream over an ONIX 3.0 message.
    :return: Iterator of ``<Product>`` elements, in document order.
    """
    context = etree.iterparse(
        stream,
        events=("end",),
        tag=f"{{{ONIX_NS}}}Product",
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_comments=True,
    )
    seen = False
    for _, element in context:
        seen = True
        yield element
        # Clearing alone is not enough: iterparse keeps every consumed product
        # attached to its parent, so the whole message would stay in memory.
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    if not seen:
        _reject_unreadable(context)


def _reject_unreadable(context) -> None:
    """Explain why a message yielded no products.

    Without this a short-tag file, or a bare ``<Product>`` document, imports as
    zero records and says nothing about why.

    :param context: The exhausted ``iterparse`` context.
    :raises ONIXReadError: Always, unless the root really is an empty message.
    """
    root = context.root
    if root is None:
        raise ONIXReadError("The file is empty or is not XML.")
    tag = etree.QName(root).localname if "}" in root.tag else root.tag
    if "}" not in root.tag:
        raise ONIXReadError(
            f"<{tag}> carries no namespace. This serializer reads ONIX 3.0 "
            "reference-tag messages in the "
            f"'{ONIX_NS}' namespace."
        )
    if tag != "ONIXMessage":
        raise ONIXReadError(
            f"Expected an <ONIXMessage> root, found <{tag}>. Supply a full "
            "ONIX 3.0 message rather than a single product."
        )


def _identifiers(product) -> tuple[str | None, str | None, dict[str, str]]:
    """Read a product's ISBN, DOI and proprietary identifiers.

    :param product: A ``<Product>`` element.
    :return: The ISBN-13, the DOI, and the proprietary ids by their type name.
    """
    isbn = _text(
        product,
        f"./onix:ProductIdentifier[onix:ProductIDType='{PRODUCT_ID_ISBN13}']"
        "/onix:IDValue",
    )
    doi = _text(
        product,
        f"./onix:ProductIdentifier[onix:ProductIDType='{PRODUCT_ID_DOI}']"
        "/onix:IDValue",
    )
    private = {}
    for element in product.findall(
        f"./onix:ProductIdentifier[onix:ProductIDType='{PRODUCT_ID_PROPRIETARY}']",
        NSMAP,
    ):
        name = _text(element, "./onix:IDTypeName")
        value = _text(element, "./onix:IDValue")
        if name and value:
            private[name] = value
    return isbn, doi, private


def _contributors(parent) -> list[dict]:
    """Read the contributors of a product or content item, in stated order.

    ``SequenceNumber`` is authoritative; document order is only the tiebreak,
    since ONIX does not require the two to agree.

    :param parent: An element holding ``<Contributor>`` children.
    :return: One dict per contributor.
    """
    out = []
    for index, element in enumerate(parent.findall("./onix:Contributor", NSMAP)):
        sequence = _int_or_none(_text(element, "./onix:SequenceNumber"))
        out.append(
            {
                "sequence": index if sequence is None else sequence,
                "onix_role": _text(element, "./onix:ContributorRole"),
                "person_name": _text(element, "./onix:PersonName"),
                "given_names": _text(element, "./onix:NamesBeforeKey"),
                "family_name": _text(element, "./onix:KeyNames"),
                "corporate_name": _text(element, "./onix:CorporateName"),
            }
        )
    return sorted(out, key=lambda c: c["sequence"])


def _supporting_resources(parent) -> list[dict]:
    """Read the files a product or content item points at.

    The role is what the rest of the serializer acts on. The format feature is
    tested before the file extension because the preprocessor omits that
    feature exactly when it has no media type for the file -- which is how the
    MARC record, sharing a content type with the book PDF, is told apart.

    :param parent: An element holding ``<SupportingResource>`` children.
    :return: One dict per file, with ``role``, ``uri``, ``filename``,
        ``format`` and ``size``.
    """
    out = []
    for element in parent.findall("./onix:SupportingResource", NSMAP):
        content_type = _text(element, "./onix:ResourceContentType")
        version = element.find("./onix:ResourceVersion", NSMAP)
        if version is None:
            continue
        features = {}
        for feature in version.findall("./onix:ResourceVersionFeature", NSMAP):
            feature_type = _text(feature, "./onix:ResourceVersionFeatureType")
            if feature_type:
                features[feature_type] = _text(feature, "./onix:FeatureValue")
        uri = _text(version, "./onix:ResourceLink")
        if not uri:
            continue
        filename = features.get(FEATURE_FILENAME)
        file_format = features.get(FEATURE_FILE_FORMAT)
        out.append(
            {
                "role": _file_role(content_type, file_format, filename),
                "uri": uri,
                "filename": filename,
                "format": file_format,
                "size": _int_or_none(features.get(FEATURE_FILE_SIZE_BYTES)),
            }
        )
    return out


def _file_role(
    content_type: str | None, file_format: str | None, filename: str | None
) -> str:
    """Decide what a supporting resource is for.

    :param content_type: ONIX ``ResourceContentType``.
    :param file_format: ONIX file format feature, when supplied.
    :param filename: Declared filename, when supplied.
    :return: One of the ``FILE_ROLE_*`` values.
    """
    if content_type == RESOURCE_CONTENT_FRONT_COVER:
        return FILE_ROLE_COVER
    if file_format == FILE_FORMAT_PDF:
        return FILE_ROLE_CONTENT
    if file_format is None and (filename or "").lower().endswith(".pdf"):
        return FILE_ROLE_CONTENT
    return FILE_ROLE_OTHER


def check_filenames(files: list[dict]) -> list[str]:
    """Report files whose URI does not end in their declared filename.

    The last segment of the URI becomes the key of the file on the record --
    there is nowhere to pass an explicit key alongside it -- so a URI that
    disagrees with the filename ONIX declares would silently produce a
    misnamed file.

    :param files: File dicts from :func:`_supporting_resources`.
    :return: A message per disagreement, empty when they all agree.
    """
    problems = []
    for entry in files:
        filename = entry.get("filename")
        if not filename:
            continue
        if entry["uri"].rstrip("/").rsplit("/", 1)[-1] != filename:
            problems.append(
                f"File '{entry['uri']}' does not end in its declared filename "
                f"'{filename}', so the file would be stored under the wrong name."
            )
    return problems


def _series(product) -> dict | None:
    """Read the collection a book belongs to.

    :param product: A ``<Product>`` element.
    :return: The series title, code and volume, or ``None``.
    """
    collection = product.find("./onix:DescriptiveDetail/onix:Collection", NSMAP)
    if collection is None:
        return None
    title = _text(collection, ".//onix:TitleElement/onix:TitleText")
    code = _text(collection, "./onix:CollectionIdentifier/onix:IDValue")
    volume = _text(collection, ".//onix:CollectionSequenceNumber")
    if not any((title, code, volume)):
        return None
    return {"title": title, "code": code, "volume": volume}


def _license(product) -> dict | None:
    """Read the open licence, whose absence marks a title as not openly licensed.

    :param product: A ``<Product>`` element.
    :return: The licence name and link, or ``None`` when there is no licence.
    """
    element = product.find("./onix:DescriptiveDetail/onix:EpubLicense", NSMAP)
    if element is None:
        return None
    return {
        "name": _text(element, "./onix:EpubLicenseName"),
        "link": _text(element, ".//onix:EpubLicenseExpressionLink"),
    }


def _collateral_text(parent, text_type: str) -> str | None:
    """Read one kind of descriptive text.

    :param parent: The element holding ``<TextContent>`` children.
    :param text_type: ONIX ``TextType`` to look for.
    :return: The text, or ``None``.
    """
    return _text(
        parent,
        f"./onix:TextContent[onix:TextType='{text_type}']/onix:Text",
    )


def _read_book(product) -> dict:
    """Read the book-level fields of a product.

    :param product: A ``<Product>`` element.
    :return: The book's source data, without its chapter summaries.
    """
    isbn, doi, private = _identifiers(product)
    title_element = (
        "./onix:DescriptiveDetail/onix:TitleDetail/onix:TitleElement"
        f"[onix:TitleElementLevel='{TITLE_LEVEL_PRODUCT}']"
    )
    collateral = product.find("./onix:CollateralDetail", NSMAP)
    descriptive = product.find("./onix:DescriptiveDetail", NSMAP)
    publishing = product.find("./onix:PublishingDetail", NSMAP)
    return {
        "type": "book",
        "record_reference": _text(product, "./onix:RecordReference"),
        "notification_type": _text(product, "./onix:NotificationType"),
        "publishing_status": (
            _text(publishing, "./onix:PublishingStatus")
            if publishing is not None
            else None
        ),
        "doi": doi,
        "isbn": isbn,
        "private_identifiers": private,
        "title": _text(product, f"{title_element}/onix:TitleText"),
        "subtitle": _text(product, f"{title_element}/onix:Subtitle"),
        "edition": _text(product, "./onix:DescriptiveDetail/onix:EditionStatement"),
        "series": _series(product),
        "contributors": (_contributors(descriptive) if descriptive is not None else []),
        "languages": _texts(
            product,
            "./onix:DescriptiveDetail/onix:Language"
            f"[onix:LanguageRole='{LANGUAGE_ROLE_TEXT}']/onix:LanguageCode",
        ),
        "page_count": _text(
            product,
            f"./onix:DescriptiveDetail/onix:Extent[onix:ExtentType='{EXTENT_TYPE_PAGES}']"
            "/onix:ExtentValue",
        ),
        "subject_codes": _split_list(
            _texts(
                product,
                "./onix:DescriptiveDetail/onix:Subject"
                f"[onix:SubjectSchemeIdentifier='{SUBJECT_SCHEME_PROPRIETARY}']"
                "/onix:SubjectCode",
            )
        ),
        "keywords": _split_list(
            _texts(
                product,
                "./onix:DescriptiveDetail/onix:Subject"
                f"[onix:SubjectSchemeIdentifier='{SUBJECT_SCHEME_KEYWORDS}']"
                "/onix:SubjectHeadingText",
            )
        ),
        "audiences": _split_list(
            _texts(
                product,
                "./onix:DescriptiveDetail/onix:Audience/onix:AudienceCodeValue",
            )
        ),
        "audience_scheme": _text(
            product,
            "./onix:DescriptiveDetail/onix:Audience/onix:AudienceCodeTypeName",
        ),
        "license": _license(product),
        "description": (
            _collateral_text(collateral, TEXT_TYPE_DESCRIPTION)
            if collateral is not None
            else None
        ),
        "reviews": (
            _collateral_text(collateral, TEXT_TYPE_REVIEW)
            if collateral is not None
            else None
        ),
        "biographical_note": (
            _collateral_text(collateral, TEXT_TYPE_BIOGRAPHICAL_NOTE)
            if collateral is not None
            else None
        ),
        "publisher": _text(
            product,
            "./onix:PublishingDetail/onix:Publisher"
            f"[onix:PublishingRole='{PUBLISHING_ROLE_PUBLISHER}']/onix:PublisherName",
        ),
        "publication_date": _text(
            product,
            "./onix:PublishingDetail/onix:PublishingDate"
            f"[onix:PublishingDateRole='{PUBLISHING_DATE_PUBLICATION}']/onix:Date",
        ),
        "copyright_year": _text(
            product,
            "./onix:PublishingDetail/onix:CopyrightStatement/onix:CopyrightYear",
        ),
        "copyright_owner": _text(
            product,
            "./onix:PublishingDetail/onix:CopyrightStatement/onix:CopyrightOwner"
            "/onix:CorporateName",
        )
        or _text(
            product,
            "./onix:PublishingDetail/onix:CopyrightStatement/onix:CopyrightOwner"
            "/onix:PersonName",
        ),
        "files": _supporting_resources(collateral) if collateral is not None else [],
    }


def _read_chapter(item, index: int) -> dict:
    """Read one content item.

    :param item: A ``<ContentItem>`` element.
    :param index: Position of the item, used when ONIX states no sequence.
    :return: The chapter's source data, without its book context.
    """
    sequence = _int_or_none(_text(item, "./onix:LevelSequenceNumber"))
    sequence = index if sequence is None else sequence
    text_item = item.find("./onix:TextItem", NSMAP)
    return {
        "type": "chapter",
        "key": f"chapter:{sequence}",
        "sequence": sequence,
        "text_item_type": (
            _text(text_item, "./onix:TextItemType") if text_item is not None else None
        ),
        "doi": (
            _text(
                text_item,
                f"./onix:TextItemIdentifier[onix:TextItemIDType='{TEXT_ITEM_ID_DOI}']"
                "/onix:IDValue",
            )
            if text_item is not None
            else None
        ),
        "title": _text(item, ".//onix:TitleElement/onix:TitleText"),
        "first_page": (
            _text(text_item, "./onix:PageRun/onix:FirstPageNumber")
            if text_item is not None
            else None
        ),
        "last_page": (
            _text(text_item, "./onix:PageRun/onix:LastPageNumber")
            if text_item is not None
            else None
        ),
        "page_count": (
            _text(text_item, "./onix:NumberOfPages") if text_item is not None else None
        ),
        "abstract": _collateral_text(item, TEXT_TYPE_DESCRIPTION),
        "contributors": _contributors(item),
        "keywords": _split_list(
            _texts(
                item,
                "./onix:Subject"
                f"[onix:SubjectSchemeIdentifier='{SUBJECT_SCHEME_KEYWORDS}']"
                "/onix:SubjectHeadingText",
            )
        ),
        "files": _supporting_resources(item),
    }


BOOK_CONTEXT_FIELDS = (
    "contributors",
    "record_reference",
    "doi",
    "isbn",
    "title",
    "subtitle",
    "publisher",
    "publication_date",
    "languages",
    "license",
    "publishing_status",
    "copyright_year",
    "copyright_owner",
)
"""What a chapter carries from its book.

A chapter is transformed on its own, in a later task, from a row in the
database -- the product element is long gone by then. Everything a chapter
inherits therefore has to travel with it.
"""


def parse_product(product) -> tuple[dict, list[dict]]:
    """Read a product into its book and its chapters.

    Each side carries a summary of the other, so either can describe the whole
    group without consulting its siblings' records.

    :param product: A ``<Product>`` element.
    :return: The book's source data and its chapters', in reading order.
    """
    book = _read_book(product)
    items = product.findall("./onix:ContentDetail/onix:ContentItem", NSMAP)
    chapters = [_read_chapter(item, index) for index, item in enumerate(items)]
    chapters.sort(key=lambda c: c["sequence"])

    context = {field: book[field] for field in BOOK_CONTEXT_FIELDS}
    for chapter in chapters:
        chapter["book"] = context
    book["chapters"] = [
        {"key": c["key"], "doi": c["doi"], "title": c["title"]} for c in chapters
    ]
    return book, chapters
