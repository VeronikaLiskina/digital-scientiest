import React from "react";
import ReactDOM from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { AppLayout } from "./components/layout/AppLayout";
import { ReaderLayout } from "./components/layout/ReaderLayout";

import { AuthorsPage } from "./pages/AuthorsPage";
import { FilesPage } from "./pages/FilesPage";
import { HomePage } from "./pages/HomePage";
import { KeywordsPage } from "./pages/KeywordsPage";
import { ProcessingLogsPage } from "./pages/ProcessingLogsPage";
import { PublicationBulkImportPage } from "./pages/PublicationBulkImportPage";
import { PublicationCreatePage } from "./pages/PublicationCreatePage";
import { PublicationDetailsPage } from "./pages/PublicationDetailsPage";
import { PublicationEditPage } from "./pages/PublicationEditPage";
import { PublicationsPage } from "./pages/PublicationsPage";
import { TopicsPage } from "./pages/TopicsPage";

import { ReaderAssistantPage } from "./pages/reader/ReaderAssistantPage";
import { ReaderHomePage } from "./pages/reader/ReaderHomePage";
import { ReaderPublicationDetailsPage } from "./pages/reader/ReaderPublicationDetailsPage";
import { ReaderPublicationsPage } from "./pages/reader/ReaderPublicationsPage";

import "./scss/main.scss";

const router = createBrowserRouter([
  {
    path: "/",
    element: <ReaderLayout />,
    children: [
      { index: true, element: <ReaderHomePage /> },
      { path: "publications", element: <ReaderPublicationsPage /> },
      {
        path: "publications/:publicationId",
        element: <ReaderPublicationDetailsPage />,
      },
      { path: "assistant", element: <ReaderAssistantPage /> },
    ],
  },

  {
    path: "/admin",
    element: <AppLayout />,
    children: [
      { index: true, element: <HomePage /> },

      { path: "publications", element: <PublicationsPage /> },
      { path: "publications/new", element: <PublicationCreatePage /> },
      { path: "publications/import", element: <PublicationBulkImportPage /> },

      {
        path: "publications/:publicationId/edit",
        element: <PublicationEditPage />,
      },

      {
        path: "publications/:publicationId",
        element: <PublicationDetailsPage />,
      },

      { path: "files", element: <FilesPage /> },
      { path: "authors", element: <AuthorsPage /> },
      { path: "topics", element: <TopicsPage /> },
      { path: "keywords", element: <KeywordsPage /> },
      { path: "processing-logs", element: <ProcessingLogsPage /> },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
