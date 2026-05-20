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
        elif isinstance(self.payload, Exception):
            self.text = ""
        else:
            self.text = str(self.payload)

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


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


def test_authorization_discovery_options_checks_all_configured_objects():
    kit = DrsTestKitV150("https://drs.example", Report())
    config = Mock()
    config.drs_object_info = [
        {"drs_id": f"object-{index}", "auth_type": "none", "auth_token": ""}
        for index in range(5)
    ]

    with patch.object(kit, "test_object_authorizations") as test_object_authorizations, \
            patch.object(kit, "test_bulk_authorizations") as test_bulk_authorizations:
        kit.run_authorization_discovery_tests(config)

    assert [call.args[1]["drs_id"] for call in test_object_authorizations.call_args_list] == [
        "object-0",
        "object-1",
        "object-2",
        "object-3",
        "object-4",
    ]
    test_bulk_authorizations.assert_called_once()


def test_bulk_authorization_options_checks_at_most_three_objects():
    kit = DrsTestKitV150("https://drs.example", Report())
    phase = Mock()
    drs_object_info = [
        {"drs_id": f"object-{index}", "auth_type": "none", "auth_token": ""}
        for index in range(5)
    ]

    with patch.object(
        kit,
        "send_request",
        return_value=MockResponse(200, {"authorizations": {}}),
    ) as send_request, patch.object(kit, "add_test_case_common"):
        kit.test_bulk_authorizations(phase, drs_object_info)

    send_request.assert_called_once_with(
        "https://drs.example",
        "/objects",
        "none",
        "",
        method="OPTIONS",
        request_body={"bulk_object_ids": ["object-0", "object-1", "object-2"]},
    )


def test_authorization_response_records_advertised_auth_types():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    response = MockResponse(200, {
        "supported_types": ["BasicAuth", "BearerAuth", "PassportAuth"],
        "passport_auth_issuers": ["https://issuer.example"],
    })

    with patch.object(kit, "add_test_case_common"):
        kit._handle_authorization_response(test, "DRS Object Authorizations", response, "authorizations.json")

    assert kit.coverage_metadata["auth_coverage"]["basic"]["authorization_metadata"] is True
    assert kit.coverage_metadata["auth_coverage"]["bearer"]["authorization_metadata"] is True
    assert kit.coverage_metadata["auth_coverage"]["passport"]["authorization_metadata"] is True


def test_error_behavior_negative_tests_call_configured_requests():
    kit = DrsTestKitV150("https://drs.example", Report())
    config = Mock()
    config.drs_object_info = [{"drs_id": "object-1"}]
    config.negative_tests = {
        "invalid_drs_ids": [{"drs_id": "missing-object", "expected_status": 404}],
        "invalid_auth": [{"drs_id": "object-1", "auth_type": "bearer", "auth_token": "bad"}],
        "invalid_access_ids": [{"drs_id": "object-1", "access_id": "missing-access"}],
        "malformed_bulk": True,
    }

    with patch.object(
        kit,
        "send_request",
        side_effect=[
            MockResponse(404, {"msg": "missing", "status_code": 404}),
            MockResponse(401, {"msg": "unauthorized", "status_code": 401}),
            MockResponse(404, {"msg": "missing", "status_code": 404}),
            MockResponse(400, {"msg": "bad request", "status_code": 400}),
        ],
    ) as send_request, patch.object(kit, "add_test_case_common"):
        kit.run_error_behavior_tests(config)

    assert send_request.call_args_list[0].args == (
        "https://drs.example",
        "/objects/missing-object",
        "none",
        "",
    )
    assert send_request.call_args_list[1].args == (
        "https://drs.example",
        "/objects/object-1",
        "bearer",
        "bad",
    )
    assert send_request.call_args_list[2].args == (
        "https://drs.example",
        "/objects/object-1/access/missing-access",
        "none",
        "",
    )
    assert send_request.call_args_list[3].kwargs == {
        "method": "POST",
        "request_body": {"bulk_object_ids": "__not_an_array__"},
    }


def test_object_semantic_cases_validate_id_and_access_id_uniqueness():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    response = MockResponse(200, {
        "id": "object-1",
        "self_uri": "drs://drs.example/object-1",
        "size": 10,
        "created_time": "2026-05-20T12:00:00Z",
        "checksums": [{"type": "md5", "checksum": "abcdef"}],
        "access_methods": [
            {"type": "https", "access_id": "https-access"},
            {"type": "https", "access_id": "https-access"},
        ],
    })
    case = test.add_case.return_value

    kit._add_drs_object_semantic_cases(test, response, False, "object-1")

    case.set_status_fail.assert_called()
    assert any(
        call.args[0] == "Duplicate access_id values: https-access"
        for call in case.set_message.call_args_list
    )


