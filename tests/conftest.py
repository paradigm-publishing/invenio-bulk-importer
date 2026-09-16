# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 Ubiquity Press.
#
# Invenio-Bulk-Importer is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""General fixtures."""

from collections import namedtuple
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import boto3
import idutils
import pytest
import responses
from flask_principal import AnonymousIdentity
from google.cloud import storage
from invenio_access.models import ActionRoles
from invenio_access.permissions import any_user as any_user_need
from invenio_access.permissions import superuser_access, system_identity
from invenio_accounts.proxies import current_datastore
from invenio_app.factory import create_api
from invenio_cache.proxies import current_cache
from invenio_communities.communities.records.api import Community
from invenio_communities.proxies import current_communities
from invenio_pidstore.errors import PIDDoesNotExistError
from invenio_rdm_records import config
from invenio_rdm_records.contrib.imprint import IMPRINT_CUSTOM_FIELDS
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_rdm_records.proxies import current_rdm_records_service as record_service
from invenio_rdm_records.records.api import RDMDraft
from invenio_rdm_records.records.api import RDMRecord as InvenioRDMRecord
from invenio_rdm_records.resources.serializers import DataCite43JSONSerializer
from invenio_rdm_records.services.permissions import RDMRequestsPermissionPolicy
from invenio_rdm_records.services.pids import providers
from invenio_records_resources.proxies import current_service_registry
from invenio_requests.proxies import current_requests_service
from invenio_users_resources.permissions import user_management_action
from invenio_users_resources.proxies import (
    current_groups_service,
    current_users_service,
)
from invenio_vocabularies.contrib.affiliations.api import Affiliation
from invenio_vocabularies.contrib.awards.api import Award
from invenio_vocabularies.contrib.funders.api import Funder
from invenio_vocabularies.contrib.subjects.api import Subject
from invenio_vocabularies.proxies import current_service as vocabulary_service
from invenio_vocabularies.records.api import Vocabulary
from moto import mock_aws
from werkzeug.local import LocalProxy

from invenio_bulk_importer.proxies import (
    current_importer_tasks_service as importer_tasks_service,
)
from invenio_bulk_importer.record_types.rdm import RDMRecord
from invenio_bulk_importer.records.api import ImporterRecord, ImporterTask
from invenio_bulk_importer.serializers.records.csv import CSVRDMRecordSerializer
from invenio_bulk_importer.serializers.records.onix3 import ONIX3RDMRecordSerializer

from .fake_datacite_client import FakeDataCiteClient
from .fake_storage import (
    GS_CONTENT,
    GS_FILE,
    GS_FILE_KEY,
    S3_BUCKET,
    S3_CONTENT,
    S3_FILE,
    S3_FILE_KEY,
    URL_CONTENT,
    URL_FILE,
    URL_FILE_KEY,
    URL_FILE_MISSING,
    FakeGCSClient,
)


def _(x):
    """Identity function for string extraction."""
    return x


@pytest.fixture(scope="module")
def mock_datacite_client():
    """Mock DataCite client."""
    return FakeDataCiteClient


@pytest.fixture(scope="function", autouse=True)
def fake_file_origins():
    """Serve the importer's remote file origins in-process.

    HTTP is served by ``responses``, S3 by ``moto``, and GCS by
    :class:`tests.fake_storage.FakeGCSClient`. Autouse because the CSV
    fixtures reference remote files from every suite, and it doubles as a
    network guard: a request to an unregistered host raises
    ``ConnectionError`` rather than leaving the process.

    :return: The active ``responses`` mock, so a test can register extra
        URLs of its own.
    """
    monkeypatch = pytest.MonkeyPatch()
    try:
        # moto needs a region and credentials to resolve the endpoint.
        monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
        monkeypatch.setattr(
            storage.Client,
            "create_anonymous_client",
            staticmethod(lambda: FakeGCSClient()),
        )
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            s3.create_bucket(Bucket=S3_BUCKET)
            # public-read so the unsigned client may read it, mirroring the
            # publicly readable buckets the importer is pointed at.
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=urlparse(S3_FILE).path.lstrip("/"),
                Body=S3_CONTENT,
                ACL="public-read",
            )
            with responses.RequestsMock(
                assert_all_requests_are_fired=False
            ) as mock_http:
                mock_http.add(
                    responses.HEAD,
                    URL_FILE,
                    headers={"Content-Length": str(len(URL_CONTENT))},
                )
                mock_http.add(responses.GET, URL_FILE, body=URL_CONTENT)
                mock_http.add(responses.HEAD, URL_FILE_MISSING, status=404)
                mock_http.add(responses.GET, URL_FILE_MISSING, status=404)
                yield mock_http
    finally:
        monkeypatch.undo()


@pytest.fixture(scope="function", autouse=True)
def clear_cache(app):
    """Clear the cache before each test function."""
    current_cache.cache.clear()


@pytest.fixture(scope="module")
def create_app(instance_path, entry_points):
    """Create app."""
    return create_api


@pytest.fixture(scope="module")
def extra_entry_points():
    """Extra entrypoints."""
    return {
        "invenio_base.blueprints": [
            "invenio_app_rdm_records = tests.mock_module:create_invenio_app_rdm_records_blueprint",  # noqa
            "invenio_app_rdm_requests = tests.mock_module:create_invenio_app_rdm_requests_blueprint",  # noqa
            "invenio_app_rdm_communities = tests.mock_module:create_invenio_app_rdm_communities_blueprint",  # noqa
        ],
    }


@pytest.fixture(scope="module")
def app_config(app_config, mock_datacite_client):
    """Overwrite pytest invenio app_config fixture."""
    supported_configurations = [
        "FILES_REST_PERMISSION_FACTORY",
        "PIDSTORE_RECID_FIELD",
        "RECORDS_PERMISSIONS_RECORD_POLICY",
        "RECORDS_REST_ENDPOINTS",
        "REQUESTS_PERMISSION_POLICY",
    ]

    for config_key in supported_configurations:
        app_config[config_key] = getattr(config, config_key, None)

    app_config["REQUESTS_PERMISSION_POLICY"] = RDMRequestsPermissionPolicy

    app_config["RECORDS_REFRESOLVER_CLS"] = (
        "invenio_records.resolver.InvenioRefResolver"
    )
    app_config["RECORDS_REFRESOLVER_STORE"] = (
        "invenio_jsonschemas.proxies.current_refresolver_store"
    )
    app_config["JSONSCHEMAS_HOST"] = "not-used"
    app_config["THEME_FRONTPAGE"] = False
    app_config["BULK_IMPORTER_CUSTOM_FIELDS"] = {
        "csv_rdm_record_serializer": [
            {
                "field": "imprint:imprint",
                "transformer": "invenio_bulk_importer.serializers.records.contrib.transformers.imprint_transform",
                "export_field": "imprint",
            }
        ]
    }
    app_config["BULK_IMPORTER_RECORD_TYPES"] = {
        "record": {
            "class": RDMRecord,
            "options": {
                "doi_minting": False,
                "publish": True,
            },
            "serializers": {
                "csv": CSVRDMRecordSerializer,
                "onix3": ONIX3RDMRecordSerializer,
            },
        }
    }
    records_index = LocalProxy(
        lambda: current_rdm_records_service.record_cls.index._name
    )
    app_config["INDEXER_DEFAULT_INDEX"] = records_index

    app_config["RDM_NAMESPACES"] = {"imprint": None}
    app_config["RDM_CUSTOM_FIELDS"] = IMPRINT_CUSTOM_FIELDS
    app_config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"] = True
    app_config["FILES_REST_STORAGE_CLASS_LIST"] = {
        "L": "Local",
        "F": "Fetch",
        "R": "Remote",
    }
    app_config["FILES_REST_DEFAULT_STORAGE_CLASS"] = "L"

    # Enable DOI minting...
    app_config["DATACITE_ENABLED"] = True
    app_config["DATACITE_USERNAME"] = "INVALID"
    app_config["DATACITE_PASSWORD"] = "INVALID"
    app_config["DATACITE_PREFIX"] = "10.1234"
    app_config["DATACITE_DATACENTER_SYMBOL"] = "TEST"
    app_config["RDM_PERSISTENT_IDENTIFIER_PROVIDERS"] = [
        # DataCite DOI provider with fake client
        providers.DataCitePIDProvider(
            "datacite",
            client=mock_datacite_client("datacite", config_prefix="DATACITE"),
            label=_("DOI"),
        ),
        # DOI provider for externally managed DOIs
        providers.ExternalPIDProvider(
            "external",
            "doi",
            validators=[providers.BlockedPrefixes(config_names=["DATACITE_PREFIX"])],
            label=_("DOI"),
        ),
        # OAI identifier
        providers.OAIPIDProvider(
            "oai",
            label=_("OAI ID"),
        ),
    ]
    app_config["RDM_PARENT_PERSISTENT_IDENTIFIER_PROVIDERS"] = [
        # DataCite Concept DOI provider
        providers.DataCitePIDProvider(
            "datacite",
            client=mock_datacite_client("datacite", config_prefix="DATACITE"),
            serializer=DataCite43JSONSerializer(schema_context={"is_parent": True}),
            label=_("Concept DOI"),
        ),
    ]
    app_config["RDM_PARENT_PERSISTENT_IDENTIFIERS"] = {
        "doi": {
            "providers": ["datacite"],
            "required": True,
            "condition": lambda rec: rec.pids.get("doi", {}).get("provider")
            == "datacite",
            "label": _("Concept DOI"),
            "validator": idutils.is_doi,
            "normalizer": idutils.normalize_doi,
            "is_enabled": providers.DataCitePIDProvider.is_enabled,
        },
    }
    app_config["RDM_PERSISTENT_IDENTIFIERS"] = {
        # DOI automatically removed if DATACITE_ENABLED is False.
        "doi": {
            "providers": ["datacite", "external"],
            "required": True,
            "label": _("DOI"),
            "validator": idutils.is_doi,
            "normalizer": idutils.normalize_doi,
            "is_enabled": providers.DataCitePIDProvider.is_enabled,
            "ui": {"default_selected": "yes"},  # "yes", "no" or "not_needed"
        },
        "oai": {
            "providers": ["oai"],
            "required": True,
            "label": _("OAI"),
            "is_enabled": providers.OAIPIDProvider.is_enabled,
        },
    }
    app_config["APP_RDM_ROUTES"] = {
        "record_detail": "/records/<pid_value>",
        "record_file_download": "/records/<pid_value>/files/<path:filename>",
    }
    return app_config


