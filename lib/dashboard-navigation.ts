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

export function dashboardPageFromPath(pathname: string): DashboardPage {
  if (pathname === '/') return 'Overview';
  return (Object.keys(dashboardPaths) as DashboardPage[])
    .find((page) => dashboardPaths[page] === pathname) ?? 'Discover';
}
