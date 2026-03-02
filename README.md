# EXIF Overlay Desktop App

Aplicacion de escritorio en Python 3.11+ para seleccionar una o varias imagenes locales, o una carpeta completa, leer sus metadatos EXIF y generar copias preparadas para timeline 4K con los datos superpuestos.

La imagen original no se modifica. La copia se guarda en una subcarpeta `exportadas` dentro de la carpeta original.

## Requisitos

- Python 3.11 o superior
- Tkinter disponible en la instalacion de Python

## Estructura

```text
main.py
requirements.txt
README.md
app/
  __init__.py
  ui.py
  exif_service.py
  image_service.py
```

## Instalacion

1. Crea un entorno virtual si quieres aislar dependencias.
2. Instala las librerias necesarias:

```bash
pip install -r requirements.txt
```

## Ejecucion

```bash
python main.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Uso

1. Pulsa `Seleccionar imagenes` para elegir varios archivos o `Seleccionar carpeta` para procesar todos los compatibles dentro de una carpeta.
2. Elige archivos `.jpg`, `.jpeg` o `.png`, o una carpeta que los contenga.
3. Pulsa `Procesar`.
4. Sigue la barra de progreso mientras se procesa el lote.
5. Revisa la subcarpeta `exportadas` creada dentro de la carpeta original de cada imagen.

## Formato mostrado

- `ExposureTime` -> `1/250 s`
- `FNumber` -> `f/2.8`
- `ISO` -> `ISO 400`

Si falta algun dato EXIF, la app muestra `N/D`.

## Notas

- JPG y JPEG estan soportados con lectura EXIF via `piexif`.
- PNG tambien se permite; si no hay EXIF util, se mostrara `N/D`.
- La salida reduce la imagen cuando hace falta para dejar la altura maxima en `2160px`.
- Los datos se dibujan directamente sobre la imagen en texto amarillo con resalte oscuro.
- La seleccion de carpeta procesa los archivos compatibles del nivel superior de esa carpeta.
- Si ya existe un archivo de salida, se crea uno nuevo con sufijo incremental.
- No se usan servicios externos ni base de datos.
