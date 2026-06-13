import { Outlet } from "react-router-dom";

import { Topbar } from "./Topbar";

export function AppLayout() {
  return (
    <div className="app">
      <Topbar />

      <main className="page">
        <div className="page__container container container_center">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
