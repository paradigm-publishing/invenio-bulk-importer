import os
from io import BytesIO

from invenio_rdm_records.records import RDMRecord

from invenio_bulk_importer.records.api import ImporterRecord, ImporterTask


def _get_importer_task_status(task_id, admin_client, headers) -> tuple[str, dict]:
    """Helper function to get the status of an importer task."""
    # Update task status
    ImporterTask.index.refresh()
    with admin_client.put(
        f"/importer-tasks/{task_id}/status",
        headers=headers,
        json={},
    ) as response:
        assert response.status_code == 200
    with admin_client.get(
        f"/importer-tasks/{task_id}",
        headers=headers,
    ) as response:
        assert response.status_code == 200
        return response.json["status"], response.json["records_status"]


def test_importer_task_with_create(
    running_app,
    db,
    admin_client,
    headers,
    minimal_importer_task,
    location,
    search_clear,
    community,
):
    """Test Importer Task APIs and the flow of creating, validating, and loading records."""
    task_id = None
    valid_record_id = None
    new_record_id = None

    # Get Record types
    with admin_client.get("/importer-tasks/config", headers=headers) as response:
        expected = ["record"]
        assert response.status_code == 200
        assert response.json == expected

    # Get Record Type config.
    with admin_client.get("/importer-tasks/config/record") as response:
        expected = {
            "serializers": ["csv", "onix3"],
            "options": {"doi_minting": False, "publish": True},
        }
        assert response.status_code == 200
        assert response.json == expected

    # Create Importer Task.
    with admin_client.post(
        "/importer-tasks", headers=headers, json=minimal_importer_task
    ) as response:
        assert response.status_code == 201
        task_id = response.json["id"]
        assert response.json["record_type"] == "record"
        assert response.json["serializer"] == "csv"
        assert response.json["status"] == "created"
        assert response.json["options"] == {
            "doi_minting": False,
            "publish": True,
        }

    # Add Metadata File to importer task.
    local_dir = os.path.dirname(__file__)
    file_path = os.path.join(f"{local_dir}/../data", "rdm_records_full.csv")
    # Read the file and create a BytesIO stream
    with open(file_path, "rb") as f:
        # Add metadata file to the importer task
        with admin_client.put(
            f"/importer-tasks/{task_id}/metadata",
            headers={
                **headers,
                "content-type": "application/octet-stream",
                "X-Filename": "rdm_records.csv",
            },
            data=BytesIO(f.read()),
        ) as response:
            assert response.status_code == 200
            assert response.json["size"] == os.path.getsize(file_path)
            assert response.json["mimetype"] == "text/csv"

    # Add Required file.
    res = admin_client.post(
        f"/importer-tasks/{task_id}/files",
        headers=headers,
        json=[
            {"key": "article.txt"},
        ],
    )
    assert res.status_code == 201
    file_entries = res.json["entries"]
    assert len(file_entries) == 2
    assert {(f["key"], f["status"]) for f in file_entries} == {
        ("article.txt", "pending"),
        ("metadata.csv", "completed"),
    }
    # Upload and commit the 1 files
    for f in ["article.txt"]:
        res = admin_client.put(
            f"/importer-tasks/{task_id}/files/{f}/content",
            headers={
                "content-type": "application/octet-stream",
                "accept": "application/json",
            },
            data=BytesIO(b"test content."),
        )
        assert res.status_code == 200
        assert res.json["status"] == "pending"

        res = admin_client.post(
            f"importer-tasks/{task_id}/files/{f}/commit", headers=headers
        )
        assert res.status_code == 200
        assert res.json["status"] == "completed"

    # Read Importer Task
    with admin_client.get(
        f"/importer-tasks/{task_id}",
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.json["status"] == "created"
        assert "records_status" not in response.json

    # Start Validation of csv file
    with admin_client.post(
        f"/importer-tasks/{task_id}/validate",
        headers=headers,
        json={},
    ) as response:
        assert response.status_code == 200

    ImporterTask.index.refresh()
    ImporterRecord.index.refresh()

    # Get Importer Records
    with admin_client.get(
        "/importer-records",
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.json["hits"]["total"] == 3

        for hit in response.json["hits"]["hits"]:
            if hit["status"] == "validated":
                valid_record_id = hit["id"]
    assert valid_record_id is not None, "No validated record found"

    # Check task status is correct after validation
    status, records_status = _get_importer_task_status(task_id, admin_client, headers)
    assert status == "validated", "Task did not complete validation successfully"
    assert records_status == {"validated": 3, "total_records": 3}

    # Trigger Importer Task loading.
    with admin_client.post(
        f"/importer-tasks/{task_id}/load",
        headers=headers,
    ) as response:
        assert response.status_code == 200

    RDMRecord.index.refresh()

    # Check task status is correct after loading records
    status, records_status = _get_importer_task_status(task_id, admin_client, headers)
    assert status == "success", "Task did not complete successfully"
    assert records_status == {"success": 3, "total_records": 3}

    # Check the new records.
    with admin_client.get(
        "/records",
        headers={
            "content-type": "application/json",
            "accept": "application/vnd.inveniordm.v1+json",
        },
    ) as response:
        assert response.status_code == 200
        assert response.json["hits"]["total"] == 3
        for hit in response.json["hits"]["hits"]:
            assert not hit["is_draft"]
            assert hit["is_published"]
            assert hit["versions"]["index"] == 1
            assert hit["status"] == "published"
            assert hit["parent"]["communities"]["entries"][0]["id"] == community.id
            if hit["metadata"]["title"] == "Micraster ernsti Schlüter 2022, sp. feb.":
                assert hit["pids"]["doi"]["provider"] == "external"
            if hit["metadata"]["title"] == "Micraster ernsti Schlüter 2023, sp. mar.":
                assert hit["pids"]["doi"]["provider"] == "datacite"
            if hit["metadata"]["title"] == "Micraster ernsti Schlüter 2024, sp. nov.":
                assert hit["pids"]["doi"]["provider"] == "external"
