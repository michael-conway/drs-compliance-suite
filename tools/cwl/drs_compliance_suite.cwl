#!/usr/bin/env cwl-runner

cwlVersion: v1.0
class: CommandLineTool
baseCommand: drs-compliance-suite
hints:
  DockerRequirement:
    dockerPull: ga4gh/drs-compliance-suite:1.0.5
inputs:
  server_base_url:
    type: string
    inputBinding:
      position: 1
      prefix: --server_base_url
  platform_name:
    type: string
    inputBinding:
      position: 2
      prefix: --platform_name
  platform_description:
    type: string
    inputBinding:
      position: 3
      prefix: --platform_description
  version:
    type: string
    inputBinding:
      position: 4
      prefix: --version
  config_file:
    type: File
    inputBinding:
      position: 5
      prefix: --config_file
  report_path:
    type: string
    inputBinding:
      position: 6
      prefix: --report_path
outputs: 
  drs-compliance-report:   
    type: File
    outputBinding:
      glob: $(inputs.report_path)
