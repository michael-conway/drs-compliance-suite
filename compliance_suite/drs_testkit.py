import json
import os
from dataclasses import dataclass, field

import requests

from compliance_suite.constants import *
from compliance_suite.validate_drs_object_response import ValidateDRSObjectResponse
from compliance_suite.validate_response import ValidateResponse


SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")


@dataclass
class DrsTestConfig:
    service_info: dict
    drs_object_info: list
    drs_object_access: list
    drs_compound_object_info: list = field(default_factory=list)
    negative_tests: dict = field(default_factory=dict)


@dataclass
class DrsTestRunResult:
    version: str
    report: object
    tests: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    compliance_score: str = "pass"


def load_config_json(config_file):
    """
    Returns the auth details for service-info endpoint and input DRS objects from the config file.
    """
    try:
        with open(os.path.join(config_file), "r") as f:
            config = json.load(f)
            return DrsTestConfig(
                service_info=config["service_info"],
                drs_object_info=config["drs_object_info"],
                drs_object_access=config["drs_object_access"],
                drs_compound_object_info=config.get("drs_compound_object_info", []),
                negative_tests=config.get("negative_tests", {}),
            )
    except Exception as e:
        raise Exception(f"Failed loading JSON config file: {config_file}", e)


class DrsTestKit:
    """
    Base test kit for DRS compliance checks.
    Common request, validation, and report helpers live here. Version-specific subclasses
    implement run_all_tests to define that version's compliance surface.
    """

    DRS_VERSION = None

    def __init__(self, server_base_url, report_object):
        self.server_base_url = server_base_url
        self.report_object = report_object
        self.access_id_map = {}

    @property
    def schema_dir(self):
        return "v" + self.DRS_VERSION

    @property
    def service_info_schema_dir(self):
        if os.path.exists(os.path.join(SCHEMA_DIR, self.schema_dir, SERVICE_INFO_SCHEMA)):
            return self.schema_dir
        return ""

    def run(self, config):
        self.run_all_tests(config)
        self.report_object.set_end_time_now()
        self.report_object.finalize()
        return self.build_test_run_result()

    def run_all_tests(self, config):
        raise NotImplementedError("DRS testkits must implement run_all_tests")

    def build_test_run_result(self):
        report_json = json.loads(self.report_object.to_json(pretty=True))
        results = report_json.get("summary", {})
        return DrsTestRunResult(
            version=self.DRS_VERSION,
            report=self.report_object,
            tests=self.extract_tests(report_json),
            results=results,
            compliance_score=self.calculate_compliance_score(results),
        )

    @staticmethod
    def extract_tests(report_json):
        tests = []
        for phase in report_json.get("phases", []):
            phase_name = phase.get("phase_name", "")
            for test in phase.get("tests", []):
                tests.append({
                    "phase": phase_name,
                    "name": test.get("test_name", ""),
                    "status": test.get("status", "UNKNOWN"),
                    "cases": test.get("case", test.get("cases", [])),
                })
        return tests

    @staticmethod
    def calculate_compliance_score(results):
        if results.get("failed", 0) or results.get("unknown", 0):
            return "fail"
        if results.get("warned", 0):
            return "warn"
        return "pass"

    @staticmethod
    def add_manual_test_case(test_object, case_name, case_description, status, message):
        test_case = test_object.add_case()
        test_case.set_case_name(case_name)
        test_case.set_case_description(case_description)

        if status == "pass":
            test_case.set_status_pass()
        elif status == "warn":
            test_case.set_status_warn()
        elif status == "fail":
            test_case.set_status_fail()
        elif status == "skip":
            test_case.set_status_skip()
        else:
            test_case.set_status_unknown()

        test_case.set_message(message)
        test_case.set_end_time_now()
        return test_case

    def call_service_info(self, auth_type, auth_token):
        return self.send_request(
            self.server_base_url,
            SERVICE_INFO_URL,
            auth_type,
            auth_token,
        )

    def run_service_info_tests(self, service_info_response, auth_type):
        service_info_phase = self.report_object.add_phase()
        service_info_phase.set_phase_name("service info")
        service_info_phase.set_phase_description("run all the tests for service_info endpoint")

        service_info_test = service_info_phase.add_test()
        service_info_test.set_test_name(f"Run test cases on the service-info endpoint; auth_type = {auth_type}")
        service_info_test.set_test_description("validate service-info status code, content-type and response schemas")

        self.add_common_test_cases(
            test_object=service_info_test,
            endpoint_name="Service Info",
            response=service_info_response,
            expected_status_code="200",
            expected_content_type="application/json",
            schema_dir=self.service_info_schema_dir,
            schema_file=SERVICE_INFO_SCHEMA,
        )

        service_info_test.set_end_time_now()
        service_info_phase.set_end_time_now()

    def run_drs_object_info_tests(self, drs_object_info):
        drs_object_phase = self.report_object.add_phase()
        drs_object_phase.set_phase_name("drs object info")
        drs_object_phase.set_phase_description("run all the tests for drs object info endpoint")

        for this_drs_object in drs_object_info:
            self.test_drs_object_info(
                drs_object_phase,
                auth_type=this_drs_object["auth_type"],
                auth_token=this_drs_object["auth_token"],
                drs_object_id=this_drs_object["drs_id"],
                is_bundle=this_drs_object["is_bundle"],
                schema_file=DRS_OBJECT_SCHEMA,
                expected_status_code="200",
                expected_content_type="application/json",
            )

        drs_object_phase.set_end_time_now()

    def run_drs_object_access_tests(self, drs_object_access):
        drs_access_phase = self.report_object.add_phase()
        drs_access_phase.set_phase_name("drs object access")
        drs_access_phase.set_phase_description("run all the tests for drs access endpoint")

        for this_drs_object in drs_object_access:
            for this_access_id in self.access_id_map.get(this_drs_object["drs_id"], []):
                self.test_drs_object_access(
                    drs_access_phase,
                    auth_type=this_drs_object["auth_type"],
                    auth_token=this_drs_object["auth_token"],
                    drs_object_id=this_drs_object["drs_id"],
                    drs_access_id=this_access_id,
                    schema_file=DRS_ACCESS_SCHEMA,
                    expected_status_code="200",
                    expected_content_type="application/json",
                )

        drs_access_phase.set_end_time_now()

    def test_drs_object_info(
            self,
            drs_object_phase,
            auth_type,
            auth_token,
            drs_object_id,
            is_bundle,
            schema_file,
            expected_status_code,
            expected_content_type):

        drs_object_test = drs_object_phase.add_test()
        drs_object_test.set_test_name(
            f"Run test cases on the drs object info endpoint for drs id = {drs_object_id}; "
            f"auth_type = {auth_type}"
        )
        drs_object_test.set_test_description("validate drs object status code, content-type and response schemas")
        endpoint_name = "DRS Object Info"

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id,
            auth_type,
            auth_token,
        )

        self.add_common_test_cases(
            test_object=drs_object_test,
            endpoint_name=endpoint_name,
            response=response,
            expected_status_code=expected_status_code,
            expected_content_type=expected_content_type,
            schema_dir=self.schema_dir,
            schema_file=schema_file,
        )

        skip_access_methods_test_cases = False
        skip_message = ""

        if is_bundle:
            response = self.send_request(
                self.server_base_url,
                DRS_OBJECT_INFO_URL + drs_object_id,
                auth_type,
                auth_token,
                expand=True,
            )

            self.add_test_case_common(
                test_object=drs_object_test,
                case_type="response_schema",
                case_name="DRS Access expand bundle validation",
                case_description="Validate DRS bundle when expand = True",
                response=response,
                schema_name=os.path.join(self.schema_dir, DRS_BUNDLE_SCHEMA),
            )

        self.add_access_methods_test_case(
            test_object=drs_object_test,
            case_type="has_access_methods",
            case_description=f"Validate that {endpoint_name} response has access_methods field provided "
                             f"and that it is non-empty",
            endpoint_name=endpoint_name,
            response=response,
            skip_access_methods_test_cases=skip_access_methods_test_cases,
            skip_message=skip_message,
            is_bundle=is_bundle,
        )

        self.access_id_map[drs_object_id] = self.add_access_methods_test_case(
            test_object=drs_object_test,
            case_type="has_access_info",
            case_description=f"Validate that each access_method in the access_methods field of the "
                             f"{endpoint_name} response has atleast one of 'access_url' or 'access_id' provided",
            endpoint_name=endpoint_name,
            response=response,
            skip_access_methods_test_cases=skip_access_methods_test_cases,
            skip_message=skip_message,
            is_bundle=is_bundle,
        )

        drs_object_test.set_end_time_now()

    def test_drs_object_access(
            self,
            drs_access_phase,
            auth_type,
            auth_token,
            drs_object_id,
            drs_access_id,
            schema_file,
            expected_status_code,
            expected_content_type):

        drs_access_test = drs_access_phase.add_test()
        drs_access_test.set_test_name(
            f"Run test cases on the drs access endpoint for drs id = {drs_object_id} "
            f"and access id = {drs_access_id}; auth_type = {auth_type}"
        )
        drs_access_test.set_test_description("validate drs access status code, content-type and response schemas")

        response = self.send_request(
            self.server_base_url,
            DRS_OBJECT_INFO_URL + drs_object_id + DRS_ACCESS_URL + drs_access_id,
            auth_type,
            auth_token,
        )

        self.add_common_test_cases(
            test_object=drs_access_test,
            endpoint_name="DRS Access",
            response=response,
            expected_status_code=expected_status_code,
            expected_content_type=expected_content_type,
            schema_dir=self.schema_dir,
            schema_file=schema_file,
        )

        drs_access_test.set_end_time_now()

    @staticmethod
    def send_request(
            server_base_url,
            endpoint_url,
            auth_type,
            auth_token,
            **kwargs):

        request_body = kwargs.get("request_body", {})
        headers = {}
        http_method = kwargs.get("method", "GET")

        if auth_type == "passport":
            if endpoint_url != SERVICE_INFO_URL:
                request_body["passports"] = auth_token
                if ("expand" in kwargs) and (kwargs["expand"]):
                    request_body["expand"] = True
                http_method = "POST"
        elif auth_type == "basic":
            headers = {"Authorization": "Basic {}".format(auth_token)}
        elif auth_type == "bearer":
            headers = {"Authorization": "Bearer {}".format(auth_token)}
        elif auth_type == "none":
            pass
        else:
            raise ValueError("Invalid auth_type")

        if "expand" in kwargs.keys() and auth_type != "passport":
            params = {"expand": True}
        else:
            params = {}

        url = endpoint_url if endpoint_url.startswith(("http://", "https://")) else server_base_url + endpoint_url

        response = requests.request(
            method=http_method,
            url=url,
            params=params,
            json=request_body,
            headers=headers,
        )

        return response

    @staticmethod
    def add_common_test_cases(
            test_object,
            endpoint_name,
            response,
            expected_status_code,
            expected_content_type,
            schema_dir,
            schema_file):
        """
        Adds common test cases to a Test object.
        Common test cases:
            1. validate response status_code
            2. validate response content_type
            3. validate response json schema
        """
        status_code_pass = DrsTestKit.add_test_case_common(
            test_object=test_object,
            case_type="status_code",
            case_name=f"{endpoint_name} response status code validation",
            case_description=f"Check if the response status code is {expected_status_code}",
            response=response,
            expected_status_code=expected_status_code,
        )

        DrsTestKit.add_test_case_common(
            test_object=test_object,
            case_type="content_type",
            case_name=f"{endpoint_name} response content-type validation",
            case_description=f"Check if the content-type is {expected_content_type}",
            response=response,
            expected_content_type=expected_content_type,
        )

        DrsTestKit.add_test_case_common(
            test_object=test_object,
            case_type="response_schema",
            case_name=f"{endpoint_name} response schema validation",
            case_description=f"Validate {endpoint_name} response schema when status = {expected_status_code}",
            response=response,
            schema_name=os.path.join(schema_dir, schema_file),
        )

        return status_code_pass

    @staticmethod
    def add_test_case_common(test_object, case_type, **kwargs):
        """
        Adds a common test case to a Test object based on type of the case.
        """
        test_case = test_object.add_case()
        test_case.set_case_name(kwargs["case_name"])
        test_case.set_case_description(kwargs["case_description"])

        validate_response = ValidateResponse()
        validate_response.set_case(test_case)
        validate_response.set_actual_response(kwargs["response"])

        if case_type == "status_code":
            validate_response.validate_status_code(kwargs["expected_status_code"])
        elif case_type == "content_type":
            validate_response.validate_content_type(kwargs["expected_content_type"])
        elif case_type == "response_schema":
            validate_response.set_response_schema_file(kwargs["schema_name"])
            validate_response.validate_response_schema()
        test_case.set_end_time_now()
        if case_type == "status_code":
            return test_case.get_status()

    @staticmethod
    def add_access_methods_test_case(
            test_object,
            case_type,
            case_description,
            endpoint_name,
            response,
            skip_access_methods_test_cases,
            skip_message,
            is_bundle):
        """
        Adds a test case to check if access information is present in the DRS object response.
        DRS v1.2.0 Spec - `access_methods`:
         - Required for single blobs; optional for bundles.
         - At least one of `access_url` and `access_id` must be provided.
        """
        test_case = test_object.add_case()
        test_case.set_case_name(f"{endpoint_name} has access information")
        test_case.set_case_description(case_description)

        validate_drs_response = ValidateDRSObjectResponse()
        validate_drs_response.set_case(test_case)
        validate_drs_response.set_actual_response(response)

        if skip_access_methods_test_cases:
            test_case.set_status_skip()
            test_case.set_message(skip_message)

        access_id_list = None
        if case_type == "has_access_methods":
            if is_bundle:
                test_case.set_status_warn()
                test_case.set_message("access_methods is optional for a DRS Bundle")
            else:
                validate_drs_response.validate_has_access_methods()
        elif case_type == "has_access_info":
            access_id_list = validate_drs_response.validate_has_access_info(is_bundle)
        test_case.set_end_time_now()
        return access_id_list
