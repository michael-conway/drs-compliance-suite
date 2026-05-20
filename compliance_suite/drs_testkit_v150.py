import json
import os
from datetime import datetime
from urllib.parse import urlparse

import requests

from compliance_suite.constants import (
    DRS_ACCESS_SCHEMA,
    DRS_ACCESS_URL,
    DRS_BUNDLE_SCHEMA,
    DRS_OBJECT_INFO_URL,
    DRS_OBJECT_SCHEMA,
)
from compliance_suite.drs_testkit import DrsTestKit


BULK_OBJECTS_URL = "/objects"
BULK_ACCESS_URL = "/objects/access"
OPTIONAL_NOT_SUPPORTED_STATUS_CODES = {204, 405, 501}
ACCEPTED_STATUS_CODES = {202}
MAX_OBJECT_AUTHORIZATION_OPTIONS_REQUESTS = 3
V150_COVERAGE_METADATA_INPUT = "_drs_v150_coverage_metadata"
AUTH_COVERAGE_TYPES = ("basic", "bearer", "passport")
AUTHORIZATION_TYPE_TO_AUTH_TYPE = {
    "BasicAuth": "basic",
    "BearerAuth": "bearer",
    "PassportAuth": "passport",
}
OPTIONAL_CAPABILITY_STATUS_PRIORITY = {
    "Not configured": 0,
    "No sample": 1,
    "Not supported": 2,
    "Supported": 3,
    "Partial": 4,
    "Failed": 5,
}
STANDARD_ACCESS_METHOD_TYPES = {
    "s3",
    "gs",
    "ftp",
    "gsiftp",
    "globus",
    "htsget",
    "https",
    "file",
}


