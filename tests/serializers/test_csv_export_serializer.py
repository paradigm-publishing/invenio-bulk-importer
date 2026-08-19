"""Test InvenioRDM record serializers to export CSV."""

import csv
import io

import pytest

from invenio_bulk_importer.serializers.records.csv import CSVRDMRecordSerializer
from invenio_bulk_importer.serializers.records.csv_export import (
    CSVRDMRecordExportSerializer,
)


def _stub_exporter(value):
    """Test-only exporter that emits columns under an ``imp.`` prefix."""
    return {f"imp.{k}": v for k, v in value.items()}


@pytest.fixture
def serialized_row(running_app, full_record_dict):
    """Run the export serializer and return the parsed first CSV row."""
    serialized = CSVRDMRecordExportSerializer().serialize_object(full_record_dict)
    return next(csv.DictReader(io.StringIO(serialized)))


def _lines(value):
    """Split a CSV cell by newline, dropping empty entries."""
    return [v for v in value.split("\n") if v] if value else []


def test_column_set(serialized_row):
    """All expected columns are emitted, no surprises."""
    expected_keys = {
        "access.embargo.active",
        "access.embargo.reason",
        "access.embargo.until",
        "access.files",
        "access.record",
        "additional_descriptions.methods.eng",
        "additional_titles.subtitle.eng",
        "contributors.affiliations.id",
        "contributors.affiliations.name",
        "contributors.family_name",
        "contributors.given_name",
        "contributors.identifiers.orcid",
        "contributors.name",
        "contributors.role.id",
        "contributors.type",
        "creators.affiliations.id",
        "creators.affiliations.name",
        "creators.family_name",
        "creators.given_name",
        "creators.identifiers.orcid",
        "creators.name",
        "creators.type",
        "dates.date",
        "dates.description",
        "dates.type.id",
        "description",
        "files",
        "formats",
        "funding.award.id",
        "funding.award.number",
        "funding.award.title",
        "funding.funder.id",
        "funding.funder.name",
        "id",
        "identifiers.identifier",
        "identifiers.scheme",
        "imprint.edition",
        "imprint.isbn",
        "imprint.pages",
        "imprint.place",
        "keywords",
        "languages.id",
        "locations.description",
        "locations.lat",
        "locations.lon",
        "locations.place",
        "publication_date",
        "publisher",
        "references.identifier",
        "references.reference",
        "references.scheme",
        "related_identifiers.identifier",
        "related_identifiers.relation_type.id",
        "related_identifiers.resource_type.id",
        "related_identifiers.scheme",
        "resource_type.id",
        "rights.description",
        "rights.id",
        "rights.link",
        "rights.title",
        "sizes",
        "subjects.scheme",
        "subjects.subject",
        "title",
        "version",
    }
    assert set(serialized_row.keys()) == expected_keys


def test_top_level_columns(serialized_row):
    """``id`` is verbatim; ``files`` is a newline-joined list of entry keys."""
    assert serialized_row["id"] == "12345-abcde"
    assert serialized_row["files"] == "test.txt"


def test_access_with_active_embargo(serialized_row):
    """Active embargo block is preserved and ``access.status`` is excluded."""
    assert serialized_row["access.record"] == "public"
    assert serialized_row["access.files"] == "restricted"
    assert serialized_row["access.embargo.active"] == "True"
    assert serialized_row["access.embargo.until"] == "2131-01-01"
    assert serialized_row["access.embargo.reason"] == "Only for medical doctors."


def test_creators_flatten_person_or_org_and_identifiers(serialized_row):
    """Creators flatten ``person_or_org`` and emit per-scheme identifier columns."""
    assert _lines(serialized_row["creators.family_name"]) == ["Nielsen", "Tom"]
    assert _lines(serialized_row["creators.given_name"]) == ["Lars Holm", "Blabin"]
    assert _lines(serialized_row["creators.type"]) == ["personal", "personal"]
    # First creator has an ORCID; second does not.
    orcids = serialized_row["creators.identifiers.orcid"].split("\n")
    assert orcids[0] == "0000-0001-8135-3489"


def test_contributors_flatten_person_or_org(serialized_row):
    """Contributors flatten the same way as creators."""
    assert _lines(serialized_row["contributors.family_name"]) == ["Nielsen", "Dirk"]
    assert _lines(serialized_row["contributors.given_name"]) == ["Lars Holm", "Dirkin"]


def test_roles_and_affiliations_are_exported(serialized_row):
    """Contributors and creators role and affiliations are properly exported."""
    assert _lines(serialized_row["contributors.role.id"]) == ["other", "other"]
    # Multiple affiliations for one creator are ";"-separated, and the id and
    # name columns stay positionally paired for the importer.
    assert _lines(serialized_row["creators.affiliations.name"])[0] == "CERN;free-text"
    assert _lines(serialized_row["creators.affiliations.id"])[0] == "cern;"


def test_metadata_scalars(serialized_row):
    """Top-level metadata scalars are emitted verbatim."""
    assert serialized_row["title"] == "InvenioRDM"
    assert serialized_row["publisher"] == "InvenioRDM"
    assert serialized_row["publication_date"] == "2018/2020-09"
    assert serialized_row["version"] == "v1.0"
    assert serialized_row["resource_type.id"] == "image-photo"
    assert (
        serialized_row["description"] == "<h1>A description</h1> <p>with HTML tags</p>"
    )


def test_lists_collapse_to_newlines(serialized_row):
    """Plain list fields are collapsed to newline-separated cells."""
    assert _lines(serialized_row["languages.id"]) == ["dan", "eng"]
    assert _lines(serialized_row["formats"]) == ["application/pdf"]
    assert _lines(serialized_row["sizes"]) == ["11 pages"]


