import { Outlet } from "react-router";

export default function BaseLayout() {
  return (
    <div className="min-h-svh">
      <header className="border-b">
        <div className="container mx-auto px-4 py-3 font-heading font-medium">
          Tutor dashboard
        </div>
      </header>
      <main className="container mx-auto px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
