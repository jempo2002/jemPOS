"""Rutas legales publicas: aviso legal y politica de privacidad.

Son publicas a proposito (sin login_required): el aviso de cookies enlaza a la
politica, y un visitante tiene que poder leerla antes de registrarse.

Igual que la landing, destruyen la sesion activa: son rutas publicas y aplican
la misma regla que /, /landing y /login.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from app.security import cerrar_sesion_publica

legal_bp = Blueprint("legal_bp", __name__, url_prefix="/legal")

# Fecha de la ultima revision del texto legal. Se muestra en ambas paginas.
# Se sube a mano cuando cambia el contenido: si cambian las finalidades del
# tratamiento o los encargados, hay que actualizarla y avisar a los usuarios.
ULTIMA_ACTUALIZACION = "23 de septiembre de 2026"

# ---------------------------------------------------------------------------
# FALTA COMPLETAR ANTES DE PUBLICAR
# ---------------------------------------------------------------------------
# La Ley 1581 de 2012 obliga a identificar al responsable del tratamiento con
# nombre y datos de contacto reales. Estos cuatro valores no se pueden inventar
# desde el codigo: salen del RUT o de la cedula de quien opera el servicio.
#
# Si operas como persona natural: razon_social = tu nombre completo y
# nit = tu cedula. Si constituiste empresa, los del certificado de Camara de
# Comercio.
#
# Mientras alguno siga con el texto "POR DEFINIR", ambas paginas legales se
# publican con <meta name="robots" content="noindex"> (ver
# templates/legal/base_legal.html): es preferible que Google no indexe un aviso
# legal a medias a que lo indexe y quede en cache.
EMPRESA = {
    "razon_social": "POR DEFINIR",
    "nit": "POR DEFINIR",
    "domicilio": "POR DEFINIR",
    "ciudad": "POR DEFINIR",
}


def empresa_incompleta() -> bool:
    """True mientras algun dato del responsable siga sin definir."""
    return any(str(valor).strip().upper() == "POR DEFINIR" for valor in EMPRESA.values())


@legal_bp.app_context_processor
def _inyectar_datos_legales():
    """Expone `empresa` y `actualizado` a las plantillas legales.

    Va como context processor y no como argumento de cada render_template para
    que base_legal.html pueda decidir el meta robots sin que cada pagina hija
    tenga que acordarse de pasarle los datos.
    """
    return {
        "empresa": EMPRESA,
        "empresa_incompleta": empresa_incompleta(),
        "actualizado": ULTIMA_ACTUALIZACION,
    }


@legal_bp.get("/aviso-legal")
def aviso_legal():
    cerrar_sesion_publica()
    return render_template("legal/aviso_legal.html")


@legal_bp.get("/politica-privacidad")
def politica_privacidad():
    cerrar_sesion_publica()
    return render_template("legal/politica_privacidad.html")
