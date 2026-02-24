import "./assets/base.css";
import "./assets/main.css";

// Mol* CSS는 App.tsx의 AppContent에서 theme에 따라 동적으로 로드됨

import { createRoot } from "react-dom/client";
import App from "./App";

createRoot(document.getElementById("root")!).render(<App />);
