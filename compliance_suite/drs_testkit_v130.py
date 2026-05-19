from compliance_suite.drs_testkit import DrsTestKit


class DrsTestKitV130(DrsTestKit):
    DRS_VERSION = "1.3.0"

    def run_all_tests(self, config):
        service_info_response = self.call_service_info(
            config.service_info["auth_type"],
            config.service_info["auth_token"],
        )
        self.run_service_info_tests(service_info_response, config.service_info["auth_type"])
        self.run_drs_object_info_tests(config.drs_object_info)
        self.run_drs_object_access_tests(config.drs_object_access)
