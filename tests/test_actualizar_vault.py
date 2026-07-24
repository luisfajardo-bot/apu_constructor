from pathlib import Path

from scripts.actualizar_vault import (
    aviso_espejo,
    bloque_bullets,
    clasificar_docs_sueltos,
    enlace_bullet,
    entradas_de_carpeta,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    generar_indice,
    sincronizar_espejos,
    tabla_markdown,
    titulo_desde_markdown,
)


def test_titulo_desde_markdown_usa_primer_encabezado(tmp_path):
    archivo = tmp_path / "algo.md"
    archivo.write_text("> nota\n\n# Mi Título\n\ncontenido\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Mi Título"


def test_titulo_desde_markdown_fallback_sin_encabezado(tmp_path):
    archivo = tmp_path / "sin-encabezado.md"
    archivo.write_text("solo texto, sin encabezado\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Sin encabezado"


def test_fecha_desde_nombre_con_prefijo():
    assert fecha_desde_nombre(Path("2026-07-24-algo-design.md")) == "2026-07-24"


def test_fecha_desde_nombre_sin_prefijo():
    assert fecha_desde_nombre(Path("README.md")) is None


def test_escribir_si_cambia_crea_archivo_nuevo(tmp_path):
    destino = tmp_path / "sub" / "nota.md"
    escribio = escribir_si_cambia(destino, "hola\n")
    assert escribio is True
    assert destino.read_text(encoding="utf-8") == "hola\n"


def test_escribir_si_cambia_no_reescribe_si_es_igual(tmp_path):
    destino = tmp_path / "nota.md"
    destino.write_text("hola\n", encoding="utf-8")
    mtime_antes = destino.stat().st_mtime_ns

    escribio = escribir_si_cambia(destino, "hola\n")

    assert escribio is False
    assert destino.stat().st_mtime_ns == mtime_antes


def test_aviso_espejo_incluye_ruta_relativa_y_texto_fijo(tmp_path):
    origen = tmp_path / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arq\n", encoding="utf-8")

    aviso = aviso_espejo(origen, tmp_path)

    assert "docs/ARQUITECTURA.md" in aviso
    assert "no editar aquí" in aviso


def test_espejar_archivo_antepone_aviso_y_copia_contenido(tmp_path):
    raiz = tmp_path
    origen = raiz / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arquitectura\n\ncontenido\n", encoding="utf-8")
    destino = raiz / "vault" / "Arquitectura" / "ARQUITECTURA.md"

    escribio = espejar_archivo(origen, destino, raiz)

    texto = destino.read_text(encoding="utf-8")
    assert escribio is True
    assert texto.startswith("> Espejo automático")
    assert "# Arquitectura" in texto
    assert "contenido" in texto


def test_espejar_archivo_es_idempotente(tmp_path):
    raiz = tmp_path
    origen = raiz / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arquitectura\n", encoding="utf-8")
    destino = raiz / "vault" / "Arquitectura" / "ARQUITECTURA.md"

    espejar_archivo(origen, destino, raiz)
    escribio_segunda_vez = espejar_archivo(origen, destino, raiz)

    assert escribio_segunda_vez is False


def test_sincronizar_espejos_copia_y_limpia_huerfanos(tmp_path):
    raiz = tmp_path
    origen_dir = raiz / "docs" / "superpowers" / "plans"
    origen_dir.mkdir(parents=True)
    (origen_dir / "2026-01-01-a.md").write_text("# A\n", encoding="utf-8")
    (origen_dir / "2026-01-02-b.md").write_text("# B\n", encoding="utf-8")
    destino_dir = raiz / "vault" / "Planes"

    sincronizar_espejos(sorted(origen_dir.glob("*.md")), destino_dir, raiz)

    assert {p.name for p in destino_dir.glob("*.md")} == {
        "2026-01-01-a.md",
        "2026-01-02-b.md",
    }

    (origen_dir / "2026-01-02-b.md").unlink()
    sincronizar_espejos(sorted(origen_dir.glob("*.md")), destino_dir, raiz)

    assert {p.name for p in destino_dir.glob("*.md")} == {"2026-01-01-a.md"}


def test_sincronizar_espejos_con_lista_vacia_deja_carpeta_vacia(tmp_path):
    raiz = tmp_path
    destino_dir = raiz / "vault" / "Auditorías"

    sincronizar_espejos([], destino_dir, raiz)

    assert destino_dir.exists()
    assert list(destino_dir.glob("*.md")) == []


def test_clasificar_docs_sueltos(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARQUITECTURA.md").write_text("# Arq\n", encoding="utf-8")
    (docs / "auditoria-codigo-2026-07-01.md").write_text("# Auditoría\n", encoding="utf-8")
    (docs / "runbook-correo.md").write_text("# Runbook\n", encoding="utf-8")
    (docs / "algo-suelto.md").write_text("# Suelto\n", encoding="utf-8")

    categorias = clasificar_docs_sueltos(docs)

    assert [a.name for a in categorias["arquitectura"]] == ["ARQUITECTURA.md"]
    assert [a.name for a in categorias["auditorias"]] == ["auditoria-codigo-2026-07-01.md"]
    assert [a.name for a in categorias["runbooks"]] == ["runbook-correo.md"]
    assert [a.name for a in categorias["otros"]] == ["algo-suelto.md"]


def test_clasificar_docs_sueltos_no_recursa_en_subcarpetas(tmp_path):
    docs = tmp_path / "docs"
    (docs / "superpowers" / "specs").mkdir(parents=True)
    (docs / "superpowers" / "specs" / "2026-01-01-x-design.md").write_text(
        "# X\n", encoding="utf-8"
    )

    categorias = clasificar_docs_sueltos(docs)

    assert categorias == {"arquitectura": [], "auditorias": [], "runbooks": [], "otros": []}


def test_entradas_de_carpeta_ordena_por_fecha_descendente(tmp_path):
    carpeta = tmp_path / "specs"
    carpeta.mkdir()
    (carpeta / "2026-01-01-vieja-design.md").write_text("# Vieja\n", encoding="utf-8")
    (carpeta / "2026-06-01-nueva-design.md").write_text("# Nueva\n", encoding="utf-8")

    entradas = entradas_de_carpeta(carpeta)

    assert entradas[0] == ("2026-06-01", "Nueva", "2026-06-01-nueva-design.md")
    assert entradas[1] == ("2026-01-01", "Vieja", "2026-01-01-vieja-design.md")


def test_entradas_de_carpeta_tiebreak_determinisico_por_nombre(tmp_path):
    carpeta = tmp_path / "specs"
    carpeta.mkdir()
    # Crear dos archivos con la misma fecha, en un orden deliberado
    (carpeta / "2026-07-02-b-design.md").write_text("# B\n", encoding="utf-8")
    (carpeta / "2026-07-02-a-design.md").write_text("# A\n", encoding="utf-8")

    # Llamar entradas_de_carpeta dos veces para verificar el orden es el mismo
    entradas1 = entradas_de_carpeta(carpeta)
    entradas2 = entradas_de_carpeta(carpeta)

    # Ambas llamadas deben devolver el mismo orden (determinístico)
    assert entradas1 == entradas2
    # El orden debe ser por nombre descendente (b antes que a)
    assert entradas1[0][2] == "2026-07-02-b-design.md"
    assert entradas1[1][2] == "2026-07-02-a-design.md"


def test_tabla_markdown_con_entradas():
    entradas = [("2026-06-01", "Nueva", "2026-06-01-nueva-design.md")]

    tabla = tabla_markdown(entradas, "Specs")

    assert "| 2026-06-01 |" in tabla
    assert "[[Specs/2026-06-01-nueva-design|Nueva]]" in tabla


def test_tabla_markdown_vacia():
    assert tabla_markdown([], "Specs") == "_(vacío)_\n"


def test_bloque_bullets_vacio():
    assert bloque_bullets("Auditorías", []) == "_(vacío)_\n"


def test_enlace_bullet_usa_titulo_y_stem(tmp_path):
    archivo = tmp_path / "runbook-correo.md"
    archivo.write_text("# Correo por Resend\n", encoding="utf-8")

    assert enlace_bullet("Runbooks", archivo) == "- [[Runbooks/runbook-correo|Correo por Resend]]\n"


def test_generar_indice_incluye_secciones_y_conteos(tmp_path):
    raiz = tmp_path
    docs = raiz / "docs"
    (docs / "superpowers" / "specs").mkdir(parents=True)
    (docs / "superpowers" / "plans").mkdir(parents=True)
    (docs / "ARQUITECTURA.md").write_text("# Arquitectura\n", encoding="utf-8")
    (raiz / "README.md").write_text("# Readme\n", encoding="utf-8")
    (raiz / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    (docs / "superpowers" / "specs" / "2026-01-01-x-design.md").write_text(
        "# X\n", encoding="utf-8"
    )
    (docs / "superpowers" / "plans" / "2026-01-01-x.md").write_text(
        "# X plan\n", encoding="utf-8"
    )

    indice = generar_indice(docs)

    assert "1 planes, 1 specs" in indice
    assert "[[Arquitectura/ARQUITECTURA|Arquitectura]]" in indice
    assert "[[Proyecto/README|Readme]]" in indice
    assert "[[Proyecto/CLAUDE|Claude]]" in indice
    assert "[[Specs/2026-01-01-x-design|X]]" in indice
    assert "[[Planes/2026-01-01-x|X plan]]" in indice
