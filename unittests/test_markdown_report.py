import json

from compliance_suite.markdown_report import report_to_markdown


def test_report_to_markdown_renders_summary_and_cases():
    report = {
        "testbed_name": "DRS Compliance Suite",
        "testbed_version": "v0.0.0",
        "platform_name": "Example DRS",
        "platform_description": "Example implementation",
        "status": "FAIL",
        "summary": {
            "passed": 1,
            "failed": 1,
            "warned": 0,
            "skipped": 0,
            "unknown": 0
        },
        "input_parameters": {
            "server_base_url": "https://drs.example.org/ga4gh/drs/v1"
        },
        "phases": [
            {
                "phase_name": "service info",
                "phase_description": "service-info checks",
                "status": "FAIL",
                "summary": {
                    "passed": 1,
                    "failed": 1,
                    "warned": 0,
                    "skipped": 0,
                    "unknown": 0
                },
                "tests": [
                    {
                        "test_name": "GET service-info",
                        "test_description": "validate service-info",
                        "status": "FAIL",
                        "case": [
                            {
                                "case_name": "status_code",
                                "status": "PASS",
                                "message": "Response Status Code is as expected"
                            },
                            {
                                "case_name": "schema",
                                "status": "FAIL",
                                "message": "Required field missing"
                            }
                        ]
                    }
                ]
            }
        ]
    }

    markdown = report_to_markdown(report)

    assert "# DRS Compliance Report" in markdown
    assert "**Overall status:** `FAIL`" in markdown
    assert "- server_base_url: `https://drs.example.org/ga4gh/drs/v1`" in markdown
    assert "| Passed | Failed | Warned | Skipped | Unknown |" in markdown
    assert "| 1 | 1 | 0 | 0 | 0 |" in markdown
    assert "#### GET service-info" in markdown
    assert "| status_code | `PASS` | Response Status Code is as expected |" in markdown
    assert "| schema | `FAIL` | Required field missing |" in markdown


def test_report_to_markdown_renders_v150_coverage_highlights():
    coverage_metadata = {
        "auth_coverage": {
            "basic": {
                "object_requests": True,
                "access_requests": False,
                "authorization_metadata": True,
                "access_method_metadata": False,
                "note": "basic auth was encountered",
            },
            "bearer": {
                "object_requests": False,
                "access_requests": False,
                "authorization_metadata": False,
                "access_method_metadata": False,
                "note": "bearer auth was not encountered",
            },
            "passport": {
                "object_requests": False,
                "access_requests": False,
                "authorization_metadata": False,
                "access_method_metadata": False,
                "note": "passport auth was not encountered",
            },
        },
        "optional_capabilities": {
            "Bulk object POST": {
                "capability": "Bulk object POST",
                "status": "Not supported",
                "evidence": ["POST /objects returned 501"],
                "deprecated": True,
            }
        },
        "compound_manifests": {
            "supported": True,
            "manifest_types": ["json"],
            "sample_manifest_type": "json",
            "sample_manifest": "{\"manifest\": []}",
        },
    }
    report = {
        "summary": {},
        "input_parameters": {
            "server_base_url": "https://drs.example.org/ga4gh/drs/v1",
            "_drs_v150_coverage_metadata": json.dumps(coverage_metadata),
        },
    }

    markdown = report_to_markdown(report)

    assert "## API Coverage Highlights" in markdown
    assert "### Optional Capability Matrix" in markdown
    assert "| Bulk object POST | `Not supported` | POST /objects returned 501<br>Deprecated or optional capability |" in markdown
    assert "### Auth Coverage Matrix" in markdown
    assert "| basic | `yes` | `no` | `yes` | `no` | basic auth was encountered |" in markdown
    assert "### Compound Manifest Support" in markdown
    assert "// Sample compound manifest returned by the DRS server" in markdown
    assert "_drs_v150_coverage_metadata" not in markdown