# Vocabularies


@pytest.fixture(scope="module")
def languages_type(app):
    """Lanuage vocabulary type."""
    return vocabulary_service.create_type(system_identity, "languages", "lng")


@pytest.fixture(scope="module")
def languages_v(app, languages_type):
    """Language vocabulary record."""
    vocabulary_service.create(
        system_identity,
        {
            "id": "dan",
            "title": {
                "en": "Danish",
                "da": "Dansk",
            },
            "props": {"alpha_2": "da"},
            "tags": ["individual", "living"],
            "type": "languages",
        },
    )

    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "eng",
            "title": {
                "en": "English",
                "da": "Engelsk",
            },
            "tags": ["individual", "living"],
            "type": "languages",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def resource_type_type(app):
    """Resource type vocabulary type."""
    return vocabulary_service.create_type(system_identity, "resourcetypes", "rsrct")


@pytest.fixture(scope="module")
def resource_type_v(app, resource_type_type):
    """Resource type vocabulary record."""
    vocabulary_service.create(
        system_identity,
        {
            "id": "dataset",
            "icon": "table",
            "props": {
                "csl": "dataset",
                "datacite_general": "Dataset",
                "datacite_type": "",
                "openaire_resourceType": "21",
                "openaire_type": "dataset",
                "eurepo": "info:eu-repo/semantics/other",
                "schema.org": "https://schema.org/Dataset",
                "subtype": "",
                "type": "dataset",
                "marc21_type": "dataset",
                "marc21_subtype": "",
            },
            "title": {"en": "Dataset"},
            "tags": ["depositable", "linkable"],
            "type": "resourcetypes",
        },
    )

    vocabulary_service.create(
        system_identity,
        {  # create base resource type
            "id": "image",
            "props": {
                "csl": "figure",
                "datacite_general": "Image",
                "datacite_type": "",
                "openaire_resourceType": "25",
                "openaire_type": "dataset",
                "eurepo": "info:eu-repo/semantics/other",
                "schema.org": "https://schema.org/ImageObject",
                "subtype": "",
                "type": "image",
                "marc21_type": "image",
                "marc21_subtype": "",
            },
            "icon": "chart bar outline",
            "title": {"en": "Image"},
            "tags": ["depositable", "linkable"],
            "type": "resourcetypes",
        },
    )

    vocabulary_service.create(
        system_identity,
        {  # create base resource type
            "id": "software",
            "props": {
                "csl": "figure",
                "datacite_general": "Software",
                "datacite_type": "",
                "openaire_resourceType": "0029",
                "openaire_type": "software",
                "eurepo": "info:eu-repo/semantics/other",
                "schema.org": "https://schema.org/SoftwareSourceCode",
                "subtype": "",
                "type": "image",
                "marc21_type": "software",
                "marc21_subtype": "",
            },
            "icon": "code",
            "title": {"en": "Software"},
            "tags": ["depositable", "linkable"],
            "type": "resourcetypes",
        },
    )

    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "image-photo",
            "props": {
                "csl": "graphic",
                "datacite_general": "Image",
                "datacite_type": "Photo",
                "openaire_resourceType": "25",
                "openaire_type": "dataset",
                "eurepo": "info:eu-repo/semantics/other",
                "schema.org": "https://schema.org/Photograph",
                "subtype": "image-photo",
                "type": "image",
                "marc21_type": "image",
                "marc21_subtype": "photo",
            },
            "icon": "chart bar outline",
            "title": {"en": "Photo"},
            "tags": ["depositable", "linkable"],
            "type": "resourcetypes",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def title_type(app):
    """title vocabulary type."""
    return vocabulary_service.create_type(system_identity, "titletypes", "ttyp")


@pytest.fixture(scope="module")
def title_type_v(app, title_type):
    """Title Type vocabulary record."""
    vocabulary_service.create(
        system_identity,
        {
            "id": "subtitle",
            "props": {"datacite": "Subtitle"},
            "title": {"en": "Subtitle"},
            "type": "titletypes",
        },
    )

    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "alternative-title",
            "props": {"datacite": "AlternativeTitle"},
            "title": {"en": "Alternative title"},
            "type": "titletypes",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def description_type(app):
    """title vocabulary type."""
    return vocabulary_service.create_type(system_identity, "descriptiontypes", "dty")


@pytest.fixture(scope="module")
def description_type_v(app, description_type):
    """Title Type vocabulary record."""
    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "methods",
            "title": {"en": "Methods"},
            "props": {"datacite": "Methods"},
            "type": "descriptiontypes",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def subject_v(app):
    """Subject vocabulary record."""
    subjects_service = current_service_registry.get("subjects")
    vocab = subjects_service.create(
        system_identity,
        {
            "id": "http://id.nlm.nih.gov/mesh/A-D000007",
            "scheme": "MeSH",
            "subject": "Abdominal Injuries",
        },
    )

    Subject.index.refresh()
    return vocab


@pytest.fixture(scope="module")
def date_type(app):
    """Date vocabulary type."""
    return vocabulary_service.create_type(system_identity, "datetypes", "dat")


@pytest.fixture(scope="module")
def date_type_v(app, date_type):
    """Subject vocabulary record."""
    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "other",
            "title": {"en": "Other"},
            "props": {"datacite": "Other", "marc": "oth"},
            "type": "datetypes",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def contributors_role_type(app):
    """Contributor role vocabulary type."""
    return vocabulary_service.create_type(system_identity, "contributorsroles", "cor")


