# Project Knowledge Snapshot Generator

A standalone Python tool for generating a comprehensive Markdown snapshot of one or more software projects. In addition to the directory tree and source code, the generated document collects important project information such as dependencies, functions, classes, routes, environment variables, project commands, TODOs, and Git metadata into a single file.

This tool is especially useful for:

- Transferring project context to ChatGPT, Claude, Gemini, Codex, or other coding agents
- Onboarding a new developer to an existing codebase
- Creating a documented snapshot of the current project state
- Performing quick code reviews and architecture inspections
- Preparing context for LLM-assisted analysis, refactoring, or debugging
- Documenting backend and frontend projects in a single Markdown file

---

## Features

`generate_project_docs.py` performs static analysis only and does **not** execute the project's code.

Main capabilities include:

- Generate a project directory tree
- Build a file index containing language, line count, and file size
- Calculate language and source-line statistics
- Detect key project files
- Extract project dependencies and scripts
- Analyze Python files using the built-in AST module
- Detect Python classes, functions, methods, decorators, and signatures
- Extract imports
- Detect API/web routes in Python, JavaScript/TypeScript, and PHP
- Extract `argparse` command-line arguments
- Detect environment variables
- Detect Python constants
- Perform lightweight JavaScript, TypeScript, and PHP analysis
- Extract TODO, FIXME, HACK, BUG, and XXX notes with file names and line numbers
- Extract Git branch, commit, and remote information when available
- Support multiple projects in a single Markdown document
- Include the full source code of selected files
- Skip binary files
- Enforce a maximum input file size
- Redact `.env` values and likely secrets by default
- Require no third-party Python packages

---

## Requirements

- Python 3.10 or newer
- Git is optional. If available, repository metadata can be added to the report.

The script has no external Python dependencies and uses only the Python Standard Library.

Check your Python version with:

```bash
python --version
```

or, on some systems:

```bash
python3 --version
```

---

## Installation

No package installation is required. You only need the following file on your system:

```text
generate_project_docs.py
```

Then run it directly with Python.

---

## Quick Start

Generate documentation for a single project:

```bash
python generate_project_docs.py -p ./my-project -o project_context.md
```

The result will be saved to:

```text
project_context.md
```

If `-o` is omitted, the default output file is:

```text
project_knowledge.md
```

---

## Windows Example

### PowerShell

```powershell
python .\generate_project_docs.py `
  -p "D:\Projects\MyProject" `
  -o "D:\Projects\MyProject\project_context.md"
```

You can also run it on a single line:

```powershell
python .\generate_project_docs.py -p "D:\Projects\MyProject" -o "D:\Projects\MyProject\project_context.md"
```

---

## Linux and macOS Example

```bash
python3 generate_project_docs.py \
  -p ~/projects/my-project \
  -o ~/projects/project_context.md
```

---

## Documenting Multiple Projects in One File

You can pass multiple project roots at once. This is especially useful when the backend and frontend are stored separately.

```bash
python generate_project_docs.py \
  -p ./backend ./frontend \
  -o full_project_context.md
```

Each project is placed in its own section of the generated Markdown file.

---

## Command-Line Options

| Option | Description |
|---|---|
| `-p`, `--path` | One or more project root paths. Required. |
| `-o`, `--output` | Output Markdown file path. |
| `-i`, `--include-ext` | Restrict documented files to specified extensions or exact file names. |
| `--ignore` | Add custom directories to the default ignore list. |
| `--max-file-kb` | Maximum text file size to include in the report. Default: `1024 KiB`. |
| `--all-text` | Attempt to include all non-binary text files. |
| `--no-source` | Generate analysis and code maps without embedding full source files. |
| `--show-secrets` | Disable redaction and show secret values. Use with caution. |

Display command-line help with:

```bash
python generate_project_docs.py --help
```

---

## Restricting File Types

