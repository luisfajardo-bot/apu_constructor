import { apiGet, apiPatch, apiPost } from "@/api/client";

export type Rol = "admin" | "editor" | "consulta";
export type Yo = { email: string; rol: Rol; nombre: string };
export type Usuario = {
  user_id: string; email: string; rol: Rol; estado: "activo" | "inactivo"; nombre: string;
};

export const getYo = () => apiGet<Yo>("/yo");
export const listarUsuarios = () => apiGet<Usuario[]>("/usuarios");
export const invitarUsuario = (email: string, rol: Rol, nombre: string) =>
  apiPost<{ user_id: string }>("/usuarios/invitar", { email, rol, nombre });
export const cambiarRol = (userId: string, rol: Rol) =>
  apiPatch(`/usuarios/${userId}/rol`, { rol });
export const cambiarEstado = (userId: string, estado: "activo" | "inactivo") =>
  apiPatch(`/usuarios/${userId}/estado`, { estado });
