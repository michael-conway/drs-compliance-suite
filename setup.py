import setuptools
from compliance_suite.supported_drs_versions import SUPPORTED_DRS_VERSIONS
with open("README.md", "r") as fh:
    long_description = fh.read()


setuptools.setup(
    name="drs-compliance-suite",
    version="1.0.5",
    author="Yash Puligundla",
    author_email="yasasvini.puligundla@ga4gh.org",
    packages=["compliance_suite"],
    package_data={'compliance_suite': ['config/*', 'config/config_samples/*', 'schemas/*', 'schemas/v1.2.0/*', 'schemas/v1.3.0/*', 'schemas/v1.5.0/*']},
    description="A compliance utility reporting system for GA4GH DRS server implementations. "
                "Supports GA4GH DRS versions - " + ",".join(SUPPORTED_DRS_VERSIONS),
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ga4gh/drs-compliance-suite",
    license='MIT',
    python_requires='>=3.10',
    install_requires=['python-json-logger==4.1.0',
                      'structlog==25.5.0',
                      'requests==2.34.2',
                      'jsonschema==4.26.0',
                      'referencing==0.37.0',
                      'ga4gh-testbed-lib==0.2.2'],
    entry_points='''
        [console_scripts]
        drs-compliance-suite=compliance_suite.report_runner:main
    '''

)