@pytest.fixture(scope="module")
def contributors_role_v(app, contributors_role_type):
    """Contributor role vocabulary record."""
    vocabulary_service.create(
        system_identity,
        {
            "id": "datamanager",
            "props": {"datacite": "DataManager"},
            "title": {"en": "Data manager"},
            "type": "contributorsroles",
        },
    )

    vocabulary_service.create(
        system_identity,
        {
            "id": "projectmanager",
            "props": {"datacite": "ProjectManager"},
            "title": {"en": "Project manager"},
            "type": "contributorsroles",
        },
    )

    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "other",
            "props": {"datacite": "Other", "marc": "oth"},
            "title": {"en": "Other"},
            "type": "contributorsroles",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def relation_type(app):
    """Relation type vocabulary type."""
    return vocabulary_service.create_type(system_identity, "relationtypes", "rlt")


@pytest.fixture(scope="module")
def relation_types_v(app, relation_type):
    """Relation type vocabulary record."""
    vocab1 = vocabulary_service.create(
        system_identity,
        {
            "id": "iscitedby",
            "props": {"datacite": "IsCitedBy"},
            "title": {"en": "Is cited by"},
            "type": "relationtypes",
        },
    )

    vocab2 = vocabulary_service.create(
        system_identity,
        {
            "id": "hasmetadata",
            "props": {"datacite": "HasMetadata"},
            "title": {"en": "Has metadata"},
            "type": "relationtypes",
        },
    )

    Vocabulary.index.refresh()

    return [vocab1, vocab2]


@pytest.fixture(scope="module")
def licenses(app):
    """Licenses vocabulary type."""
    return vocabulary_service.create_type(system_identity, "licenses", "lic")


@pytest.fixture(scope="module")
def licenses_v(app, licenses):
    """Licenses vocabulary record."""
    vocab = vocabulary_service.create(
        system_identity,
        {
            "id": "cc-by-4.0",
            "props": {
                "url": "https://creativecommons.org/licenses/by/4.0/legalcode",
                "scheme": "spdx",
                "osi_approved": "",
            },
            "title": {"en": "Creative Commons Attribution 4.0 International"},
            "tags": ["recommended", "all"],
            "description": {
                "en": "The Creative Commons Attribution license allows"
                " re-distribution and re-use of a licensed work on"
                " the condition that the creator is appropriately credited."
            },
            "type": "licenses",
        },
    )

    Vocabulary.index.refresh()

    return vocab


@pytest.fixture(scope="module")
def affiliations_v(app):
    """Affiliation vocabulary record."""
    affiliations_service = current_service_registry.get("affiliations")
    aff = affiliations_service.create(
        system_identity,
        {
            "id": "cern",
            "name": "CERN",
            "acronym": "CERN",
            "identifiers": [
                {
                    "scheme": "ror",
                    "identifier": "01ggx4157",
                },
                {
                    "scheme": "isni",
                    "identifier": "000000012156142X",
                },
            ],
        },
    )

    Affiliation.index.refresh()

    return aff


@pytest.fixture(scope="module")
def funders_v(app):
    """Funder vocabulary record."""
    funders_service = current_service_registry.get("funders")
    funder = funders_service.create(
        system_identity,
        {
            "id": "00k4n6c32",
            "identifiers": [
                {
                    "identifier": "000000012156142X",
                    "scheme": "isni",
                },
                {
                    "identifier": "00k4n6c32",
                    "scheme": "ror",
                },
            ],
            "name": "European Commission",
            "title": {
                "en": "European Commission",
                "fr": "Commission européenne",
            },
            "country": "BE",
        },
    )

    Funder.index.refresh()

    return funder


@pytest.fixture(scope="module")
def awards_v(app, funders_v):
    """Funder vocabulary record."""
    awards_service = current_service_registry.get("awards")
    award = awards_service.create(
        system_identity,
        {
            "id": "00k4n6c32::755021",
            "identifiers": [
                {
                    "identifier": "https://cordis.europa.eu/project/id/755021",
                    "scheme": "url",
                }
            ],
            "number": "755021",
            "title": {
                "en": (
                    "Personalised Treatment For Cystic Fibrosis Patients With "
                    "Ultra-rare CFTR Mutations (and beyond)"
                ),
            },
            "funder": {"id": "00k4n6c32"},
            "acronym": "HIT-CF",
            "program": "H2020",
        },
    )

    Award.index.refresh()

    return award


@pytest.fixture(scope="module")
def community_type_record(app):
    """Create and retrieve community type records."""
    vocabulary_service.create_type(system_identity, "communitytypes", "comtyp")
    record = vocabulary_service.create(
        identity=system_identity,
        data={
            "id": "topic",
            "title": {"en": "Topic"},
            "type": "communitytypes",
        },
    )
    Vocabulary.index.refresh()  # Refresh the index

    return record


RunningApp = namedtuple(
    "RunningApp",
    [
        "app",
        "location",
        "cache",
        "resource_type_v",
        "subject_v",
        "languages_v",
        "affiliations_v",
        "title_type_v",
        "description_type_v",
        "date_type_v",
        "contributors_role_v",
        "relation_types_v",
        "licenses_v",
        "funders_v",
        "awards_v",
    ],
)


@pytest.fixture
def running_app(
    app,
    location,
    cache,
    resource_type_v,
    subject_v,
    languages_v,
    affiliations_v,
    title_type_v,
    description_type_v,
    date_type_v,
    contributors_role_v,
    relation_types_v,
    licenses_v,
    funders_v,
    awards_v,
):
    """This fixture provides an app with the typically needed db data loaded.

    All of these fixtures are often needed together, so collecting them
    under a semantic umbrella makes sense.
    """
    return RunningApp(
        app,
        location,
        cache,
        resource_type_v,
        subject_v,
        languages_v,
        affiliations_v,
        title_type_v,
        description_type_v,
        date_type_v,
        contributors_role_v,
        relation_types_v,
        licenses_v,
        funders_v,
        awards_v,
    )


#
# Services
#
@pytest.fixture(scope="module")
def user_service(app):
    """User service."""
    return current_users_service


@pytest.fixture(scope="module")
def group_service(app):
    """Group service."""
    return current_groups_service


#
# Users
#
@pytest.fixture(scope="module")
def anon_identity():
    """A new user."""
    identity = AnonymousIdentity()
    identity.provides.add(any_user_need)
    return identity


@pytest.fixture(scope="module")
def user_admin(users, database, superadmin_group):
    """User with notfications disabled."""
    action_name = user_management_action.value
    super_admin = users["admin_user"]

    action_role = ActionRoles.create(action=superuser_access, role=superadmin_group)
    database.session.add(action_role)

    # super_admin.user.roles.append(admin_group)
    super_admin.user.roles.append(superadmin_group)
    database.session.commit()
    current_groups_service.indexer.process_bulk_queue()
    current_groups_service.record_cls.index.refresh()
    return super_admin


@pytest.fixture(scope="module")
def user_moderator(UserFixture, app, database, users, admin_group):
    """Admin user for requests."""
    action_name = user_management_action.value
    moderator = users["user_moderator"]

    action_role = ActionRoles.create(action=user_management_action, role=admin_group)
    database.session.add(action_role)

    moderator.user.roles.append(admin_group)
    database.session.commit()
    current_groups_service.indexer.process_bulk_queue()
    current_groups_service.record_cls.index.refresh()
    return moderator


@pytest.fixture(scope="module")
def users_data():
    """Data for users."""
    return [
        {
            "username": "user_moderator",
            "email": "user_moderator@inveniosoftware.org",
            "profile": {
                "full_name": "Mr",
                "affiliations": "Admin",
            },
            "preferences": {
                "visibility": "restricted",
                "email_visibility": "public",
            },
        },
        {
            "username": "admin_user",
            "email": "super_admin@inveniosoftware.org",
            "profile": {
                "full_name": "Mr",
                "affiliations": "Super Admin",
            },
            "preferences": {
                "visibility": "restricted",
                "email_visibility": "public",
            },
        },
    ]


@pytest.fixture(scope="module")
def users(UserFixture, app, database, users_data):
    """Test users."""
    users = {}
    for obj in users_data:
        u = UserFixture(
            username=obj["username"],
            email=obj["email"],
            password=obj["username"],
            user_profile=obj.get("profile"),
            preferences=obj.get("preferences"),
            active=obj.get("active", True),
            confirmed=obj.get("confirmed", True),
        )
        u.create(app, database)
        users[obj["username"]] = u
    database.session.commit()
    current_users_service.record_cls.index.refresh()
    return users


