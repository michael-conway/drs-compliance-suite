# drs-compliance-suite
Tests to verify the compliance of an external DRS implementation with the GA4GH Data Repository Service (DRS) specification.

The compliance suite is a client-side test runner. It does not start a built-in DRS server. Start the DRS implementation you want to test first, create a JSON config file describing test object IDs and auth, then run the suite against that external endpoint.

This compliance suite currently supports the following DRS versions and will aim to support more versions of DRS in the future.
* DRS 1.2.0
* DRS 1.3.0
* DRS 1.5.0

## Installations
- [Python 3.10+](https://www.python.org/downloads/) is required to run DRS Compliance Suite natively or using PyPI package.
- [Docker Desktop](https://docs.docker.com/get-docker/) is required to run DRS Compliance Suite using a docker image.
- S3 access sampling uses `boto3`, which is installed by the provided requirements.

## Running DRS Compliance Suite
Basic workflow:
1. Start or identify the external DRS server to test.
2. Create a config file with service-info auth, DRS object IDs, object auth, access endpoint auth, and optional sampler settings.
3. Run the compliance suite with `--server_base_url`, `--version`, `--config_file`, and `--report_path`.
4. Review the generated static Markdown report.

### 1. Natively

Install the packages from requirements.txt
```bash
cd drs-compliance-suite
pip3 install -r requirements.txt
```

Add PYTHONPATH to env variables
```bash
export PYTHONPATH=<absolute path to drs-compliance-suite>
```

Run the compliance suite against an external DRS server
```bash
python3 compliance_suite/report_runner.py --server_base_url "http://localhost:8085/ga4gh/drs/v1" --platform_name "ga4gh starter kit drs" --platform_description "GA4GH reference implementation of DRS specification" --version "1.5.0" --config_file "compliance_suite/config/config_samples/config_basic.json" --report_path "./output/drs_compliance_report.md"
```
Note: This specific command is an example of testing an external DRS deployment running on port 8085. The compliance suite does not start or embed a DRS server.
The compliance suite uses `--version` to choose the version-specific DRS testkit.
When running the compliance suite, configure the command line arguments and config file according to the DRS implementation you're testing.
Please refer to the [Command Line Arguments](#command-line-arguments) section for details on each of these arguments.

### 2. Using PyPI Package

Install the latest version of the `drs-compliance-suite` PyPI package using pip3
```bash
pip3 install drs-compliance-suite --upgrade
```
Run the compliance suite
```bash
drs-compliance-suite --server_base_url "http://localhost:8085/ga4gh/drs/v1" --platform_name "ga4gh starter kit drs" --platform_description "GA4GH reference implementation of DRS specification" --version "1.5.0" --config_file "compliance_suite/config/config_samples/config_basic.json" --report_path "./output/drs_compliance_report.md"
```
Note: This specific command is an example of testing an external DRS deployment running on port 8085. The compliance suite writes a static Markdown report.
The compliance suite uses `--version` to choose the version-specific DRS testkit.
When running the compliance suite, configure the command line arguments and config file according to the DRS implementation you're testing.
Please refer to the [Command Line Arguments](#command-line-arguments) section for details on each of these arguments.

### 3. Using Docker

Pull the latest docker image from dockerhub. 
```bash
docker pull ga4gh/drs-compliance-suite:1.0.3
```
Run the compliance suite using the docker image. Make sure your config file is available at `config/config_drs.json`

```bash
docker run --rm --name drs-compliance-suite -v $(PWD)/output/:/usr/src/app/output/ -v ${PWD}/config/:/usr/src/app/config/ ga4gh/drs-compliance-suite:1.0.3 --server_base_url "http://host.docker.internal:8085/ga4gh/drs/v1" --platform_name "ga4gh starter kit drs" --platform_description "GA4GH reference implementation of DRS specification" --version "1.5.0" --report_path "./output/drs-cs-report.md" --config_file "./config/config_drs.json"
```
Note: 
* To run this docker image on MAC ARM processor, append `--platform linux/x86_64` to the above command.
* This specific command is an example of testing a DRS deployment available from the container at `host.docker.internal:8085`.
When running the compliance suite, configure the command line arguments and config file according to the DRS implementation you're testing.
Please refer to the [Command Line Arguments](#command-line-arguments) section for details on each of these arguments.

### Command Line Arguments
| Command Line Argument | Description | Optional/Required | Default Value |
| --------------------- | ----------- | ----------------- | ------------- |
| --server_base_url | The base URL of the DRS implementation that is being tested by the compliance suite. | Required | N/A |
| --platform_name | The name of the platform hosting the DRS server. | Required | N/A |
| --platform_description | The description of the platform hosting the DRS server. | Required | N/A |
| --version | The DRS specification version to test against. The suite uses this value to dispatch to the matching version-specific testkit. It can be one of the following: "1.2.0", "1.3.0", "1.5.0" | Required | N/A |
| --config_file | The file path of the JSON config file. The config file must contain auth information for service-info endpoint and different DRS objects. Refer to the [config-file](#config-file) section for more details. | Required | N/A |
| --report_path | The path of the output Markdown report file. | Optional | "./output/drs_compliance_report.md" |

#### Config File

The compliance suite is provided with information for testing the DRS server through a user-provided JSON config file. This file includes the following details:
- Authorization information for the service-info endpoint
- DRS Object IDs that are present in the DRS server
- Authorization information for each DRS object and access endpoint
- Whether each DRS object is a bundle, a compound object, or a single blob
- Optional compound manifest format information
- Optional access-method sampler settings

Here's a template for a config file that can be used to configure these details:
```json
{
  "service_info": {
    "auth_type": "basic",
    "auth_token": "dXNlcm5hbWU6cGFzc3dvcmQ="
  },
  "sampler_config": {
    "sample_https": true,
    "sample_s3": true,
    "sample_s3_profile": "profile-name",
    "sample_file": true
  },
  "drs_object_info" : [
    {
      "drs_id": "697907bf-d5bd-433e-aac2-1747f1faf366",
      "auth_type": "none",
      "auth_token": "",
      "is_bundle": false,
      "is_compound": false,
      "compound_manifest_type": "json"
    },
    {
      "drs_id": "0bb9d297-2710-48f6-ab4d-80d5eb0c9eaa",
      "auth_type": "basic",
      "auth_token": "dXNlcm5hbWU6cGFzc3dvcmQ=",
      "is_bundle": false,
      "is_compound": false,
      "compound_manifest_type": "json"
    },
    {
      "drs_id" : "41898242-62a9-4129-9a2c-5a4e8f5f0afb",
      "auth_type": "bearer",
      "auth_token": "secret-bearer-token-1",
      "is_bundle": true,
      "is_compound": false,
      "compound_manifest_type": "json"
    },
    {
      "drs_id" : "a1dd4ae2-8d26-43b0-a199-342b64c7dff6",
      "auth_type": "passport",
      "auth_token": ["43b-passport-a1d"],
      "is_bundle": true,
      "is_compound": true,
      "compound_manifest_type": "json"
    }
  ],
  "drs_object_access" : [
    {
      "drs_id": "697907bf-d5bd-433e-aac2-1747f1faf366",
      "auth_type": "none",
      "auth_token": ""
    },
    {
      "drs_id" : "41898242-62a9-4129-9a2c-5a4e8f5f0afb",
      "auth_type": "bearer",
      "auth_token": "secret-bearer-token-1"
    }
  ]
}
```

Top-level config fields:
- `service_info`: Auth used to call `/service-info`.
- `drs_object_info`: DRS objects to test through `/objects/{object_id}`.
- `drs_object_access`: DRS objects whose discovered `access_id` values should be tested through `/objects/{object_id}/access/{access_id}`.
- `drs_compound_object_info`: Optional additional DRS objects to include in v1.5.0 compound/access sampling. This field has the same object shape as `drs_object_info`.
- `sampler_config`: Optional v1.5.0 sampler controls.

DRS object fields:
- `drs_id`: Object ID used in `/objects/{object_id}`.
- `auth_type`: One of `basic`, `bearer`, `passport`, or `none`.
- `auth_token`: Token value for the configured auth type. For `passport`, use a JSON array of passports. For `none`, use an empty string.
- `is_bundle`: `true` when the object is a DRS bundle.
- `is_compound`: `true` when the object should resolve to a compound manifest through an advertised access method.
- `compound_manifest_type`: Expected compound manifest format. Supported values are `json`, `yaml`, and `text`. Unknown values produce a warning during v1.5.0 sampling.

Sampler config fields:
- `sample_https`: When `true`, v1.5.0 sampling tries one configured object that advertises an `https` access method or HTTP(S) access URL.
- `sample_file`: When `true`, v1.5.0 sampling tries one configured object that advertises a `file` access method or local file URL.
- `sample_s3`: When `true`, v1.5.0 sampling tries one configured object that advertises an `s3` access method or `s3://` URL.
- `sample_s3_profile`: Optional AWS profile name used by `boto3.Session(profile_name=...)` for S3 sampling.

When a sampled access method includes both a direct `access_url` and an `access_id`, the v1.5.0 testkit tries both. When only an `access_id` is present, the testkit resolves it through `/objects/{object_id}/access/{access_id}` and then samples the returned access URL.

For HTTP(S) access URL retrieval, the testkit sends headers listed in the returned `AccessURL.headers`. If no `Authorization` header is present and the configured object auth is `basic` or `bearer`, the configured token is used as a fallback. Passport auth is only used for DRS API calls unless the returned `AccessURL.headers` includes data-access auth headers.

Compound manifest validation is intentionally basic:
- `json`: Payload must parse as JSON and be a JSON object or array.
- `yaml`: Payload must be non-empty and parse as YAML when PyYAML is installed. Without PyYAML, the suite performs a simple shape check.
- `text`: Payload must be non-empty text.

You can find some sample config files [here](./compliance_suite/config/config_samples)

## Unittesting

Run the unittests with coverage
```
pytest --cov=compliance_suite unittests/
```

## Changelog

### v1.0.3
* provide flexibility in providing different auth information for drs object and drs access endpoints
* remove incorrect skip status setting

### v1.0.2
* Reduce the docker image size by using python:3.11-slim-bullseye instead of python:3

### v1.0.1
* Fixed a bug in the docker deployment of DRS Compliance Suite 
* Update README documentation

### v1.0.0
* DRS Compliance Suite for [Data Repository Service v1.2.0](https://ga4gh.github.io/data-repository-service-schemas/preview/release/drs-1.2.0/docs/)

## Maintainers

* GA4GH Tech Team [ga4gh-tech-team@ga4gh.org](mailto:ga4gh-tech-team@ga4gh.org)
