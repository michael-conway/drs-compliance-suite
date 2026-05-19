import json
import os


SUMMARY_FIELDS = [
    ("passed", "Passed"),
    ("failed", "Failed"),
    ("warned", "Warned"),
    ("skipped", "Skipped"),
    ("unknown", "Unknown"),
]


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
        return [f"- {_text(key)}: {_inline(value)}" for key, value in inputs.items()]

    lines = []
    for entry in inputs:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("key")
            value = entry.get("value")
            if name is not None:
                lines.append(f"- {_text(name)}: {_inline(value)}")
    return lines


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
