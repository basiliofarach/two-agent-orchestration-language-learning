import { GraduationCap } from "lucide-react";
import { Link, NavLink, Outlet } from "react-router";

export default function BaseLayout() {
  return (
    <div className="min-h-svh">
      <a
        href="#main"
        className="sr-only rounded-lg bg-background px-3 py-2 focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/80">
        <div className="container mx-auto flex items-center justify-between gap-4 px-4 py-3">
          <Link
            to="/"
            className="flex items-center gap-2 font-heading font-medium"
          >
            <GraduationCap aria-hidden="true" className="size-5" />
            Tutor dashboard
          </Link>
          <nav aria-label="Primary">
            <NavLink
              to="/"
              end
              className="text-sm underline-offset-4 hover:underline aria-[current=page]:font-medium aria-[current=page]:underline"
            >
              Sessions
            </NavLink>
          </nav>
        </div>
      </header>
      <main
        id="main"
        tabIndex={-1}
        className="container mx-auto px-4 py-6 outline-none"
      >
        <Outlet />
      </main>
    </div>
  );
}
