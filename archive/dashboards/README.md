# Archived dashboard explorations

V2, V3, V4, V5 and the former version-picker landing page are preserved here.
They are outside the Next.js app directory and are not public routes or imported
by the active frontend. The original dashboard loads directly at `/`, without
a version label. Old V1–V5 URLs redirect to `/`, so saved links continue to work.

To restore a version later, move its directory into `app/` and remove that
version's redirect from `next.config.ts`. The version-picker files can similarly
be restored to `app/` if comparison navigation is wanted again.
