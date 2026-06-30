import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import MisCorridas from "@/pages/MisCorridas";
import CorridasInicio from "@/pages/CorridasInicio";
import Corrida from "@/pages/Corrida";
import Insumos from "@/pages/Insumos";
import Apus from "@/pages/Apus";
import { ArmadoVivoProvider } from "@/lib/armado";

export default function App() {
  return (
    <ArmadoVivoProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/corridas" replace />} />
          <Route path="corridas" element={<MisCorridas />} />
          <Route path="corridas/nueva" element={<CorridasInicio />} />
          <Route path="corridas/:id" element={<Corrida />} />
          <Route path="insumos" element={<Insumos />} />
          <Route path="apus" element={<Apus />} />
        </Route>
      </Routes>
    </ArmadoVivoProvider>
  );
}
