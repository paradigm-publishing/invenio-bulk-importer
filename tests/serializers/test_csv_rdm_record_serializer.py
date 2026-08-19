from copy import deepcopy

from invenio_bulk_importer.serializers.records.csv import (
    CSVRDMRecordSerializer,
)


def test_record_transform_with_custom_fields(running_app, csv_rdm_record):
    """Test the transformation of a CSV record into a RDM record."""
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record)
    except Exception:
        raise

    # Access
    assert errors is None
    assert result
    assert result["access"] == {
        "record": "public",
        "files": "restricted",
        "embargo": {"active": "TRUE", "reason": "espionage", "until": "2120-10-06"},
    }

    # Files
    assert result["files"] == ["treatment.pdf", "image1.png"]

    # Custom_fields
    assert result["custom_fields"] == {
        "imprint:imprint": {
            "edition": "23rd",
            "isbn": "978-3-16-148410-0",
            "pages": "15-23",
            "place": "Whoville",
        },
    }
    # Metadata
    assert result["metadata"]
    metadata = result["metadata"]
    assert metadata["resource_type"] == {"id": "publication"}
    assert metadata["creators"] == [
        {
            "person_or_org": {
                "type": "personal",
                "family_name": "Schlüter",
                "given_name": "Nils",
                "identifiers": [
                    {"scheme": "orcid", "identifier": "0000-0002-5699-3684"}
                ],
            },
            "affiliations": [{"name": "Museum für Naturkunde"}],
        },
        {
            "person_or_org": {
                "type": "personal",
                "family_name": "John",
                "given_name": "Smith",
                "identifiers": [{"scheme": "gnd", "identifier": "0000-9876554"}],
            },
            "affiliations": [{"name": "CERN"}],
        },
        {
            "person_or_org": {
                "type": "organizational",
                "name": "Ubiquity Press",
                "identifiers": [],
            },
            "affiliations": [],
        },
        {
            "person_or_org": {
                "type": "organizational",
                "name": "California Institute of Technology",
                "identifiers": [
                    {"scheme": "isni", "identifier": "0000 0001 0706 8890"},
                    {"scheme": "ror", "identifier": "05dxps055"},
                ],
            },
            "affiliations": [],
        },
    ]
    assert metadata["contributors"] == [
        {
            "person_or_org": {
                "type": "personal",
                "family_name": "Collins",
                "given_name": "Bob",
                "identifiers": [
                    {"scheme": "orcid", "identifier": "0000-0002-5699-3685"},
                    {"scheme": "isni", "identifier": "0000 0001 0706 8891"},
                ],
            },
            "affiliations": [{"name": "Somewhere Press"}, {"name": "Everywhere Press"}],
            "role": {
                "id": "05dxps055",
            },
        }
    ]
    assert metadata["title"] == "Micraster ernsti Schlüter 2024, sp. nov."
    assert metadata["additional_titles"] == [
        {
            "title": "Something else",
            "type": {"id": "alternative-title"},
            "lang": {"id": "eng"},
        },
    ]
    assert metadata["publication_date"] == "2024-01-18"
    assert metadata["description"]
    assert metadata["languages"] == [{"id": "eng"}]
    assert metadata["version"] == "1.0.1"
    assert metadata["publisher"] == "Ubiquity Press"
    assert metadata["additional_descriptions"] == [
        {"description": "abstract", "type": {"id": "abstract"}},
        {"description": "methods", "type": {"id": "methods"}, "lang": {"id": "eng"}},
        {"description": "notes", "type": {"id": "notes"}},
    ]
    assert metadata["rights"] == [
        {"id": "cc0-1.0", "description": {"en": "Public domain dedication"}},
        {
            "title": {"en": "New license"},
            "description": {"en": "A free-form rationale"},
        },
        {"id": "cc0-4.0"},
    ]
    assert metadata["subjects"] == [
        {"subject": "custom"},
        {"id": "http://id.nlm.nih.gov/mesh/A-D000007", "subject": "Abdominal Injuries"},
    ]
    assert metadata["references"] == [
        {
            "reference": "Rowe, A. W. (1899) An analysis of the genus Micraster, as determined by rigid zonal collecting from the zone of Rhynchonella Cuvieri to that of Micraster cor-anguinum. The Quarterly Journal of the Geological Society of London, 55, 494 - 547. https: // doi. org / 10.1144 / GSL. JGS. 1899.055.01 - 04.34"
        },
        {
            "reference": "Neraudeau, D., David, B. & Madon, C. (1998) Tuberculation in spatangoid fascioles: Delineating plausible homologies. Lethaia, 31, 323 - 333. https: // doi. org / 10.1111 / j. 1502 - 3931.1998. tb 00522. x"
        },
        {
            "reference": "Gauthier, V. (1888) Types nouveaux d'Echinides cretaces. Association Francaise pour l'Avancement des Sciences Comptes Rendus, 16, 527 - 534."
        },
        {
            "reference": "Stokes, R. B. (1975) Royaumes et provinces fauniques du Cretace etablis sur la base d'une etude systematique du genre Micraster. Memoires du Museum national d'Histoire naturelle, Serie C, 31, 1 - 94."
        },
        {
            "reference": "Lambert, J. (1920 a) Echinides fossiles des environs de Santander recueilis par M. L. Mengaud. Annales de la Societe Linneenne de Lyon, New Series, 67, 1 - 16."
        },
        {
            "reference": "Ernst, G. (1970 b) Zur Stammesgeschichte und stratigraphischen Bedeutung der Echiniden-Gattung Micraster in der nordwestdeutschen Oberkreide. Mitteilungen aus dem Geologisch-Palaeontologischen Institut der Universitat Hamburg, 39, 117 - 135."
        },
        {
            "reference": "Schluter, N. (2016) Ecophenotypic variation and developmental instability in the late Cretaceous echinoid Micraster brevis (Irregularia; Spatangoida). PLoS ONE, 11, 1 - 26. https: // doi. org / 10.1371 / journal. pone. 0148341"
        },
        {
            "reference": "Lamarck, J. - B. M. de (1816) Histoire naturelle des animaux sans vertebres. Tome 2. Verdiere, Paris, 568 pp."
        },
        {
            "reference": "Gauthier, V. (1887) Echinides. Description des especes de la craie de Reims et de quelques especes nouvelles de l'Aube et de l'Yonne. Bulletin de la Societe des Sciences Historiques et Naturelles de l'Yonne, 41, 367 - 399."
        },
        {
            "reference": "Lambert, J. (1901) Essai d'une monographie du genre Micraster et notes sur quelques echinites. Errata et addenda. In: Grossouvre, A. (Ed.), Recherches sur la Craie superieur. Memoires du Service de la Carte geologique de France, 23, pp. 957 - 971."
        },
        {
            "reference": "Kermack, K. A. (1954) A biometrical study of Micraster coranguinum and M. (Isomicraster) senonensis. Philosophical Transactions of the Royal Society of London, Series B 237, 375 - 428. https: // doi. org / 10.1098 / rstb. 1954.0001"
        },
        {
            "reference": "Smith, A. B. & Wright, C. V. (2012) British Cretaceous echinoids. Part 9, Atelostomata, 2. Spatangoida (2). Monograph of the Palaeontographical Society, 166, 635 - 754. https: // doi. org / 10.1080 / 25761900.2022.12131819"
        },
        {
            "reference": "Cotteau, G. (1889) Echinides cretaces de Madagascar. Bulletin de la Societe zoologique de France, 14, 87 – 89."
        },
    ]
    assert metadata["identifiers"] == [
        {"identifier": "10.2307/4146128", "scheme": "doi"},
    ]
    assert metadata["related_identifiers"] == [
        {
            "scheme": "doi",
            "identifier": "1.11646/zootaxa.5403.1.5",
            "resource_type": {"id": "publication-article"},
            "relation_type": {"id": "ispartof"},
        },
        {
            "scheme": "arxiv",
            "identifier": "http://zenodo.org/record/10561536",
            "resource_type": {"id": "publication-article"},
            "relation_type": {"id": "ispartof"},
        },
        {
            "scheme": "doi",
            "identifier": "http://publication.plazi.org/id/FFECFF80FFD08E48FFFC3B76AC0CFF83",
            "resource_type": {"id": "publication-article"},
            "relation_type": {"id": "ispartof"},
        },
        {
            "scheme": "doi",
            "identifier": "https://sibils.text-analytics.ch/search/collections/plazi/03D587F8FFD18E4FFF6B3C2BADAEFB92",
            "resource_type": {"id": None},
            "relation_type": {"id": "issourceof"},
        },
        {
            "scheme": "arxiv",
            "identifier": "10.5281/zenodo.10561540",
            "resource_type": {"id": "image-figure"},
            "relation_type": {"id": "cites"},
        },
        {
            "scheme": "doi",
            "identifier": "10.5281/zenodo.10561542",
            "resource_type": {"id": "image-figure"},
            "relation_type": {"id": "cites"},
        },
        {
            "scheme": "doi",
            "identifier": "10.5281/zenodo.10561544",
            "resource_type": {"id": "image-figure"},
            "relation_type": {"id": "cites"},
        },
        {
            "scheme": "doi",
            "identifier": "10.5281/zenodo.10561546",
            "resource_type": {"id": "image-figure"},
            "relation_type": {"id": "cites"},
        },
        {
            "scheme": "arxiv",
            "identifier": "http://table.plazi.org/id/DF036666FFD88E40FF6B39B0A9A7FC87",
            "resource_type": {"id": "dataset"},
            "relation_type": {"id": "cites"},
        },
        {
            "scheme": "doi",
            "identifier": "http://zoobank.org/9C92DE83-EFD7-497C-999C-5C3A0CFDF830",
            "resource_type": {"id": "publication-article"},
            "relation_type": {"id": "ispartof"},
        },
    ]

    assert metadata["dates"] == [
        {
            "date": "2020-12-31",
            "type": {"id": "other"},
            "description": "Random test date",
        },
        {
            "date": "2025-12-31",
            "type": {"id": "other"},
        },
    ]

    assert metadata["funding"] == [
        {
            "funder": {
                "id": "00k4n6c32",
            },
            "award": {"id": "00k4n6c32::755021"},
        },
        {
            "funder": {
                "id": "00k4n6c64",
            },
        },
        {
            "award": {
                "number": "100",
                "title": {"en": "Some award"},
            },
            "funder": {
                "id": "00k4n6c96",
            },
        },
    ]


