# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or modify
# it under the terms of the MIT License; see LICENSE file for more details.
#

"""Turn ONIX source data into an InvenioRDM record payload.

The payload is assembled in plain functions from the dictionaries
:mod:`.reader` produced, then checked against pydantic models built from the
shared record shapes in :mod:`..models`. This is where ONIX values meet
repository vocabularies: contributor roles, licences and dates are mapped here,
at transform time, so that a corrected mapping takes effect on re-validation.

Known gaps, deliberately not papered over:

* Licence names need a lookup table (``licenses`` setting). Creative Commons
  licence *links* resolve without one.
* The ONIX carries no ``<Funding>``, so ``metadata.funding`` stays empty.
* Audience values are proprietary per publisher (``AudienceCodeType`` 02) and
  have no repository target without a per-source table; they are not mapped.
* Proprietary subject codes (scheme 23) are dropped unless ``subject_codes``
  maps them.
* A part title grouping several chapters is dropped upstream, before the ONIX
  is written, and cannot be recovered here.
"""

import re

from flask import current_app
from pydantic import BaseModel, Field

from ..models import (
    BaseIdentifier,
    Contributor,
    Creator,
    FullIdentifier,
    load_configured_custom_fields,
)
from .codes import (
    CONTRIBUTORS,
    CREATORS,
    DEFAULT_CONTRIBUTOR_ROLES,
    FILE_ROLE_CONTENT,
    FILE_ROLE_COVER,
    UNMAPPED_CONTRIBUTOR_ROLE,
)
from .linking import RESOURCE_TYPE_BOOK, RESOURCE_TYPE_CHAPTER, sibling_links

ONIX3_CUSTOM_FIELDS_KEY = "onix3_rdm_record_serializer"
"""Key the ONIX serializer's entries sit under in ``BULK_IMPORTER_CUSTOM_FIELDS``."""

DEFAULT_SETTINGS = {
    "access": {"record": "public", "files": "restricted"},
    "use_license_for_access": True,
    "contributor_roles": {},
    "licenses": {},
    "subject_codes": {},
    "imprint_field": "imprint:imprint",
}
"""Settings a site may override through ``BULK_IMPORTER_ONIX3_SERIALIZER``.

``access``
    Access given to every record.
``use_license_for_access``
    When on, an openly licensed title (one ONIX gives an ``<EpubLicense>``)
    gets public files regardless of ``access``. The absence of that licence is
    what marks a title as not openly licensed.
``contributor_roles``
    ONIX codelist-17 codes mapped to ``[list, role id]``, merged over the
    defaults in
    :py:data:`~invenio_bulk_importer.serializers.records.onix3.codes.DEFAULT_CONTRIBUTOR_ROLES`.
``licenses``
    Licence names or links mapped to repository licence ids.
``subject_codes``
    Proprietary subject codes mapped to subject terms.
``imprint_field``
    Custom field the book and chapter imprint is written to, or ``None`` to
    write none.
"""


def get_settings() -> dict:
    """Read the serializer settings, defaults filled in.

    :return: The effective settings.
    """
    settings = {**DEFAULT_SETTINGS}
    settings.update(current_app.config.get("BULK_IMPORTER_ONIX3_SERIALIZER", {}))
    return settings


def format_date(value: str | None) -> str | None:
    """Convert an ONIX date to EDTF.

    :param value: ``YYYYMMDD``, ``YYYYMM`` or ``YYYY``.
    :return: ``YYYY-MM-DD``, ``YYYY-MM`` or ``YYYY``; the value unchanged when
        it is none of those, so validation reports it rather than it vanishing.
    """
    if not value:
        return None
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    if re.fullmatch(r"\d{6}", value):
        return f"{value[:4]}-{value[4:]}"
    return value


CC_LICENSE_LINK = re.compile(
    r"creativecommons\.org/licenses/(?P<code>[a-z-]+)/(?P<version>\d+(?:\.\d+)?)"
)
CC_ZERO_LINK = re.compile(r"creativecommons\.org/publicdomain/zero/(?P<version>[\d.]+)")


def license_id(license: dict | None, mapping: dict) -> str | None:
    """Resolve an ONIX licence to a repository licence id.

    :param license: The licence the reader found, or ``None``.
    :param mapping: The ``licenses`` setting.
    :return: The licence id, or ``None`` when it cannot be resolved.
    """
    if not license:
        return None
    for candidate in (license.get("link"), license.get("name")):
        if candidate and candidate in mapping:
            return mapping[candidate]
    link = license.get("link") or ""
    if match := CC_LICENSE_LINK.search(link):
        return f"cc-{match['code']}-{match['version']}"
    if match := CC_ZERO_LINK.search(link):
        return f"cc0-{match['version']}"
    current_app.logger.warning(
        "ONIX licence %r has no repository licence id; add it to the "
        "'licenses' setting to map it.",
        license.get("name") or link,
    )
    return None


