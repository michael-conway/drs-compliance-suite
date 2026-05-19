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
