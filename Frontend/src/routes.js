import { matchPath } from "react-router";

export const projectPath = (id) => `/projects/${encodeURIComponent(id)}`;
export const suitePath = (id) => `/suites/${encodeURIComponent(id)}`;

export function returnPath(from) {
  if (typeof from !== "string" || !from.startsWith("/") || from.startsWith("//")) return "/";
  const pathname = from.split(/[?#]/)[0];
  return pathname === "/" || matchPath("/projects/:projectId", pathname) || matchPath("/suites/:suiteId", pathname)
    ? from : "/";
}
