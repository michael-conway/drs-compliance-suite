import json
import os
from urllib.parse import unquote, urlparse

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
SAMPLER_CONFIG_KEYS = {
    "https": "sample_https",
    "file": "sample_file",
    "s3": "sample_s3",
}


class DrsTestKitV150(DrsTestKit):
    DRS_VERSION = "1.5.0"

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
        self.run_access_sampler_tests(config)

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
        self._add_drs_object_semantic_cases(test, response, is_bundle)

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

        self._handle_optional_endpoint_response(
            test,
            "Bulk DRS Access",
            response,
            success_schema="bulk_access_url_response.json",
        )
        test.set_end_time_now()
        phase.set_end_time_now()

    def run_http_access_tests(self, config):
        self.run_access_sampler_tests(config)

    def run_access_sampler_tests(self, config):
        phase = self.report_object.add_phase()
        phase.set_phase_name("access method sampler")
        phase.set_phase_description("sample configured DRS access methods and validate compound manifests")

        sampler_types = self._enabled_sampler_types(config.sampler_config)
        drs_objects = self._configured_sampler_objects(config)

        if not sampler_types:
            test = phase.add_test()
            test.set_test_name("Run DRS 1.5.0 access method sampler")
            test.set_test_description("sample access methods when sampler_config enables one or more schemes")
            self.add_manual_test_case(
                test,
                "Access method sampler configured",
                "Validate sampler_config enables at least one access method sampler",
                "skip",
                "No access method samplers were enabled",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        if not drs_objects:
            test = phase.add_test()
            test.set_test_name("Run DRS 1.5.0 access method sampler")
            test.set_test_description("sample access methods for configured DRS objects")
            self.add_manual_test_case(
                test,
                "Access method sampler object configured",
                "Validate at least one DRS object is configured for access method sampling",
                "warn",
                "No DRS object IDs were configured",
            )
            test.set_end_time_now()
            phase.set_end_time_now()
            return

        for sampler_type in sampler_types:
            self.test_access_sampler(phase, drs_objects, config.sampler_config, sampler_type)

        phase.set_end_time_now()

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

        self._handle_authorization_response(test, "DRS Object Authorizations", response, "authorizations.json")
        test.set_end_time_now()

    def test_bulk_authorizations(self, phase, drs_object_info):
        test = phase.add_test()
        test.set_test_name("Run DRS 1.5.0 bulk authorization discovery")
        test.set_test_description("validate optional OPTIONS /objects authorization metadata")

        if not drs_object_info:
            self.add_manual_test_case(
                test,
                "Bulk authorization request configured",
                "Validate object IDs are configured for bulk authorization discovery",
                "warn",
                "No DRS object IDs were configured",
            )
            test.set_end_time_now()
            return

        object_ids = [drs_object["drs_id"] for drs_object in drs_object_info]
        response = self.send_request(
            self.server_base_url,
            BULK_OBJECTS_URL,
            "none",
            "",
            method="OPTIONS",
            request_body={"bulk_object_ids": object_ids},
        )

        self._handle_authorization_response(
            test,
            "Bulk DRS Object Authorizations",
            response,
            "bulk_authorizations_response.json",
        )
        test.set_end_time_now()

    def test_access_sampler(self, phase, drs_objects, sampler_config, sampler_type):
        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 {sampler_type} access method sampler")
        test.set_test_description(
            f"sample one configured DRS object that advertises a {sampler_type} access method"
        )

        for drs_object in drs_objects:
            drs_object_json = self._fetch_drs_object_for_sampler(test, drs_object)
            if not drs_object_json:
                test.set_end_time_now()
                return

            access_methods = self._matching_access_methods(drs_object_json, sampler_type)
            if not access_methods:
                continue

            self.add_manual_test_case(
                test,
                f"{sampler_type} sampler object selected",
                f"Validate at least one configured DRS object advertises a {sampler_type} access method",
                "pass",
                f"Selected DRS object {drs_object['drs_id']} for {sampler_type} sampling",
            )

            for access_method in access_methods:
                self._sample_access_method(test, drs_object, access_method, sampler_type, sampler_config)
            test.set_end_time_now()
            return

        self.add_manual_test_case(
            test,
            f"{sampler_type} access method advertised",
            f"Validate at least one configured DRS object advertises a {sampler_type} access method",
            "warn",
            f"No configured DRS object advertised a {sampler_type} access method",
        )
        test.set_end_time_now()

    def _fetch_drs_object_for_sampler(self, test, drs_object):
        drs_object_id = drs_object["drs_id"]
        auth_type = drs_object["auth_type"]
        auth_token = drs_object["auth_token"]

        request_kwargs = {"expand": True} if self._should_expand_object(drs_object) else {}
        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
            **request_kwargs,
        )

        if not self._add_200_or_202_status_cases(test, "DRS Object access sampler discovery", response):
            return None

        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            return None

        drs_object_json = self._safe_json(response)
        if not isinstance(drs_object_json, dict):
            self.add_manual_test_case(
                test,
                "DRS Object access sampler discovery JSON",
                "Validate DRS object response is a JSON object before access method resolution",
                "fail",
                "DRS object response body was not a JSON object",
            )
            return None
        return drs_object_json

    def _sample_access_method(self, test, drs_object, access_method, sampler_type, sampler_config):
        drs_object_id = drs_object["drs_id"]
        auth_type = drs_object["auth_type"]
        auth_token = drs_object["auth_token"]
        manifest_type = self._compound_manifest_type(drs_object)
        sampled_access_method = False

        direct_access_url = access_method.get("access_url", {})
        direct_url = direct_access_url.get("url")
        if self._access_url_matches_sampler(direct_url, sampler_type):
            self.add_manual_test_case(
                test,
                f"{sampler_type} access_url advertised",
                f"Validate an advertised access method provides a direct {sampler_type} access_url",
                "pass",
                f"Found direct {sampler_type} access_url: {direct_url}",
            )
            self._sample_access_url(
                test,
                direct_access_url,
                auth_type,
                auth_token,
                manifest_type,
                sampler_type,
                sampler_config,
            )
            sampled_access_method = True

        access_id = access_method.get("access_id")
        if access_id:
            resolved_access_url = self._resolve_access_id_url(
                drs_object_id,
                access_id,
                auth_type,
                auth_token,
                test,
                sampler_type,
            )
            if resolved_access_url:
                self._sample_access_url(
                    test,
                    resolved_access_url,
                    auth_type,
                    auth_token,
                    manifest_type,
                    sampler_type,
                    sampler_config,
                )
            sampled_access_method = True

        if not sampled_access_method:
            self.add_manual_test_case(
                test,
                f"{sampler_type} access method resolution",
                f"Validate selected access method can be sampled as {sampler_type}",
                "warn",
                "Selected access method did not include a matching access_url or access_id",
            )

    def test_http_access_method(self, phase, drs_object):
        test = phase.add_test()
        test.set_test_name(f"Run DRS 1.5.0 HTTP access tests for drs id = {drs_object['drs_id']}")
        test.set_test_description("resolve an advertised HTTP(S) access method and retrieve the referenced data")

        drs_object_json = self._fetch_drs_object_for_sampler(test, drs_object)
        if not drs_object_json:
            test.set_end_time_now()
            return

        access_methods = self._matching_access_methods(drs_object_json, "https")
        if not access_methods:
            self.add_manual_test_case(
                test,
                "HTTP(S) access method advertised",
                "Validate the DRS object advertises a direct HTTP(S) access_url or resolvable access_id",
                "warn",
                "No HTTP(S) access_url or access_id was advertised for this DRS object",
            )
            test.set_end_time_now()
            return

        self._sample_access_method(test, drs_object, access_methods[0], "https", {})
        test.set_end_time_now()

    def _resolve_http_access_url(self, drs_object_id, access_method, auth_type, auth_token, test):
        return self._resolve_access_url(drs_object_id, access_method, auth_type, auth_token, test, "https")

    def _resolve_access_url(self, drs_object_id, access_method, auth_type, auth_token, test, sampler_type):
        direct_access_url = access_method.get("access_url", {})
        direct_url = direct_access_url.get("url")
        if self._access_url_matches_sampler(direct_url, sampler_type):
            self.add_manual_test_case(
                test,
                f"{sampler_type} access_url advertised",
                f"Validate an advertised access method provides a direct {sampler_type} access_url",
                "pass",
                f"Found direct {sampler_type} access_url: {direct_url}",
            )
            return direct_access_url

        access_id = access_method.get("access_id")
        if not access_id:
            self.add_manual_test_case(
                test,
                f"{sampler_type} access method resolution",
                f"Validate selected access method can be resolved to a {sampler_type} access_url",
                "warn",
                "Selected access method did not include access_url or access_id",
            )
            return None

        return self._resolve_access_id_url(drs_object_id, access_id, auth_type, auth_token, test, sampler_type)

    def _resolve_access_id_url(self, drs_object_id, access_id, auth_type, auth_token, test, sampler_type):
        self.add_manual_test_case(
            test,
            f"{sampler_type} access_id advertised",
            "Validate an advertised access method can be resolved through /objects/{object_id}/access/{access_id}",
            "pass",
            f"Found access_id: {access_id}",
        )
        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id + DRS_ACCESS_URL + access_id,
            auth_type,
            auth_token,
        )

        if not self._add_200_or_202_status_cases(test, "DRS Access", response):
            return None

        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            return None

        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="DRS Access response schema validation",
            case_description="Validate resolved DRS Access response schema when status = 200",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_ACCESS_SCHEMA),
        )

        access_url = self._safe_json(response)
        resolved_url = access_url.get("url") if isinstance(access_url, dict) else None
        if self._access_url_matches_sampler(resolved_url, sampler_type):
            self.add_manual_test_case(
                test,
                f"Resolved {sampler_type} access_url",
                f"Validate /access returned a {sampler_type} access_url",
                "pass",
                f"Resolved {sampler_type} access_url: {resolved_url}",
            )
            return access_url

        self.add_manual_test_case(
            test,
            f"Resolved {sampler_type} access_url",
            f"Validate /access returned a {sampler_type} access_url",
            "warn",
            f"Resolved access_url was not usable for {sampler_type}: {resolved_url}",
        )
        return None

    def _sample_access_url(self, test, access_url, auth_type, auth_token, manifest_type, sampler_type, sampler_config):
        if sampler_type == "https":
            self._sample_https_access_url(test, access_url, auth_type, auth_token, manifest_type)
        elif sampler_type == "file":
            self._sample_file_access_url(test, access_url, manifest_type)
        elif sampler_type == "s3":
            self._sample_s3_access_url(test, access_url, manifest_type, sampler_config)
        else:
            self.add_manual_test_case(
                test,
                "Access method sampler type",
                "Validate requested sampler type is supported",
                "warn",
                f"Unknown sampler type: {sampler_type}",
            )

    def _fetch_http_access_url(self, test, access_url, auth_type, auth_token, expect_json_payload):
        manifest_type = "json" if expect_json_payload else None
        self._sample_https_access_url(test, access_url, auth_type, auth_token, manifest_type)

    def _sample_https_access_url(self, test, access_url, auth_type, auth_token, manifest_type):
        url = access_url.get("url")
        if not self._is_http_url(url):
            self.add_manual_test_case(
                test,
                "HTTP(S) access_url",
                "Validate access_url is an HTTP(S) URL before retrieval",
                "warn",
                f"Access URL is not HTTP(S): {url}",
            )
            return

        headers = self._access_url_headers(access_url, auth_type, auth_token)
        response = requests.request("GET", url, headers=headers)
        if 200 <= response.status_code < 300:
            self.add_manual_test_case(
                test,
                "HTTP(S) access_url retrieval",
                "Validate the HTTP(S) access_url can be retrieved",
                "pass",
                f"Retrieved access_url with status code {response.status_code}",
            )
        else:
            self.add_manual_test_case(
                test,
                "HTTP(S) access_url retrieval",
                "Validate the HTTP(S) access_url can be retrieved",
                "fail",
                f"Expected a 2xx response when retrieving access_url, got {response.status_code}",
            )
            return

        if not manifest_type:
            return

        self._validate_compound_manifest_payload(test, response, manifest_type)

    def _sample_file_access_url(self, test, access_url, manifest_type):
        url = access_url.get("url")
        path = self._file_access_path(url)
        if not path:
            self.add_manual_test_case(
                test,
                "file access_url",
                "Validate access_url is a local file URL before retrieval",
                "warn",
                f"Access URL is not a local file URL: {url}",
            )
            return

        try:
            with open(path, "rb") as manifest_file:
                payload = manifest_file.read()
        except OSError as error:
            self.add_manual_test_case(
                test,
                "file access_url retrieval",
                "Validate the local file access_url can be read",
                "fail",
                f"Failed reading file access_url {url}: {error}",
            )
            return

        self.add_manual_test_case(
            test,
            "file access_url retrieval",
            "Validate the local file access_url can be read",
            "pass",
            f"Read file access_url {url}",
        )
        self._validate_compound_manifest_payload(test, payload, manifest_type)

    def _sample_s3_access_url(self, test, access_url, manifest_type, sampler_config):
        url = access_url.get("url")
        parsed_url = urlparse(url or "")
        if parsed_url.scheme != "s3" or not parsed_url.netloc or not parsed_url.path:
            self.add_manual_test_case(
                test,
                "s3 access_url",
                "Validate access_url is an s3:// URL before retrieval",
                "warn",
                f"Access URL is not an s3:// URL: {url}",
            )
            return

        try:
            import boto3
        except ImportError:
            self.add_manual_test_case(
                test,
                "s3 sampler dependency",
                "Validate boto3 is available for S3 access sampling",
                "warn",
                "boto3 is not installed; S3 access_url retrieval was not attempted",
            )
            return

        profile_name = sampler_config.get("sample_s3_profile")
        session_kwargs = {"profile_name": profile_name} if profile_name else {}
        try:
            session = boto3.Session(**session_kwargs)
            s3_client = session.client("s3")
            response = s3_client.get_object(
                Bucket=parsed_url.netloc,
                Key=unquote(parsed_url.path.lstrip("/")),
            )
            payload = response["Body"].read()
        except Exception as error:
            self.add_manual_test_case(
                test,
                "s3 access_url retrieval",
                "Validate the s3 access_url can be retrieved",
                "fail",
                f"Failed retrieving {url}: {error}",
            )
            return
        else:
            self.add_manual_test_case(
                test,
                "s3 access_url retrieval",
                "Validate the s3 access_url can be retrieved",
                "pass",
                f"Retrieved s3 access_url {url}",
            )
        self._validate_compound_manifest_payload(test, payload, manifest_type)

    def _validate_compound_manifest_payload(self, test, payload, manifest_type):
        if not manifest_type:
            return

        normalized_manifest_type = str(manifest_type).lower()
        if normalized_manifest_type == "json":
            self._validate_json_manifest_payload(test, payload)
        elif normalized_manifest_type == "yaml":
            self._validate_yaml_manifest_payload(test, payload)
        elif normalized_manifest_type == "text":
            self._validate_text_manifest_payload(test, payload)
        else:
            self.add_manual_test_case(
                test,
                "Compound manifest type",
                "Validate compound_manifest_type is one of json, yaml, or text",
                "warn",
                f"Unknown compound_manifest_type: {manifest_type}",
            )

    def _validate_json_manifest_payload(self, test, payload):
        try:
            manifest = payload.json() if hasattr(payload, "json") else json.loads(self._payload_text(payload))
        except (TypeError, ValueError):
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound access response is valid JSON",
                "fail",
                "Compound manifest payload was not valid JSON",
            )
            return

        if isinstance(manifest, (dict, list)):
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound access response is valid JSON",
                "pass",
                "Compound manifest payload was valid JSON",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound JSON manifest payload",
                "Validate compound access response is a JSON object or array",
                "fail",
                "Compound manifest JSON payload was not an object or array",
            )

    def _validate_yaml_manifest_payload(self, test, payload):
        manifest_text = self._payload_text(payload).strip()
        if not manifest_text:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound access response is non-empty YAML",
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
                    "Validate compound access response has a basic YAML shape",
                    "pass",
                    "Compound manifest payload had a basic YAML shape",
                )
            else:
                self.add_manual_test_case(
                    test,
                    "Compound YAML manifest payload",
                    "Validate compound access response has a basic YAML shape",
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
                "Validate compound access response is valid YAML",
                "fail",
                f"Compound manifest payload was not valid YAML: {error}",
            )
            return

        if manifest is None:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound access response is non-empty YAML",
                "fail",
                "Compound manifest YAML payload was empty",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound YAML manifest payload",
                "Validate compound access response is valid YAML",
                "pass",
                "Compound manifest payload was valid YAML",
            )

    def _validate_text_manifest_payload(self, test, payload):
        if self._payload_text(payload).strip():
            self.add_manual_test_case(
                test,
                "Compound text manifest payload",
                "Validate compound access response is non-empty text",
                "pass",
                "Compound manifest payload was non-empty text",
            )
        else:
            self.add_manual_test_case(
                test,
                "Compound text manifest payload",
                "Validate compound access response is non-empty text",
                "fail",
                "Compound manifest text payload was empty",
            )

    def _handle_authorization_response(self, test, endpoint_name, response, schema_file):
        if response.status_code == 200:
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

    def _test_expanded_bundle(self, test, drs_object_id, auth_type, auth_token):
        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
            expand=True,
        )
        if not self._add_200_or_202_status_cases(test, "DRS Object expand bundle", response):
            return
        if response.status_code == 202:
            self._add_retry_after_case(test, response)
            return
        self.add_test_case_common(
            test_object=test,
            case_type="response_schema",
            case_name="DRS Object expand bundle validation",
            case_description="Validate DRS bundle when expand = True",
            response=response,
            schema_name=os.path.join(self.schema_dir, DRS_BUNDLE_SCHEMA),
        )

    def _add_drs_object_semantic_cases(self, test, response, is_bundle):
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

        self_uri = drs_object.get("self_uri", "")
        if isinstance(self_uri, str) and self_uri.startswith("drs://"):
            self.add_manual_test_case(
                test,
                "DRS Object self_uri",
                "Validate self_uri is a drs:// URI",
                "pass",
                f"self_uri is {self_uri}",
            )
        else:
            self.add_manual_test_case(
                test,
                "DRS Object self_uri",
                "Validate self_uri is a drs:// URI",
                "fail",
                f"Expected self_uri to start with drs://, got {self_uri}",
            )

        if is_bundle:
            return

        access_methods = drs_object.get("access_methods", [])
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
    def _safe_json(response):
        try:
            payload = response.json()
        except ValueError:
            return {}
        return payload

    @staticmethod
    def _select_http_access_method(drs_object):
        access_methods = drs_object.get("access_methods", [])
        for access_method in access_methods:
            if DrsTestKitV150._is_http_url(access_method.get("access_url", {}).get("url")):
                return access_method
        for access_method in access_methods:
            if access_method.get("access_id"):
                return access_method
        return None

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

    @staticmethod
    def _expects_json_access_payload(drs_object):
        return bool(drs_object.get("is_compound") or drs_object.get("is_bundle"))

    @staticmethod
    def _enabled_sampler_types(sampler_config):
        sampler_config = sampler_config or {}
        return [
            sampler_type
            for sampler_type, config_key in SAMPLER_CONFIG_KEYS.items()
            if sampler_config.get(config_key)
        ]

    @staticmethod
    def _matching_access_methods(drs_object, sampler_type):
        matching_methods = []
        for access_method in drs_object.get("access_methods", []) or []:
            access_url = access_method.get("access_url", {}).get("url")
            access_type = access_method.get("type")
            if access_type == sampler_type or DrsTestKitV150._access_url_matches_sampler(access_url, sampler_type):
                matching_methods.append(access_method)
        return matching_methods

    @staticmethod
    def _should_expand_object(drs_object):
        return bool(drs_object.get("is_compound") or drs_object.get("is_bundle"))

    @staticmethod
    def _compound_manifest_type(drs_object):
        if not drs_object.get("is_compound"):
            return None
        return drs_object.get("compound_manifest_type") or "unknown"

    @staticmethod
    def _configured_sampler_objects(config):
        return DrsTestKitV150._configured_http_access_objects(config)

    @staticmethod
    def _configured_http_access_objects(config):
        drs_objects = []
        seen_drs_ids = set()
        for candidate_objects in (config.drs_compound_object_info, config.drs_object_info):
            for drs_object in candidate_objects:
                drs_object_id = drs_object.get("drs_id")
                if not drs_object_id or drs_object_id in seen_drs_ids:
                    continue
                drs_objects.append(drs_object)
                seen_drs_ids.add(drs_object_id)
        return drs_objects

    @staticmethod
    def _is_http_url(url):
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    @staticmethod
    def _is_file_url(url):
        if not isinstance(url, str):
            return False
        parsed_url = urlparse(url)
        return parsed_url.scheme == "file" or (not parsed_url.scheme and url.startswith("/"))

    @staticmethod
    def _is_s3_url(url):
        return isinstance(url, str) and urlparse(url).scheme == "s3"

    @staticmethod
    def _access_url_matches_sampler(url, sampler_type):
        if sampler_type == "https":
            return DrsTestKitV150._is_http_url(url)
        if sampler_type == "file":
            return DrsTestKitV150._is_file_url(url)
        if sampler_type == "s3":
            return DrsTestKitV150._is_s3_url(url)
        return False

    @staticmethod
    def _file_access_path(url):
        if not isinstance(url, str):
            return None
        parsed_url = urlparse(url)
        if parsed_url.scheme == "file":
            return unquote(parsed_url.path)
        if not parsed_url.scheme and url.startswith("/"):
            return url
        return None

    @staticmethod
    def _payload_text(payload):
        if hasattr(payload, "text"):
            return payload.text
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return str(payload)
