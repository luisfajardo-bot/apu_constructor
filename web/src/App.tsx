import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import { RutaProtegida, RequiereRol } from "@/components/rutas";
import Login from "@/pages/Login";
import DefinirClave from "@/pages/DefinirClave";
import MisCorridas from "@/pages/MisCorridas";
import CorridasInicio from "@/pages/CorridasInicio";
import Corrida from "@/pages/Corrida";
import Insumos from "@/pages/Insumos";
import Apus from "@/pages/Apus";
import Usuarios from "@/pages/Usuarios";
import { ArmadoVivoProvider } from "@/lib/armado";

export default function App() {
  return (
    <ArmadoVivoProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/definir-clave" element={<DefinirClave />} />
        <Route element={<RutaProtegida />}>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/corridas" replace />} />
            <Route path="corridas" element={<MisCorridas />} />
            <Route path="corridas/nueva" element={<CorridasInicio />} />
            <Route path="corridas/:id" element={<Corrida />} />
            <Route path="insumos" element={<Insumos />} />
            <Route path="apus" element={<Apus />} />
            <Route element={<RequiereRol minimo="admin" />}>
              <Route path="usuarios" element={<Usuarios />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </ArmadoVivoProvider>
  );
}
