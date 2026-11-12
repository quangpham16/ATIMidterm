# Test Case Gen

Generate API test cases from OpenAPI files and unit tests from pasted code or Python source files, with private accounts, saved suites, and projects.

## Generate, download and run tests

Upload an OpenAPI file, paste source code, or select related Python modules and
choose the module to test. Generate and review your cases, then download Python,
JavaScript/TypeScript, JSON or CSV from the saved suite. Python file uploads also
include a ZIP download containing the original modules and generated tests. Run the
downloaded test code in your own environment or CI. No GitHub connection or app
registration is required.

See [Running downloaded tests](docs/running-downloaded-tests.md) for commands and
configuration. JSON and CSV contain case data; use the matching code download to
execute tests.

Python uploads keep their original filenames so imports between modules work.
Choose up to 20 flat `.py` files (128 KiB each, 512 KiB total); filenames must be
ASCII module names using letters, digits and underscores, with no leading digit,
such as `helpers.py`; `test_generated.py`, `pytest.py`, and
`__main__.py` are reserved by the test runner.
Use either pasted source or source files in one suite. An OpenAPI file can be
included with either input. Extract the ZIP and run the tests locally; uploaded
source is not executed by the web app.

The frontend has URLs for sign-in, registration, projects, and saved suites. See
[Frontend routing](docs/routing.md) for routes, direct links, and hosting setup.

Downloaded API tests make actual HTTP requests when run with pytest. Configure
`API_BASE_URL` and optional `API_BEARER_TOKEN` / `API_HEADERS_JSON`. Requests that
change data require `API_ALLOW_MUTATIONS=true`. The web app does not execute these
requests during generation. This repository's own CI continues to mock external
services.

## Automatic checks on GitHub

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every push, pull request, merge-queue update, and manual workflow run.

The backend and frontend checks run in parallel:

- **Backend tests:** install the Python dependencies, check dependency compatibility, run the test suite, and verify the FastAPI application starts and `/health` responds successfully.
- **Frontend tests and build:** install packages from the lockfile using `npm ci`, run the frontend tests, and build the app.
- **CI passed:** succeeds only when both jobs succeed. Use this check in your GitHub branch rules to require passing checks before merging.

The workflow uses Python 3.14 and Node.js 24. Tests mock Gemini, so no Gemini key or deployment secrets are needed. The startup check uses `data/ci.db` in the disposable runner checkout; individual tests use isolated temporary databases.

Git tracks the frontend folder as `Frontend` with a capital F. The workflow uses that spelling so it works on GitHub's Linux runners; Windows may display the local folder as `frontend`.

After a run, open **Actions > CI** in your GitHub repository. Failed steps show their logs. The backend JUnit report and successful frontend build are available as downloadable artifacts for seven days.

To publish the workflow with the repository's existing GitHub remote:

```powershell
git add .github/workflows/ci.yml .gitignore requirements-dev.txt README.md
git commit -m "Add automated backend and frontend CI checks"
git push -u origin HEAD
```

Once the first GitHub run completes, add **CI passed** as a required status check in your branch rules if you want failed checks to prevent merging. See [GitHub's required status check documentation](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

The workflow produces a tested frontend build. Automatic deployment can be connected when a hosting target is selected.

## Run the same checks locally

Install dependencies in your Python virtual environment, then run:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip check
python -m pytest tests -q

cd Frontend
npm ci
npm test
npm run build
```

Commit application source files and `Frontend/package-lock.json`. Installed `node_modules`, generated `dist`, virtual environments, local configuration, and database files are ignored.
