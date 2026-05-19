import json

from unittest.mock import Mock, patch

from ga4gh.testbed.report.report import Report

from compliance_suite.drs_testkit import load_config_json
from compliance_suite.drs_testkit_v150 import DrsTestKitV150


class MockResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}
        self.headers = headers or {}
        if isinstance(self.payload, (dict, list)):
            self.text = json.dumps(self.payload)
        elif isinstance(self.payload, bytes):
            self.text = self.payload.decode("utf-8", errors="replace")
        elif isinstance(self.payload, Exception):
            self.text = ""
        else:
            self.text = str(self.payload)

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def test_select_http_access_method_prefers_direct_http_url():
    drs_object = {
        "access_methods": [
            {"type": "file", "access_url": {"url": "file:///tmp/object"}},
            {
                "type": "https",
                "access_url": {"url": "https://data.example/object"},
            },
            {"type": "https", "access_id": "https-access"},
        ]
    }

    access_method = DrsTestKitV150._select_http_access_method(drs_object)

    assert access_method["access_url"]["url"] == "https://data.example/object"


def test_select_http_access_method_falls_back_to_access_id():
    drs_object = {
        "access_methods": [
            {"type": "file", "access_url": {"url": "file:///tmp/object"}},
            {"type": "https", "access_id": "https-access"},
        ]
    }

    access_method = DrsTestKitV150._select_http_access_method(drs_object)

    assert access_method["access_id"] == "https-access"


def test_access_url_headers_parse_returned_headers_and_preserve_authorization():
    headers = DrsTestKitV150._access_url_headers(
        {
            "url": "https://data.example/object",
            "headers": [
                "Authorization: Bearer returned-token",
                "X-DRS-Test: yes",
                "malformed",
            ],
        },
        "bearer",
        "configured-token",
    )

    assert headers == {
        "Authorization": "Bearer returned-token",
        "X-DRS-Test": "yes",
    }


def test_access_url_headers_fall_back_to_configured_bearer_token():
    headers = DrsTestKitV150._access_url_headers(
        {"url": "https://data.example/object", "headers": ["X-DRS-Test: yes"]},
        "bearer",
        "configured-token",
    )

    assert headers == {
        "X-DRS-Test": "yes",
        "Authorization": "Bearer configured-token",
    }


def test_enabled_sampler_types_reads_sampler_config():
    assert DrsTestKitV150._enabled_sampler_types({
        "sample_https": True,
        "sample_s3": False,
        "sample_file": True,
    }) == ["https", "file"]


def test_matching_access_methods_uses_type_or_url_scheme():
    drs_object = {
        "access_methods": [
            {"type": "https", "access_id": "https-access"},
            {"type": "file", "access_url": {"url": "file:///tmp/manifest.txt"}},
            {"type": "s3", "access_url": {"url": "s3://bucket/key"}},
        ]
    }

    assert len(DrsTestKitV150._matching_access_methods(drs_object, "https")) == 1
    assert len(DrsTestKitV150._matching_access_methods(drs_object, "file")) == 1
    assert len(DrsTestKitV150._matching_access_methods(drs_object, "s3")) == 1


def test_add_200_or_202_status_cases_passes_for_accepted_response():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    assert kit._add_200_or_202_status_cases(test, "DRS Object Info", MockResponse(202))
    case.set_status_pass.assert_called_once()


def test_retry_after_case_fails_when_header_is_missing():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._add_retry_after_case(test, MockResponse(202))

    case.set_status_fail.assert_called_once()
    case.set_message.assert_called_with("Expected integer Retry-After header, got None")


def test_optional_endpoint_unsupported_response_warns():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._handle_optional_endpoint_response(
        test,
        "Bulk DRS Object",
        MockResponse(501),
        success_schema="bulk_drs_object_response.json",
    )

    case.set_status_warn.assert_called_once()


