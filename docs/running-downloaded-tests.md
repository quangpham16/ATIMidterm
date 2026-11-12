# Running downloaded tests

1. Sign in to Case Foundry and upload an OpenAPI JSON/YAML file, paste source code,
   or select related Python source files and choose the module to test.
2. Generate and review the test cases and code.
3. Download the matching code file from the saved suite. JSON and CSV downloads
   contain case descriptions and data for review.
4. Run the downloaded tests locally, or add them to your own project's CI.

No GitHub account connection, app registration, or repository permissions are
required. Downloaded tests run independently of Case Foundry and do not call Gemini.

## API tests (Python)

Download **Python** as `test_generated.py`, then install its dependencies:

```powershell
python -m pip install pytest httpx
```

Set your API URL, including any path prefix, and run the downloaded file:

```powershell
$env:API_BASE_URL = "http://localhost:8000/api/v1"
python -m pytest test_generated.py -q
```

Optional configuration:

| Variable | Purpose |
| --- | --- |
| `API_BEARER_TOKEN` | Bearer token for authenticated requests |
| `API_HEADERS_JSON` | JSON object containing API-key or other custom headers |
| `API_ALLOW_MUTATIONS` | Set to `true` to include POST, PUT, PATCH and DELETE requests |
| `API_TIMEOUT_SECONDS` | Request timeout, greater than zero and at most 300; default 15 |

For example, to test authenticated endpoints and requests that change test data:

```powershell
$env:API_BEARER_TOKEN = "<your test token>"
$env:API_ALLOW_MUTATIONS = "true"
python -m pytest test_generated.py -q
```

Use a test environment with appropriate starting data. Requests that change state
are skipped unless enabled. The runner makes actual HTTP requests, checks the
expected status code, and does not follow redirects. Case descriptions can include
body assertions or business rules that you should add after review.

The Python file embeds its case data. Editing the JSON/CSV download alone does
not change the executable tests; update the Python data or generate a fresh suite.

## Python unit tests

### Uploaded Python files

Select your entry module and any Python modules it imports. Use flat `.py` module
filenames, such as `service.py` and `helpers.py`, without folders. Filenames must
use ASCII letters, digits and underscores, cannot start with a digit, and cannot
be Python keywords; `test_generated.py`,
`pytest.py`, and `__main__.py` are reserved by the test runner. Select at most
20 files, each at most 128 KiB, and at most 512 KiB
in total. Adding files preserves earlier selections; remove a file before
uploading a replacement with the same name. Filenames must also be distinct
without regard to case, for compatibility with Windows.

Use either uploaded Python files or pasted source in a suite. You can include an
OpenAPI file with either. The selected entry module is the main target for unit
tests; other uploaded modules provide context for its imports.

Download **Python bundle (.zip)** from the saved suite and extract it. The bundle
contains your source files with their original names, `test_generated.py`, and
run instructions. Keep those names and files together. From the extracted folder:

```powershell
python -m pip install pytest
python -m pytest test_generated.py -q
```

Install any third-party packages your source imports as well. If the suite also
contains API tests, install httpx and set the API variables described above.
Case Foundry generates the tests without executing your uploaded source. Review
the code before running it locally or in CI.

### Pasted Python code

Download **Python** as `test_generated.py`. Save your original source beside it as
`source_under_test.py`. Install pytest and your source code's dependencies:

```powershell
python -m pip install pytest
python -m pytest test_generated.py -q
```

Keep any modules imported by your source available in the same project or Python
environment. Generated unit tests import and call the original source.

## JavaScript and TypeScript unit tests

Download the matching **JavaScript** or **TypeScript** file as
`test_generated.test.js` or `test_generated.test.ts`. Save your source beside it as
`source_under_test.js` or `source_under_test.ts` and export the targets under test.
From your project folder, install Vitest and your code's dependencies:

```powershell
npm install --save-dev vitest
npx vitest run test_generated.test.js
```

Use `test_generated.test.ts` in the command for TypeScript.

## Your own CI

Commit the reviewed downloaded code to your project and run the same pytest or
Vitest command from its CI workflow. Supply API configuration through that CI
system's environment variables and secrets. Case Foundry does not create branches,
pull requests, or workflows in your repositories.
