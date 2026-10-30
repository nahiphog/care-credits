export const dashboardPaths = {
  Overview: '/overview',
  'My Credits': '/my-credits',
  Discover: '/discover',
  Events: '/events',
  Certificates: '/certificates',
  'About credits': '/about-credits',
  Settings: '/settings',
} as const;

export type DashboardPage = keyof typeof dashboardPaths;

export const loginPath = '/log_in';
export const signupPath = '/sign_up';

export function dashboardReturnPath(pathname: string | null): string {
  // Only known dashboard pages can be a post-login destination.
  return pathname !== null && (pathname === '/' || Object.values(dashboardPaths).some((path) => path === pathname))
    ? pathname : '/';
}

export function authPathFor(path: typeof loginPath | typeof signupPath, returnTo: string | null): string {
  const next = dashboardReturnPath(returnTo);
  return next === '/' ? path : `${path}?next=${encodeURIComponent(next)}`;
}

export function dashboardPageFromPath(pathname: string): DashboardPage {
  if (pathname === '/') return 'Overview';
  return (Object.keys(dashboardPaths) as DashboardPage[])
    .find((page) => dashboardPaths[page] === pathname) ?? 'Discover';
}
