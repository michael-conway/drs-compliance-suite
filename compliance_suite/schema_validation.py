import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7


def validate_json_schema(instance, schema_file_path):
    schema_path = Path(schema_file_path).resolve()
    registry = _schema_registry(schema_path.parent)
    validator = jsonschema.Draft7Validator(
        {"$ref": schema_path.as_uri()},
        registry=registry,
    )
    validator.validate(instance)


def _schema_registry(schema_dir):
    resources = []
    for schema_path in Path(schema_dir).resolve().glob("*.json"):
        with schema_path.open("r", encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
        resources.append((
            schema_path.as_uri(),
            Resource.from_contents(schema, default_specification=DRAFT7),
        ))
    return Registry().with_resources(resources)