def _person_or_org(contributor: dict) -> dict:
    """Build the ``person_or_org`` of a contributor.

    :param contributor: A contributor as the reader produced it.
    :return: An RDM ``person_or_org``.
    """
    if contributor.get("family_name"):
        person = {"type": "personal", "family_name": contributor["family_name"]}
        if contributor.get("given_names"):
            person["given_name"] = contributor["given_names"]
        return person
    if contributor.get("corporate_name"):
        return {"type": "organizational", "name": contributor["corporate_name"]}
    # Only an unstructured name: RDM needs a family name for a person, so the
    # whole name stands in for it rather than the contributor being lost.
    return {"type": "personal", "family_name": contributor.get("person_name") or ""}


def split_contributors(
    contributors: list[dict], roles: dict
) -> tuple[list[dict], list[dict]]:
    """Sort contributors into RDM creators and contributors.

    :param contributors: Contributors as the reader produced them, in order.
    :param roles: ONIX role code mapped to ``(list, role id)``.
    :return: ``(creators, contributors)``.
    """
    out = {CREATORS: [], CONTRIBUTORS: []}
    for contributor in contributors:
        code = contributor.get("onix_role")
        target, role = roles.get(code) or UNMAPPED_CONTRIBUTOR_ROLE
        if code not in roles:
            current_app.logger.warning(
                "ONIX contributor role %r is not mapped; recording %s as '%s'.",
                code,
                contributor.get("person_name"),
                role,
            )
        out[target].append(
            {"person_or_org": _person_or_org(contributor), "role": {"id": role}}
        )
    return out[CREATORS], out[CONTRIBUTORS]


class ONIXMetadata(BaseModel):
    """The ``metadata`` of a book or chapter record."""

    resource_type: dict[str, str]
    title: str
    publication_date: str
    publisher: str | None = None
    additional_titles: list[dict] = Field(default_factory=list)
    description: str | None = None
    additional_descriptions: list[dict] = Field(default_factory=list)
    languages: list[dict[str, str]] = Field(default_factory=list)
    creators: list[Creator] = Field(min_length=1)
    contributors: list[Contributor] = Field(default_factory=list)
    subjects: list[dict] = Field(default_factory=list)
    identifiers: list[BaseIdentifier] = Field(default_factory=list)
    related_identifiers: list[FullIdentifier] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    rights: list[dict] = Field(default_factory=list)
    copyright: str | None = None


class ONIXRecordSchema(BaseModel):
    """An RDM record payload built from ONIX."""

    pids: dict = Field(default_factory=dict)
    access: dict
    communities: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    custom_fields: dict = Field(default_factory=dict)
    metadata: ONIXMetadata


def _roles(settings: dict) -> dict:
    """Merge configured contributor roles over the codelist-17 defaults.

    :param settings: Effective serializer settings.
    :return: ONIX role code mapped to ``(list, role id)``.
    """
    roles = dict(DEFAULT_CONTRIBUTOR_ROLES)
    roles.update({code: tuple(v) for code, v in settings["contributor_roles"].items()})
    return roles


def _subjects(keywords: list[str], codes: list[str], mapping: dict) -> list[dict]:
    """Build free-text subjects from keywords and mapped subject codes.

    :param keywords: Keyword terms.
    :param codes: Proprietary subject codes.
    :param mapping: The ``subject_codes`` setting.
    :return: RDM subjects, without duplicates.
    """
    terms = list(keywords)
    for code in codes:
        if term := mapping.get(code):
            terms.append(term)
    seen, out = set(), []
    for term in terms:
        if term not in seen:
            seen.add(term)
            out.append({"subject": term})
    return out


def _access(license: dict | None, settings: dict) -> dict:
    """Decide a record's access.

    :param license: The title's licence, or ``None`` when not openly licensed.
    :param settings: Effective serializer settings.
    :return: RDM ``access``.
    """
    access = dict(settings["access"])
    if settings["use_license_for_access"] and license:
        access["files"] = "public"
    return access


def _files(files: list[dict], roles: tuple[str, ...]) -> list[str]:
    """Pick the file URIs a record gets, content first.

    :param files: Files as the reader produced them.
    :param roles: File roles to keep, in the order they should appear.
    :return: File URIs.
    """
    return [f["uri"] for role in roles for f in files if f["role"] == role]


def _imprint(settings: dict, **values) -> dict:
    """Build the imprint custom field, dropping empty values.

    :param settings: Effective serializer settings.
    :param values: Imprint subfields.
    :return: ``{field name: imprint}``, or empty when there is nothing to write.
    """
    field = settings["imprint_field"]
    imprint = {k: v for k, v in values.items() if v}
    return {field: imprint} if field and imprint else {}


def _pids(doi: str | None) -> dict:
    """Carry an already registered DOI.

    :param doi: The DOI, when there is one.
    :return: RDM ``pids``.
    """
    if not doi:
        return {}
    return {"doi": {"identifier": doi, "provider": "external"}}