def test_schema_without_custom_fields(running_app, csv_rdm_record):
    """Test validation without custom fields to see if it causes an issue."""
    csv_rdm_record_without_cf = deepcopy(csv_rdm_record)
    for key in csv_rdm_record.keys():
        if key.startswith("imprint."):
            csv_rdm_record_without_cf.pop(key)

    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record_without_cf)
    except Exception:
        raise
    assert errors is None
    assert result["custom_fields"] == {}


def test_schema_with_record_id(running_app, csv_rdm_record):
    """Test validation without custom fields to see if it causes an issue."""
    csv_rdm_record_with_id = deepcopy(csv_rdm_record)
    csv_rdm_record_with_id["id"] = "1234567890abcdef"
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record_with_id)
    except Exception:
        raise
    assert errors is None
    assert result["id"] == "1234567890abcdef"


def test_schema_missing_required_field(running_app, csv_rdm_record):
    """Test validation error when a required field is missing."""
    # Invalidate CSV input
    csv_rdm_record["title"] = ""
    csv_rdm_record["publication_date"] = ""
    csv_rdm_record["resource_type.id"] = ""
    csv_rdm_record["contributors.role.id"] = ""
    for key in csv_rdm_record.keys():
        if key.startswith("creators."):
            csv_rdm_record[key] = ""
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record)
    except Exception:
        raise

    assert result is None
    expected_errors = [
        {
            "type": "string_too_short",
            "loc": "title",
            "msg": "String should have at least 1 character",
        },
        {
            "type": "string_too_short",
            "loc": "publication_date",
            "msg": "String should have at least 1 character",
        },
        {
            "type": "value_error",
            "loc": "resource_type.id",
            "msg": "Value error, Missing 'resource_type.id'",
        },
        {
            "type": "too_short",
            "loc": "creators",
            "msg": "List should have at least 1 item after validation, not 0",
        },
        {"type": "missing", "loc": "contributors.0.role", "msg": "Field required"},
    ]
    # Check that each expected error is in the actual errors
    for expected_error in expected_errors:
        assert any(
            expected_error["type"] == error["type"]
            and expected_error["loc"] == error["loc"]
            and expected_error["msg"] == error["msg"]
            for error in errors
        ), f"Expected error not found: {expected_error}"

    # Check that we have the right number of errors
    assert len(errors) == len(expected_errors)


