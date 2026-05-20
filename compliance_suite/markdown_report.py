import json
import os


SUMMARY_FIELDS = [
    ("passed", "Passed"),
    ("failed", "Failed"),
    ("warned", "Warned"),
    ("skipped", "Skipped"),
    ("unknown", "Unknown"),
]
V150_COVERAGE_METADATA_INPUT = "_drs_v150_coverage_metadata"


def report_to_markdown(report):
    """Render a GA4GH testbed report object or dict as Markdown."""

    if hasattr(report, "to_json"):
        report = json.loads(report.to_json(pretty=True))

    lines = [
        "# DRS Compliance Report",
        "",
        f"**Overall status:** `{report.get('status', 'UNKNOWN')}`",
        "",
        "## Target",
        "",
        f"- Testbed: {_inline(report.get('testbed_name'))}",
        f"- Testbed version: {_inline(report.get('testbed_version'))}",
        f"- Platform: {_inline(report.get('platform_name'))}",
        f"- Platform description: {_inline(report.get('platform_description'))}",
    ]

    input_lines = _format_inputs(report)
    if input_lines:
        lines.extend(["", "## Inputs", ""])
        lines.extend(input_lines)

    lines.extend(["", "## Summary", ""])
    lines.extend(_summary_table(report.get("summary", {})))

    coverage_metadata = _coverage_metadata(report)
    if coverage_metadata:
        lines.extend(_coverage_highlights_to_markdown(coverage_metadata))

    phases = report.get("phases", [])
    if phases:
        lines.extend(["", "## Phases"])

    for phase in phases:
        lines.extend(_phase_to_markdown(phase))

    lines.append("")
    return "\n".join(lines)


def write_markdown_report(report, report_path):
    """Write a GA4GH testbed report object or dict to a Markdown file."""

    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_to_markdown(report))


def _phase_to_markdown(phase):
    lines = [
        "",
        f"### {_text(phase.get('phase_name', 'Unnamed phase'))}",
        "",
        f"**Status:** `{phase.get('status', 'UNKNOWN')}`",
        "",
        _text(phase.get("phase_description", "")),
        "",
    ]
    lines.extend(_summary_table(phase.get("summary", {})))

    tests = phase.get("tests", [])
    for test in tests:
        lines.extend(_test_to_markdown(test))

    return lines


def _test_to_markdown(test):
    lines = [
        "",
        f"#### {_text(test.get('test_name', 'Unnamed test'))}",
        "",
        f"**Status:** `{test.get('status', 'UNKNOWN')}`",
        "",
        _text(test.get("test_description", "")),
    ]

    message = test.get("message")
    if message:
        lines.extend(["", f"**Message:** {_text(message)}"])

    cases = test.get("case", test.get("cases", []))
    if cases:
        lines.extend([
            "",
            "| Case | Status | Message |",
            "| --- | --- | --- |",
        ])
        for case in cases:
            lines.append(
                "| {name} | `{status}` | {message} |".format(
                    name=_cell(case.get("case_name", "")),
                    status=_cell(case.get("status", "UNKNOWN")),
                    message=_cell(case.get("message", "")),
                )
            )

    return lines


def _summary_table(summary):
    header = "| " + " | ".join(label for _, label in SUMMARY_FIELDS) + " |"
    separator = "| " + " | ".join("---" for _ in SUMMARY_FIELDS) + " |"
    values = "| " + " | ".join(str(summary.get(key, 0)) for key, _ in SUMMARY_FIELDS) + " |"
    return [header, separator, values]


def _format_inputs(report):
    inputs = report.get("input_parameters") or report.get("input_parameter") or []
    if isinstance(inputs, dict):
        return [
            f"- {_text(key)}: {_inline(value)}"
            for key, value in inputs.items()
            if key != V150_COVERAGE_METADATA_INPUT
        ]

    lines = []
    for entry in inputs:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("key")
            value = entry.get("value")
            if name is not None and name != V150_COVERAGE_METADATA_INPUT:
                lines.append(f"- {_text(name)}: {_inline(value)}")
    return lines


def _coverage_metadata(report):
    inputs = report.get("input_parameters") or report.get("input_parameter") or []
    if isinstance(inputs, dict):
        return _load_coverage_metadata(inputs.get(V150_COVERAGE_METADATA_INPUT))

    for entry in inputs:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("key")
        if name == V150_COVERAGE_METADATA_INPUT:
            return _load_coverage_metadata(entry.get("value"))
    return {}