def build_book_payload(src: dict, settings: dict) -> dict:
    """Assemble the record payload of a book.

    :param src: A book's source data.
    :param settings: Effective serializer settings.
    :return: The payload, before validation.
    """
    creators, contributors = split_contributors(src["contributors"], _roles(settings))
    if not creators:
        # An edited volume: the editors are the nearest thing to creators, and
        # a record without creators does not validate.
        creators, contributors = contributors, []
    related, _ = sibling_links(src)
    series = src.get("series") or {}
    rights_id = license_id(src.get("license"), settings["licenses"])

    additional_descriptions = [
        {"description": text, "type": {"id": "other"}}
        for text in (src.get("reviews"), src.get("biographical_note"))
        if text
    ]
    copyright_ = (
        f"© {src['copyright_year']} {src['copyright_owner']}"
        if src.get("copyright_year") and src.get("copyright_owner")
        else None
    )
    custom_fields = _imprint(
        settings,
        isbn=src.get("isbn"),
        series_name=series.get("title"),
        volume=series.get("volume"),
        edition=src.get("edition"),
    )
    custom_fields.update(load_configured_custom_fields(ONIX3_CUSTOM_FIELDS_KEY, src))

    return {
        "pids": _pids(src.get("doi")),
        "access": _access(src.get("license"), settings),
        "files": _files(src["files"], (FILE_ROLE_CONTENT, FILE_ROLE_COVER)),
        "custom_fields": custom_fields,
        "metadata": {
            "resource_type": {"id": RESOURCE_TYPE_BOOK},
            "title": src.get("title"),
            "publication_date": format_date(src.get("publication_date")),
            "publisher": src.get("publisher"),
            "additional_titles": (
                [{"title": src["subtitle"], "type": {"id": "subtitle"}}]
                if src.get("subtitle")
                else []
            ),
            "description": src.get("description"),
            "additional_descriptions": additional_descriptions,
            "languages": [{"id": code} for code in src.get("languages", [])],
            "creators": creators,
            "contributors": contributors,
            "subjects": _subjects(
                src.get("keywords", []),
                src.get("subject_codes", []),
                settings["subject_codes"],
            ),
            "identifiers": (
                [{"scheme": "isbn", "identifier": src["isbn"]}]
                if src.get("isbn")
                else []
            ),
            "related_identifiers": related,
            "sizes": [f"{src['page_count']} pages"] if src.get("page_count") else [],
            "rights": [{"id": rights_id}] if rights_id else [],
            "copyright": copyright_,
        },
    }


def build_chapter_payload(src: dict, settings: dict) -> dict:
    """Assemble the record payload of a chapter.

    A chapter inherits publisher, publication date, languages, licence and
    access from its book. Its own contributors are its creators; with none of
    its own (routine for front matter) it falls back to the book's, since
    a record without creators does not validate.

    :param src: A chapter's source data, carrying its book's context.
    :param settings: Effective serializer settings.
    :return: The payload, before validation.
    """
    book = src.get("book") or {}
    roles = _roles(settings)
    related, _ = sibling_links(src)
    rights_id = license_id(book.get("license"), settings["licenses"])

    if src.get("contributors"):
        # Everyone credited on a chapter authored it, whatever their book role.
        own_creators, own_contributors = split_contributors(src["contributors"], roles)
        creators = own_creators + own_contributors
        contributors = []
    else:
        creators, contributors = split_contributors(book.get("contributors", []), roles)
        if not creators:
            # An edited volume: the editors are the nearest thing to creators.
            creators, contributors = contributors, []

    pages = (
        f"{src['first_page']}-{src['last_page']}"
        if src.get("first_page") and src.get("last_page")
        else src.get("first_page")
    )
    custom_fields = _imprint(
        settings, title=book.get("title"), isbn=book.get("isbn"), pages=pages
    )
    custom_fields.update(load_configured_custom_fields(ONIX3_CUSTOM_FIELDS_KEY, src))

    return {
        "pids": _pids(src.get("doi")),
        "access": _access(book.get("license"), settings),
        "files": _files(src["files"], (FILE_ROLE_CONTENT,)),
        "custom_fields": custom_fields,
        "metadata": {
            "resource_type": {"id": RESOURCE_TYPE_CHAPTER},
            "title": src.get("title"),
            "publication_date": format_date(book.get("publication_date")),
            "publisher": book.get("publisher"),
            "description": src.get("abstract"),
            "languages": [{"id": code} for code in book.get("languages", [])],
            "creators": creators,
            "contributors": contributors,
            "subjects": [{"subject": kw} for kw in src.get("keywords", [])],
            "related_identifiers": related,
            "sizes": [f"{src['page_count']} pages"] if src.get("page_count") else [],
            "rights": [{"id": rights_id}] if rights_id else [],
        },
    }