def test_configured_compound_objects_selects_only_compound_objects():
    config = Mock()
    config.drs_compound_object_info = [
        {"drs_id": "compound-1", "is_compound": True},
        {"drs_id": "plain-1", "is_compound": False},
    ]
    config.drs_object_info = [
        {"drs_id": "compound-1", "is_compound": True},
        {"drs_id": "compound-2", "is_compound": True},
    ]

    compound_objects = DrsTestKitV150._configured_compound_objects(config)

    assert [drs_object["drs_id"] for drs_object in compound_objects] == ["compound-1", "compound-2"]


def test_access_url_headers_parse_returned_headers_and_fallback_to_bearer():
    assert DrsTestKitV150._access_url_headers(
        {
            "url": "https://data.example/manifest",
            "headers": ["X-DRS-Test: yes"],
        },
        "bearer",
        "token",
    ) == {
        "X-DRS-Test": "yes",
        "Authorization": "Bearer token",
    }


def test_resolve_compound_http_access_url_prefers_direct_http_url():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    access_url = {"url": "http://data.example/manifest"}

    resolved_access_url = kit._resolve_compound_http_access_url(
        test,
        "compound-1",
        {"access_methods": [{"type": "https", "access_url": access_url}]},
        "none",
        "",
    )

    assert resolved_access_url == access_url


def test_resolve_compound_access_id_uses_drs_access_endpoint():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()

    with patch.object(
        kit,
        "send_request",
        return_value=MockResponse(200, {"url": "http://data.example/manifest"}),
    ) as send_request, patch.object(kit, "add_test_case_common"):
        access_url = kit._resolve_compound_access_id(
            test,
            "compound-1",
            "https-access",
            "bearer",
            "token",
        )

    send_request.assert_called_once_with(
        "https://drs.example",
        "/objects/compound-1/access/https-access",
        "bearer",
        "token",
    )
    assert access_url == {"url": "http://data.example/manifest"}


@patch("compliance_suite.drs_testkit_v150.requests.request")
def test_fetch_and_validate_compound_manifest_validates_json_response(request):
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value
    request.return_value = MockResponse(200, {"manifest": []})

    kit._fetch_and_validate_compound_manifest(
        test,
        {"url": "http://data.example/manifest", "headers": ["X-DRS-Test: yes"]},
        "none",
        "",
        "json",
    )

    request.assert_called_once_with(
        "GET",
        "http://data.example/manifest",
        headers={"X-DRS-Test": "yes"},
    )
    assert case.set_status_pass.call_count == 2
    case.set_status_fail.assert_not_called()


@patch("compliance_suite.drs_testkit_v150.requests.request")
def test_fetch_and_validate_compound_manifest_fails_invalid_json(request):
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value
    request.return_value = MockResponse(200, ValueError("not json"))

    kit._fetch_and_validate_compound_manifest(
        test,
        {"url": "https://data.example/manifest"},
        "none",
        "",
        "json",
    )

    case.set_status_fail.assert_called_once()
    case.set_message.assert_called_with("Compound manifest payload was not valid JSON")


def test_validate_text_compound_manifest_requires_non_empty_text():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._validate_compound_manifest_payload(test, MockResponse(200, "root\nchild"), "text")

    case.set_status_pass.assert_called_once()
    case.set_status_fail.assert_not_called()


def test_validate_unknown_compound_manifest_type_warns():
    kit = DrsTestKitV150("https://drs.example", Report())
    test = Mock()
    case = test.add_case.return_value

    kit._validate_compound_manifest_payload(test, MockResponse(200, "manifest"), "xml")

    case.set_status_warn.assert_called_once()
    case.set_message.assert_called_with("Unknown compound_manifest_type: xml")


def test_load_config_json_accepts_optional_compound_object_info(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("""{
      "service_info": {"auth_type": "none", "auth_token": ""},
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
      ],
      "negative_tests": {
        "invalid_drs_ids": ["missing-object"]
      }
    }""")

    config = load_config_json(str(config_file))

    assert config.drs_compound_object_info[0]["drs_id"] == "compound-1"
    assert config.drs_compound_object_info[0]["is_compound"] is True
    assert config.drs_compound_object_info[0]["compound_manifest_type"] == "yaml"
    assert config.negative_tests["invalid_drs_ids"] == ["missing-object"]
