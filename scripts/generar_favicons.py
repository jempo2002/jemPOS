"""Genera los favicons raster a partir de static/img/favicon.svg.

El SVG es la fuente de verdad; este script produce los formatos que todavia
hacen falta porque no todos los clientes leen SVG:

  favicon.ico          16+32+48 px  -> navegadores viejos y la peticion implicita
                                       que el navegador hace a /favicon.ico
  favicon-32.png       32 px        -> pestana en pantallas normales
  favicon-192.png      192 px       -> Android / manifest
  apple-touch-icon.png 180 px       -> iOS, sin canal alfa (Safari lo pinta negro)

Se dibuja con Pillow (ya estaba en requirements.txt) en vez de rasterizar el SVG,
para no añadir cairosvg solo para esto. Las formas replican el isotipo del SVG.

    python scripts/generar_favicons.py
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img")

AZUL = (59, 130, 246, 255)      # --color-primary del sistema de diseno
BLANCO = (255, 255, 255, 255)

# Se dibuja grande y se reduce con LANCZOS: los bordes salen suaves sin
# necesitar antialiasing manual.
LIENZO = 512


def _dibujar(fondo_transparente: bool = False) -> Image.Image:
    """Isotipo jemPOS a 512 px: recibo redondeado con lineas y un check."""
    fondo = (0, 0, 0, 0) if fondo_transparente else AZUL
    img = Image.new("RGBA", (LIENZO, LIENZO), fondo)
    d = ImageDraw.Draw(img)

    e = LIENZO / 32.0            # escala: el SVG esta en una rejilla de 32

    if fondo_transparente:
        # Sin placa de color, el recibo se dibuja en azul para que se vea.
        trazo, relleno = AZUL, (59, 130, 246, 46)
    else:
        d.rounded_rectangle([0, 0, LIENZO - 1, LIENZO - 1], radius=int(7 * e), fill=AZUL)
        trazo, relleno = BLANCO, (255, 255, 255, 46)

    # Cuerpo del recibo
    d.rounded_rectangle(
        [9 * e, 6 * e, 23 * e, 26 * e],
        radius=int(3 * e),
        fill=relleno,
        outline=trazo,
        width=max(1, int(1.8 * e)),
    )
    # Dos lineas de texto
    grosor = max(1, int(1.8 * e))
    d.line([12.5 * e, 11.5 * e, 19.5 * e, 11.5 * e], fill=trazo, width=grosor)
    d.line([12.5 * e, 15 * e, 17 * e, 15 * e], fill=trazo, width=grosor)
    # Check
    grosor_check = max(1, int(2.2 * e))
    d.line(
        [13 * e, 20.5 * e, 15.2 * e, 22.7 * e, 19.6 * e, 18.3 * e],
        fill=trazo,
        width=grosor_check,
        joint="curve",
    )
    return img


def main() -> int:
    if not os.path.isdir(DESTINO):
        print(f"ERROR: no existe {DESTINO}")
        return 1

    base = _dibujar()
    creados = []

    def guardar(img: Image.Image, nombre: str, **kwargs) -> None:
        ruta = os.path.join(DESTINO, nombre)
        img.save(ruta, **kwargs)
        creados.append((nombre, os.path.getsize(ruta)))

    # ICO multi-tamano: lo pide el navegador solo en /favicon.ico
    guardar(base, "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    guardar(base.resize((32, 32), Image.LANCZOS), "favicon-32.png", format="PNG", optimize=True)
    guardar(base.resize((192, 192), Image.LANCZOS), "favicon-192.png", format="PNG", optimize=True)

    # iOS ignora la transparencia y rellena de negro: se aplana sobre el azul.
    apple = Image.new("RGB", (180, 180), AZUL[:3])
    apple.paste(base.resize((180, 180), Image.LANCZOS), (0, 0), base.resize((180, 180), Image.LANCZOS))
    guardar(apple, "apple-touch-icon.png", format="PNG", optimize=True)

    for nombre, peso in creados:
        print(f"  {peso:>7} B  static/img/{nombre}")
    print(f"OK: {len(creados)} archivos generados en static/img/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
