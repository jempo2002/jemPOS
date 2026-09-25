"""Genera static/img/punto-de-venta-jempos.jpg, la imagen de previsualizacion al compartir.

Sin este archivo, las etiquetas og:image y twitter:image del landing apuntan a
un 404 y WhatsApp, Instagram o X comparten el enlace sin tarjeta: solo la URL
pelada. Es el canal principal por el que se pasa un enlace de jemPOS, asi que
la imagen no es decorativa.

Medidas: 1200x630 px (proporcion 1.91:1, lo que piden Open Graph y Twitter
summary_large_image). JPEG y no PNG porque no hay transparencia que conservar y
pesa la mitad; los rastreadores de varias redes descartan imagenes muy pesadas.

El isotipo se reutiliza de generar_favicons.py en vez de volver a dibujarlo: el
SVG sigue siendo la fuente de verdad de la marca.

    python scripts/generar_og_cover.py
"""

from __future__ import annotations

import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFont

from generar_favicons import DESTINO, _dibujar

ANCHO, ALTO = 1200, 630

FONDO = (15, 23, 42)          # --color-text, el azul mas oscuro de la paleta
BLANCO = (255, 255, 255)
AZUL_CLARO = (96, 165, 250)   # --color-primary-on-dark
GRIS = (148, 163, 184)        # gris de apoyo sobre fondo oscuro

TITULO = "jemPOS"
LEMA = "Tu negocio en la palma de tu mano"
BAJADA = "Punto de venta, inventario y contabilidad en la nube"
PIE = "Ventas | Inventario | Cartera | Turnos de caja | Reportes"


def _fuente(tamano: int) -> ImageFont.FreeTypeFont:
    """Fuente escalable sin depender de las que tenga instalado el sistema.

    ponytail: se usa la fuente que Pillow trae incorporada (Aileron, una
    Helvetica libre) en lugar de buscar Segoe UI o DejaVu en el disco. Asi el
    archivo sale identico en cualquier maquina, que es lo que se quiere de algo
    que se genera una vez y se versiona. Si mas adelante la marca define una
    tipografia propia, el cambio es poner su .ttf aqui con ImageFont.truetype.
    """
    return ImageFont.load_default(size=tamano)


def _centrar_x(d: ImageDraw.ImageDraw, texto: str, fuente, y: int, color) -> None:
    ancho_texto = d.textlength(texto, font=fuente)
    d.text(((ANCHO - ancho_texto) / 2, y), texto, font=fuente, fill=color)


def construir() -> Image.Image:
    img = Image.new("RGB", (ANCHO, ALTO), FONDO)
    d = ImageDraw.Draw(img)

    # Banda superior azul: da un borde de color al recorte cuadrado que hacen
    # algunos clientes de chat.
    d.rectangle([0, 0, ANCHO, 10], fill=AZUL_CLARO)

    # Isotipo: se dibuja a 512 y se reduce con LANCZOS (bordes limpios).
    #
    # Dos detalles del canal alfa que hay que respetar a la vez:
    #   - _dibujar() devuelve el lienzo azul opaco de lado a lado, asi que las
    #     esquinas redondeadas del icono no estan en el alfa y al pegarlo
    #     saldria un cuadrado.
    #   - el cuerpo del recibo se pinta con un blanco casi transparente
    #     (alfa 46). Si se pega con una mascara propia, ese alfa se ignora y el
    #     recibo sale blanco macizo, perdiendo las lineas y el check.
    # Se multiplican ambas mascaras: el alfa original manda dentro del icono y
    # el rectangulo redondeado recorta el borde.
    lado = 168
    logo = _dibujar().resize((lado, lado), Image.LANCZOS)
    esquinas = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(esquinas).rounded_rectangle(
        [0, 0, lado - 1, lado - 1], radius=int(lado * 7 / 32), fill=255
    )
    img.paste(logo, ((ANCHO - lado) // 2, 78), ImageChops.multiply(logo.getchannel("A"), esquinas))

    _centrar_x(d, TITULO, _fuente(92), 276, BLANCO)
    _centrar_x(d, LEMA, _fuente(44), 392, AZUL_CLARO)
    _centrar_x(d, BAJADA, _fuente(30), 456, GRIS)

    # Separador fino antes del pie: ordena la lectura sin meter otra caja.
    d.line([(ANCHO - 420) / 2, 520, (ANCHO + 420) / 2, 520], fill=(51, 65, 85), width=2)
    _centrar_x(d, PIE, _fuente(24), 552, GRIS)

    return img


def main() -> int:
    if not os.path.isdir(DESTINO):
        print(f"ERROR: no existe {DESTINO}")
        return 1

    ruta = os.path.join(DESTINO, "punto-de-venta-jempos.jpg")
    # quality=88 + optimize: por debajo de 200 kB, que es el limite practico
    # para que WhatsApp genere la miniatura sin recomprimir.
    construir().save(ruta, format="JPEG", quality=88, optimize=True, progressive=True)
    print(f"  {os.path.getsize(ruta):>7} B  static/img/punto-de-venta-jempos.jpg  ({ANCHO}x{ALTO})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
