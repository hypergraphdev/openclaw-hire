import { BrowserRouter, Route, Routes } from "react-router-dom";

import { NavBar } from "./components/NavBar";
import { PhoneFrame } from "./components/PhoneFrame";
import { EmployeeDetailPage } from "./pages/EmployeeDetailPage";
import { EmployeeListPage } from "./pages/EmployeeListPage";
import { HireEmployeePage } from "./pages/HireEmployeePage";
import { RegisterPage } from "./pages/RegisterPage";

export default function App() {
  return (
    <BrowserRouter>
      <PhoneFrame>
        <NavBar />
        <Routes>
          <Route path="/" element={<RegisterPage />} />
          <Route path="/hire" element={<HireEmployeePage />} />
          <Route path="/employees" element={<EmployeeListPage />} />
          <Route path="/employees/:employeeId" element={<EmployeeDetailPage />} />
        </Routes>
      </PhoneFrame>
    </BrowserRouter>
  );
}