class DrsTestKitV150(DrsTestKit):
    DRS_VERSION = "1.5.0"

    def __init__(self, server_base_url, report_object):
        super().__init__(server_base_url, report_object)
        self.coverage_metadata = self._new_coverage_metadata()

    def run_all_tests(self, config):
        service_info_response = self.call_service_info(
            config.service_info["auth_type"],
            config.service_info["auth_token"],
        )
        self.run_service_info_tests(service_info_response, config.service_info["auth_type"])
        self.run_service_info_semantic_tests(service_info_response)
        self.run_authorization_discovery_tests(config)
        self.run_drs_object_info_tests(config.drs_object_info)
        self.run_drs_object_access_tests(config.drs_object_access)
        self.run_bulk_object_tests(config)
        self.run_bulk_access_tests(config)
        self.run_compound_manifest_tests(config)
        self.run_error_behavior_tests(config)
        self._publish_coverage_metadata()

    def run_service_info_semantic_tests(self, service_info_response):
        phase = self.report_object.add_phase()
        phase.set_phase_name("service info semantics")
        phase.set_phase_description("run DRS 1.5.0-specific checks on service-info")

        test = phase.add_test()
        test.set_test_name("Validate DRS 1.5.0 service-info metadata")
        test.set_test_description("validate DRS service type and bulk capability metadata")

        service_info = self._safe_json(service_info_response)
        service_type = service_info.get("type", {}) if isinstance(service_info, dict) else {}
        drs_metadata = service_info.get("drs", {}) if isinstance(service_info, dict) else {}

        self._add_required_value_case(
            test,
            "service-info type.group",
            "Validate service-info type.group is org.ga4gh",
            service_type.get("group"),
            "org.ga4gh",
        )
        self._add_required_value_case(
            test,
            "service-info type.artifact",
            "Validate service-info type.artifact is drs",
            service_type.get("artifact"),
            "drs",
        )
        self._add_version_case(test, service_type.get("version"))

        max_bulk_length = drs_metadata.get("maxBulkRequestLength") or service_info.get("maxBulkRequestLength")
        if isinstance(max_bulk_length, int) and max_bulk_length >= 1:
            self.add_manual_test_case(
                test,
                "DRS maxBulkRequestLength metadata",
                "Validate service-info advertises a positive maxBulkRequestLength",
                "pass",
                f"maxBulkRequestLength is {max_bulk_length}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS maxBulkRequestLength metadata",
                "Validate service-info advertises a positive maxBulkRequestLength",
                "warn",
                "maxBulkRequestLength was not present as a positive integer; bulk tests will still run when configured",
            )

        test.set_end_time_now()
        phase.set_end_time_now()

    def run_authorization_discovery_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("authorization discovery")
        phase.set_phase_description("run optional DRS 1.5.0 OPTIONS authorization discovery checks")

        for drs_object in config.drs_object_info:
            self.test_object_authorizations(phase, drs_object)

        self.test_bulk_authorizations(phase, config.drs_object_info)
        phase.set_end_time_now()

    def run_drs_object_info_tests(self, drs_object_info):
        phase = self.report_object.add_phase()
        phase.set_phase_name("drs object info")
        phase.set_phase_description("run DRS 1.5.0 tests for drs object info endpoint")

        for drs_object in drs_object_info:
            self.test_v150_drs_object_info(phase, drs_object)

        phase.set_end_time_now()

    def test_v150_drs_object_info(self, phase, drs_object):
        drs_object_id = drs_object["drs_id"]
        auth_type = drs_object["auth_type"]
        auth_token = drs_object["auth_token"]
        is_bundle = drs_object["is_bundle"]
        self._mark_auth_sample(auth_type, "object")

        test = phase.add_test()
        test.set_test_name(
            f"Run DRS 1.5.0 object tests for drs id = {drs_object_id}; auth_type = {auth_type}"
        )
        test.set_test_description("validate DRS object status, schema, required fields, and access methods")

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
        )
        if auth_type == "passport":
            self._record_capability(
                "Passport object POST",
                self._capability_status_from_endpoint_response(response),
                f"/objects/{drs_object_id} returned {response.status_code}",
            )

        if not self._add_200_or_202_status_cases(test, "DRS Object Info", response):
            test.set_end_time_now()
            return

        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            test.set_end_time_now()
            return

        self.add_test_case_common(
            test_object=test,
            case_type="content_type",
            case_name="DRS Object Info response content-type validation",
            case_description="Check if the content-type is application/json",
            response=response,
            expected_content_type="application/json",
        )
        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="DRS Object Info response schema validation",
            case_description="Validate DRS Object Info response schema when status = 200",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_OBJECT_SCHEMA),
        )
        self._add_drs_object_semantic_cases(test, response, is_bundle, drs_object_id)
        self._observe_drs_object_access_method_authorizations(response)

        if is_bundle:
            self._test_expanded_bundle(test, drs_object_id, auth_type, auth_token)

        self.add_access_methods_test_case(
            test_object=test,
            case_type="has_access_methods",
            case_description="Validate that DRS Object Info response has non-empty access_methods for blobs",
            endpoint_name="DRS Object Info",
            response=response,
            skip_access_methods_test_cases=False,
            skip_message="",
            is_bundle=is_bundle,
        )

        self.access_id_map[drs_object_id] = self.add_access_methods_test_case(
            test_object=test,
            case_type="has_access_info",
            case_description="Validate each access_method has at least one of access_url or access_id",
            endpoint_name="DRS Object Info",
            response=response,
            skip_access_methods_test_cases=False,
            skip_message="",
            is_bundle=is_bundle,
        )

        test.set_end_time_now()

    def run_bulk_object_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("bulk drs objects")
        phase.set_phase_description("run optional DRS 1.5.0 bulk object endpoint checks")

        test = phase.add_test()
        test.set_test_name("Run DRS 1.5.0 bulk object tests")
        test.set_test_description("validate POST /objects for configured DRS object IDs")

        if not config.drs_object_info:
            self._record_capability(
                "Bulk object POST",
                "Not configured",
                "No DRS object IDs were configured for deprecated bulk object testing",
                deprecated=True,
            )
            self.add_manual_test_case(
                test,
                "Bulk object request configured",
                "Validate at least one object ID is configured for bulk object testing",
                "warn",
                "No DRS object IDs were configured; skipping optional bulk object endpoint test",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        first_object = config.drs_object_info[0]
        object_ids = [drs_object["drs_id"] for drs_object in config.drs_object_info]
        response = self.send_request(
            self.server_base_url,
            BULK_OBJECTS_URL,
            first_object["auth_type"],
            first_object["auth_token"],
            method="POST",
            request_body={"bulk_object_ids": object_ids},
        )
        self._record_capability(
            "Bulk object POST",
            self._capability_status_from_endpoint_response(response),
            f"POST /objects returned {response.status_code}",
            deprecated=True,
        )

        self._handle_optional_endpoint_response(
            test,
            "Bulk DRS Object",
            response,
            success_schema="bulk_drs_object_response.json",
        )
        test.set_end_time_now()
        phase.set_end_time_now()

    def run_drs_object_access_tests(self, drs_object_access):
        phase = self.report_object.add_phase()
        phase.set_phase_name("drs object access")
        phase.set_phase_description("run DRS 1.5.0 tests for drs access endpoint")

        tested_access_ids = 0
        for drs_object in drs_object_access:
            for access_id in self.access_id_map.get(drs_object["drs_id"], []) or []:
                tested_access_ids += 1
                self.test_v150_drs_object_access(phase, drs_object, access_id)

        if tested_access_ids == 0:
            self._record_capability(
                "Access ID URL resolution",
                "No sample",
                "No access_id values were discovered for /objects/{object_id}/access/{access_id}",
            )
            test = phase.add_test()
            test.set_test_name("Run DRS 1.5.0 access URL tests")
            test.set_test_description("validate /objects/{object_id}/access/{access_id} when access_id is advertised")
            self.add_manual_test_case(
                test,
                "DRS access_id discovery",
                "Validate at least one access_id is available for access endpoint testing",
                "skip",
                "No access_id values were discovered; all configured objects may use direct access_url methods",
            )
            test.set_end_time_now()

        phase.set_end_time_now()

    def test_v150_drs_object_access(self, phase, drs_object, access_id):
        drs_object_id = drs_object["drs_id"]
        auth_type = drs_object["auth_type"]
        auth_token = drs_object["auth_token"]
        self._mark_auth_sample(auth_type, "access")

        test = phase.add_test()
        test.set_test_name(
            f"Run DRS 1.5.0 access URL tests for drs id = {drs_object_id} and access id = {access_id}; "
            f"auth_type = {auth_type}"
        )
        test.set_test_description("validate DRS access URL status, Retry-After behavior, and response schema")

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id + DRS_ACCESS_URL + access_id,
            auth_type,
            auth_token,
        )
        self._record_capability(
            "Access ID URL resolution",
            self._capability_status_from_endpoint_response(response),
            f"/objects/{drs_object_id}/access/{access_id} returned {response.status_code}",
        )
        if auth_type == "passport":
            self._record_capability(
                "Passport access POST",
                self._capability_status_from_endpoint_response(response),
                f"/objects/{drs_object_id}/access/{access_id} returned {response.status_code}",
            )

        if not self._add_200_or_202_status_cases(test, "DRS Access", response):
            test.set_end_time_now()
            return

        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            test.set_end_time_now()
            return

        self.add_test_case_common(
            test_object=test,
            case_type="content_type",
            case_name="DRS Access response content-type validation",
            case_description="Check if the content-type is application/json",
            response=response,
            expected_content_type="application/json",
        )
        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="DRS Access response schema validation",
            case_description="Validate DRS Access response schema when status = 200",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_ACCESS_SCHEMA),
        )
        test.set_end_time_now()

    def run_bulk_access_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("bulk drs access")
        phase.set_phase_description("run optional DRS 1.5.0 bulk access URL endpoint checks")

        test = phase.add_test()
        test.set_test_name("Run DRS 1.5.0 bulk access URL tests")
        test.set_test_description("validate POST /objects/access for discovered access IDs")

        bulk_access_ids = []
        for drs_object in config.drs_object_access:
            access_ids = self.access_id_map.get(drs_object["drs_id"], [])
            if access_ids:
                bulk_access_ids.append({
                    "bulk_object_id": drs_object["drs_id"],
                    "bulk_access_ids": access_ids,
                })

        if not bulk_access_ids:
            self._record_capability(
                "Bulk access POST",
                "No sample",
                "No access_id values were discovered for deprecated bulk access testing",
                deprecated=True,
            )
            self.add_manual_test_case(
                test,
                "Bulk access request configured",
                "Validate at least one access_id is available for bulk access testing",
                "warn",
                "No access_id values were discovered; direct access_url methods do not require /objects/access",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        first_object = config.drs_object_access[0]
        response = self.send_request(
            self.server_base_url,
            BULK_ACCESS_URL,
            first_object["auth_type"],
            first_object["auth_token"],
            method="POST",
            request_body={"bulk_object_access_ids": bulk_access_ids},
        )
        self._record_capability(
            "Bulk access POST",
            self._capability_status_from_endpoint_response(response),
            f"POST /objects/access returned {response.status_code}",
            deprecated=True,
        )

        self._handle_optional_endpoint_response(
            test,
            "Bulk DRS Access",
            response,
            success_schema="bulk_access_url_response.json",
        )
        test.set_end_time_now()
        phase.set_end_time_now()

    def run_compound_manifest_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("compound manifests")
        phase.set_phase_description("retrieve HTTP(S) manifests for configured DRS 1.5.0 compound objects")

        compound_objects = self._configured_compound_objects(config)
        if not compound_objects:
            self._record_capability(
                "Compound manifest retrieval",
                "No sample",
                "No DRS objects were configured with is_compound = true",
            )
            test = phase.add_test()
            test.set_test_name("Run DRS 1.5.0 compound manifest tests")
            test.set_test_description("validate compound manifests when compound objects are configured")
            self.add_manual_test_case(
                test,
                "Compound object configured",
                "Validate at least one compound object is configured for manifest validation",
                "skip",
                "No DRS objects were configured with is_compound = true",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        for drs_object in compound_objects:
            self.test_compound_manifest(phase, drs_object)

        phase.set_end_time_now()

    def run_error_behavior_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("error behavior")
        phase.set_phase_description("run configured DRS 1.5.0 negative tests for documented error responses")

        negative_tests = getattr(config, "negative_tests", {}) or {}
        invalid_drs_ids = self._as_list(negative_tests.get("invalid_drs_ids"))
        invalid_auth = self._as_list(negative_tests.get("invalid_auth"))
        invalid_access_ids = self._as_list(negative_tests.get("invalid_access_ids"))
        malformed_bulk = negative_tests.get("malformed_bulk")

        if not any([invalid_drs_ids, invalid_auth, invalid_access_ids, malformed_bulk]):
            test = phase.add_test()
            test.set_test_name("Run DRS 1.5.0 negative tests")
            test.set_test_description("validate known invalid IDs, invalid auth, and malformed requests")
            self.add_manual_test_case(
                test,
                "Negative test configuration",
                "Validate at least one negative test case is configured",
                "warn",
                "No negative_tests entries were configured; invalid IDs, invalid auth, and malformed request behavior were not exercised",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        for entry in invalid_drs_ids:
            self.test_invalid_drs_object_id(phase, entry)

        for entry in invalid_auth:
            self.test_invalid_auth(phase, entry, config)

        for entry in invalid_access_ids:
            self.test_invalid_access_id(phase, entry, config)

        if malformed_bulk:
            self.test_malformed_bulk_object_request(phase)

        phase.set_end_time_now()

    def test_invalid_drs_object_id(self, phase, entry):
        entry = self._normalize_negative_entry(entry)
        drs_object_id = entry.get("drs_id")
        auth_type = entry.get("auth_type", "none")
        auth_token = entry.get("auth_token", "")
        expected_statuses = self._expected_statuses(entry, {404})

        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 invalid object ID test for drs id = {drs_object_id}")
        test.set_test_description("validate GET /objects/{object_id} returns a documented error for a known invalid ID")

        if not drs_object_id:
            self.add_manual_test_case(
                test,
                "Invalid DRS object ID configured",
                "Validate an invalid DRS object ID is configured for negative testing",
                "warn",
                "Negative test entry did not include drs_id",
            )
            test.set_end_time_now()
            return

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
        )
        self._add_expected_error_response_cases(test, "Invalid DRS Object", response, expected_statuses)
        test.set_end_time_now()

    def test_invalid_auth(self, phase, entry, config):
        entry = self._normalize_negative_entry(entry)
        drs_object_id = entry.get("drs_id") or self._first_configured_drs_id(config)
        auth_type = entry.get("auth_type", "bearer")
        auth_token = entry.get("auth_token", "")
        expected_statuses = self._expected_statuses(entry, {401, 403})

        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 invalid auth test for drs id = {drs_object_id}")
        test.set_test_description("validate GET /objects/{object_id} rejects known invalid credentials")

        if not drs_object_id:
            self.add_manual_test_case(
                test,
                "Invalid auth object configured",
                "Validate an object ID is configured for invalid auth testing",
                "warn",
                "No object ID was available for invalid auth testing",
            )
            test.set_end_time_now()
            return

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
        )
        self._add_expected_error_response_cases(test, "Invalid DRS Auth", response, expected_statuses)
        test.set_end_time_now()

    def test_invalid_access_id(self, phase, entry, config):
        entry = self._normalize_negative_entry(entry)
        drs_object_id = entry.get("drs_id") or self._first_configured_drs_id(config)
        access_id = entry.get("access_id", "__drs_compliance_invalid_access_id__")
        auth_type = entry.get("auth_type", "none")
        auth_token = entry.get("auth_token", "")
        expected_statuses = self._expected_statuses(entry, {404})

        test = phase.add_test()
        test.set_test_name(
            f"Run DRS 1.5.0 invalid access ID test for drs id = {drs_object_id} and access id = {access_id}"
        )
        test.set_test_description(
            "validate GET /objects/{object_id}/access/{access_id} returns a documented error for a known invalid access ID"
        )

        if not drs_object_id:
            self.add_manual_test_case(
                test,
                "Invalid access object configured",
                "Validate an object ID is configured for invalid access testing",
                "warn",
                "No object ID was available for invalid access ID testing",
            )
            test.set_end_time_now()
            return

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id + DRS_ACCESS_URL + access_id,
            auth_type,
            auth_token,
        )
        self._add_expected_error_response_cases(test, "Invalid DRS Access", response, expected_statuses)
        test.set_end_time_now()

    def test_malformed_bulk_object_request(self, phase):
        test = phase.add_test()
        test.set_test_name("Run DRS 1.5.0 malformed bulk object request test")
        test.set_test_description("validate POST /objects returns a documented error for malformed bulk payloads")

        response = self.send_request(
            self.server_base_url,
            BULK_OBJECTS_URL,
            "none",
            "",
            method="POST",
            request_body={"bulk_object_ids": "__not_an_array__"},
        )
        self._add_expected_error_response_cases(
            test,
            "Malformed Bulk DRS Object",
            response,
            {400},
            optional_unsupported_is_warn=True,
        )
        test.set_end_time_now()

    def test_compound_manifest(self, phase, drs_object):
        drs_object_id = drs_object["drs_id"]
        auth_type = drs_object["auth_type"]
        auth_token = drs_object["auth_token"]
        manifest_type = drs_object.get("compound_manifest_type") or "unknown"

        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 compound manifest tests for drs id = {drs_object_id}")
        test.set_test_description("resolve an HTTP(S) access URL and validate the returned compound manifest")

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
        )
        if not self._add_200_or_202_status_cases(test, "Compound DRS Object", response):
            test.set_end_time_now()
            return
        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            test.set_end_time_now()
            return

        drs_object_json = self._safe_json(response)
        if not isinstance(drs_object_json, dict):
            self.add_manual_test_case(
                test,
                "Compound DRS Object JSON body",
                "Validate DRS object response is a JSON object before manifest resolution",
                "fail",
                "DRS object response body was not a JSON object",
            )
            test.set_end_time_now()
            return

        access_url = self._resolve_compound_http_access_url(
            test,
            drs_object_id,
            drs_object_json,
            auth_type,
            auth_token,
        )
        if access_url:
            self._fetch_and_validate_compound_manifest(test, access_url, auth_type, auth_token, manifest_type)

        test.set_end_time_now()

    def _resolve_compound_http_access_url(self, test, drs_object_id, drs_object_json, auth_type, auth_token):
        access_methods = drs_object_json.get("access_methods", []) or []
        for access_method in access_methods:
            access_url = access_method.get("access_url", {})
            url = access_url.get("url")
            if self._is_http_url(url):
                self.add_manual_test_case(
                    test,
                    "Compound HTTP(S) access_url advertised",
                    "Validate compound object advertises a direct HTTP(S) access_url",
                    "pass",
                    f"Found direct HTTP(S) access_url: {url}",
                )
                return access_url

        for access_method in access_methods:
            if access_method.get("type") != "https":
                continue
            access_id = access_method.get("access_id")
            if not access_id:
                continue
            return self._resolve_compound_access_id(test, drs_object_id, access_id, auth_type, auth_token)

        self.add_manual_test_case(
            test,
            "Compound HTTP(S) access method advertised",
            "Validate compound object advertises an HTTP(S) access_url or access_id",
            "warn",
            "No HTTP(S) access_url or access_id was advertised for this compound object",
        )
        self._record_capability(
            "Compound manifest retrieval",
            "Not supported",
            f"Compound object {drs_object_id} did not advertise an HTTP(S) access_url or access_id",
        )
        return None

    def _resolve_compound_access_id(self, test, drs_object_id, access_id, auth_type, auth_token):
        self.add_manual_test_case(
            test,
            "Compound HTTP(S) access_id advertised",
            "Validate compound object access_id can be resolved through /objects/{object_id}/access/{access_id}",
            "pass",
            f"Found access_id: {access_id}",
        )
        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id + DRS_ACCESS_URL + access_id,
            auth_type,
            auth_token,
        )
        if not self._add_200_or_202_status_cases(test, "Compound DRS Access", response):
            self._record_capability(
                "Compound manifest retrieval",
                "Failed",
                f"Compound access_id {access_id} returned {response.status_code}",
            )
            return None
        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            self._record_capability(
                "Compound manifest retrieval",
                "Supported",
                f"Compound access_id {access_id} returned 202 Accepted",
            )
            return None

        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="Compound DRS Access response schema validation",
            case_description="Validate resolved compound DRS Access response schema when status = 200",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_ACCESS_SCHEMA),
        )

        access_url = self._safe_json(response)
        url = access_url.get("url") if isinstance(access_url, dict) else None
        if self._is_http_url(url):
            self.add_manual_test_case(
                test,
                "Resolved compound HTTP(S) access_url",
                "Validate /access returned an HTTP(S) access_url for the compound object",
                "pass",
                f"Resolved HTTP(S) access_url: {url}",
            )
            return access_url

        self.add_manual_test_case(
            test,
            "Resolved compound HTTP(S) access_url",
            "Validate /access returned an HTTP(S) access_url for the compound object",
            "fail",
            f"Resolved access_url was not HTTP(S): {url}",
        )
        self._record_capability(
            "Compound manifest retrieval",
            "Failed",
            f"Resolved access_url was not HTTP(S) for compound object {drs_object_id}: {url}",
        )
        return None

    def _fetch_and_validate_compound_manifest(self, test, access_url, auth_type, auth_token, manifest_type):
        url = access_url.get("url")
        if not self._is_http_url(url):
            self.add_manual_test_case(
                test,
                "Compound HTTP(S) access_url",
                "Validate compound access_url is an HTTP(S) URL before retrieval",
                "fail",
                f"Access URL is not HTTP(S): {url}",
            )
            self._record_capability(
                "Compound manifest retrieval",
                "Failed",
                f"Compound access_url was not HTTP(S): {url}",
            )
            return

        headers = self._access_url_headers(access_url, auth_type, auth_token)
        try:
            response = requests.request("GET", url, headers=headers)
        except requests.RequestException as error:
            self.add_manual_test_case(
                test,
                "Compound HTTP(S) manifest retrieval",
                "Validate the compound HTTP(S) access_url can be retrieved",
                "fail",
                f"Failed retrieving compound manifest: {error}",
            )
            self._record_capability(
                "Compound manifest retrieval",
                "Failed",
                f"Failed retrieving compound manifest from {url}: {error}",
            )
            return

        if 200 <= response.status_code < 300:
            manifest_sample = self._manifest_sample(response, manifest_type)
            self._record_compound_manifest_sample(manifest_type, manifest_sample)
            self._record_capability(
                "Compound manifest retrieval",
                "Supported",
                f"Retrieved {manifest_type} compound manifest from {url} with status code {response.status_code}",
            )
            self.add_manual_test_case(
                test,
                "Compound HTTP(S) manifest retrieval",
                "Validate the compound HTTP(S) access_url can be retrieved",
                "pass",
                f"Retrieved compound manifest with status code {response.status_code}",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound HTTP(S) manifest retrieval",
                "Validate the compound HTTP(S) access_url can be retrieved",
                "fail",
                f"Expected a 2xx response when retrieving compound manifest, got {response.status_code}",
            )
            self._record_capability(
                "Compound manifest retrieval",
                "Failed",
                f"Retrieving compound manifest from {url} returned {response.status_code}",
            )
            return

        self._validate_compound_manifest_payload(test, response, manifest_type)

    def test_object_authorizations(self, phase, drs_object):
        drs_object_id = drs_object["drs_id"]
        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 authorization discovery for drs id = {drs_object_id}")
        test.set_test_description("validate optional OPTIONS /objects/{object_id} authorization metadata")

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            "none",
            "",
            method="OPTIONS",
        )
        self._record_capability(
            "Object authorization OPTIONS",
            self._capability_status_from_authorization_response(response),
            f"OPTIONS /objects/{drs_object_id} returned {response.status_code}",
        )

        self._handle_authorization_response(test, "DRS Object Authorizations", response, "authorizations.json")
        test.set_end_time_now()

    def test_bulk_authorizations(self, phase, drs_object_info):
        test = phase.add_test()
        test.set_test_name("Run DRS 1.5.0 bulk authorization discovery")
        test.set_test_description(
            "validate optional OPTIONS /objects authorization metadata for up to three configured DRS object IDs"
        )

        if not drs_object_info:
            self._record_capability(
                "Bulk authorization OPTIONS",
                "Not configured",
                "No DRS object IDs were configured for OPTIONS /objects",
            )
            self.add_manual_test_case(
                test,
                "Bulk authorization request configured",
                "Validate object IDs are configured for bulk authorization discovery",
                "warn",
                "No DRS object IDs were configured",
            )
            test.set_end_time_now()
            return

        bulk_drs_objects = drs_object_info[:MAX_OBJECT_AUTHORIZATION_OPTIONS_REQUESTS]
        object_ids = [drs_object["drs_id"] for drs_object in bulk_drs_objects]
        response = self.send_request(
            self.server_base_url,
            BULK_OBJECTS_URL,
            "none",
            "",
            method="OPTIONS",
            request_body={"bulk_object_ids": object_ids},
        )
        self._record_capability(
            "Bulk authorization OPTIONS",
            self._capability_status_from_authorization_response(response),
            f"OPTIONS /objects returned {response.status_code} for {len(object_ids)} object IDs",
        )

        self._handle_authorization_response(
            test,
            "Bulk DRS Object Authorizations",
            response,
            "bulk_authorizations_response.json",
        )
        test.set_end_time_now()

    def _handle_authorization_response(self, test, endpoint_name, response, schema_file):
        if response.status_code == 200:
            self._observe_authorization_payload(self._safe_json(response), endpoint_name)
            self.add_manual_test_case(
                test,
                f"{endpoint_name} response status code validation",
                "Validate optional authorization discovery returned metadata",
                "pass",
                "Authorization discovery metadata was returned",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="content_type",
                case_name=f"{endpoint_name} response content-type validation",
                case_description="Check if the content-type is application/json",
                response=response,
                expected_content_type="application/json",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="response_schema",
                case_name=f"{endpoint_name} response schema validation",
                case_description=f"Validate {endpoint_name} response schema when status = 200",
                response=response,
                schema_name=os.path.join(self.schema_dir, schema_file),
            )
        elif response.status_code in OPTIONAL_NOT_SUPPORTED_STATUS_CODES:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} optional support",
                "Validate optional authorization discovery support",
                "warn",
                f"Authorization discovery is not supported; server returned {response.status_code}",
            )
        else:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} response status code validation",
                "Validate authorization discovery status code",
                "fail",
                f"Expected 200 or optional unsupported status, but got {response.status_code}",
            )

    def _handle_optional_endpoint_response(self, test, endpoint_name, response, success_schema):
        if response.status_code == 200:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} response status code validation",
                "Validate optional endpoint returned a successful response",
                "pass",
                "Optional endpoint is implemented and returned 200",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="content_type",
                case_name=f"{endpoint_name} response content-type validation",
                case_description="Check if the content-type is application/json",
                response=response,
                expected_content_type="application/json",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="response_schema",
                case_name=f"{endpoint_name} response schema validation",
                case_description=f"Validate {endpoint_name} response schema when status = 200",
                response=response,
                schema_name=os.path.join(self.schema_dir, success_schema),
            )
        elif response.status_code in ACCEPTED_STATUS_CODES:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} accepted response",
                "Validate delayed optional endpoint response",
                "pass",
                "Server returned 202 Accepted",
            )
            self._add_retry_after_case(test, response)
        elif response.status_code in OPTIONAL_NOT_SUPPORTED_STATUS_CODES:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} optional support",
                "Validate optional endpoint support",
                "warn",
                f"Optional endpoint is not supported; server returned {response.status_code}",
            )
        else:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} response status code validation",
                "Validate optional endpoint status code",
                "fail",
                f"Expected 200, 202, or optional unsupported status, but got {response.status_code}",
            )

    def _add_expected_error_response_cases(
            self,
            test,
            endpoint_name,
            response,
            expected_statuses,
            optional_unsupported_is_warn=False):
        if response.status_code in expected_statuses:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} error status code validation",
                f"Validate response status code is one of {self._format_statuses(expected_statuses)}",
                "pass",
                f"Response status code is {response.status_code}",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="content_type",
                case_name=f"{endpoint_name} error response content-type validation",
                case_description="Check if the content-type is application/json",
                response=response,
                expected_content_type="application/json",
            )
            self.add_test_case_common(
                test_object=test,
                case_type="response_schema",
                case_name=f"{endpoint_name} error response schema validation",
                case_description=f"Validate {endpoint_name} error response schema",
                response=response,
                schema_name=os.path.join(self.schema_dir, "error.json"),
            )
            return

        if optional_unsupported_is_warn and response.status_code in OPTIONAL_NOT_SUPPORTED_STATUS_CODES:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} optional support",
                "Validate optional endpoint support for negative testing",
                "warn",
                f"Optional endpoint is not supported; server returned {response.status_code}",
            )
            return

        self.add_manual_test_case(
            test,
            f"{endpoint_name} error status code validation",
            f"Validate response status code is one of {self._format_statuses(expected_statuses)}",
            "fail",
            f"Expected status code {self._format_statuses(expected_statuses)}, but got {response.status_code}",
        )

    def _test_expanded_bundle(self, test, drs_object_id, auth_type, auth_token):
        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
            expand=True,
        )
        if not self._add_200_or_202_status_cases(test, "DRS Object expand bundle", response):
            self._record_capability(
                "Bundle expand",
                "Failed",
                f"GET /objects/{drs_object_id}?expand=true returned {response.status_code}",
                deprecated=True,
            )
            return
        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            self._record_capability(
                "Bundle expand",
                "Supported",
                f"GET /objects/{drs_object_id}?expand=true returned 202 Accepted",
                deprecated=True,
            )
            return
        self._record_capability(
            "Bundle expand",
            "Supported",
            f"GET /objects/{drs_object_id}?expand=true returned {response.status_code}",
            deprecated=True,
        )
        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="DRS Object expand bundle validation",
            case_description="Validate DRS bundle when expand = True",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_BUNDLE_SCHEMA),
        )
        self._add_bundle_contents_semantic_cases(test, response)

    def _add_drs_object_semantic_cases(self, test, response, is_bundle, expected_drs_object_id):
        drs_object = self._safe_json(response)
        if not isinstance(drs_object, dict):
            self.add_manual_test_case(
                test,
                "DRS Object JSON body",
                "Validate DRS object response is a JSON object",
                "fail",
                "Response body was not a JSON object",
            )
            return

        required_fields = ["id", "self_uri", "size", "created_time", "checksums"]
        missing_fields = [field for field in required_fields if field not in drs_object]
        if missing_fields:
            self.add_manual_test_case(
                test,
                "DRS Object required fields",
                "Validate DRS object includes required DRS 1.5.0 fields",
                "fail",
                f"Missing required fields: {', '.join(missing_fields)}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object required fields",
                "Validate DRS object includes required DRS 1.5.0 fields",
                "pass",
                "DRS object includes required fields",
            )

        actual_drs_object_id = drs_object.get("id")
        if actual_drs_object_id == expected_drs_object_id:
            self.add_manual_test_case(
                test,
                "DRS Object id",
                "Validate returned DRS object id matches requested object_id",
                "pass",
                f"Returned id matches requested object_id {expected_drs_object_id}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object id",
                "Validate returned DRS object id matches requested object_id",
                "fail",
                f"Expected id {expected_drs_object_id}, got {actual_drs_object_id}",
            )

        self_uri = drs_object.get("self_uri", "")
        parsed_self_uri = urlparse(self_uri) if isinstance(self_uri, str) else None
        if parsed_self_uri and parsed_self_uri.scheme == "drs" and parsed_self_uri.netloc:
            self.add_manual_test_case(
                test,
                "DRS Object self_uri",
                "Validate self_uri is a resolvable drs:// URI",
                "pass",
                f"self_uri is {self_uri}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object self_uri",
                "Validate self_uri is a resolvable drs:// URI",
                "fail",
                f"Expected self_uri to be a drs:// URI with a host, got {self_uri}",
            )

        self._add_non_negative_size_case(test, drs_object)
        self._add_rfc3339_time_case(test, drs_object, "created_time")
        if "updated_time" in drs_object:
            self._add_rfc3339_time_case(test, drs_object, "updated_time")
        self._add_checksum_semantic_cases(test, drs_object)

        if is_bundle:
            return

        access_methods = drs_object.get("access_methods", [])
        self._add_alternative_access_method_case(test, access_methods)
        self._add_access_id_uniqueness_case(test, access_methods)
        direct_access_urls = [
            access_method.get("access_url", {}).get("url")
            for access_method in access_methods
            if access_method.get("access_url", {}).get("url")
        ]
        if direct_access_urls:
            self.add_manual_test_case(
                test,
                "DRS Object direct access_url",
                "Validate at least one direct access_url is available when advertised",
                "pass",
                f"Found {len(direct_access_urls)} direct access_url values",
            )

    def _add_alternative_access_method_case(self, test, access_methods):
        alternative_types = sorted({
            access_method.get("type")
            for access_method in access_methods
            if isinstance(access_method, dict)
            and isinstance(access_method.get("type"), str)
            and access_method.get("type") not in STANDARD_ACCESS_METHOD_TYPES
        })
        if alternative_types:
            self.add_manual_test_case(
                test,
                "DRS Object alternative access methods",
                "Record access method types outside the standard DRS set",
                "warn",
                f"Alternative access method types present: {', '.join(alternative_types)}",
            )

    def _add_non_negative_size_case(self, test, drs_object):
        size = drs_object.get("size")
        if isinstance(size, int) and size >= 0:
            self.add_manual_test_case(
                test,
                "DRS Object size",
                "Validate DRS object size is a non-negative integer",
                "pass",
                f"size is {size}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object size",
                "Validate DRS object size is a non-negative integer",
                "fail",
                f"Expected non-negative integer size, got {size}",
            )

    def _add_rfc3339_time_case(self, test, drs_object, field_name):
        timestamp = drs_object.get(field_name)
        if self._is_rfc3339_datetime(timestamp):
            self.add_manual_test_case(
                test,
                f"DRS Object {field_name}",
                f"Validate {field_name} is an RFC3339 timestamp",
                "pass",
                f"{field_name} is {timestamp}",
            )
        else:
            self.add_manual_test_case(
                test,
                f"DRS Object {field_name}",
                f"Validate {field_name} is an RFC3339 timestamp",
                "fail",
                f"Expected RFC3339 timestamp, got {timestamp}",
            )

    def _add_checksum_semantic_cases(self, test, drs_object):
        checksums = drs_object.get("checksums")
        if not isinstance(checksums, list) or not checksums:
            return

        missing_parts = []
        non_hex_values = []
        for index, checksum in enumerate(checksums):
            checksum_type = checksum.get("type") if isinstance(checksum, dict) else None
            checksum_value = checksum.get("checksum") if isinstance(checksum, dict) else None
            if not checksum_type or not checksum_value:
                missing_parts.append(str(index))
            elif not self._is_hex_string(checksum_value):
                non_hex_values.append(str(index))

        if missing_parts:
            self.add_manual_test_case(
                test,
                "DRS Object checksum fields",
                "Validate each checksum includes type and checksum values",
                "fail",
                f"Checksums missing type or checksum at indexes: {', '.join(missing_parts)}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object checksum fields",
                "Validate each checksum includes type and checksum values",
                "pass",
                "Each checksum includes type and checksum values",
            )

        if non_hex_values:
            self.add_manual_test_case(
                test,
                "DRS Object checksum encoding",
                "Validate checksum values are hex strings",
                "warn",
                f"Checksum values were not hex-like at indexes: {', '.join(non_hex_values)}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object checksum encoding",
                "Validate checksum values are hex strings",
                "pass",
                "Checksum values were hex-like",
            )

    def _add_access_id_uniqueness_case(self, test, access_methods):
        access_ids = [
            access_method.get("access_id")
            for access_method in access_methods
            if isinstance(access_method, dict) and access_method.get("access_id")
        ]
        duplicates = sorted({access_id for access_id in access_ids if access_ids.count(access_id) > 1})
        if duplicates:
            self.add_manual_test_case(
                test,
                "DRS Object access_id uniqueness",
                "Validate access_id values are unique within a DRS object",
                "fail",
                f"Duplicate access_id values: {', '.join(duplicates)}",
            )
        elif access_ids:
            self.add_manual_test_case(
                test,
                "DRS Object access_id uniqueness",
                "Validate access_id values are unique within a DRS object",
                "pass",
                "All access_id values were unique",
            )

    def _add_bundle_contents_semantic_cases(self, test, response):
        drs_object = self._safe_json(response)
        contents = drs_object.get("contents") if isinstance(drs_object, dict) else None
        if contents is None:
            self.add_manual_test_case(
                test,
                "DRS Bundle contents",
                "Validate expanded bundle response includes contents",
                "warn",
                "Expanded bundle response did not include contents; bundles are deprecated and contents may be absent",
            )
            return
        if not isinstance(contents, list):
            self.add_manual_test_case(
                test,
                "DRS Bundle contents",
                "Validate expanded bundle contents is an array",
                "fail",
                f"Expected contents array, got {type(contents).__name__}",
            )
            return

        names = [content.get("name") for content in contents if isinstance(content, dict)]
        duplicate_names = sorted({name for name in names if name and names.count(name) > 1})
        if duplicate_names:
            self.add_manual_test_case(
                test,
                "DRS Bundle content names",
                "Validate bundle content names are unique within the bundle",
                "fail",
                f"Duplicate content names: {', '.join(duplicate_names)}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Bundle content names",
                "Validate bundle content names are unique within the bundle",
                "pass",
                "Bundle content names were unique",
            )

    def _add_200_or_202_status_cases(self, test, endpoint_name, response):
        if response.status_code in {200, 202}:
            self.add_manual_test_case(
                test,
                f"{endpoint_name} response status code validation",
                "Validate response status code is 200 or 202",
                "pass",
                f"Response status code is {response.status_code}",
            )
            return True

        self.add_manual_test_case(
            test,
            f"{endpoint_name} response status code validation",
            "Validate response status code is 200 or 202",
            "fail",
            f"Expected status code 200 or 202, but got {response.status_code}",
        )
        return False

    def _add_retry_after_case(self, test, response):
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            self.add_manual_test_case(
                test,
                "202 Retry-After header",
                "Validate 202 responses include integer Retry-After header",
                "pass",
                f"Retry-After is {retry_after}",
            )
        else:
            self.add_manual_test_case(
                test,
                "202 Retry-After header",
                "Validate 202 responses include integer Retry-After header",
                "fail",
                f"Expected integer Retry-After header, got {retry_after}",
            )

    def _add_required_value_case(self, test, case_name, case_description, actual_value, expected_value):
        if actual_value == expected_value:
            self.add_manual_test_case(
                test,
                case_name,
                case_description,
                "pass",
                f"{case_name} is {expected_value}",
            )
        else:
            self.add_manual_test_case(
                test,
                case_name,
                case_description,
                "fail",
                f"Expected {expected_value}, got {actual_value}",
            )

    def _add_version_case(self, test, version):
        if version in {"1.5", "1.5.0"}:
            self.add_manual_test_case(
                test,
                "service-info type.version",
                "Validate service-info type.version is DRS 1.5",
                "pass",
                f"type.version is {version}",
            )
        else:
            self.add_manual_test_case(
                test,
                "service-info type.version",
                "Validate service-info type.version is DRS 1.5",
                "fail",
                f"Expected type.version 1.5 or 1.5.0, got {version}",
            )

    @staticmethod
    def _new_coverage_metadata():
        return {
            "version": "1.5.0",
            "notes": [],
            "auth_coverage": {
                auth_type: {
                    "object_requests": False,
                    "access_requests": False,
                    "authorization_metadata": False,
                    "access_method_metadata": False,
                }
                for auth_type in AUTH_COVERAGE_TYPES
            },
            "optional_capabilities": {},
            "compound_manifests": {
                "supported": False,
                "manifest_types": [],
                "sample_manifest_type": "",
                "sample_manifest": "",
                "notes": [],
            },
        }

    def _publish_coverage_metadata(self):
        self._record_missing_coverage_samples()
        self.report_object.add_input_parameter(
            V150_COVERAGE_METADATA_INPUT,
            json.dumps(self.coverage_metadata, sort_keys=True),
        )

    def _record_missing_coverage_samples(self):
        for auth_type, coverage in self.coverage_metadata["auth_coverage"].items():
            if not any(coverage.values()):
                coverage["note"] = f"{auth_type} auth was not encountered in configured requests or DRS metadata"
            elif not coverage["object_requests"] and not coverage["access_requests"]:
                coverage["note"] = f"{auth_type} auth was advertised but no configured sample used it"
            else:
                coverage["note"] = f"{auth_type} auth was encountered"

        if "Passport object POST" not in self.coverage_metadata["optional_capabilities"]:
            self._record_capability(
                "Passport object POST",
                "No sample",
                "No configured DRS object used auth_type passport",
            )
        if "Passport access POST" not in self.coverage_metadata["optional_capabilities"]:
            self._record_capability(
                "Passport access POST",
                "No sample",
                "No configured DRS access sample used auth_type passport with a discovered access_id",
            )
        if "Object authorization OPTIONS" not in self.coverage_metadata["optional_capabilities"]:
            self._record_capability(
                "Object authorization OPTIONS",
                "No sample",
                "No configured DRS object IDs were available for OPTIONS /objects/{object_id}",
            )
        if "Bulk authorization OPTIONS" not in self.coverage_metadata["optional_capabilities"]:
            self._record_capability(
                "Bulk authorization OPTIONS",
                "Not configured",
                "No configured DRS object IDs were available for OPTIONS /objects",
            )
        if "Bundle expand" not in self.coverage_metadata["optional_capabilities"]:
            self._record_capability(
                "Bundle expand",
                "No sample",
                "No configured DRS object was marked is_bundle = true",
                deprecated=True,
            )

    def _mark_auth_sample(self, auth_type, context):
        if auth_type not in self.coverage_metadata["auth_coverage"]:
            return
        if context == "object":
            self.coverage_metadata["auth_coverage"][auth_type]["object_requests"] = True
        elif context == "access":
            self.coverage_metadata["auth_coverage"][auth_type]["access_requests"] = True

    def _observe_authorization_payload(self, payload, endpoint_name):
        authorization_objects = []
        if isinstance(payload, dict) and "resolved_drs_object" in payload:
            authorization_objects = payload.get("resolved_drs_object") or []
        elif isinstance(payload, dict):
            authorization_objects = [payload]

        for authorization in authorization_objects:
            if not isinstance(authorization, dict):
                continue
            for supported_type in authorization.get("supported_types", []) or []:
                auth_type = AUTHORIZATION_TYPE_TO_AUTH_TYPE.get(supported_type)
                if auth_type:
                    self.coverage_metadata["auth_coverage"][auth_type]["authorization_metadata"] = True

            supported_types = authorization.get("supported_types", []) or []
            if "PassportAuth" in supported_types and not authorization.get("passport_auth_issuers"):
                self.coverage_metadata["notes"].append(
                    f"{endpoint_name} advertised PassportAuth without passport_auth_issuers"
                )

    def _observe_drs_object_access_method_authorizations(self, response):
        drs_object = self._safe_json(response)
        if not isinstance(drs_object, dict):
            return

        for access_method in drs_object.get("access_methods", []) or []:
            if not isinstance(access_method, dict):
                continue
            authorizations = access_method.get("authorizations", {}) or {}
            for supported_type in authorizations.get("supported_types", []) or []:
                auth_type = AUTHORIZATION_TYPE_TO_AUTH_TYPE.get(supported_type)
                if auth_type:
                    self.coverage_metadata["auth_coverage"][auth_type]["access_method_metadata"] = True

    def _record_capability(self, capability, status, evidence, deprecated=False):
        capabilities = self.coverage_metadata["optional_capabilities"]
        record = capabilities.setdefault(
            capability,
            {
                "capability": capability,
                "status": status,
                "statuses": [],
                "evidence": [],
                "deprecated": deprecated,
            },
        )
        record["deprecated"] = record.get("deprecated", False) or deprecated
        record["statuses"].append(status)
        if evidence:
            record["evidence"].append(evidence)
        record["status"] = self._aggregate_capability_status(record["statuses"])

    @staticmethod
    def _aggregate_capability_status(statuses):
        status_set = set(statuses)
        if "Failed" in status_set:
            return "Failed"
        if "Supported" in status_set and "Not supported" in status_set:
            return "Partial"
        return max(
            statuses,
            key=lambda status: OPTIONAL_CAPABILITY_STATUS_PRIORITY.get(status, -1),
        )

    @staticmethod
    def _capability_status_from_authorization_response(response):
        if response.status_code == 200:
            return "Supported"
        if response.status_code in OPTIONAL_NOT_SUPPORTED_STATUS_CODES:
            return "Not supported"
        return "Failed"

    @staticmethod
    def _capability_status_from_endpoint_response(response):
        if response.status_code in {200, 202}:
            return "Supported"
        if response.status_code in OPTIONAL_NOT_SUPPORTED_STATUS_CODES:
            return "Not supported"
        return "Failed"

    def _record_compound_manifest_sample(self, manifest_type, manifest_sample):
        compound_coverage = self.coverage_metadata["compound_manifests"]
        compound_coverage["supported"] = True
        normalized_manifest_type = str(manifest_type).lower()
        if normalized_manifest_type not in compound_coverage["manifest_types"]:
            compound_coverage["manifest_types"].append(normalized_manifest_type)
        if manifest_sample and not compound_coverage["sample_manifest"]:
            compound_coverage["sample_manifest_type"] = normalized_manifest_type
            compound_coverage["sample_manifest"] = manifest_sample

    def _manifest_sample(self, response, manifest_type):
        normalized_manifest_type = str(manifest_type).lower()
        if normalized_manifest_type == "json":
            try:
                sample = json.dumps(response.json(), indent=2, sort_keys=True)
            except ValueError:
                sample = self._response_text(response)
        else:
            sample = self._response_text(response)
        return sample[:4000]

    @staticmethod
    def _is_rfc3339_datetime(value):
        if not isinstance(value, str) or not value:
            return False
        normalized = value.replace("Z", "+00:00")
        try:
            datetime.fromisoformat(normalized)
        except ValueError:
            return False
        return True

    @staticmethod
    def _is_hex_string(value):
        if not isinstance(value, str) or not value:
            return False
        return all(character in "0123456789abcdefABCDEF" for character in value)

    @staticmethod
    def _as_list(value):
        if not value:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _normalize_negative_entry(entry):
        if isinstance(entry, str):
            return {"drs_id": entry}
        if isinstance(entry, dict):
            return entry
        return {}

    @staticmethod
    def _expected_statuses(entry, default_statuses):
        status_value = entry.get("expected_statuses", entry.get("expected_status"))
        if status_value is None:
            return set(default_statuses)
        if isinstance(status_value, list):
            return {int(status) for status in status_value}
        return {int(status_value)}

    @staticmethod
    def _format_statuses(statuses):
        return ", ".join(str(status) for status in sorted(statuses))

    @staticmethod
    def _first_configured_drs_id(config):
        if getattr(config, "drs_object_info", None):
            return config.drs_object_info[0].get("drs_id")
        return None

    @staticmethod
    def _safe_json(response):
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload

    @staticmethod
    def _configured_compound_objects(config):
        compound_objects = []
        seen_drs_ids = set()
        for candidate_objects in (config.drs_compound_object_info, config.drs_object_info):
            for drs_object in candidate_objects:
                drs_object_id = drs_object.get("drs_id")
                if not drs_object_id or drs_object_id in seen_drs_ids:
                    continue
                if not drs_object.get("is_compound"):
                    continue
                compound_objects.append(drs_object)
                seen_drs_ids.add(drs_object_id)
        return compound_objects

    @staticmethod
    def _is_http_url(url):
        if not isinstance(url, str):
            return False
        return urlparse(url.strip()).scheme.lower() in {"http", "https"}

    @staticmethod
    def _access_url_headers(access_url, auth_type, auth_token):
        headers = {}
        for header in access_url.get("headers", []) or []:
            if ":" not in header:
                continue
            name, value = header.split(":", 1)
            headers[name.strip()] = value.strip()

        if "Authorization" not in headers:
            if auth_type == "basic":
                headers["Authorization"] = f"Basic {auth_token}"
            elif auth_type == "bearer":
                headers["Authorization"] = f"Bearer {auth_token}"
        return headers

    def _validate_compound_manifest_payload(self, test, response, manifest_type):
        normalized_manifest_type = str(manifest_type).lower()
        if normalized_manifest_type == "json":
            self._validate_json_manifest_payload(test, response)
        elif normalized_manifest_type == "yaml":
            self._validate_yaml_manifest_payload(test, response)
        elif normalized_manifest_type == "text":
            self._validate_text_manifest_payload(test, response)
        else:
            self.add_manual_test_case(
                test,
                "Compound manifest type",
                "Validate compound_manifest_type is one of json, yaml, or text",
                "warn",
                f"Unknown compound_manifest_type: {manifest_type}",
            )

    def _validate_json_manifest_payload(self, test, response):
        try:
            manifest = response.json()
        except ValueError:
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound manifest response is valid JSON",
                "fail",
                "Compound manifest payload was not valid JSON",
            )
            return

        if isinstance(manifest, (dict, list)):
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound manifest response is valid JSON",
                "pass",
                "Compound manifest payload was valid JSON",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound manifest response is a JSON object or array",
                "fail",
                "Compound manifest JSON payload was not an object or array",
            )

    def _validate_yaml_manifest_payload(self, test, response):
        manifest_text = self._response_text(response).strip()
        if not manifest_text:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound manifest response is non-empty YAML",
                "fail",
                "Compound manifest YAML payload was empty",
            )
            return

        try:
            import yaml
        except ImportError:
            if ":" in manifest_text or manifest_text.startswith("-"):
                self.add_manual_test_case(
                    test,
                    "Compound YAML manifest payload",
                    "Validate compound manifest response has a basic YAML shape",
                    "pass",
                    "Compound manifest payload had a basic YAML shape",
                )
            else:
                self.add_manual_test_case(
                    test,
                    "Compound YAML manifest payload",
                    "Validate compound manifest response has a basic YAML shape",
                    "fail",
                    "Compound manifest payload did not look like YAML",
                )
            return

        try:
            manifest = yaml.safe_load(manifest_text)
        except yaml.YAMLError as error:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound manifest response is valid YAML",
                "fail",
                f"Compound manifest payload was not valid YAML: {error}",
            )
            return

        if manifest is None:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound manifest response is non-empty YAML",
                "fail",
                "Compound manifest YAML payload was empty",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound manifest response is valid YAML",
                "pass",
                "Compound manifest payload was valid YAML",
            )

    def _validate_text_manifest_payload(self, test, response):
        if self._response_text(response).strip():
            self.add_manual_test_case(
                test,
                "Compound text manifest payload",
                "Validate compound manifest response is non-empty text",
                "pass",
                "Compound manifest payload was non-empty text",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound text manifest payload",
                "Validate compound manifest response is non-empty text",
                "fail",
                "Compound manifest text payload was empty",
            )

    @staticmethod
    def _response_text(response):
        if hasattr(response, "text"):
            return response.text
        content = getattr(response, "content", b"")
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)
