import { Routes, Route, Navigate } from "react-router-dom";
import { useState } from "react";
import { loadIdentity, purgeLegacyKeys, type Identity } from "./state/identity";
import { SidebarProvider } from "./state/sidebar";
import SignIn from "./pages/SignIn";
import Onboarding from "./pages/Onboarding";
import MainChat from "./pages/MainChat";
import Settings from "./pages/Settings";

function App() {
  const [identity, setIdentity] = useState<Identity | null>(() => {
    purgeLegacyKeys();
    return loadIdentity();
  });

  if (!identity) {
    return (
      <Routes>
        <Route path="*" element={<SignIn onIdentityCreated={setIdentity} />} />
      </Routes>
    );
  }

  return (
    <SidebarProvider>
      <Routes>
        <Route path="/signin" element={<Navigate to="/" replace />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/" element={<MainChat />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </SidebarProvider>
  );
}

export default App;