def test_additional_titles_and_descriptions_collapse(serialized_row):
    """Discriminator columns collapse ``<group>.<type>[.<lang>]``."""
    assert (
        serialized_row["additional_titles.subtitle.eng"]
        == "a research data management platform"
    )
    assert serialized_row["additional_descriptions.methods.eng"] == "Bla bla bla"


def test_subjects_split_vocab_and_free_text(serialized_row):
    """Vocab subjects land in ``subjects.*``; free-text subjects land in ``keywords``."""
    assert serialized_row["subjects.subject"] == "Abdominal Injuries"
    assert serialized_row["subjects.scheme"] == "MeSH"
    assert serialized_row["keywords"] == "custom"


def test_locations_geometry_split(serialized_row):
    """``Point`` geometry coordinates split into ``lat``/``lon`` columns; identifiers are dropped."""
    assert serialized_row["locations.lat"] == "-32.94682"
    assert serialized_row["locations.lon"] == "-60.63932"
    assert serialized_row["locations.place"] == "test location place"
    assert serialized_row["locations.description"] == "test location description"


def test_funding_i18n_title_unwrapped(serialized_row):
    """``funding.award.title`` is unwrapped from its ``{"en": ...}`` envelope."""
    assert (
        serialized_row["funding.award.title"]
        == "Launching of the research program on meaning processing"
    )
    assert serialized_row["funding.funder.id"] == "00k4n6c32"
    assert serialized_row["funding.funder.name"] == "European Commission"
    assert serialized_row["funding.award.id"] == "00k4n6c32::101122956"
    assert serialized_row["funding.award.number"] == "111023"


def test_rights_i18n_title_and_description_unwrapped(serialized_row):
    """``rights.title`` and ``rights.description`` are unwrapped from their ``{"en": ...}`` envelopes."""
    titles = _lines(serialized_row["rights.title"])
    assert "A custom license" in titles
    assert "Creative Commons Attribution 4.0 International" in titles
    descs = _lines(serialized_row["rights.description"])
    assert "A description" in descs


def test_dates_grouped_columns(serialized_row):
    """Dates are emitted as grouped sub-columns: ``date``, ``type.id``, ``description``."""
    assert serialized_row["dates.date"] == "1939/1945"
    assert serialized_row["dates.type.id"] == "other"
    assert serialized_row["dates.description"] == "A date"


def test_identifiers_grouped_columns(serialized_row):
    """Identifiers are emitted as grouped sub-columns."""
    assert serialized_row["identifiers.identifier"] == "1924MNRAS..84..308E"
    assert serialized_row["identifiers.scheme"] == "ads"


def test_related_identifiers_grouped_columns(serialized_row):
    """Related identifiers preserve relation and resource type sub-columns."""
    assert serialized_row["related_identifiers.identifier"] == "10.1234/foo.bar"
    assert serialized_row["related_identifiers.scheme"] == "doi"
    assert serialized_row["related_identifiers.relation_type.id"] == "iscitedby"
    assert serialized_row["related_identifiers.resource_type.id"] == "dataset"


def test_references_grouped_columns(serialized_row):
    """References preserve ``identifier``/``scheme`` alongside ``reference``."""
    assert serialized_row["references.reference"] == "Nielsen et al,.."
    assert serialized_row["references.identifier"] == "0000 0001 1456 7559"
    assert serialized_row["references.scheme"] == "isni"


def test_custom_fields_use_export_field_prefix(serialized_row):
    """Custom fields configured with ``export_field`` flatten under that prefix."""
    assert serialized_row["imprint.isbn"] == "978-3-16-148410-0"
    assert serialized_row["imprint.pages"] == "15-23"
    assert serialized_row["imprint.place"] == "Whoville"
    assert serialized_row["imprint.edition"] == "23rd"


def test_custom_fields_with_configured_exporter(running_app, set_app_config_fn_scoped):
    """A configured ``exporter`` callable is invoked on the value."""
    set_app_config_fn_scoped(
        {
            "BULK_IMPORTER_CUSTOM_FIELDS": {
                "csv_rdm_record_serializer": [
                    {
                        "field": "imprint:imprint",
                        "exporter": _stub_exporter,
                        "export_field": "ignored",
                    }
                ],
            }
        }
    )
    result = CSVRDMRecordExportSerializer()._process_custom_fields(
        {"imprint:imprint": {"isbn": "978", "pages": "15-23"}}
    )
    assert result == {"imp.isbn": "978", "imp.pages": "15-23"}


def test_custom_fields_fallback_when_no_config_entry(
    running_app, set_app_config_fn_scoped
):
    """A custom field absent from the config falls back to ``_flatten`` with the raw field name as prefix."""
    set_app_config_fn_scoped({"BULK_IMPORTER_CUSTOM_FIELDS": {}})
    result = CSVRDMRecordExportSerializer()._process_custom_fields(
        {"unknown:field": {"a": "1", "b": "2"}}
    )
    assert result == {"unknown:field.a": "1", "unknown:field.b": "2"}


def test_exported_row_reimports_with_its_files(serialized_row):
    """An exported row must import back with its files still attached.

    Each serializer was only ever tested on its own, so the exporter's
    ``files`` column and the importer's ``filenames`` alias drifted apart and
    exported CSVs re-imported as metadata-only records.
    """
    result, errors = CSVRDMRecordSerializer().transform(dict(serialized_row))

    assert errors is None
    assert result["files"] == ["test.txt"]
