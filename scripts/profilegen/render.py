"""Template rendering for profile-gen.

Templates under ``templates/*.j2`` are NOT Jinja templates (the ``.j2``
extension is just a familiar naming convention) -- they're rendered with a
tiny regex-based substitution engine so this module has zero dependencies.

Supported mini-syntax:

  {{ field }}            Variable substitution. Dotted paths address nested
                          dict keys, e.g. {{ generation.backend }} looks up
                          fields["generation"]["backend"]. None -> YAML
                          "null", booleans -> YAML "true"/"false", everything
                          else -> str(value). Templates are responsible for
                          wrapping string fields in their own quotes where
                          YAML needs it (see the two .j2 templates: fields
                          that are always strings are written as
                          "{{ field }}"; fields that can be null, like
                          generation.seed/gif_mode, are left unquoted so a
                          null renders as a real YAML null rather than the
                          string "null").

  {% if field %}...{% endif %}
                          Conditional block. ``field`` supports the same
                          dotted-path lookup as substitution. The block is
                          kept (with its markers stripped) when the looked-up
                          value is truthy (not None, not "", not False), and
                          dropped entirely otherwise. Blocks may not nest.

Both ``templates/profile.standalone.md.j2`` and
``templates/profile.embedded.md.j2`` must only use this syntax.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")
_IF_RE = re.compile(
    r"\{%\s*if\s+([a-zA-Z0-9_.]+)\s*%\}(.*?)\{%\s*endif\s*%\}", re.DOTALL
)


def _lookup(fields: dict[str, Any], path: str) -> Any:
    value: Any = fields
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def _render_conditionals(text: str, fields: dict[str, Any]) -> str:
    def _sub(match: "re.Match[str]") -> str:
        path, body = match.group(1), match.group(2)
        return body if _lookup(fields, path) else ""

    return _IF_RE.sub(_sub, text)


def _to_text(value: Any) -> str:
    """Render a looked-up value as YAML/markdown-safe text.

    Booleans and None need YAML-lowercase spellings (``true``/``false``/
    ``null``) since substituted values commonly land inside YAML frontmatter.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_variables(text: str, fields: dict[str, Any]) -> str:
    def _sub(match: "re.Match[str]") -> str:
        return _to_text(_lookup(fields, match.group(1)))

    return _VAR_RE.sub(_sub, text)


def render_template(template_text: str, fields: dict[str, Any]) -> str:
    text = _render_conditionals(template_text, fields)
    text = _render_variables(text, fields)
    return text


def _load(name: str) -> str:
    return (_TEMPLATES_DIR / name).read_text(encoding="utf-8")


def render_standalone(fields: dict[str, Any]) -> str:
    return render_template(_load("profile.standalone.md.j2"), fields)


def render_embedded(fields: dict[str, Any]) -> str:
    return render_template(_load("profile.embedded.md.j2"), fields)
