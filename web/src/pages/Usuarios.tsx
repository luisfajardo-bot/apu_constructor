import { useEffect, useState } from "react";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";
import {
  listarUsuarios, invitarUsuario, cambiarRol, cambiarEstado,
  type Usuario, type Rol,
} from "@/api/usuarios";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const ROLES: Rol[] = ["consulta", "editor", "admin"];

const ROL_LABEL: Record<Rol, string> = {
  admin: "admin",
  editor: "editor",
  consulta: "consulta",
};

const ROL_BADGE: Record<Rol, "default" | "secondary" | "outline"> = {
  admin: "default",
  editor: "secondary",
  consulta: "outline",
};

export default function Usuarios() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [cargando, setCargando] = useState(false);
  const [invitarOpen, setInvitarOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [nombre, setNombre] = useState("");
  const [rol, setRol] = useState<Rol>("consulta");
  const [enviando, setEnviando] = useState(false);

  const cargar = () => {
    setCargando(true);
    return listarUsuarios()
      .then(setUsuarios)
      .catch((e) => toast.error(e instanceof Error ? e.message : "No se pudo cargar la lista de usuarios."))
      .finally(() => setCargando(false));
  };

  useEffect(() => {
    cargar();
  }, []);

  async function invitar(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      await invitarUsuario(email, rol, nombre);
      toast.success(`Invitación enviada a ${email}.`);
      setEmail("");
      setNombre("");
      setRol("consulta");
      setInvitarOpen(false);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo invitar al usuario.");
    } finally {
      setEnviando(false);
    }
  }

  async function setRolDe(u: Usuario, nuevo: Rol) {
    if (nuevo === u.rol) return;
    try {
      await cambiarRol(u.user_id, nuevo);
      toast.success(`Rol de ${u.email} actualizado a ${ROL_LABEL[nuevo]}.`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo cambiar el rol.");
    }
  }

  async function setEstadoDe(u: Usuario, estado: "activo" | "inactivo") {
    try {
      await cambiarEstado(u.user_id, estado);
      toast.success(estado === "activo" ? `${u.email} activado.` : `${u.email} desactivado.`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo cambiar el estado.");
    }
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b">
        <h2 className="text-sm font-semibold">Usuarios</h2>
        {cargando && (
          <span className="text-xs text-muted-foreground animate-pulse">cargando…</span>
        )}
        <div className="ml-auto">
          <Button size="xs" variant="outline" onClick={() => setInvitarOpen(true)}>
            <UserPlus data-icon="inline-start" />
            Invitar usuario
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b">
                Correo
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-40">
                Nombre
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-36">
                Rol
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-24">
                Estado
              </th>
              <th className="px-2 py-1.5 text-right font-medium text-muted-foreground border-b w-32">
              </th>
            </tr>
          </thead>
          <tbody>
            {usuarios.map((u) => (
              <tr key={u.user_id} className="hover:bg-muted/40 even:bg-muted/10">
                <td className="px-2 py-1">{u.email}</td>
                <td className="px-2 py-1 text-muted-foreground truncate">{u.nombre}</td>
                <td className="px-1 py-0.5">
                  <Select value={u.rol} onValueChange={(v) => setRolDe(u, v as Rol)}>
                    <SelectTrigger size="sm" className="h-6 text-xs w-full">
                      <Badge variant={ROL_BADGE[u.rol]}>
                        <SelectValue />
                      </Badge>
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map((r) => (
                        <SelectItem key={r} value={r}>{ROL_LABEL[r]}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-2 py-1">
                  <Badge variant={u.estado === "activo" ? "secondary" : "outline"}>
                    {u.estado}
                  </Badge>
                </td>
                <td className="px-2 py-1 text-right">
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => setEstadoDe(u, u.estado === "activo" ? "inactivo" : "activo")}
                  >
                    {u.estado === "activo" ? "Desactivar" : "Activar"}
                  </Button>
                </td>
              </tr>
            ))}
            {usuarios.length === 0 && !cargando && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground text-sm">
                  Sin usuarios registrados
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Dialog open={invitarOpen} onOpenChange={setInvitarOpen}>
        <DialogContent>
          <form onSubmit={invitar}>
            <DialogHeader>
              <DialogTitle>Invitar usuario</DialogTitle>
            </DialogHeader>
            <div className="flex flex-col gap-3 py-3">
              <div className="flex flex-col gap-1">
                <label htmlFor="invitar-email" className="text-xs font-medium text-muted-foreground">
                  Correo
                </label>
                <Input
                  id="invitar-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoFocus
                  placeholder="nombre@obra.co"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="invitar-nombre" className="text-xs font-medium text-muted-foreground">
                  Nombre
                </label>
                <Input
                  id="invitar-nombre"
                  value={nombre}
                  onChange={(e) => setNombre(e.target.value)}
                  placeholder="Nombre completo"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label htmlFor="invitar-rol" className="text-xs font-medium text-muted-foreground">
                  Rol
                </label>
                <Select value={rol} onValueChange={(v) => setRol(v as Rol)}>
                  <SelectTrigger id="invitar-rol" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROLES.map((r) => (
                      <SelectItem key={r} value={r}>{ROL_LABEL[r]}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setInvitarOpen(false)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={enviando}>
                {enviando ? "Enviando…" : "Enviar invitación"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
