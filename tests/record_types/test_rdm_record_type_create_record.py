import idutils
import pytest
import responses
from invenio_files_rest.models import Bucket, FileInstance, ObjectVersion
from invenio_rdm_records.proxies import current_rdm_records_service
from invenio_rdm_records.records import RDMDraft, RDMRecord
from invenio_rdm_records.records.models import RDMDraftMetadata, RDMRecordMetadata
from invenio_rdm_records.services.errors import ReviewNotFoundError
from invenio_rdm_records.services.pids import providers

from invenio_bulk_importer.proxies import (
    current_importer_tasks_service as tasks_service,
)
from tests.fake_storage import URL_FILE, URL_FILE_KEY


def assert_counts(buckets=0, objs=0, fileinstances=0, drafts=0, records=0):
    """Helper to assert counts of file related tables."""
    assert Bucket.query.count() == buckets
    assert ObjectVersion.query.count() == objs
    assert FileInstance.query.count() == fileinstances
    assert RDMDraftMetadata.query.count() == drafts
    assert RDMRecordMetadata.query.count() == records


def test_publish_record_with_files_into_a_community(
    app, db, user_admin, validated_rdm_record_instance_with_community, search_clear
):
    """Test publishing a record with files into a community."""
    assert_counts(buckets=2, objs=2, fileinstances=2)
    record = validated_rdm_record_instance_with_community.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    assert record
    assert_counts(buckets=4, objs=6, fileinstances=6, drafts=1, records=1)
    all_records = current_rdm_records_service.search(user_admin.identity)
    hit = list(all_records.hits)[0]
    assert hit["id"] == record["id"]
    assert hit["parent"]["communities"]["entries"][0]["slug"] == "test-community"
    assert hit["pids"]["doi"]["provider"] == "external"
    assert hit["is_published"]
    assert not hit["is_draft"]
    assert all_records.total == 1


def test_publish_record_with_files_with_no_community(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance,
    search_clear,
):
    assert app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    set_app_config_fn_scoped({"RDM_COMMUNITY_REQUIRED_TO_PUBLISH": False})
    assert not app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    assert_counts(buckets=1, objs=2, fileinstances=2)
    record = validated_rdm_record_instance.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    assert record
    assert_counts(buckets=3, objs=6, fileinstances=6, drafts=1, records=1)
    all_records = current_rdm_records_service.search(user_admin.identity)
    hit = list(all_records.hits)[0]
    assert hit["id"] == record["id"]
    assert not hit["parent"]["communities"]
    assert hit["is_published"]
    assert not hit["is_draft"]
    assert all_records.total == 1


def test_publish_record_with_no_files_with_no_community(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance_no_files,
    search_clear,
):
    assert app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    set_app_config_fn_scoped({"RDM_COMMUNITY_REQUIRED_TO_PUBLISH": False})
    assert not app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    assert_counts(buckets=1, objs=2, fileinstances=2)
    record = validated_rdm_record_instance_no_files.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    assert record
    assert_counts(buckets=3, objs=2, fileinstances=2, drafts=1, records=1)
    all_records = current_rdm_records_service.search(user_admin.identity)
    hit = list(all_records.hits)[0]
    assert hit["id"] == record["id"]
    assert not hit["parent"]["communities"]
    assert hit["is_published"]
    assert not hit["is_draft"]
    assert all_records.total == 1


def test_publish_record_with_minted_doi(
    app,
    db,
    set_app_config_fn_scoped,
    user_admin,
    validated_rdm_record_instance_no_doi,
    search_clear,
):
    """Test publishing a record with files and a minted DOI."""
    # Set Persisent identifier config to not require datacite minted doi.
    set_app_config_fn_scoped(
        {
            "RDM_PERSISTENT_IDENTIFIERS": {
                "doi": {
                    "providers": ["datacite"],
                    "required": True,
                    "condition": lambda rec: rec.pids.get("doi", {}).get("provider")
                    == "datacite",
                    "label": "Concept DOI",
                    "validator": idutils.is_doi,
                    "normalizer": idutils.normalize_doi,
                    "is_enabled": providers.DataCitePIDProvider.is_enabled,
                },
            }
        }
    )
    # set minting doi to True
    validated_rdm_record_instance_no_doi.options = {
        "doi_minting": True,
        "publish": True,
    }
    assert_counts(buckets=2, objs=2, fileinstances=2)
    record = validated_rdm_record_instance_no_doi.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    assert record
    assert_counts(buckets=4, objs=6, fileinstances=6, drafts=1, records=1)
    all_records = current_rdm_records_service.search(user_admin.identity)
    hit = list(all_records.hits)[0]
    assert hit["id"] == record["id"]
    assert hit["pids"]["doi"]["provider"] == "datacite"
    assert hit["is_published"]
    assert not hit["is_draft"]
    assert all_records.total == 1