For example, if you only want Python, TypeScript, TSX, JSON, YAML, and SQL files:

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --include-ext py ts tsx json yaml sql
```

Important project files such as `package.json`, `Dockerfile`, and similar files may still be detected according to the tool's internal rules.

---

## Including All Text Files

By default, the tool focuses on common source-code and configuration files. To attempt to include every non-binary text file in the project:

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --all-text
```

Files detected as binary are excluded from the report.

---

## Generating a Report Without Full Source Code

If you only need architecture and extracted project information, and do not want to embed the complete source code:

```bash
python generate_project_docs.py \
  -p . \
  -o project_map.md \
  --no-source
```

This mode can significantly reduce context size for large projects.

---

## Setting the Maximum File Size

By default, files larger than `1024 KiB` are not read.

To increase the limit to 2 MiB:

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --max-file-kb 2048
```

Skipped files and the reason they were skipped are listed in the generated report.

---

## Ignoring Additional Directories

The tool ignores several common directories by default, including:

```text
.git
.venv
venv
node_modules
vendor
dist
build
coverage
.next
.nuxt
__pycache__
logs
tmp
```

To add more directories to the ignore list:

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --ignore migrations storage generated
```

The custom directories are added to the default ignore list.

---

## Output Structure

The generated Markdown file typically contains sections like these:

```text
Project Knowledge Snapshot
│
├── Contents
│
├── Project Overview
│   ├── Project root
│   ├── Documented files
│   ├── Documented lines
│   ├── Documented size
│   └── Git information
│
├── Language / File Statistics
├── Key Project Files
├── Project Structure
├── File Index
├── Skipped Files
├── Dependencies and Project Commands
├── Environment Variables
├── Python Code Map
├── JavaScript / TypeScript / PHP Code Map
├── TODO / FIXME / Technical-Debt Notes
└── Source Files
```

Some sections are generated only when relevant information exists in the project.

---

## Python Analysis

Python files are analyzed using the built-in `ast` module. The tool can extract information from code such as:

```python
class UserService(BaseService):
    ...

async def create_user(name: str, email: str) -> User:
    ...
```

It can detect:

- Imports
- Classes
- Functions
- Methods
- Decorators
- Type annotations
- Function signatures
- Environment variables
- Constants
- Selected web/API routes
- Arguments defined with `argparse`

If a Python file contains a syntax error, the tool records a parse warning in the report instead of stopping execution.

---

## JavaScript and TypeScript Analysis

JavaScript and TypeScript analysis is lighter than Python analysis and is primarily based on pattern matching.

The tool can detect patterns such as:

- `import`
- `require()`
- Functions
- Classes
- Some arrow functions
- `process.env.*`
- `import.meta.env.*`
- Common Express/Router routes

Example:

```javascript
router.get('/users', getUsers)
```

may appear in the report approximately as:

```text
GET /users
```

---

## PHP and Laravel Analysis

For PHP files, the tool extracts selected important structures, including:

- `use` statements
- Classes
- Interfaces
- Traits
- Functions
- `env()` variables
- Common Laravel routes

Example:

```php
Route::get('/users', [UserController::class, 'index']);
```

The corresponding route is included in the code map.

---

## Dependencies and Project Commands

The tool can extract information from several common project manifests.

### Python

From files such as:

```text
requirements.txt
requirements-dev.txt
```

### Node.js

From:

```text
package.json
```

including:

- `dependencies`
- `devDependencies`
- `peerDependencies`
- `scripts`

### PHP / Composer

From:

```text
composer.json
```

including:

- `require`
- `require-dev`

### Go

From:

```text
go.mod
```

---

## Environment Variables

Environment variable names are extracted from several common patterns, including:

```python
os.getenv("DATABASE_URL")
os.environ["API_KEY"]
```

```javascript
process.env.API_URL
```

```php
env('APP_KEY')
```

Only the variable names are listed in the summary. Their values are not displayed there.