def _load_coverage_metadata(value):
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        metadata = json.loads(value)
    except ValueError:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _coverage_highlights_to_markdown(metadata):
    lines = [
        "",
        "## API Coverage Highlights",
        "",
        "> Coverage gaps in this section are informational unless an individual test case failed.",
    ]
    optional_lines = _optional_capability_matrix(metadata.get("optional_capabilities", {}))
    if optional_lines:
        lines.extend(["", "### Optional Capability Matrix", ""])
        lines.extend(optional_lines)

    auth_lines = _auth_coverage_matrix(metadata.get("auth_coverage", {}))
    if auth_lines:
        lines.extend(["", "### Auth Coverage Matrix", ""])
        lines.extend(auth_lines)

    compound_lines = _compound_manifest_section(metadata.get("compound_manifests", {}))
    if compound_lines:
        lines.extend(["", "### Compound Manifest Support", ""])
        lines.extend(compound_lines)

    notes = metadata.get("notes", [])
    if notes:
        lines.extend(["", "### Coverage Notes", ""])
        for note in notes:
            lines.append(f"- {_text(note)}")

    return lines


def _optional_capability_matrix(optional_capabilities):
    if not isinstance(optional_capabilities, dict) or not optional_capabilities:
        return []

    lines = [
        "| Capability | Status | Notes |",
        "| --- | --- | --- |",
    ]
    for capability in sorted(optional_capabilities):
        record = optional_capabilities[capability]
        evidence = record.get("evidence", [])
        if isinstance(evidence, list):
            evidence_text = "<br>".join(_text(item) for item in evidence[:3])
        else:
            evidence_text = _text(evidence)
        if record.get("deprecated"):
            evidence_text = (evidence_text + "<br>" if evidence_text else "") + "Deprecated or optional capability"
        lines.append(
            "| {capability} | `{status}` | {evidence} |".format(
                capability=_cell(record.get("capability", capability)),
                status=_cell(record.get("status", "UNKNOWN")),
                evidence=_cell(evidence_text),
            )
        )
    return lines


def _auth_coverage_matrix(auth_coverage):
    if not isinstance(auth_coverage, dict) or not auth_coverage:
        return []

    lines = [
        "| Auth Type | Object Requests | Access Requests | Authorization Metadata | Access Method Metadata | Note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for auth_type in ("basic", "bearer", "passport"):
        record = auth_coverage.get(auth_type, {})
        lines.append(
            "| {auth_type} | {object_requests} | {access_requests} | {authorization_metadata} | {access_method_metadata} | {note} |".format(
                auth_type=_cell(auth_type),
                object_requests=_coverage_mark(record.get("object_requests")),
                access_requests=_coverage_mark(record.get("access_requests")),
                authorization_metadata=_coverage_mark(record.get("authorization_metadata")),
                access_method_metadata=_coverage_mark(record.get("access_method_metadata")),
                note=_cell(record.get("note", "")),
            )
        )
    return lines


def _compound_manifest_section(compound_manifests):
    if not isinstance(compound_manifests, dict):
        return []

    supported = "yes" if compound_manifests.get("supported") else "no"
    manifest_types = compound_manifests.get("manifest_types") or []
    sample_manifest = compound_manifests.get("sample_manifest")
    sample_manifest_type = compound_manifests.get("sample_manifest_type") or "text"
    lines = [
        f"- Supported: `{supported}`",
        f"- Manifest types observed: `{', '.join(manifest_types) if manifest_types else 'none'}`",
    ]

    notes = compound_manifests.get("notes", [])
    for note in notes:
        lines.append(f"- {_text(note)}")

    if sample_manifest:
        code_type = sample_manifest_type if sample_manifest_type in {"json", "yaml"} else "text"
        commented_sample = _commented_manifest_sample(sample_manifest, code_type)
        lines.extend([
            "",
            "Sample manifest:",
            "",
            f"```{code_type}",
            commented_sample,
            "```",
        ])
    return lines


def _commented_manifest_sample(sample_manifest, code_type):
    comment_prefix = "//" if code_type == "json" else "#"
    return "\n".join(
        [f"{comment_prefix} Sample compound manifest returned by the DRS server"]
        + _text(sample_manifest).splitlines()
    )


def _coverage_mark(value):
    return "`yes`" if value else "`no`"


def _inline(value):
    if value is None:
        return ""
    return f"`{_text(value)}`"


def _cell(value):
    return _text(value).replace("|", "\\|").replace("\n", "<br>")


def _text(value):
    if value is None:
        return ""
    return str(value)
