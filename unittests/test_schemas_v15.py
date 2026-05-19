import json
import os

import jsonschema


SCHEMA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "compliance_suite",
    "schemas",
    "v1.5.0"
)


def load_schema(name):
    with open(os.path.join(SCHEMA_DIR, name), "r") as f:
        return json.load(f)


def validate_payload(schema_name, payload):
    schema = load_schema(schema_name)
    resolver = jsonschema.RefResolver(
        base_uri="file://" + os.path.abspath(SCHEMA_DIR) + "/",
        referrer=None
    )
    jsonschema.validate(instance=payload, schema=schema, resolver=resolver)


def test_v15_service_info_schema_accepts_drs_metadata():
    validate_payload("service_info.json", {
        "id": "org.example.drs",
        "name": "Example DRS",
        "type": {
            "artifact": "drs"
        },
        "organization": {
            "name": "Example Organization",
            "url": "https://example.org/"
        },
        "version": "1.5.0",
        "environment": "prod",
        "drs": {
            "maxBulkRequestLength": 1000,
            "objectCount": 10,
            "totalObjectSize": 12345
        }
    })


def test_v15_drs_object_schema_accepts_access_method_metadata():
    validate_payload("drs_object.json", {
        "id": "object-1",
        "name": "object-1.txt",
        "self_uri": "drs://drs.example.org/object-1",
        "size": 12,
        "created_time": "2026-01-01T00:00:00Z",
        "checksums": [
            {
                "type": "md5",
                "checksum": "d41d8cd98f00b204e9800998ecf8427e"
            }
        ],
        "access_methods": [
            {
                "type": "https",
                "access_id": "signed-url",
                "cloud": "aws",
                "region": "us-east-1",
                "available": True,
                "authorizations": {
                    "drs_object_id": "object-1",
                    "supported_types": ["BearerAuth"],
                    "bearer_auth_issuers": ["https://issuer.example.org"]
                }
            }
        ]
    })


def test_v15_access_url_schema_accepts_headers():
    validate_payload("access_url.json", {
        "url": "https://download.example.org/object-1",
        "headers": ["Authorization: Bearer token"]
    })


def test_v15_bulk_response_schema_accepts_resolved_and_unresolved_objects():
    validate_payload("bulk_drs_object_response.json", {
        "summary": {
            "requested": 2,
            "resolved": 1,
            "unresolved": 1
        },
        "unresolved_drs_objects": [
            {
                "error_code": 404,
                "object_ids": ["missing-object"]
            }
        ],
        "resolved_drs_object": [
            {
                "id": "object-1",
                "self_uri": "drs://drs.example.org/object-1",
                "size": 12,
                "created_time": "2026-01-01T00:00:00Z",
                "checksums": [
                    {
                        "type": "md5",
                        "checksum": "d41d8cd98f00b204e9800998ecf8427e"
                    }
                ],
                "access_methods": [
                    {
                        "type": "https",
                        "access_url": {
                            "url": "https://download.example.org/object-1"
                        }
                    }
                ]
            }
        ]
    })


def test_v15_bulk_access_url_response_schema_accepts_access_urls():
    validate_payload("bulk_access_url_response.json", {
        "summary": {
            "requested": 1,
            "resolved": 1,
            "unresolved": 0
        },
        "resolved_drs_object_access_urls": [
            {
                "drs_object_id": "object-1",
                "drs_access_id": "signed-url",
                "url": "https://download.example.org/object-1",
                "headers": ["Authorization: Bearer token"]
            }
        ]
    })