#
# User groups
#
def _create_group(id, name, description, is_managed, database):
    """Creates a Role/Group."""
    r = current_datastore.create_role(
        id=id, name=name, description=description, is_managed=is_managed
    )
    current_datastore.commit()
    return r


@pytest.fixture(scope="module")
def superadmin_group(database):
    """Superadmin group."""
    r = _create_group(
        id="admin",
        name="admin",
        description="Super Admin Group",
        is_managed=True,
        database=database,
    )
    return r


@pytest.fixture(scope="module")
def admin_group(database):
    """Admin group."""
    action_name = user_management_action.value
    r = _create_group(
        id=action_name,
        name=action_name,
        description="user_management_action group",
        is_managed=True,
        database=database,
    )
    return r


#
# Communities
#
@pytest.fixture()
def minimal_community():
    """Minimal community data."""
    return {
        "slug": "test-community",
        "access": {
            "visibility": "public",
            "review_policy": "open",
        },
        "metadata": {
            "title": "Test community",
            "type": {"id": "topic"},
            "page": "test-page",
        },
    }


@pytest.fixture()
def minimal_restricted_community(minimal_community):
    """Minimal restricted community data."""
    minimal_community["access"]["visibility"] = "restricted"
    return minimal_community


@pytest.fixture()
def community_owner(UserFixture, app, db):
    """Community owner."""
    u = UserFixture(
        email="community_owner@up.up",
        password="community_owner",
    )
    u.create(app, db)
    return u


def _community(community, owner):
    slug = community["slug"]
    try:
        c = current_communities.service.record_cls.pid.resolve(slug)
    except PIDDoesNotExistError:
        c = current_communities.service.create(
            owner.identity,
            community,
        )
        Community.index.refresh()
    return c


@pytest.fixture()
def community(running_app, community_type_record, community_owner, minimal_community):
    """Create community using the minimal fixture data."""
    return _community(minimal_community, community_owner)


@pytest.fixture()
def restricted_community(
    running_app, community_type_record, community_owner, minimal_restricted_community
):
    """Create a restricted community."""
    return _community(minimal_restricted_community, community_owner)


#
#
#
@pytest.fixture()
def minimal_record():
    """Minimal record data as dict coming from the external world."""
    return {
        "pids": {
            "doi": {"identifier": "10.5281/zenodo.10572732", "provider": "external"}
        },
        "files": {
            "enabled": False,  # Most tests don't care about files
        },
        "metadata": {
            "creators": [
                {
                    "person_or_org": {
                        "family_name": "Howlett",
                        "given_name": "James",
                        "type": "personal",
                    }
                },
            ],
            "publication_date": "2020-06-01",
            "publisher": "Acme Inc",
            "resource_type": {"id": "dataset"},
            "title": "Logan",
        },
    }


@pytest.fixture()
def record_owner(UserFixture, app, db):
    """Record owner."""
    u = UserFixture(
        email="record_owner@up.up",
        password="record_owner",
    )
    u.create(app, db)
    return u


@pytest.fixture()
def record(running_app, record_owner, minimal_record, app_config, community):
    """Create record using the minimal record fixture data."""
    r = record_service.create(record_owner.identity, minimal_record)
    data = {
        "type": "community-submission",
        "receiver": {"community": community.id},
    }
    # Update record parent with community relationships request.
    request = record_service.review.update(
        system_identity,
        r.id,
        data,
    )
    # Submit record to community to be accepted.
    current_requests_service.execute_action(
        system_identity, id_=request.id, action="submit"
    )
    # Accept Record into the community.
    current_requests_service.execute_action(
        system_identity,
        id_=request.id,
        action="accept",
        send_notification=False,
    )

    InvenioRDMRecord.index.refresh()

    return r


@pytest.fixture()
def draft(running_app, record_owner, minimal_record):
    """Create record using the minimal record fixture data."""
    r = record_service.create(record_owner.identity, minimal_record)

    RDMDraft.index.refresh()

    return r


#
# Importer Tasks
#
@pytest.fixture()
def minimal_importer_task():
    """Minimal importer task data."""
    return {
        "title": "Test Importer Task",
        "description": "This is a test importer task.",
        "mode": "import",
        "status": "created",
        "start_time": None,
        "end_time": None,
        "record_type": "record",
        "serializer": "csv",
    }


@pytest.fixture()
def task(running_app, user_admin, minimal_importer_task, app_config):
    """Create record using the minimal record fixture data."""
    r = importer_tasks_service.create(user_admin.identity, minimal_importer_task)

    # Path to the test file (assuming it's in the same directory)
    file_path = Path(__file__).parent / "data" / "rdm_records.csv"

    # Read the file and create a BytesIO stream
    with file_path.open("rb") as f:
        stream = BytesIO(f.read())
        importer_tasks_service.update_metadata_file(
            user_admin.identity,
            r.id,
            "rdm_records.csv",
            stream,
            content_length=stream.getbuffer().nbytes,
        )

    # Add other files needed for records to be created
    content = BytesIO(b"test file content")
    result = importer_tasks_service._update_file(
        user_admin.identity, r._record, content, "article", ".txt"
    )
    assert result.to_dict()["key"] == "article.txt"
    ImporterTask.index.refresh()
    return r


