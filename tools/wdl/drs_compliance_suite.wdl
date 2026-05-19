version 1.0
## It is not complete yet
task createDrsComplianceReport{
    
    input {
        String server_base_url
        String platform_name
        String platform_description
        String version
        File config_file
        String report_path
        String image_version
    }

    command {
        drs-compliance-suite --server_base_url ${server_base_url} --platform_name "${platform_name}" --platform_description "${platform_description}" --version "${version}" --config_file "${config_file}" --report_path "${report_path}"
    }

    output {
        File drs_compliance_report = "${report_path}"
    }

    runtime {
        docker: "ga4gh/drs-compliance-suite:${image_version}"
    }
}

workflow drsComplianceReportWorkflow {

    input {
        String server_base_url
        String platform_name
        String platform_description
        String version
        File config_file
        String report_path
        String image_version
    }

    call createDrsComplianceReport { 
        input: server_base_url=server_base_url, platform_name=platform_name, platform_description=platform_description, version=version, config_file=config_file, report_path=report_path, image_version=image_version
    }
}
