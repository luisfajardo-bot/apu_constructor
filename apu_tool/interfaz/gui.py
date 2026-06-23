"""
Interfaz gráfica (tkinter) del armador de APUs.

Flujo:
  1. Cargar la base (ingesta del Excel histórico si hace falta).
  2. Cargar la lista de licitación (o generar un ejemplo).
  3. Armar los APUs: matching + IA acotada + precios.
  4. Revisar y confirmar los ítems dudosos (doble clic en una fila marcada).
  5. Exportar el cuadro resumen a Excel.

La IA nunca ve precios: eso lo garantiza el módulo privacy.py, no la interfaz.
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    LEFT,
    RIGHT,
    TOP,
    X,
    Y,
    BooleanVar,
    StringVar,
    Tk,
    filedialog,
    messagebox,
)
from tkinter import ttk

from apu_tool import config
from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.dominio.assemble import Assembler
from apu_tool.dominio.licitacion import read_licitacion
from apu_tool.nucleo.models import AssembledApu, MatchStatus
from apu_tool.dominio.pipeline import db_is_empty, generate_sample, get_almacen
from apu_tool.datos.seed import seed as _seed_excel
from apu_tool.dominio.report import write_report

_STATUS_LABEL = {
    MatchStatus.AUTO: "Automático",
    MatchStatus.REVIEW: "Revisar",
    MatchStatus.NEW: "Manual",
    MatchStatus.CONFIRMED: "Confirmado",
}
_STATUS_COLOR = {
    MatchStatus.AUTO: "#1a7f37",
    MatchStatus.CONFIRMED: "#1a7f37",
    MatchStatus.REVIEW: "#9a6700",
    MatchStatus.NEW: "#b35900",
}


class ApuApp:
    def __init__(self, root: Tk):
        self.root = root
        root.title("Armador de APUs — Obra Civil")
        root.geometry("1180x720")

        self.alm = get_almacen()
        self.assembler: Assembler | None = None
        self.assembled: list[AssembledApu] = []
        self._items = []
        self._q: queue.Queue = queue.Queue()

        self.licitacion_path = StringVar(value="")
        self.shift_var = StringVar(value=config.SHIFT_DIURNO)
        self.use_ai = BooleanVar(value=config.ai_available())

        self._build_ui()
        self._refresh_status()
        self.root.after(120, self._poll_queue)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", rowheight=24)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        top = ttk.Frame(self.root, padding=10)
        top.pack(side=TOP, fill=X)

        ttk.Label(top, text="Armador de APUs", font=("Segoe UI", 16, "bold")).pack(side=LEFT)
        self.status_lbl = ttk.Label(top, text="", foreground="#555")
        self.status_lbl.pack(side=RIGHT)

        # Barra de acciones
        bar = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        bar.pack(side=TOP, fill=X)

        ttk.Button(bar, text="1. Cargar histórico", command=self._on_ingest).pack(side=LEFT)
        ttk.Button(bar, text="Generar ejemplo", command=self._on_sample).pack(side=LEFT, padx=4)
        ttk.Button(bar, text="2. Cargar lista…", command=self._on_pick_file).pack(side=LEFT, padx=4)

        ttk.Label(bar, text="Turno:").pack(side=LEFT, padx=(12, 2))
        ttk.Combobox(bar, textvariable=self.shift_var, width=10, state="readonly",
                     values=[config.SHIFT_DIURNO, config.SHIFT_NOCTURNO]).pack(side=LEFT)

        self.ai_chk = ttk.Checkbutton(bar, text="Usar IA", variable=self.use_ai)
        self.ai_chk.pack(side=LEFT, padx=10)
        if not config.ai_available():
            self.ai_chk.state(["disabled"])

        ttk.Button(bar, text="3. Armar APUs", style="Accent.TButton",
                   command=self._on_build).pack(side=LEFT, padx=6)
        ttk.Button(bar, text="Exportar cuadro…", command=self._on_export).pack(side=RIGHT)

        # archivo seleccionado
        fr = ttk.Frame(self.root, padding=(10, 0))
        fr.pack(side=TOP, fill=X)
        ttk.Label(fr, text="Lista:").pack(side=LEFT)
        ttk.Label(fr, textvariable=self.licitacion_path, foreground="#1F4E78").pack(side=LEFT, padx=4)

        # progreso
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(side=TOP, fill=X, padx=10, pady=4)

        # tabla de resultados
        cols = ("item", "desc", "und", "cant", "contractual", "costo",
                "margen", "margenpct", "estado", "conf")
        headers = {
            "item": ("Ítem", 50), "desc": ("Descripción", 360), "und": ("Und", 50),
            "cant": ("Cant.", 70), "contractual": ("Contractual", 120),
            "costo": ("Costo", 120), "margen": ("Margen", 120),
            "margenpct": ("Margen %", 70), "estado": ("Estado", 90),
            "conf": ("Conf.", 55),
        }
        wrap = ttk.Frame(self.root, padding=(10, 0))
        wrap.pack(side=TOP, fill=BOTH, expand=True)
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse")
        for c in cols:
            txt, w = headers[c]
            self.tree.heading(c, text=txt)
            anchor = "w" if c in ("desc",) else ("center" if c in ("und", "estado", "conf") else "e")
            self.tree.column(c, width=w, anchor=anchor, stretch=(c == "desc"))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=LEFT, fill=BOTH, expand=True)
        vsb.pack(side=RIGHT, fill=Y)
        self.tree.bind("<Double-1>", self._on_row_double_click)

        for st, color in _STATUS_COLOR.items():
            self.tree.tag_configure(st.value, foreground=color)
        self.tree.tag_configure("neg", background="#FCE4E4")

        # totales + log
        bottom = ttk.Frame(self.root, padding=10)
        bottom.pack(side=TOP, fill=X)
        self.totals_lbl = ttk.Label(bottom, text="", font=("Segoe UI", 11, "bold"))
        self.totals_lbl.pack(side=LEFT)
        self.hint_lbl = ttk.Label(
            bottom, foreground="#9a6700",
            text="Doble clic en una fila 'Revisar'/'Manual' para elegir el APU base.")
        self.hint_lbl.pack(side=RIGHT)

    # ------------------------------------------------------------------ helpers
    def _refresh_status(self) -> None:
        c = self.alm.counts()
        ai = "IA habilitada" if config.ai_available() else "IA: fallback determinístico"
        self.status_lbl.config(
            text=f"Insumos: {c['insumos']}   APUs: {c['apus']}   "
                 f"Componentes: {c['apu_componentes']}   |   {ai}")

    def _log(self, msg: str) -> None:
        self.status_lbl.config(text=msg)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for child in self.root.winfo_children():
            pass  # los botones individuales se gestionan por acción

    # ------------------------------------------------------------------ acciones
    def _on_ingest(self) -> None:
        def work():
            try:
                counts = _seed_excel(self.alm, force=True)
                self._q.put(("done_ingest", f"Semillado OK: {counts}"))
            except Exception as e:
                self._q.put(("error", f"Semillado: {e}"))
        self.progress.config(mode="indeterminate")
        self.progress.start(12)
        self._log("Semillando histórico…")
        threading.Thread(target=work, daemon=True).start()

    def _on_sample(self) -> None:
        try:
            if db_is_empty(self.alm):
                messagebox.showinfo("Histórico", "Primero carga el histórico (botón 1).")
                return
            path = generate_sample(n=15)
            self.licitacion_path.set(str(path))
            self._log(f"Ejemplo generado: {path.name}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _on_pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Selecciona la lista de licitación",
            filetypes=[("Excel/CSV", "*.xlsx *.xlsm *.csv"), ("Todos", "*.*")])
        if path:
            self.licitacion_path.set(path)
            self._log(f"Lista: {Path(path).name}")

    def _on_build(self) -> None:
        path = self.licitacion_path.get()
        if not path:
            messagebox.showinfo("Lista", "Selecciona o genera una lista de licitación.")
            return
        if db_is_empty(self.alm):
            messagebox.showinfo("Histórico", "Primero carga el histórico (botón 1).")
            return

        def work():
            try:
                items = read_licitacion(path, default_shift=self.shift_var.get())
                advisor = ApuAdvisor(enabled=self.use_ai.get())
                assembler = Assembler(self.alm, advisor=advisor)
                self._items = items

                def prog(i, total, desc):
                    self._q.put(("progress", (i, total, desc)))

                assembled = assembler.assemble_all(items, progress=prog)
                self._q.put(("done_build", (assembler, assembled)))
            except Exception as e:
                self._q.put(("error", f"Armado: {e}"))

        self.progress.config(mode="determinate", maximum=100, value=0)
        self._log("Armando APUs…")
        threading.Thread(target=work, daemon=True).start()

    def _on_export(self) -> None:
        if not self.assembled:
            messagebox.showinfo("Exportar", "Primero arma los APUs.")
            return
        path = filedialog.asksaveasfilename(
            title="Guardar cuadro resumen", defaultextension=".xlsx",
            initialdir=str(config.OUTPUT_DIR), initialfile="cuadro_resumen.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            write_report(self.assembled, path)
            messagebox.showinfo("Exportado", f"Cuadro resumen guardado en:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _on_row_double_click(self, _event) -> None:
        sel = self.tree.selection()
        if not sel or self.assembler is None:
            return
        idx = int(self.tree.item(sel[0], "values")[0]) if False else self.tree.index(sel[0])
        if idx >= len(self.assembled):
            return
        a = self.assembled[idx]
        if a.status not in (MatchStatus.REVIEW, MatchStatus.NEW, MatchStatus.CONFIRMED):
            return
        self._open_review_dialog(idx, a)

    # ------------------------------------------------------------------ revisión
    def _open_review_dialog(self, idx: int, a: AssembledApu) -> None:
        from tkinter import Toplevel
        win = Toplevel(self.root)
        win.title(f"Revisar ítem {a.item.item}")
        win.geometry("720x420")
        win.transient(self.root)

        ttk.Label(win, text=a.item.descripcion, font=("Segoe UI", 11, "bold"),
                  wraplength=680).pack(anchor="w", padx=12, pady=(12, 2))
        ttk.Label(win, text=f"Turno: {a.shift}   |   {a.explicacion}",
                  foreground="#555", wraplength=680).pack(anchor="w", padx=12)

        cols = ("cod", "nombre", "score")
        tv = ttk.Treeview(win, columns=cols, show="headings", height=10)
        tv.heading("cod", text="Código"); tv.column("cod", width=80, anchor="center")
        tv.heading("nombre", text="APU candidato"); tv.column("nombre", width=470)
        tv.heading("score", text="Similar."); tv.column("score", width=80, anchor="center")
        tv.pack(fill=BOTH, expand=True, padx=12, pady=8)

        candidatos = self.assembler.matcher.candidates(a.item.descripcion, a.shift, top_n=8)
        for c in candidatos:
            tv.insert("", END, values=(c.apu_codigo, c.apu_nombre, f"{c.score:.0%}"))

        def confirm():
            sel = tv.selection()
            if not sel:
                messagebox.showinfo("Selecciona", "Elige un APU candidato.")
                return
            cod = tv.item(sel[0], "values")[0]
            new_a = self.assembler.reassemble_with_choice(a.item, cod, a.shift)
            self.assembled[idx] = new_a
            self._render_results()
            win.destroy()

        btns = ttk.Frame(win, padding=10)
        btns.pack(fill=X)
        ttk.Button(btns, text="Confirmar selección", style="Accent.TButton",
                   command=confirm).pack(side=RIGHT)
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side=RIGHT, padx=6)

    # ------------------------------------------------------------------ render
    def _render_results(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for a in self.assembled:
            tags = [a.status.value]
            if a.margen_total < 0:
                tags.append("neg")
            self.tree.insert("", END, tags=tags, values=(
                a.item.item, a.item.descripcion, a.unidad,
                f"{a.item.cantidad:,.2f}",
                f"${a.item.precio_contractual:,.0f}",
                f"${a.costo_unitario:,.0f}",
                f"${a.margen_unitario:,.0f}",
                f"{a.margen_pct:.0%}",
                _STATUS_LABEL.get(a.status, a.status.value),
                f"{a.confianza:.2f}",
            ))
        total_c = sum(a.contractual_total for a in self.assembled)
        total_k = sum(a.costo_total for a in self.assembled)
        margen = total_c - total_k
        pct = (margen / total_c) if total_c else 0
        n_rev = sum(1 for a in self.assembled
                    if a.status in (MatchStatus.REVIEW, MatchStatus.NEW))
        self.totals_lbl.config(
            text=f"Contractual: ${total_c:,.0f}    Costo: ${total_k:,.0f}    "
                 f"Margen: ${margen:,.0f} ({pct:.1%})    Por revisar: {n_rev}")

    # ------------------------------------------------------------------ cola
    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "progress":
                    i, total, desc = payload
                    self.progress.config(maximum=total, value=i)
                    self._log(f"[{i}/{total}] {desc[:50]}")
                elif kind == "done_ingest":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0)
                    self._refresh_status()
                    self._log(payload)
                elif kind == "done_build":
                    self.assembler, self.assembled = payload
                    self.progress.config(value=self.progress["maximum"])
                    self._render_results()
                    self._log("Armado completo. Revisa los ítems marcados y exporta.")
                elif kind == "error":
                    self.progress.stop()
                    self.progress.config(mode="determinate", value=0)
                    messagebox.showerror("Error", payload)
                    self._log("Error.")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)


def main() -> None:
    root = Tk()
    ApuApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