@pytest.fixture
def validated_ir_data():
    """Validated importer record data for testing.

    Has been processed successfully via validation of serializer and record_type.
    """
    return {
        "status": "validated",
        "src_data": {
            "Id": "",
            "doi": "10.5281/zenodo.10572732",
            "title": "Micraster ernsti Schlüter 2024, sp. nov.",
            "version": "1.0.1",
            "keywords": "custom",
            "filenames": f"{URL_FILE}\n",
            "publisher": "Ubiquity Press",
            "rights.id": "cc0-1.0\n\ncc0-4.0",
            "communities": "test-community",
            "description": "<i>Micraster ernsti</i> sp. nov.   <p>(Figs. 2&ndash;5)</p>  <p> ? 1954 <i>Micraster</i> (<i>Isomicraster</i>) <i>senonensis</i> Lambert; Kermack, pl. 24, fig. 13; pl. 25, fig. 15; pl. 26, fig. 17.</p>   <p> 1972 <i>Micraster</i> (<i>Gibbaster</i>) sp.; Ernst, figs. 4, 2a; pl. 18, fig. 3&ndash;4.</p>   <p> 1989 <i>Gibbaster</i> sp.; Frerichs, p.161, fig. 6.</p>   <p> pars 2012 <i>Micraster stolleyi</i> Lambert; Smith &amp; Wright, p. 683, text-fig. 303; pl. 247, figs. 1&ndash;7.</p>   <p> 2023 <i>Micraster</i> sp.; Schl&uuml;ter &amp; Schneider, p. 57, fig. 60.</p>   <p> <b>Diagnosis.</b> Conical lateral profile with a polygonate outline; apical disc subcentral, periproct well below mid-height of the test. Generally slender labral plate with a smooth rim at its tip, largely covering the peristome. Peristome faces forward; the oral surface surrounding the peristome is slightly depressed. The peristome is relatively far away from the anterior margin (mean=20% of the test length): the periplastronal plates have a granular-mammilate surface; the perradial area in the plates of the petals is inflated. The anterior ambulacrum has aborally elongated pore pairs.</p>   <p> <b>Types.</b> Holotype is MB.E.8577 from the <i>Echinocorys conica</i> / <i>Galeola pappilosa</i> Zone, lower Campanian from the quarry adjacent to H&ouml;ver, southeast of Hannover, Lower Saxony, Germany; paratypes are MB.E.8583 <i>conica</i> / <i>pappilosa</i> Zone, Teutonia Nord quarry, Hannover, and MB.E.8576, <i>conica</i> / <i>pappilosa</i> Zone, lower Campanian, H&ouml;ver.</p>   <p> <b>Derivatio nominis.</b> In honour of the late Gundolf Ernst, who contributed tremendously with his work to the knowledge of the evolution of the genus <i>Micraster</i>.</p>   <p> <b>Stratum typicum.</b> From the <i>conica</i> / <i>pappilosa</i> Zone, lower Campanian.</p>   <p> <b>Locus typicus.</b> The area southeast of Hannover, Lower Saxony, Germany, i.e. the working limestone quarries in Hannover-Misburg, Teutonia Nord and Germania IV, as well as the quarry in H&ouml;ver in the vicinity of Hannover, Lower Saxony, Germany.</p>   <p> <b>Additional material.</b> MB.E:8574, 8575 (ex leg. Duckstein), MB.E.8576, 8578, 8579, MB.E.8580, MB.E.8581&ndash; 8582 from the lower Campanian of H&ouml;ver, vicinity of Hannover, Lower Saxony, Germany.</p>   <p> <b>Description.</b> Cordiform and polygonate (more pronounced in larger specimens) in outline. The test is slightly wider than long (length/width ratio of the tests ranges from 1.00 to 1.07, mean=1.02, n=10). The tests have a somewhat conical lateral profile, rather rounded towards the apex. Specimen MB.E.8583 is clearly more conical in profile, tapering towards the apex. The test is highest approximately a bit posterior from the apical disc which has a slightly elongated outline (Fig. 5B). It is ethmophract, having four gonopores and an enlarged madreporite; the posterior genital plates are not separated by the madreporite (Fig. 5C). The apical disc is in a subcentral position, somewhat anterior to the mid-length of the test, ranging from 34 to 44% of the test length (mean=40%, n=7) from the test length (measured from the anterior edge of ocular plate III).</p>   <p>The little sunken paired petals have conjugate anisopores with outer elongated pores. The perradius of the petals is weakly inflated (see Rowe, 1899; Olszewska-Neijbert, 2007; Fig. 4B) with a shallow granular ridge adapically of the pore pairs. The anterior paired petals have a straight outline and bear 75 pore pairs per column at a length of 64 mm and the posterior petals bear 68 pore pairs per column at the same test length. The outline of the posterior paired petals is straight and only very slightly curved close to the apical disc. The anterior paired petals diverge with an angle of 122&ndash;150&deg; (mean=130&deg;, n=7), whereas the posterior paired petals diverge with an angle of 52&ndash;64&deg; (mean=57&deg;, n=6) (both measured in plan view from photos).</p>  <p>Ambitally, ambulacrum III forms a very shallow anterior notch which leads adorally as a little depressed groove towards the faintly sunken peristome. Aborally, AIII is only very slightly sunken in an adapical direction where it shows conjugate anisopores with slightly more elongated outer pores. The surface of the ambulacrum III is granular and plating sutures are easily visible.</p>  <p>The amphisternous plastron has symmetrical (Fig. 5A) to asymmetrical sternal plates in specimen MB.E.8576 (Fig. 5B); in the latter case, the contact of the sternals to the labrum is convex, rather than concave (Fig. 5B) and their length is 46% of the test length (43&ndash;51%, n=8).</p>  <p>The shape of the labral plate is slender with almost parallel sides (Fig. 5A). The labral plate is relatively short, equal to 10% of the test length (range: 7&ndash;13%, n=8). The tip of the labrum has a prominent smooth rim. The labrum is projecting and covers completely the peristome or in such a way that only a small part of the peristomal opening can be seen from the oral view. The second ambulacral plates (I.a.2 and I.b.2) adjacent to the labrum are relatively long, extending beyond the back of the labrum by about one-third of their length. The peristome is located in a slight depression and is obliquely facing forward. Its anterior margin is at a distance of 17&ndash;23% of the test length to the anterior edge of the test (mean=20%, n=9). Moderately-developed phyllodes comprise 4&ndash;6 enlarged isopores with a prominent interporal knob in ambulacrum II; III and IV, with smaller-sized pore pairs in ambulacrum I and V. Interambulacrum 2 and 3 are disjunct from the peristomal opening. Interambulacrum 1 and 5 on the oral surface are amphiplacous.</p>  <p> The periplastronal ambulacral plates reveal scattered tubercles surrounded by a granular-mammilate surface (Fig. 4D). The upper surface has densely arranged granules with sparse small tubercles. Aligned granules can be seen shortly above the oral surface from the distal ends of the paired petals to the ambitus, resembling parafascioles (<i>sensu</i> N&eacute;raudeau <i>et al.</i>, 1998); such parafascioles can be also found at the lower third of the junction of the interambulacral plates (interradius) in interambulacrum 1 and 4.</p>   <p>The adapical edge of the periproct is 37&ndash;49% of the test height (mean=43%, n=8).</p>  <p>In contrast, no traces of a subanal fasciole were found in any specimen and the posterior face is truncated and almost vertical.</p>  <p> <b>Remarks.</b> <i>Micraster</i> species with a more inflated and conical shape, a low-positioned periproct and subpetaloid anterior ambulacra were traditionally referred to as the subgenus <i>Gibbaster</i> (Gauthier, 1888). Stokes (1975) and Schl&uuml;ter <i>et al.</i> (2023) declined to further subdivide <i>Micraster</i> into <i>Gibbaster</i> and consider <i>Gibbaster</i> to be synonymous with <i>Micraster</i> due to the polyphyletic development in the shape of the test. In addition, the subpetaloid development in ambulacrum III can also occur in specimens which would be commonly addressed as <i>Micraster</i>. Further, Schl&uuml;ter <i>et al.</i> (2023) found that the subpetaloid development in ambulacrum III and the degree of the test inflation can vary dramatically within species from the Santonian of northern Cantabria, Spain. In particular, in <i>Micraster mengaudi</i> (Lambert 1920a) and <i>Micraster quebrada</i>, intraspecific variation ranges from non-petaloid to sub-petaloid in pore pair development in ambulacrum III, and the test shape can range from rather flat to highly inflated.</p>   <p> Regarding the history of the herein-described species, Ernst (1970b) identified several specimens of what he assumed at this time to be an undescribed species of the genus <i>Gibbaster</i>. These were from sandy, glauconitic marls from different localities in southern western Munsterland, Germany and this material was dated ranging from upper Santonian to early lower Campanian. Judging by the architecture of the oral surface (dimension of the labrum, presence of a smooth rim at its tip, position of the peristome) and the polygonate outline, this material is indistinguishable from the specimens described herein. However, the Munsterland material is flatter in the lateral profile. Ernst also mentioned the absence of a subanal fasciole in the Santonian specimens and the presence of a subanal fasciole in the Campanian specimens.</p>   <p> Differences in test height as well as the development of a subanal fasciole may also have been caused by phenotypic plasticity in response to differences in the sediment (Schl&uuml;ter 2016). Nonetheless, these differences are most likely due to intraspecific variations and are insufficient to address both forms as distinct species. Accordingly, <i>Micraster ernsti</i> <b>sp. nov.</b> can likely be dated back to the upper Santonian, as present in the Munsterland; unfortunately, the material described by Ernst from there could not be traced. Other late Santonian and Campanian <i>Micraster</i> species which also show a subpetaloid ambulacrum III, i.e. <i>Micraster gibbus</i> (Lamarck, 1816) <i>Micraster fastigatus</i> (Gauthier, 1887), <i>Micraster stolleyi</i> (Lambert, 1901), have a more conical, inflated test and a low-positioned periproct, similar to <i>Micraster ernsti</i> <b>sp. nov.</b>, can be easily distinguished by the position of their peristome which is closer to the anterior margin, their more projecting labrum and the granular tip of the labrum. Another very distinctive feature is the polygonal-shaped outline of the test in <i>Micraster ernsti</i> <b>sp. nov.</b> However, Kermack (1954) illustrated a specimen from the Santonian (Northfleet, Kent, UK) closely resembling <i>Micraster ernsti</i> <b>sp. nov.</b> in the outline and the position of the peristome that may belong to <i>Micraster ernsti</i> <b>sp. nov.</b> under the name <i>Micraster</i> (<i>Isomicraster</i>) <i>senonensis</i>. <i>Micraster senonensis</i> is undoubtedly a synonym of <i>Micraster gibbus</i> (see Smith &amp; Wright, 2012). The Campanian <i>Micraster gourdoni</i> Cotteau, 1889 from France also has a subpetaloid ambulacrum III, the type specimen has a somewhat polygonal outline but is very different to the herein described species by the peristome close to the anterior margin, the strongly projecting labrum and the longer posterior petals. The late Santonian <i>Micraster quebrada</i> has a similar position of the peristome, however, is significantly different in the non-projecting labrum and downward-facing peristome. The morphological distinctions between <i>Micraster ernsti</i> <b>sp. nov.</b>, the here-discussed species, and few other (contemporary) species, as well as additional details, are consolidated in Table 1.</p>",
            "access.files": "restricted",
            "imprint.isbn": "978-3-16-148410-0",
            "languages.id": "eng",
            "rights.title": "\nNew license\nExisting license",
            "creators.name": "\n\nUbiquity Press\nCalifornia Institute of Technology",
            "creators.type": "personal\npersonal\norganizational\norganizational",
            "imprint.pages": "15-23",
            "imprint.place": "Whoville",
            "locations.lat": "38.8951",
            "locations.lon": "-77.0364",
            "imprint.edition": "23rd",
            "locations.place": "Washington",
            "subjects.scheme": "MeSH",
            "creators.role.id": "",
            "publication_date": "2024-01-18",
            "resource_type.id": "publication",
            "subjects.subject": "Abdominal Injuries",
            "contributors.name": "",
            "contributors.type": "personal",
            "identifiers.scheme": "doi",
            "Imprint.series_name": "Some series",
            "creators.given_name": "Nils\nSmith\n\n",
            "access.embargo.until": "2120-10-06",
            "contributors.role.id": "editor",
            "creators.family_name": "Schlüter\nJohn\n\n",
            "references.reference": "Rowe, A. W. (1899) An analysis of the genus Micraster, as determined by rigid zonal collecting from the zone of Rhynchonella Cuvieri to that of Micraster cor-anguinum. The Quarterly Journal of the Geological Society of London, 55, 494 - 547. https: // doi. org / 10.1144 / GSL. JGS. 1899.055.01 - 04.34 \nNeraudeau, D., David, B. & Madon, C. (1998) Tuberculation in spatangoid fascioles: Delineating plausible homologies. Lethaia, 31, 323 - 333. https: // doi. org / 10.1111 / j. 1502 - 3931.1998. tb 00522. x \nGauthier, V. (1888) Types nouveaux d'Echinides cretaces. Association Francaise pour l'Avancement des Sciences Comptes Rendus, 16, 527 - 534. \nStokes, R. B. (1975) Royaumes et provinces fauniques du Cretace etablis sur la base d'une etude systematique du genre Micraster. Memoires du Museum national d'Histoire naturelle, Serie C, 31, 1 - 94. \nLambert, J. (1920 a) Echinides fossiles des environs de Santander recueilis par M. L. Mengaud. Annales de la Societe Linneenne de Lyon, New Series, 67, 1 - 16. \nErnst, G. (1970 b) Zur Stammesgeschichte und stratigraphischen Bedeutung der Echiniden-Gattung Micraster in der nordwestdeutschen Oberkreide. Mitteilungen aus dem Geologisch-Palaeontologischen Institut der Universitat Hamburg, 39, 117 - 135. \nSchluter, N. (2016) Ecophenotypic variation and developmental instability in the late Cretaceous echinoid Micraster brevis (Irregularia; Spatangoida). PLoS ONE, 11, 1 - 26. https: // doi. org / 10.1371 / journal. pone. 0148341 \nLamarck, J. - B. M. de (1816) Histoire naturelle des animaux sans vertebres. Tome 2. Verdiere, Paris, 568 pp. \nGauthier, V. (1887) Echinides. Description des especes de la craie de Reims et de quelques especes nouvelles de l'Aube et de l'Yonne. Bulletin de la Societe des Sciences Historiques et Naturelles de l'Yonne, 41, 367 - 399. \nLambert, J. (1901) Essai d'une monographie du genre Micraster et notes sur quelques echinites. Errata et addenda. In: Grossouvre, A. (Ed.), Recherches sur la Craie superieur. Memoires du Service de la Carte geologique de France, 23, pp. 957 - 971. \nKermack, K. A. (1954) A biometrical study of Micraster coranguinum and M. (Isomicraster) senonensis. Philosophical Transactions of the Royal Society of London, Series B 237, 375 - 428. https: // doi. org / 10.1098 / rstb. 1954.0001 \nSmith, A. B. & Wright, C. V. (2012) British Cretaceous echinoids. Part 9, Atelostomata, 2. Spatangoida (2). Monograph of the Palaeontographical Society, 166, 635 - 754. https: // doi. org / 10.1080 / 25761900.2022.12131819 \nCotteau, G. (1889) Echinides cretaces de Madagascar. Bulletin de la Societe zoologique de France, 14, 87 – 89.",
            "access.embargo.active": "TRUE",
            "access.embargo.reason": "espionage",
            "locations.description": "Big city",
            "identifiers.identifier": "10.5281/zenodo.10572732\n",
            "contributors.given_name": "Bob",
            "contributors.family_name": "Collins",
            "creators.affiliations.id": "",
            "creators.identifiers.gnd": "\n1089945302",
            "creators.identifiers.ror": "\n\n\n05dxps055",
            "creators.identifiers.isni": "\n\n\n0000 0001 0706 8890",
            "creators.affiliations.name": "Museum für Naturkunde\nCERN\n\n",
            "creators.identifiers.orcid": "0000-0002-1825-0097\n",
            "related_identifiers.scheme": "doi\narxiv\ndoi\ndoi\narxiv\ndoi\ndoi\ndoi\narxiv\ndoi",
            "contributors.affiliations.id": "",
            "contributors.identifiers.gnd": "",
            "contributors.identifiers.ror": "",
            "additional_descriptions.notes": "notes",
            "contributors.identifiers.isni": "0000 0001 2146 438X\n",
            "contributors.affiliations.name": "Somewhere Press;Everywhere Press",
            "contributors.identifiers.orcid": "0000-0002-1825-0097\n",
            "related_identifiers.identifier": "10.1080/10509585.2015.1092083\n2305.12345\n10.1080/10509585.2015.1092083/987\n10.1080/10509585.2015.1092033\n2305.12345v1\n10.5281/zenodo.10561542\n10.5281/zenodo.10561544\n10.5281/zenodo.10561546\nastro-ph/0703123v2\n10.5281/zenodo.1056154987",
            "additional_descriptions.abstract": "abstract",
            "additional_descriptions.methods.eng": "methods",
            "related_identifiers.relation_type.id": "ispartof\nispartof\nispartof\nissourceof\ncites\ncites\ncites\ncites\ncites\nispartof",
            "related_identifiers.resource_type.id": "publication-article\npublication-article\npublication-article\npublication-article\nimage-figure \nimage-figure \nimage-figure \nimage-figure \ndataset\npublication-article",
            "additional_titles.alternative-title.eng": "Something else",
        },
        "serializer_data": {},
        "transformed_data": {
            "pids": {
                "doi": {"identifier": "10.5281/zenodo.10572732", "provider": "external"}
            },
            "files": {"enabled": True},
            "metadata": {
                "resource_type": {"id": "dataset"},
                "creators": [
                    {
                        "person_or_org": {
                            "type": "personal",
                            "given_name": "Nils",
                            "family_name": "Schlüter",
                            "identifiers": [
                                {"identifier": "0000-0002-1825-0097", "scheme": "orcid"}
                            ],
                            "name": "Schlüter, Nils",
                        },
                        "affiliations": [{"name": "Museum für Naturkunde"}],
                    },
                    {
                        "person_or_org": {
                            "type": "personal",
                            "given_name": "Smith",
                            "family_name": "John",
                            "identifiers": [
                                {"identifier": "gnd:1089945302", "scheme": "gnd"}
                            ],
                            "name": "John, Smith",
                        },
                        "affiliations": [{"name": "CERN"}],
                    },
                    {
                        "person_or_org": {
                            "type": "organizational",
                            "name": "Ubiquity Press",
                        }
                    },
                    {
                        "person_or_org": {
                            "type": "organizational",
                            "name": "California Institute of Technology",
                            "identifiers": [
                                {"identifier": "05dxps055", "scheme": "ror"},
                                {"identifier": "0000 0001 0706 8890", "scheme": "isni"},
                            ],
                        }
                    },
                ],
                "title": "Micraster ernsti Schlüter 2024, sp. nov.",
                "additional_titles": [
                    {
                        "title": "Something else",
                        "type": {"id": "alternative-title"},
                        "lang": {"id": "eng"},
                    }
                ],
                "publisher": "Ubiquity Press",
                "publication_date": "2024-01-18",
                "subjects": [
                    {"subject": "custom"},
                    {
                        "id": "http://id.nlm.nih.gov/mesh/A-D000007",
                        "subject": "Abdominal Injuries",
                    },
                ],
                "contributors": [
                    {
                        "person_or_org": {
                            "type": "personal",
                            "given_name": "Bob",
                            "family_name": "Collins",
                            "identifiers": [
                                {"identifier": "0000 0001 2146 438X", "scheme": "isni"},
                                {
                                    "identifier": "0000-0002-1825-0097",
                                    "scheme": "orcid",
                                },
                            ],
                            "name": "Collins, Bob",
                        },
                        "role": {"id": "datamanager"},
                        "affiliations": [
                            {"name": "Somewhere Press"},
                            {"name": "Everywhere Press"},
                        ],
                    }
                ],
                "languages": [{"id": "eng"}],
                "identifiers": [
                    {"identifier": "10.5281/zenodo.10572732", "scheme": "doi"}
                ],
                "related_identifiers": [
                    {
                        "identifier": "10.1080/10509585.2015.1092083",
                        "scheme": "doi",
                        "relation_type": {"id": "iscitedby"},
                        "resource_type": {"id": "dataset"},
                    },
                    {
                        "identifier": "arXiv:2305.12345",
                        "scheme": "arxiv",
                        "relation_type": {"id": "iscitedby"},
                        "resource_type": {"id": "dataset"},
                    },
                ],
                "version": "1.0.1",
                "rights": [
                    {"id": "cc-by-4.0"},
                ],
                "description": "<i>Micraster ernsti</i> sp. nov.   <p>(Figs. 2&ndash;5)</p>  <p> ? 1954 <i>Micraster</i> (<i>Isomicraster</i>) <i>senonensis</i> Lambert; Kermack, pl. 24, fig. 13; pl. 25, fig. 15; pl. 26, fig. 17.</p>   <p> 1972 <i>Micraster</i> (<i>Gibbaster</i>) sp.; Ernst, figs. 4, 2a; pl. 18, fig. 3&ndash;4.</p>   <p> 1989 <i>Gibbaster</i> sp.; Frerichs, p.161, fig. 6.</p>   <p> pars 2012 <i>Micraster stolleyi</i> Lambert; Smith &amp; Wright, p. 683, text-fig. 303; pl. 247, figs. 1&ndash;7.</p>   <p> 2023 <i>Micraster</i> sp.; Schl&uuml;ter &amp; Schneider, p. 57, fig. 60.</p>   <p> <b>Diagnosis.</b> Conical lateral profile with a polygonate outline; apical disc subcentral, periproct well below mid-height of the test. Generally slender labral plate with a smooth rim at its tip, largely covering the peristome. Peristome faces forward; the oral surface surrounding the peristome is slightly depressed. The peristome is relatively far away from the anterior margin (mean=20% of the test length): the periplastronal plates have a granular-mammilate surface; the perradial area in the plates of the petals is inflated. The anterior ambulacrum has aborally elongated pore pairs.</p>   <p> <b>Types.</b> Holotype is MB.E.8577 from the <i>Echinocorys conica</i> / <i>Galeola pappilosa</i> Zone, lower Campanian from the quarry adjacent to H&ouml;ver, southeast of Hannover, Lower Saxony, Germany; paratypes are MB.E.8583 <i>conica</i> / <i>pappilosa</i> Zone, Teutonia Nord quarry, Hannover, and MB.E.8576, <i>conica</i> / <i>pappilosa</i> Zone, lower Campanian, H&ouml;ver.</p>   <p> <b>Derivatio nominis.</b> In honour of the late Gundolf Ernst, who contributed tremendously with his work to the knowledge of the evolution of the genus <i>Micraster</i>.</p>   <p> <b>Stratum typicum.</b> From the <i>conica</i> / <i>pappilosa</i> Zone, lower Campanian.</p>   <p> <b>Locus typicus.</b> The area southeast of Hannover, Lower Saxony, Germany, i.e. the working limestone quarries in Hannover-Misburg, Teutonia Nord and Germania IV, as well as the quarry in H&ouml;ver in the vicinity of Hannover, Lower Saxony, Germany.</p>   <p> <b>Additional material.</b> MB.E:8574, 8575 (ex leg. Duckstein), MB.E.8576, 8578, 8579, MB.E.8580, MB.E.8581&ndash; 8582 from the lower Campanian of H&ouml;ver, vicinity of Hannover, Lower Saxony, Germany.</p>   <p> <b>Description.</b> Cordiform and polygonate (more pronounced in larger specimens) in outline. The test is slightly wider than long (length/width ratio of the tests ranges from 1.00 to 1.07, mean=1.02, n=10). The tests have a somewhat conical lateral profile, rather rounded towards the apex. Specimen MB.E.8583 is clearly more conical in profile, tapering towards the apex. The test is highest approximately a bit posterior from the apical disc which has a slightly elongated outline (Fig. 5B). It is ethmophract, having four gonopores and an enlarged madreporite; the posterior genital plates are not separated by the madreporite (Fig. 5C). The apical disc is in a subcentral position, somewhat anterior to the mid-length of the test, ranging from 34 to 44% of the test length (mean=40%, n=7) from the test length (measured from the anterior edge of ocular plate III).</p>   <p>The little sunken paired petals have conjugate anisopores with outer elongated pores. The perradius of the petals is weakly inflated (see Rowe, 1899; Olszewska-Neijbert, 2007; Fig. 4B) with a shallow granular ridge adapically of the pore pairs. The anterior paired petals have a straight outline and bear 75 pore pairs per column at a length of 64 mm and the posterior petals bear 68 pore pairs per column at the same test length. The outline of the posterior paired petals is straight and only very slightly curved close to the apical disc. The anterior paired petals diverge with an angle of 122&ndash;150&deg; (mean=130&deg;, n=7), whereas the posterior paired petals diverge with an angle of 52&ndash;64&deg; (mean=57&deg;, n=6) (both measured in plan view from photos).</p>  <p>Ambitally, ambulacrum III forms a very shallow anterior notch which leads adorally as a little depressed groove towards the faintly sunken peristome. Aborally, AIII is only very slightly sunken in an adapical direction where it shows conjugate anisopores with slightly more elongated outer pores. The surface of the ambulacrum III is granular and plating sutures are easily visible.</p>  <p>The amphisternous plastron has symmetrical (Fig. 5A) to asymmetrical sternal plates in specimen MB.E.8576 (Fig. 5B); in the latter case, the contact of the sternals to the labrum is convex, rather than concave (Fig. 5B) and their length is 46% of the test length (43&ndash;51%, n=8).</p>  <p>The shape of the labral plate is slender with almost parallel sides (Fig. 5A). The labral plate is relatively short, equal to 10% of the test length (range: 7&ndash;13%, n=8). The tip of the labrum has a prominent smooth rim. The labrum is projecting and covers completely the peristome or in such a way that only a small part of the peristomal opening can be seen from the oral view. The second ambulacral plates (I.a.2 and I.b.2) adjacent to the labrum are relatively long, extending beyond the back of the labrum by about one-third of their length. The peristome is located in a slight depression and is obliquely facing forward. Its anterior margin is at a distance of 17&ndash;23% of the test length to the anterior edge of the test (mean=20%, n=9). Moderately-developed phyllodes comprise 4&ndash;6 enlarged isopores with a prominent interporal knob in ambulacrum II; III and IV, with smaller-sized pore pairs in ambulacrum I and V. Interambulacrum 2 and 3 are disjunct from the peristomal opening. Interambulacrum 1 and 5 on the oral surface are amphiplacous.</p>  <p> The periplastronal ambulacral plates reveal scattered tubercles surrounded by a granular-mammilate surface (Fig. 4D). The upper surface has densely arranged granules with sparse small tubercles. Aligned granules can be seen shortly above the oral surface from the distal ends of the paired petals to the ambitus, resembling parafascioles (<i>sensu</i> N&eacute;raudeau <i>et al.</i>, 1998); such parafascioles can be also found at the lower third of the junction of the interambulacral plates (interradius) in interambulacrum 1 and 4.</p>   <p>The adapical edge of the periproct is 37&ndash;49% of the test height (mean=43%, n=8).</p>  <p>In contrast, no traces of a subanal fasciole were found in any specimen and the posterior face is truncated and almost vertical.</p>  <p> <b>Remarks.</b> <i>Micraster</i> species with a more inflated and conical shape, a low-positioned periproct and subpetaloid anterior ambulacra were traditionally referred to as the subgenus <i>Gibbaster</i> (Gauthier, 1888). Stokes (1975) and Schl&uuml;ter <i>et al.</i> (2023) declined to further subdivide <i>Micraster</i> into <i>Gibbaster</i> and consider <i>Gibbaster</i> to be synonymous with <i>Micraster</i> due to the polyphyletic development in the shape of the test. In addition, the subpetaloid development in ambulacrum III can also occur in specimens which would be commonly addressed as <i>Micraster</i>. Further, Schl&uuml;ter <i>et al.</i> (2023) found that the subpetaloid development in ambulacrum III and the degree of the test inflation can vary dramatically within species from the Santonian of northern Cantabria, Spain. In particular, in <i>Micraster mengaudi</i> (Lambert 1920a) and <i>Micraster quebrada</i>, intraspecific variation ranges from non-petaloid to sub-petaloid in pore pair development in ambulacrum III, and the test shape can range from rather flat to highly inflated.</p>   <p> Regarding the history of the herein-described species, Ernst (1970b) identified several specimens of what he assumed at this time to be an undescribed species of the genus <i>Gibbaster</i>. These were from sandy, glauconitic marls from different localities in southern western Munsterland, Germany and this material was dated ranging from upper Santonian to early lower Campanian. Judging by the architecture of the oral surface (dimension of the labrum, presence of a smooth rim at its tip, position of the peristome) and the polygonate outline, this material is indistinguishable from the specimens described herein. However, the Munsterland material is flatter in the lateral profile. Ernst also mentioned the absence of a subanal fasciole in the Santonian specimens and the presence of a subanal fasciole in the Campanian specimens.</p>   <p> Differences in test height as well as the development of a subanal fasciole may also have been caused by phenotypic plasticity in response to differences in the sediment (Schl&uuml;ter 2016). Nonetheless, these differences are most likely due to intraspecific variations and are insufficient to address both forms as distinct species. Accordingly, <i>Micraster ernsti</i> <b>sp. nov.</b> can likely be dated back to the upper Santonian, as present in the Munsterland; unfortunately, the material described by Ernst from there could not be traced. Other late Santonian and Campanian <i>Micraster</i> species which also show a subpetaloid ambulacrum III, i.e. <i>Micraster gibbus</i> (Lamarck, 1816) <i>Micraster fastigatus</i> (Gauthier, 1887), <i>Micraster stolleyi</i> (Lambert, 1901), have a more conical, inflated test and a low-positioned periproct, similar to <i>Micraster ernsti</i> <b>sp. nov.</b>, can be easily distinguished by the position of their peristome which is closer to the anterior margin, their more projecting labrum and the granular tip of the labrum. Another very distinctive feature is the polygonal-shaped outline of the test in <i>Micraster ernsti</i> <b>sp. nov.</b> However, Kermack (1954) illustrated a specimen from the Santonian (Northfleet, Kent, UK) closely resembling <i>Micraster ernsti</i> <b>sp. nov.</b> in the outline and the position of the peristome that may belong to <i>Micraster ernsti</i> <b>sp. nov.</b> under the name <i>Micraster</i> (<i>Isomicraster</i>) <i>senonensis</i>. <i>Micraster senonensis</i> is undoubtedly a synonym of <i>Micraster gibbus</i> (see Smith &amp; Wright, 2012). The Campanian <i>Micraster gourdoni</i> Cotteau, 1889 from France also has a subpetaloid ambulacrum III, the type specimen has a somewhat polygonal outline but is very different to the herein described species by the peristome close to the anterior margin, the strongly projecting labrum and the longer posterior petals. The late Santonian <i>Micraster quebrada</i> has a similar position of the peristome, however, is significantly different in the non-projecting labrum and downward-facing peristome. The morphological distinctions between <i>Micraster ernsti</i> <b>sp. nov.</b>, the here-discussed species, and few other (contemporary) species, as well as additional details, are consolidated in Table 1.</p>",
                "additional_descriptions": [
                    {
                        "description": "methods",
                        "type": {"id": "methods"},
                        "lang": {"id": "eng"},
                    },
                ],
                "locations": {
                    "features": [
                        {
                            "geometry": {
                                "coordinates": [38.8951, -77.0364],
                                "type": "Point",
                            },
                            "place": "Washington",
                            "description": "Big city",
                        }
                    ]
                },
                "references": [
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
                ],
            },
            "custom_fields": {
                "imprint:imprint": {
                    "isbn": "978-3-16-148410-0",
                    "pages": "15-23",
                    "place": "Whoville",
                    "edition": "23rd",
                }
            },
            "access": {
                "record": "public",
                "files": "restricted",
                "embargo": {
                    "active": True,
                    "until": "2120-10-06",
                    "reason": "espionage",
                },
            },
        },
        "community_uuids": None,
        "record_files": [URL_FILE],
        "validated_record_files": [
            {
                "key": "article.txt",
                "full_path": "article.txt",
                "origin": "local",
                "size": 17,
            },
            {
                "key": S3_FILE_KEY,
                "full_path": S3_FILE,
                "origin": "s3",
                "size": len(S3_CONTENT),
            },
            {
                "key": GS_FILE_KEY,
                "full_path": GS_FILE,
                "origin": "gs",
                "size": len(GS_CONTENT),
            },
            {
                "key": URL_FILE_KEY,
                "full_path": URL_FILE,
                "origin": "url",
                "size": len(URL_CONTENT),
            },
        ],
    }


