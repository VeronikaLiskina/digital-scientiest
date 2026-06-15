import { Outlet } from "react-router-dom";

import { Topbar } from "./Topbar";

export function ReaderLayout() {
  return (
    <div className="app reader-layout">
      <Topbar role="Учёный" homeTo="/" />

      <main className="page">
        <div className="page__container container container_center">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
