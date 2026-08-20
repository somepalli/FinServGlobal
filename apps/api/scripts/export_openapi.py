import json
from pathlib import Path

from compliance.api.main import app

WEB_PATHS = ("/query", "/screen")


def _references(value: object) -> set[str]:
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str):
                found.add(item.rsplit("/", maxsplit=1)[-1])
            else:
                found.update(_references(item))
        return found
    if isinstance(value, list):
        return set().union(*(_references(item) for item in value))
    return set()


def _used_schemas(paths: object, schemas: dict[str, object]) -> set[str]:
    used = _references(paths)
    pending = list(used)
    while pending:
        name = pending.pop()
        dependencies = _references(schemas[name]) - used
        used.update(dependencies)
        pending.extend(dependencies)
    return used


def main() -> None:
    schema = app.openapi()
    paths = {path: schema["paths"][path] for path in WEB_PATHS}
    schemas = schema["components"]["schemas"]
    used = _used_schemas(paths, schemas)
    web_schema = {
        "openapi": schema["openapi"],
        "info": schema["info"],
        "paths": paths,
        "components": {"schemas": {name: schemas[name] for name in sorted(used)}},
    }
    output = Path(__file__).parents[2] / "web" / "openapi.json"
    output.write_text(
        json.dumps(web_schema, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
