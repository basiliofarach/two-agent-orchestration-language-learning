import type { RouteConfig } from "@react-router/dev/routes";
import { flatRoutes } from "@react-router/fs-routes";

// File-based flat routes (DEC-0008): `_base.tsx` is the pathless tutor shell,
// `_base._index.tsx` is `/`, `_base.sessions.$sessionId/route.tsx` is
// `/sessions/:sessionId`.
export default flatRoutes() satisfies RouteConfig;
