import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import CorridasInicio from "@/pages/CorridasInicio";
import Corrida from "@/pages/Corrida";
import Insumos from "@/pages/Insumos";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/corridas" replace />} />
        <Route path="corridas" element={<CorridasInicio />} />
        <Route path="corridas/:id" element={<Corrida />} />
        <Route path="insumos" element={<Insumos />} />
      </Route>
    </Routes>
  );
}
