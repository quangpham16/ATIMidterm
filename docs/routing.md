# Frontend routing

The frontend uses React Router with browser history. Navigation updates the URL
without reloading the document, and browser Back/Forward restores the corresponding
view. Each project or suite URL loads its data from the authenticated backend, so
direct links and refreshing work without first opening the item in the sidebar.

| URL | View |
| --- | --- |
| `/` | All saved suites and the new-suite editor |
| `/login` | Sign in |
| `/register` | Create an account |
| `/projects/:projectId` | Project-filtered history and its new-suite editor |
| `/suites/:suiteId` | Saved suite, test cases, code, and downloads |
| Any unmatched URL | Page not found, with a link back |

Workspace, project, and suite routes require a valid session. If you open one
while signed out, the app redirects to `/login` and returns to the requested URL
after signing in. Switching to registration preserves that destination. Signing
out returns to `/login`.

Creating a project navigates to its project URL. Generating a suite navigates to
its suite URL. Deleting an opened suite replaces its history entry with its
project URL, or `/` when the suite has no project.

Missing or inaccessible records show the backend's error and offer retry and
workspace links. Requests are aborted when their view unmounts, preventing a late
response from replacing the data for a newer URL.

## Implementation

- `Frontend/src/main.jsx` wraps the app in `BrowserRouter`.
- `Frontend/src/App.jsx` declares routes, checks the session, and loads the route's
  project/suite IDs. Sidebar navigation uses `Link` elements, which also support
  opening an item in a new tab.
- `Frontend/src/routes.js` builds encoded project/suite URLs and validates the
  destination used after sign-in.

Pagination has been removed. `GET /projects` and `GET /testcases/history` return
complete arrays again, with the existing account isolation and project filtering.

## Hosting and refresh

Vite's development and preview servers provide the SPA fallback. A production
frontend host must serve `index.html` for frontend routes that do not correspond
to a static asset. For example, an Nginx frontend-only server can use:

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

Keep backend API routes on their API origin or give their reverse-proxy locations
priority over this fallback. Set `VITE_API_URL` to the backend origin when building
the frontend. The FastAPI app continues to serve the API separately.

## Checks

```powershell
.venv\Scripts\python.exe -m pytest tests -q
cd Frontend
npm test
npm run build
```

`npm test` runs the existing Node tests and the React routing integration tests
under Vitest/jsdom. Backend calls in the routing tests are mocked.

See the [React Router routing guide](https://reactrouter.com/start/declarative/routing)
for the routing APIs used here.
