import { AllCommunityModule, ModuleRegistry } from "ag-grid-community";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ModuleRegistry.registerModules([AllCommunityModule]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
