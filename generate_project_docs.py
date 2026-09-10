#!/usr/bin/env python3
"""
Generate a single Markdown knowledge snapshot for one or more code projects.

The report is designed to preserve both source code and the information that is
most useful when handing a project to another developer or an LLM:
- project tree and file index
- language/file statistics
- key manifests/configuration files
- dependency summaries
- Python symbols, imports, decorators, routes, CLI arguments and env usage
- lightweight JS/TS symbols/imports/env usage
- TODO/FIXME/HACK/XXX notes
- source file contents with secret redaction by default

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".turbo",
    "__pycache__",
    "logs",
    "tmp",
    "temp",
}

DEFAULT_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".jsx",
    ".ts",
    ".tsx",
    ".vue",
    ".php",
    ".java",
    ".kt",
    ".kts",
    ".go",
    ".rs",
    ".cs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".md",
    ".rst",
    ".txt",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".xml",
    ".graphql",
    ".gql",
    ".proto",
    ".env",
}

SPECIAL_FILENAMES = {
    "Dockerfile",
    "dockerfile",
    "Makefile",
    "makefile",
    "Procfile",
    "Gemfile",
    "Rakefile",
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "Pipfile",
    "Pipfile.lock",
    "poetry.lock",
    "uv.lock",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "composer.json",
    "composer.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle.properties",
    "AGENTS.md",
    "CLAUDE.md",
    "README",
    "README.md",
    "README.rst",
    ".gitignore",
    ".dockerignore",
    ".env",
    ".env.example",
    ".env.sample",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "vue",
    ".php": "php",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    ".md": "markdown",
    ".rst": "rst",
    ".json": "json",
    ".jsonc": "jsonc",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "text",
    ".properties": "properties",
    ".xml": "xml",
    ".graphql": "graphql",
    ".gql": "graphql",
    ".proto": "protobuf",
    ".env": "bash",
}

KEY_FILE_PRIORITIES = {
    "README.md": 1,
    "README.rst": 1,
    "README": 1,
    "pyproject.toml": 2,
    "requirements.txt": 2,
    "package.json": 2,
    "composer.json": 2,
    "go.mod": 2,
    "Cargo.toml": 2,
    "pom.xml": 2,
    "Dockerfile": 3,
    "docker-compose.yml": 3,
    "docker-compose.yaml": 3,
    ".env.example": 4,
    ".env.sample": 4,
    "Makefile": 5,
    "AGENTS.md": 6,
    "CLAUDE.md": 6,
}

SECRET_KEY_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"client[_-]?secret|auth[_-]?token|bearer|dsn|database[_-]?url|connection[_-]?string)"
)

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b[:\s-]*(.*)", re.IGNORECASE)

DOCKER_COMPOSE_RE = re.compile(r"^docker-compose(?:\.[^.]+)?\.ya?ml$", re.IGNORECASE)
ENV_FILENAME_RE = re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE)


@dataclass
class FileRecord:
    path: Path
    relative: Path
    language: str
    size: int
    lines: int
    text: str


@dataclass
class PythonFileAnalysis:
    imports: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    cli_arguments: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)
    constants: list[str] = field(default_factory=list)
    parse_error: Optional[str] = None


@dataclass
class GenericAnalysis:
    imports: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    routes: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------


def normalize_extension(value: str) -> str:
    if value.startswith("."):
        return value.lower()
    if "." not in value and value.lower() not in {"dockerfile", "makefile"}:
        return "." + value.lower()
    return value


def is_docker_compose_file(filename: str) -> bool:
    return bool(DOCKER_COMPOSE_RE.match(filename))


def is_special_file(path: Path) -> bool:
    return path.name in SPECIAL_FILENAMES or is_docker_compose_file(path.name) or bool(
        ENV_FILENAME_RE.match(path.name)
    )


def language_for_file(path: Path) -> str:
    if path.name.lower() == "dockerfile":
        return "dockerfile"
    if is_docker_compose_file(path.name):
        return "yaml"
    if path.name.lower() == "makefile":
        return "makefile"
    if path.name in {"requirements.txt", "requirements-dev.txt"}:
        return "text"
    if ENV_FILENAME_RE.match(path.name):
        return "bash"
    return LANGUAGE_BY_EXTENSION.get(path.suffix.lower(), "text")


def markdown_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value)
    return value.strip("-")


def safe_read_text(path: Path, max_bytes: int) -> tuple[Optional[str], Optional[str]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return None, f"stat failed: {exc}"

    if size > max_bytes:
        return None, f"skipped: file is {size:,} bytes (limit {max_bytes:,})"

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"read failed: {exc}"

    # Crude but effective binary check. UTF-16 can contain NUL, so try decoding it first.
    if b"\x00" in raw:
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(encoding), None
            except UnicodeDecodeError:
                pass
        return None, "skipped: appears to be a binary file"

    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), None
        except UnicodeDecodeError:
            continue

    return None, "skipped: could not decode text"


def choose_fence(text: str) -> str:
    longest = 0
    for match in re.finditer(r"`+", text):
        longest = max(longest, len(match.group(0)))
    return "`" * max(3, longest + 1)


def short_docstring(value: Optional[str], limit: int = 160) -> str:
    if not value:
        return ""
    line = " ".join(value.strip().split())
    return line if len(line) <= limit else line[: limit - 1] + "…"


def run_git(root: Path, args: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


def redact_env_file(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _, value = line.partition("=")
        if value.strip():
            output.append(f"{key}=<REDACTED>")
        else:
            output.append(line)
    return "\n".join(output)


def redact_common_secrets(text: str) -> str:
    """Best-effort masking for obvious inline secrets; intentionally conservative."""
    patterns = [
        # KEY = "value" / KEY: "value"
        re.compile(
            r"(?im)^(\s*[A-Za-z_][\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|client[_-]?secret)[\w.-]*\s*[:=]\s*)"
            r"([\"'])([^\n\"']+)(\2)"
        ),
        # JSON/YAML-ish quoted key
        re.compile(
            r"(?im)([\"'][^\"']*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|client[_-]?secret)[^\"']*[\"']\s*:\s*)"
            r"([\"'])([^\n\"']+)(\2)"
        ),
    ]
    redacted = text
    for pattern in patterns:
        redacted = pattern.sub(lambda m: m.group(1) + m.group(2) + "<REDACTED>" + m.group(4), redacted)
    return redacted


def redact_content(path: Path, text: str, show_secrets: bool) -> str:
    if show_secrets:
        return text
    if ENV_FILENAME_RE.match(path.name):
        return redact_env_file(text)
    return redact_common_secrets(text)


# ---------------------------------------------------------------------------
# File discovery and tree
# ---------------------------------------------------------------------------


def should_include_file(
    path: Path,
    include_extensions: Optional[set[str]],
    include_all_text: bool,
) -> bool:
    if is_special_file(path):
        return True

    if include_extensions is not None:
        return path.suffix.lower() in include_extensions or path.name in include_extensions

    if include_all_text:
        return True

    return path.suffix.lower() in DEFAULT_EXTENSIONS


def iter_project_files(
    root: Path,
    ignore_dirs: set[str],
    include_extensions: Optional[set[str]],
    include_all_text: bool,
    output_file: Optional[Path] = None,
) -> Iterable[Path]:
    for current_root, dirs, files in os.walk(root):
        current = Path(current_root)
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in ignore_dirs
            and not d.startswith(".")
            and d != "__pycache__"
        )
        for filename in sorted(files):
            path = current / filename
            try:
                if output_file and path.resolve() == output_file.resolve():
                    continue
            except OSError:
                pass
            if should_include_file(path, include_extensions, include_all_text):
                yield path


def collect_files(
    root: Path,
    ignore_dirs: set[str],
    include_extensions: Optional[set[str]],
    include_all_text: bool,
    max_bytes: int,
    output_file: Optional[Path],
) -> tuple[list[FileRecord], list[tuple[Path, str]]]:
    records: list[FileRecord] = []
    skipped: list[tuple[Path, str]] = []

    for path in iter_project_files(
        root, ignore_dirs, include_extensions, include_all_text, output_file
    ):
        text, error = safe_read_text(path, max_bytes)
        relative = path.relative_to(root)
        if text is None:
            skipped.append((relative, error or "unknown reason"))
            continue
        lines = 0 if not text else text.count("\n") + 1
        records.append(
            FileRecord(
                path=path,
                relative=relative,
                language=language_for_file(path),
                size=path.stat().st_size,
                lines=lines,
                text=text,
            )
        )
    return records, skipped


def build_tree(root: Path, records: list[FileRecord]) -> list[str]:
    paths = sorted((r.relative for r in records), key=lambda p: tuple(str(x).lower() for x in p.parts))
    tree: dict[str, dict] = {}
    for rel in paths:
        node = tree
        for part in rel.parts:
            node = node.setdefault(part, {})

    lines = [f"{root.name}/"]

    def render(node: dict[str, dict], prefix: str) -> None:
        items = sorted(node.items(), key=lambda x: (not bool(x[1]), x[0].lower()))
        for index, (name, children) in enumerate(items):
            last = index == len(items) - 1
            connector = "└── " if last else "├── "
            suffix = "/" if children else ""
            lines.append(f"{prefix}{connector}{name}{suffix}")
            if children:
                render(children, prefix + ("    " if last else "│   "))

    render(tree, "")
    return lines


# ---------------------------------------------------------------------------
# Python static analysis
# ---------------------------------------------------------------------------


def ast_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = ast_name(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    if isinstance(node, ast.Call):
        return ast_name(node.func)
    if isinstance(node, ast.Subscript):
        return ast_name(node.value)
    return ""


def ast_literal_string(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def format_ast_default(node: ast.AST) -> str:
    try:
        value = ast.unparse(node)
    except Exception:
        return "…"
    if len(value) > 50:
        return value[:49] + "…"
    if SECRET_KEY_RE.search(value):
        return "<REDACTED>"
    return value


def format_python_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    positional = list(node.args.posonlyargs) + list(node.args.args)
    defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)

    for index, (arg, default) in enumerate(zip(positional, defaults)):
        part = arg.arg
        if arg.annotation:
            try:
                part += ": " + ast.unparse(arg.annotation)
            except Exception:
                pass
        if default is not None:
            part += " = " + format_ast_default(default)
        args.append(part)
        if node.args.posonlyargs and index + 1 == len(node.args.posonlyargs):
            args.append("/")

    if node.args.vararg:
        part = "*" + node.args.vararg.arg
        if node.args.vararg.annotation:
            try:
                part += ": " + ast.unparse(node.args.vararg.annotation)
            except Exception:
                pass
        args.append(part)
    elif node.args.kwonlyargs:
        args.append("*")

    for kwarg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        part = kwarg.arg
        if kwarg.annotation:
            try:
                part += ": " + ast.unparse(kwarg.annotation)
            except Exception:
                pass
        if default is not None:
            part += " = " + format_ast_default(default)
        args.append(part)

    if node.args.kwarg:
        part = "**" + node.args.kwarg.arg
        if node.args.kwarg.annotation:
            try:
                part += ": " + ast.unparse(node.args.kwarg.annotation)
            except Exception:
                pass
        args.append(part)

    returns = ""
    if node.returns:
        try:
            returns = " -> " + ast.unparse(node.returns)
        except Exception:
            pass

    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({', '.join(args)}){returns}"


def decorator_text(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return ast_name(node)


class PythonAnalyzer(ast.NodeVisitor):
    ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "route", "websocket"}

    def __init__(self) -> None:
        self.result = PythonFileAnalysis()
        self.class_stack: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.result.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        names = ", ".join(alias.name for alias in node.names)
        self.result.imports.append(f"from {module} import {names}")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast_name(base) for base in node.bases if ast_name(base)]
        decorators = [decorator_text(d) for d in node.decorator_list]
        text = f"class {node.name}"
        if bases:
            text += f"({', '.join(bases)})"
        doc = short_docstring(ast.get_docstring(node))
        if decorators:
            text += f"  [decorators: {', '.join(decorators)}]"
        if doc:
            text += f" — {doc}"
        self.result.classes.append(text)

        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        signature = format_python_signature(node)
        decorators = [decorator_text(d) for d in node.decorator_list]
        doc = short_docstring(ast.get_docstring(node))
        detail = signature
        if decorators:
            detail += f"  [decorators: {', '.join(decorators)}]"
        if doc:
            detail += f" — {doc}"

        if self.class_stack:
            self.result.methods.append(f"{'.'.join(self.class_stack)}.{detail}")
        else:
            self.result.functions.append(detail)

        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = ast_name(decorator.func)
            method = name.rsplit(".", 1)[-1].lower()
            if method in self.ROUTE_METHODS:
                path = ast_literal_string(decorator.args[0]) if decorator.args else None
                self.result.routes.append(
                    f"{method.upper()} {path or '<dynamic>'} -> {node.name}"
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # Record uppercase module-level-ish constants by name, not secret values.
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.isupper():
                self.result.constants.append(target.id)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id.isupper():
            self.result.constants.append(node.target.id)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = ast_name(node.func)

        # Environment variables: os.getenv("X"), os.environ.get("X")
        if name in {"os.getenv", "os.environ.get", "environ.get"} and node.args:
            key = ast_literal_string(node.args[0])
            if key:
                self.result.env_vars.append(key)

        # argparse calls: parser.add_argument("--foo", ...)
        if name.endswith(".add_argument"):
            flags = [ast_literal_string(arg) for arg in node.args]
            flags = [flag for flag in flags if flag]
            if flags:
                self.result.cli_arguments.append(", ".join(flags))

        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        name = ast_name(node.value)
        if name in {"os.environ", "environ"}:
            key = ast_literal_string(node.slice)
            if key:
                self.result.env_vars.append(key)
        self.generic_visit(node)


def analyze_python(text: str) -> PythonFileAnalysis:
    analyzer = PythonAnalyzer()
    try:
        tree = ast.parse(text)
        analyzer.visit(tree)
    except SyntaxError as exc:
        analyzer.result.parse_error = f"line {exc.lineno}: {exc.msg}"
    result = analyzer.result
    result.imports = sorted(set(result.imports))
    result.routes = sorted(set(result.routes))
    result.cli_arguments = sorted(set(result.cli_arguments))
    result.env_vars = sorted(set(result.env_vars))
    result.constants = sorted(set(result.constants))
    return result


# ---------------------------------------------------------------------------
# Lightweight JS / TS / PHP and generic analysis
# ---------------------------------------------------------------------------

JS_IMPORT_RE = re.compile(
    r"(?m)^\s*(?:import\s+.*?\s+from\s+|import\s*\(|require\s*\()\s*[\"']([^\"']+)[\"']"
)
JS_SYMBOL_RE = re.compile(
    r"(?m)^\s*(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)"
)
JS_ARROW_RE = re.compile(
    r"(?m)^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\([^\n]*?\)\s*=>"
)
JS_ENV_RE = re.compile(r"\b(?:process\.env\.|import\.meta\.env\.)([A-Za-z_][A-Za-z0-9_]*)")
JS_ROUTE_RE = re.compile(
    r"(?m)\b(?:app|router|server)\.(get|post|put|patch|delete|options|head)\s*\(\s*[\"']([^\"']+)[\"']"
)

PHP_USE_RE = re.compile(r"(?m)^\s*use\s+([^;]+);")
PHP_SYMBOL_RE = re.compile(r"(?m)^\s*(?:final\s+|abstract\s+)?(?:class|interface|trait|function)\s+([A-Za-z_][\w]*)")
PHP_ENV_RE = re.compile(r"\benv\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")
PHP_ROUTE_RE = re.compile(
    r"Route::(get|post|put|patch|delete|options|any|match)\s*\(\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)


def analyze_generic(record: FileRecord) -> GenericAnalysis:
    result = GenericAnalysis()
    text = record.text
    suffix = record.path.suffix.lower()

    if suffix in {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".vue"}:
        result.imports = sorted(set(JS_IMPORT_RE.findall(text)))
        result.symbols = sorted(set(JS_SYMBOL_RE.findall(text)) | set(JS_ARROW_RE.findall(text)))
        result.env_vars = sorted(set(JS_ENV_RE.findall(text)))
        result.routes = sorted(
            f"{method.upper()} {path}" for method, path in JS_ROUTE_RE.findall(text)
        )
    elif suffix == ".php":
        result.imports = sorted(set(PHP_USE_RE.findall(text)))
        result.symbols = sorted(set(PHP_SYMBOL_RE.findall(text)))
        result.env_vars = sorted(set(PHP_ENV_RE.findall(text)))
        result.routes = sorted(
            f"{method.upper()} {path}" for method, path in PHP_ROUTE_RE.findall(text)
        )

    return result


# ---------------------------------------------------------------------------
# Dependency and metadata extraction
# ---------------------------------------------------------------------------


def extract_requirements(text: str) -> list[str]:
    deps: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(("-r", "--")):
            continue
        deps.append(line)
    return deps


def extract_package_json(text: str) -> dict[str, list[str] | str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: dict[str, list[str] | str] = {}
    if isinstance(data, dict):
        if data.get("name"):
            result["name"] = str(data["name"])
        if data.get("version"):
            result["version"] = str(data["version"])
        for key in ("dependencies", "devDependencies", "peerDependencies"):
            value = data.get(key)
            if isinstance(value, dict):
                result[key] = [f"{name}: {version}" for name, version in sorted(value.items())]
        scripts = data.get("scripts")
        if isinstance(scripts, dict):
            result["scripts"] = [f"{name}: {command}" for name, command in sorted(scripts.items())]
    return result


def extract_composer_json(text: str) -> dict[str, list[str] | str]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    result: dict[str, list[str] | str] = {}
    if isinstance(data, dict):
        if data.get("name"):
            result["name"] = str(data["name"])
        for key in ("require", "require-dev"):
            value = data.get(key)
            if isinstance(value, dict):
                result[key] = [f"{name}: {version}" for name, version in sorted(value.items())]
    return result


def extract_go_mod(text: str) -> list[str]:
    deps: list[str] = []
    in_require = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("require ("):
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue
        if line.startswith("require "):
            deps.append(line[len("require ") :].strip())
        elif in_require and line and not line.startswith("//"):
            deps.append(line)
    return deps


def parse_env_keys(text: str) -> list[str]:
    keys = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            keys.append(key)
    return sorted(set(keys))


def dependency_summary(records: list[FileRecord]) -> list[tuple[str, str, list[str]]]:
    sections: list[tuple[str, str, list[str]]] = []
    for record in records:
        name = record.path.name
        if name.startswith("requirements") and name.endswith(".txt"):
            deps = extract_requirements(record.text)
            if deps:
                sections.append((str(record.relative), "Python requirements", deps))
        elif name == "package.json":
            data = extract_package_json(record.text)
            for key in ("dependencies", "devDependencies", "peerDependencies", "scripts"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    sections.append((str(record.relative), key, value))
        elif name == "composer.json":
            data = extract_composer_json(record.text)
            for key in ("require", "require-dev"):
                value = data.get(key)
                if isinstance(value, list) and value:
                    sections.append((str(record.relative), key, value))
        elif name == "go.mod":
            deps = extract_go_mod(record.text)
            if deps:
                sections.append((str(record.relative), "Go modules", deps))
    return sections


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def find_key_files(records: list[FileRecord]) -> list[FileRecord]:
    def priority(record: FileRecord) -> tuple[int, int, str]:
        name = record.path.name
        if is_docker_compose_file(name):
            rank = 3
        else:
            rank = KEY_FILE_PRIORITIES.get(name, 50)
        return rank, len(record.relative.parts), str(record.relative).lower()

    return sorted(
        [r for r in records if r.path.name in KEY_FILE_PRIORITIES or is_docker_compose_file(r.path.name)],
        key=priority,
    )


def find_todos(records: list[FileRecord], max_items: int = 200) -> list[tuple[str, int, str, str]]:
    items: list[tuple[str, int, str, str]] = []
    for record in records:
        for lineno, line in enumerate(record.text.splitlines(), 1):
            match = TODO_RE.search(line)
            if match:
                note = match.group(2).strip()
                note = re.sub(r"\s+", " ", note)
                items.append((str(record.relative), lineno, match.group(1).upper(), note[:180]))
                if len(items) >= max_items:
                    return items
    return items


def aggregate_analysis(records: list[FileRecord]):
    python_results: dict[str, PythonFileAnalysis] = {}
    generic_results: dict[str, GenericAnalysis] = {}
    all_env_vars: set[str] = set()

    for record in records:
        key = str(record.relative)
        if record.path.suffix.lower() in {".py", ".pyi"}:
            result = analyze_python(record.text)
            python_results[key] = result
            all_env_vars.update(result.env_vars)
        else:
            result = analyze_generic(record)
            if result.imports or result.symbols or result.routes or result.env_vars:
                generic_results[key] = result
                all_env_vars.update(result.env_vars)

        if ENV_FILENAME_RE.match(record.path.name):
            all_env_vars.update(parse_env_keys(record.text))

    return python_results, generic_results, sorted(all_env_vars)


def write_project_report(
    f,
    root: Path,
    records: list[FileRecord],
    skipped: list[tuple[Path, str]],
    show_source: bool,
    show_secrets: bool,
    project_number: Optional[int] = None,
) -> None:
    title = root.name
    if project_number is not None:
        f.write(f"# {project_number}. {title}\n\n")
    else:
        f.write(f"# {title}\n\n")

    git_branch = run_git(root, ["branch", "--show-current"])
    git_commit = run_git(root, ["rev-parse", "--short", "HEAD"])
    git_remote = run_git(root, ["config", "--get", "remote.origin.url"])

    total_lines = sum(r.lines for r in records)
    total_bytes = sum(r.size for r in records)
    language_counts = Counter(r.language for r in records)
    language_lines = Counter()
    for record in records:
        language_lines[record.language] += record.lines

    py_results, generic_results, env_vars = aggregate_analysis(records)
    todos = find_todos(records)
    dependencies = dependency_summary(records)

    f.write("## Project Overview\n\n")
    f.write(f"- **Project root:** `{root.absolute()}`\n")
    f.write(f"- **Documented files:** {len(records):,}\n")
    f.write(f"- **Documented lines:** {total_lines:,}\n")
    f.write(f"- **Documented size:** {total_bytes / 1024:.1f} KiB\n")
    if git_branch:
        f.write(f"- **Git branch:** `{git_branch}`\n")
    if git_commit:
        f.write(f"- **Git commit:** `{git_commit}`\n")
    if git_remote:
        f.write(f"- **Git remote:** `{git_remote}`\n")
    f.write("\n")

    f.write("### Language / File Statistics\n\n")
    f.write("| Language | Files | Lines |\n|---|---:|---:|\n")
    for language, count in language_counts.most_common():
        f.write(f"| {markdown_escape(language)} | {count} | {language_lines[language]:,} |\n")
    f.write("\n")

    key_files = find_key_files(records)
    if key_files:
        f.write("### Key Project Files\n\n")
        for record in key_files[:30]:
            f.write(f"- `{record.relative}`\n")
        f.write("\n")

    f.write("## Project Structure\n\n")
    f.write("```text\n")
    f.write("\n".join(build_tree(root, records)))
    f.write("\n```\n\n")

    f.write("## File Index\n\n")
    f.write("| File | Language | Lines | Size |\n|---|---|---:|---:|\n")
    for record in records:
        f.write(
            f"| `{markdown_escape(str(record.relative))}` | {record.language} | "
            f"{record.lines:,} | {record.size:,} B |\n"
        )
    f.write("\n")

    if skipped:
        f.write("### Skipped Files\n\n")
        for relative, reason in skipped:
            f.write(f"- `{relative}` — {markdown_escape(reason)}\n")
        f.write("\n")

    if dependencies:
        f.write("## Dependencies and Project Commands\n\n")
        for path, category, values in dependencies:
            f.write(f"### {path} — {category}\n\n")
            for value in values:
                f.write(f"- `{markdown_escape(value)}`\n")
            f.write("\n")

    f.write("## Environment Variables\n\n")
    if env_vars:
        f.write(
            "The following environment-variable names were detected. Values are not shown here.\n\n"
        )
        for name in env_vars:
            f.write(f"- `{name}`\n")
    else:
        f.write("No environment-variable usage was detected by the static analyzer.\n")
    f.write("\n")

    # Python architecture summary
    has_python_info = any(
        result.imports
        or result.functions
        or result.classes
        or result.methods
        or result.routes
        or result.cli_arguments
        or result.constants
        or result.parse_error
        for result in py_results.values()
    )
    if has_python_info:
        f.write("## Python Code Map\n\n")
        for path, result in py_results.items():
            if not any(
                [
                    result.imports,
                    result.functions,
                    result.classes,
                    result.methods,
                    result.routes,
                    result.cli_arguments,
                    result.constants,
                    result.parse_error,
                ]
            ):
                continue
            f.write(f"### `{path}`\n\n")
            if result.parse_error:
                f.write(f"> AST parse warning: {result.parse_error}\n\n")
            if result.imports:
                f.write("**Imports**\n\n")
                for value in result.imports:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.classes:
                f.write("**Classes**\n\n")
                for value in result.classes:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.functions:
                f.write("**Functions**\n\n")
                for value in result.functions:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.methods:
                f.write("**Methods**\n\n")
                for value in result.methods:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.routes:
                f.write("**Detected API / Web Routes**\n\n")
                for value in result.routes:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.cli_arguments:
                f.write("**Detected CLI Arguments**\n\n")
                for value in result.cli_arguments:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.constants:
                f.write("**Named Constants**\n\n")
                for value in result.constants:
                    f.write(f"- `{value}`\n")
                f.write("\n")

    if generic_results:
        f.write("## JavaScript / TypeScript / PHP Code Map\n\n")
        for path, result in generic_results.items():
            f.write(f"### `{path}`\n\n")
            if result.imports:
                f.write("**Imports / Uses**\n\n")
                for value in result.imports:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.symbols:
                f.write("**Detected Symbols**\n\n")
                for value in result.symbols:
                    f.write(f"- `{value}`\n")
                f.write("\n")
            if result.routes:
                f.write("**Detected Routes**\n\n")
                for value in result.routes:
                    f.write(f"- `{markdown_escape(value)}`\n")
                f.write("\n")
            if result.env_vars:
                f.write("**Environment Variables**\n\n")
                for value in result.env_vars:
                    f.write(f"- `{value}`\n")
                f.write("\n")

    f.write("## TODO / FIXME / Technical-Debt Notes\n\n")
    if todos:
        f.write("| Type | File | Line | Note |\n|---|---|---:|---|\n")
        for path, line, kind, note in todos:
            f.write(
                f"| {kind} | `{markdown_escape(path)}` | {line} | {markdown_escape(note or '—')} |\n"
            )
    else:
        f.write("No TODO/FIXME/HACK/XXX/BUG markers were detected.\n")
    f.write("\n")

    if show_source:
        f.write("## Source Files\n\n")
        for record in records:
            f.write(f"### `{record.relative}`\n\n")
            content = redact_content(record.path, record.text, show_secrets)
            fence = choose_fence(content)
            f.write(f"{fence}{record.language}\n")
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")
            f.write(f"{fence}\n\n")


def generate_documentation(
    root_dirs: list[str],
    output_file: str,
    include_extensions: Optional[list[str]] = None,
    ignore_dirs: Optional[list[str]] = None,
    max_file_kb: int = 1024,
    include_all_text: bool = False,
    show_source: bool = True,
    show_secrets: bool = False,
) -> None:
    output_path = Path(output_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ext_filter: Optional[set[str]] = None
    if include_extensions:
        ext_filter = set()
        for value in include_extensions:
            normalized = normalize_extension(value)
            ext_filter.add(normalized)
            ext_filter.add(value)

    ignored = set(DEFAULT_IGNORE_DIRS)
    if ignore_dirs:
        ignored.update(ignore_dirs)

    project_data = []
    for root_dir in root_dirs:
        root = Path(root_dir).expanduser().resolve()
        records, skipped = collect_files(
            root=root,
            ignore_dirs=ignored,
            include_extensions=ext_filter,
            include_all_text=include_all_text,
            max_bytes=max_file_kb * 1024,
            output_file=output_path,
        )
        project_data.append((root, records, skipped))

    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write("# Project Knowledge Snapshot\n\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(
            "> This document is generated by static inspection. It does not execute project code. "
            "Secret-like values and `.env` values are redacted by default.\n\n"
        )

        f.write("## Contents\n\n")
        for index, (root, _, _) in enumerate(project_data, 1):
            label = f"{index}. {root.name}" if len(project_data) > 1 else root.name
            f.write(f"- [{label}](#{slugify(label)})\n")
        f.write("\n---\n\n")

        for index, (root, records, skipped) in enumerate(project_data, 1):
            write_project_report(
                f,
                root,
                records,
                skipped,
                show_source=show_source,
                show_secrets=show_secrets,
                project_number=index if len(project_data) > 1 else None,
            )
            if index < len(project_data):
                f.write("\n---\n\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a comprehensive Markdown snapshot of one or more code projects, "
            "including project structure, code-map metadata, dependencies and source files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_project_docs.py -p ./my-project -o project_context.md
  python generate_project_docs.py -p ./api ./frontend -o full_context.md
  python generate_project_docs.py -p . -o context.md --include-ext py ts tsx json yaml sql
  python generate_project_docs.py -p . -o context.md --no-source
  python generate_project_docs.py -p . -o context.md --max-file-kb 2048
  python generate_project_docs.py -p . -o context.md --ignore migrations storage

Security:
  Secret-like values and .env values are redacted by default.
  Use --show-secrets only if you explicitly want raw secret values in the Markdown.
        """,
    )

    parser.add_argument(
        "-p",
        "--path",
        required=True,
        nargs="+",
        help="One or more project root directories.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="project_knowledge.md",
        help="Output Markdown path (default: project_knowledge.md).",
    )
    parser.add_argument(
        "-i",
        "--include-ext",
        nargs="+",
        help=(
            "Optional extension/name filter, e.g. py ts tsx json yaml SQL. "
            "Special project files are still included."
        ),
    )
    parser.add_argument(
        "--ignore",
        nargs="+",
        help="Additional directory names to ignore.",
    )
    parser.add_argument(
        "--max-file-kb",
        type=int,
        default=1024,
        help="Maximum size of an individual text file to include (default: 1024 KiB).",
    )
    parser.add_argument(
        "--all-text",
        action="store_true",
        help="Try to include every non-binary text file, not only known source/config types.",
    )
    parser.add_argument(
        "--no-source",
        action="store_true",
        help="Generate only the analyzed project map, without full source file contents.",
    )
    parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Do not redact .env or obvious secret-like values. Use with care.",
    )

    args = parser.parse_args()

    valid_paths: list[str] = []
    for raw_path in args.path:
        path = Path(raw_path).expanduser()
        if not path.exists():
            print(f"Warning: '{raw_path}' does not exist and will be skipped.")
            continue
        if not path.is_dir():
            print(f"Warning: '{raw_path}' is not a directory and will be skipped.")
            continue
        valid_paths.append(str(path))

    if not valid_paths:
        parser.error("No valid project directories were provided.")
    if args.max_file_kb <= 0:
        parser.error("--max-file-kb must be greater than zero.")

    print(f"Generating documentation for {len(valid_paths)} project(s)...")
    for path in valid_paths:
        print(f"  - {Path(path).resolve()}")
    print(f"Output: {Path(args.output).expanduser().resolve()}")

    generate_documentation(
        root_dirs=valid_paths,
        output_file=args.output,
        include_extensions=args.include_ext,
        ignore_dirs=args.ignore,
        max_file_kb=args.max_file_kb,
        include_all_text=args.all_text,
        show_source=not args.no_source,
        show_secrets=args.show_secrets,
    )

    print("Documentation generated successfully.")


if __name__ == "__main__":
    main()
