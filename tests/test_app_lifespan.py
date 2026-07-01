from apu_tool.servicio.app import create_app


def test_app_arranca_y_expone_almacen():
    app = create_app()
    assert app.state.almacen is not None
    # el lifespan de cierre no debe reventar con SQLite (cx es None -> no-op)
    app.state.almacen.cerrar()
