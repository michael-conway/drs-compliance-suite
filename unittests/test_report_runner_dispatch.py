import json

import pytest

from compliance_suite import report_runner as report_runner_module
from compliance_suite.drs_testkit import DrsTestKit, DrsTestRunResult
from compliance_suite.drs_testkit_v120 import DrsTestKitV120
from compliance_suite.drs_testkit_v130 import DrsTestKitV130
from compliance_suite.drs_testkit_v150 import DrsTestKitV150
from compliance_suite.report_runner import get_drs_testkit_class


@pytest.mark.parametrize("drs_version,testkit_class", [
    ("1.2.0", DrsTestKitV120),
    ("1.3.0", DrsTestKitV130),
    ("1.5.0", DrsTestKitV150),
])
def test_get_drs_testkit_class_uses_supported_version_matrix(drs_version, testkit_class):
    assert get_drs_testkit_class(drs_version) is testkit_class


def test_get_drs_testkit_class_rejects_unsupported_version():
    with pytest.raises(ValueError, match="Unsupported DRS version '2.0.0'"):
        get_drs_testkit_class("2.0.0")


@pytest.mark.parametrize("results,score", [
    ({"passed": 4, "failed": 0, "warned": 0, "unknown": 0}, "pass"),
    ({"passed": 4, "failed": 0, "warned": 1, "unknown": 0}, "warn"),
    ({"passed": 4, "failed": 1, "warned": 0, "unknown": 0}, "fail"),
    ({"passed": 4, "failed": 0, "warned": 0, "unknown": 1}, "fail"),
])
def test_calculate_compliance_score(results, score):
    assert DrsTestKit.calculate_compliance_score(results) == score


def test_report_runner_dispatches_explicit_version_to_testkit(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "service_info": {
            "auth_type": "none",
            "auth_token": "",
        },
        "drs_object_info": [
            {
                "drs_id": "object-1",
                "auth_type": "none",
                "auth_token": "",
                "is_bundle": False,
            }
        ],
        "drs_object_access": [
            {
                "drs_id": "object-1",
                "auth_type": "none",
                "auth_token": "",
            }
        ],
    }))

    calls = {}

    class FakeDrsTestKit:
        DRS_VERSION = "1.5.0"

        def __init__(self, server_base_url, report_object):
            calls["init"] = (server_base_url, report_object)

        def run(self, config):
            calls["run"] = config
            return DrsTestRunResult(
                version=self.DRS_VERSION,
                report=calls["init"][1],
                tests=[{"name": "fake test"}],
                results={"passed": 1, "failed": 0, "warned": 0},
                compliance_score="pass",
            )

    monkeypatch.setitem(report_runner_module.DRS_TESTKIT_MATRIX, "1.5.0", FakeDrsTestKit)

    result = report_runner_module.report_runner(
        server_base_url="https://drs.example",
        platform_name="example platform",
        platform_description="example description",
        version="1.5.0",
        config_file=str(config_file),
    )

    assert calls["init"][0] == "https://drs.example"
    assert calls["run"].drs_object_info[0]["drs_id"] == "object-1"
    assert calls["run"].drs_object_access[0]["drs_id"] == "object-1"
    assert result.version == "1.5.0"
    assert result.compliance_score == "pass"
    assert result.tests == [{"name": "fake test"}]
