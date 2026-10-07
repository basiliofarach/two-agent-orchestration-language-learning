import { Link, Outlet } from "react-router";

export default function BaseLayout() {
  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="container mx-auto flex items-baseline justify-between px-4 py-3">
          <p className="font-heading font-medium">Tutor dashboard</p>
          <Link to="/" className="text-sm underline">
            Sessions
          </Link>
        </div>
      </header>
      <main className="container mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