def test_resolve_http_access_url_uses_access_id_endpoint():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()

    with patch.object(
        kit,
        "send_request",
        return_value=MockResponse(200, {"url": "https://data.example/object"}),
    ) as send_request, patch.object(kit, "add_test_case_common"):
        access_url = kit._resolve_http_access_url(
            "object-1",
            {"type": "https", "access_id": "https-access"},
            "bearer",
            "token",
            test,
        )

    send_request.assert_called_once_with(
        "https://drs.example",
        "/objects/object-1/access/https-access",
        "bearer",
        "token",
    )
    assert access_url == {"url": "https://data.example/object"}


def test_sample_access_method_tries_direct_url_and_access_id():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    drs_object = {
        "drs_id": "object-1",
        "auth_type": "none",
        "auth_token": "",
        "is_compound": False,
    }
    access_method = {
        "type": "https",
        "access_url": {"url": "https://data.example/direct"},
        "access_id": "https-access",
    }

    with patch.object(
        kit,
        "_resolve_access_id_url",
        return_value={"url": "https://data.example/resolved"},
    ) as resolve_access_id_url, patch.object(kit, "_sample_access_url") as sample_access_url:
        kit._sample_access_method(test, drs_object, access_method, "https", {})

    resolve_access_id_url.assert_called_once_with(
        "object-1",
        "https-access",
        "none",
        "",
        test,
        "https",
    )
    assert sample_access_url.call_count == 2


@patch("compliance_suite.drs_testkit_v150.requests.request")
def test_fetch_http_access_url_validates_compound_json_payload(request):
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value
    request.return_value = MockResponse(200, {"manifest": []})

    kit._fetch_http_access_url(
        test,
        {"url": "https://data.example/manifest", "headers": ["X-DRS-Test: yes"]},
        "none",
        "",
        expect_json_payload=True,
    )

    request.assert_called_once_with(
        "GET",
        "https://data.example/manifest",
        headers={"X-DRS-Test": "yes"},
    )
    assert case.set_status_pass.call_count == 2
    case.set_status_fail.assert_not_called()


@patch("compliance_suite.drs_testkit_v150.requests.request")
def test_fetch_http_access_url_fails_when_compound_payload_is_not_json(request):
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value
    request.return_value = MockResponse(200, ValueError("not json"))

    kit._fetch_http_access_url(
        test,
        {"url": "https://data.example/manifest"},
        "none",
        "",
        expect_json_payload=True,
    )

    case.set_status_fail.assert_called_once()
    case.set_message.assert_called_with("Compound manifest payload was not valid JSON")


def test_sample_file_access_url_validates_text_manifest(tmp_path):
    manifest_file = tmp_path / "manifest.txt"
    manifest_file.write_text("root\\n  child")
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._sample_file_access_url(test, {"url": str(manifest_file)}, "text")

    assert case.set_status_pass.call_count == 2
    case.set_status_fail.assert_not_called()


def test_validate_unknown_compound_manifest_type_warns():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._validate_compound_manifest_payload(test, b"manifest", "xml")

    case.set_status_warn.assert_called_once()
    case.set_message.assert_called_with("Unknown compound_manifest_type: xml")


def test_load_config_json_accepts_optional_compound_object_info(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("""{
      "service_info": {"auth_type": "none", "auth_token": ""},
      "sampler_config": {"sample_https": true, "sample_s3": false, "sample_file": true},
      "drs_object_info": [],
      "drs_object_access": [],
      "drs_compound_object_info": [
        {
          "drs_id": "compound-1",
          "auth_type": "none",
          "auth_token": "",
          "is_bundle": true,
          "is_compound": true,
          "compound_manifest_type": "yaml"
        }
      ]
    }""")

    config = load_config_json(str(config_file))

    assert config.drs_compound_object_info[0]["drs_id"] == "compound-1"
    assert config.drs_compound_object_info[0]["is_compound"] is True
    assert config.drs_compound_object_info[0]["compound_manifest_type"] == "yaml"
    assert config.sampler_config["sample_https"] is True