def test_schema_for_delete_success(running_app, record):
    """Test validation without custom fields to see if it causes an issue."""
    csv_rdm_record = {"id": record.id, "reason": "Test delete"}
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record, mode="delete")
    except Exception:
        raise
    assert errors is None
    assert result == {
        "id": record.id,
        "reason": "Test delete",
    }


def test_schema_for_delete_success_no_reason(running_app, record):
    """Test validation without custom fields to see if it causes an issue."""
    csv_rdm_record = {"id": record.id, "reason": None}
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record, mode="delete")
    except Exception:
        raise
    assert errors is None
    assert result == {
        "id": record.id,
    }


def test_schema_for_delete_missing_id(running_app):
    """Test validation without custom fields to see if it causes an issue."""
    csv_rdm_record = {"id": "", "reason": "Test delete"}
    serializer = CSVRDMRecordSerializer()
    try:
        result, errors = serializer.transform(csv_rdm_record, mode="delete")
    except Exception:
        raise
    assert errors == [
        {
            "type": "value_error",
            "loc": "id",
            "msg": "Value error, ID must be provided for deletion.",
        }
    ]
    assert result is None


def test_record_transform_accepts_exported_files_column(running_app, csv_rdm_record):
    """The exporter's ``files`` column round-trips back through the importer."""
    serializer = CSVRDMRecordSerializer()
    exported = deepcopy(csv_rdm_record)
    exported["files"] = exported.pop("filenames")

    result, errors = serializer.transform(exported)

    assert errors is None
    assert result["files"] == ["treatment.pdf", "image1.png"]