---

## Security and Redaction

By default, the tool attempts to remove obvious secrets from the source snapshot.

For `.env` files, variable values are transformed into a form like:

```env
DATABASE_URL=<REDACTED>
API_KEY=<REDACTED>
SECRET_KEY=<REDACTED>
```

It also masks selected values associated with names such as:

```text
password
secret
token
api_key
private_key
client_secret
```

### Important Security Note

Secret redaction is **best effort only** and cannot guarantee detection of every possible credential or sensitive value.

Always review the generated Markdown before sending it to an external service, publishing it in a public repository, or sharing it with another person.

To disable secret masking, only when absolutely necessary, use:

```bash
--show-secrets
```

Example:

```bash
python generate_project_docs.py \
  -p . \
  -o private_context.md \
  --show-secrets
```

Using this option is **not recommended** for files that will be uploaded or shared.

---

## Git Information

If the project is a Git repository and the `git` command is available, the tool attempts to include:

- Current branch
- Short commit hash
- Remote origin URL

If Git is unavailable or the target directory is not a Git repository, the tool continues without failing.

---

## Using the Tool with LLMs and Coding Agents

One of the main use cases is to create a single, structured project context file.

Example:

```bash
python generate_project_docs.py \
  -p ./backend ./frontend \
  -o llm_project_context.md
```

You can then provide `llm_project_context.md` to an AI model and ask questions such as:

```text
Review this project and explain its architecture.
```

```text
Identify the main dependencies and coupling points in the codebase.
```

```text
Prioritize the most important TODOs and technical-debt items.
```

```text
Based on the current structure, which files should be changed to add authentication?
```

For very large projects, it is recommended to start with `--no-source` and include full source code only when necessary.

---

## Usage Examples

### Full Project Snapshot

```bash
python generate_project_docs.py -p . -o project_context.md
```

### Python Only

```bash
python generate_project_docs.py -p . -o python_context.md --include-ext py
```

### Backend and Frontend

```bash
python generate_project_docs.py \
  -p ./backend ./frontend \
  -o full_context.md
```

### Code Map Only, Without Source Code

```bash
python generate_project_docs.py \
  -p . \
  -o code_map.md \
  --no-source
```

### Include All Text Files

```bash
python generate_project_docs.py \
  -p . \
  -o all_text_context.md \
  --all-text
```

### Ignore Custom Directories

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --ignore storage cache generated
```

### Increase File-Size Limit

```bash
python generate_project_docs.py \
  -p . \
  -o project_context.md \
  --max-file-kb 4096
```

---

## Limitations

This tool is a static documentation generator and is not a replacement for a language-specific parser or full static-analysis framework.

Current limitations include:

- Python analysis is more accurate than JavaScript/TypeScript/PHP analysis.
- JS/TS/PHP analysis is largely based on regular expressions.
- Dynamic routes may not always be detected completely.
- Not every package ecosystem is currently analyzed.
- Secret detection is not guaranteed to be complete.
- Files larger than the configured limit are skipped.
- Binary files are excluded from the Markdown output.
- Project code is never executed, so runtime behavior is not analyzed.

---

## Recommendations for Large Projects

For large repositories, it is often better to generate context in stages.

Start with the code map only:

```bash
python generate_project_docs.py -p . -o overview.md --no-source
```

Then generate a focused snapshot of important areas:

```bash
python generate_project_docs.py \
  -p ./src ./config \
  -o focused_context.md \
  --include-ext py ts json yaml
```

This approach keeps the resulting Markdown smaller and more useful for LLMs.

---

## Suggested Output File Names

Depending on the intended use, you can use names such as:

```text
project_knowledge.md
project_context.md
project_snapshot.md
codebase_context.md
llm_context.md
architecture_snapshot.md
```

---

## License

No license is currently defined for this tool. If you plan to publish it publicly on GitHub, consider adding a license such as the MIT License.