@pytest.fixture
def validated_ir_data_with_community(validated_ir_data, community):
    """Fixture to create valid importer task data, with community required."""
    validated_ir_data["community_uuids"] = {
        "default": community.id,
        "ids": [community.id],
    }
    return validated_ir_data


def _search_create_indexes(current_search, current_search_client):
    """Create all registered search indexes."""
    to_create = [
        InvenioRDMRecord.index._name,
        RDMDraft.index._name,
        Community.index._name,
        ImporterTask.index._name,
        ImporterRecord.index._name,
    ]
    # list to trigger iter
    list(current_search.create(ignore_existing=True, index_list=to_create))
    current_search_client.indices.refresh()


def _search_delete_indexes(current_search):
    """Delete all registered search indexes."""
    to_delete = [
        InvenioRDMRecord.index._name,
        RDMDraft.index._name,
        Community.index._name,
        ImporterTask.index._name,
        ImporterRecord.index._name,
    ]
    list(current_search.delete(index_list=to_delete))


# overwrite pytest_invenio.fixture to only delete record indices
# keeping vocabularies.
@pytest.fixture()
def search_clear(search):
    """Clear search indices after test finishes (function scope).

    This fixture rollback any changes performed to the indexes during a test,
    in order to leave search in a clean state for the next test.
    """
    from invenio_search import current_search, current_search_client

    yield search
    _search_delete_indexes(current_search)
    _search_create_indexes(current_search, current_search_client)