def test_publish_record_unpublished_in_community(
    app,
    db,
    user_admin,
    validated_rdm_record_instance_with_community,
    search_clear,
):
    """Test publishing a record with files and a minted DOI."""
    # set publishing to False
    validated_rdm_record_instance_with_community.options = {
        "doi_minting": False,
        "publish": False,
    }
    assert_counts(buckets=2, objs=2, fileinstances=2)
    record = validated_rdm_record_instance_with_community.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    assert record
    assert_counts(buckets=4, objs=6, fileinstances=6, drafts=1, records=0)
    all_records = current_rdm_records_service.search(user_admin.identity)
    assert all_records.total == 0
    review = current_rdm_records_service.review.read(user_admin.identity, record.id)
    ir = validated_rdm_record_instance_with_community._importer_record
    assert review.to_dict()["receiver"]["community"] == ir["community_uuids"]["ids"][0]
    all_drafts = current_rdm_records_service.search_drafts(user_admin.identity)
    hit = list(all_drafts.hits)[0]
    assert hit["id"] == record["id"]
    assert hit["pids"]["doi"]["provider"] == "external"
    assert not hit["is_published"]
    assert hit["is_draft"]
    assert hit["status"] == "draft"
    assert all_drafts.total == 1


def test_publish_record_unpublished_no_community(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance,
    search_clear,
):
    """Test publishing a record with files and a minted DOI."""
    # Set community required to publish to False
    assert app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    set_app_config_fn_scoped({"RDM_COMMUNITY_REQUIRED_TO_PUBLISH": False})
    assert not app.config["RDM_COMMUNITY_REQUIRED_TO_PUBLISH"]
    # set publishing to False
    validated_rdm_record_instance.options = {"doi_minting": False, "publish": False}
    assert_counts(buckets=1, objs=2, fileinstances=2)
    # Create the record
    record = validated_rdm_record_instance.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()
    # Assertions
    assert record
    all_records = current_rdm_records_service.search(user_admin.identity)
    assert all_records.total == 0
    with pytest.raises(ReviewNotFoundError):
        current_rdm_records_service.review.read(user_admin.identity, record.id)
    all_drafts = current_rdm_records_service.search_drafts(user_admin.identity)
    hit = list(all_drafts.hits)[0]
    assert hit["id"] == record["id"]
    assert hit["pids"]["doi"]["provider"] == "external"
    assert not hit["parent"]["communities"]
    assert not hit["is_published"]
    assert hit["is_draft"]
    assert hit["status"] == "draft"
    assert all_drafts.total == 1


def test_failed_file_upload_leaves_nothing_behind(
    app,
    set_app_config_fn_scoped,
    db,
    user_admin,
    validated_rdm_record_instance,
    fake_file_origins,
    search_clear,
):
    """A file failing mid-import must not leave a record without its files.

    The run creates the draft and uploads three of the four files before the
    fourth fails, so this only passes if the whole run is rolled back.
    """
    set_app_config_fn_scoped({"RDM_COMMUNITY_REQUIRED_TO_PUBLISH": False})
    # The remote file goes away between validation and import.
    fake_file_origins.replace(responses.GET, URL_FILE, status=500)

    assert_counts(buckets=1, objs=2, fileinstances=2)
    record = validated_rdm_record_instance.run()
    RDMDraft.index.refresh()
    RDMRecord.index.refresh()

    # Nothing was committed: no draft, no record, no new bucket or files.
    assert_counts(buckets=1, objs=2, fileinstances=2)
    assert current_rdm_records_service.search(user_admin.identity).total == 0
    assert current_rdm_records_service.search_drafts(user_admin.identity).total == 0

    # The failure is reported once, against the file that actually failed.
    assert record is None
    assert validated_rdm_record_instance.is_successful is False
    (error,) = validated_rdm_record_instance.errors
    assert error["type"] == "file_add_error"
    assert error["loc"] == "files"
    assert error["msg"].startswith(f"Error uploading and commiting '{URL_FILE_KEY}'")
