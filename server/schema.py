"""Strict JSON schemas for tool inputs and outputs, in the small vocabulary
Cognic's safety file accepts for embedded schemas.

Every object lists its properties, requires all of them and forbids any
other ("additionalProperties": false); every array has items and a
maxItems; every string has a maxLength. The only other keywords are
description, minLength, minimum, maximum and enum. No unions, references or
patterns.

check() validates a value against such a schema and returns the first
problem as text, or None; check_schema() verifies that a schema stays inside
the vocabulary and the depth and size limits.
"""

ALLOWED = {"type", "description", "properties", "required", "additionalProperties", "items", "maxItems",
           "maxLength", "minLength", "minimum", "maximum", "enum"}
TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
MAX_DEPTH = 12
MAX_NODES = 1024


def string(max_length, description=None, enum=None, min_length=None):
    out = {"type": "string", "maxLength": max_length}
    if min_length is not None:
        out["minLength"] = min_length
    if enum is not None:
        out["enum"] = list(enum)
    if description:
        out["description"] = description
    return out


def integer(minimum=None, maximum=None, description=None):
    out = {"type": "integer"}
    if minimum is not None:
        out["minimum"] = minimum
    if maximum is not None:
        out["maximum"] = maximum
    if description:
        out["description"] = description
    return out


def number(description=None, minimum=None, maximum=None):
    out = {"type": "number"}
    if minimum is not None:
        out["minimum"] = minimum
    if maximum is not None:
        out["maximum"] = maximum
    if description:
        out["description"] = description
    return out


def boolean(description=None):
    out = {"type": "boolean"}
    if description:
        out["description"] = description
    return out


def array(items, max_items, description=None):
    out = {"type": "array", "items": items, "maxItems": max_items}
    if description:
        out["description"] = description
    return out


def obj(properties, description=None, optional=()):
    """An object that allows exactly these properties; all are required
    except those named in optional."""
    out = {"type": "object", "properties": properties,
           "required": [name for name in properties if name not in optional], "additionalProperties": False}
    if description:
        out["description"] = description
    return out


def _type_ok(kind, value):
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return value is None


def check(schema, value, path="$"):
    """The first way value breaks schema, as text; None when it conforms."""
    kind = schema["type"]
    if not _type_ok(kind, value):
        return "{}: expected {}".format(path, kind)
    if "enum" in schema and value not in schema["enum"]:
        return "{}: not one of the allowed values".format(path)
    if kind == "string":
        if len(value) > schema["maxLength"]:
            return "{}: longer than {} characters".format(path, schema["maxLength"])
        if len(value) < schema.get("minLength", 0):
            return "{}: shorter than {} characters".format(path, schema["minLength"])
    if kind in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            return "{}: below {}".format(path, schema["minimum"])
        if "maximum" in schema and value > schema["maximum"]:
            return "{}: above {}".format(path, schema["maximum"])
    if kind == "array":
        if len(value) > schema["maxItems"]:
            return "{}: more than {} items".format(path, schema["maxItems"])
        for index, item in enumerate(value):
            problem = check(schema["items"], item, "{}[{}]".format(path, index))
            if problem:
                return problem
    if kind == "object":
        properties = schema["properties"]
        for name in value:
            if name not in properties:
                return "{}: unknown property {!r}".format(path, name)
        for name in schema["required"]:
            if name not in value:
                return "{}: missing property {!r}".format(path, name)
        for name, item in value.items():
            problem = check(properties[name], item, "{}.{}".format(path, name))
            if problem:
                return problem
    return None


def check_schema(schema, depth=1, counter=None):
    """Raise ValueError unless schema stays inside the vocabulary and limits."""
    counter = counter if counter is not None else [0]
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise ValueError("schema has more than {} nodes".format(MAX_NODES))
    if depth > MAX_DEPTH:
        raise ValueError("schema is deeper than {}".format(MAX_DEPTH))
    unknown = set(schema) - ALLOWED
    if unknown:
        raise ValueError("unsupported keywords: {}".format(sorted(unknown)))
    kind = schema.get("type")
    if kind not in TYPES:
        raise ValueError("bad type {!r}".format(kind))
    if kind == "object":
        if schema.get("additionalProperties") is not False or "properties" not in schema or "required" not in schema:
            raise ValueError("objects need properties, required and additionalProperties: false")
        if len(schema["properties"]) > 64:
            raise ValueError("more than 64 properties")
        if not set(schema["required"]) <= set(schema["properties"]):
            raise ValueError("required names a property that does not exist")
        for item in schema["properties"].values():
            check_schema(item, depth + 1, counter)
    elif any(k in schema for k in ("properties", "required", "additionalProperties")):
        raise ValueError("object keywords on a non-object")
    if kind == "array":
        if "items" not in schema or "maxItems" not in schema or not 0 <= schema["maxItems"] <= 1000:
            raise ValueError("arrays need items and maxItems up to 1000")
        check_schema(schema["items"], depth + 1, counter)
    elif "items" in schema or "maxItems" in schema:
        raise ValueError("array keywords on a non-array")
    if kind == "string":
        if "maxLength" not in schema or not 0 <= schema["maxLength"] <= 8000:
            raise ValueError("strings need maxLength up to 8000")
    elif "maxLength" in schema or "minLength" in schema:
        raise ValueError("string keywords on a non-string")
    if "enum" in schema and (not schema["enum"] or len(schema["enum"]) > 64):
        raise ValueError("enum needs 1 to 64 values")
    return counter[0]
