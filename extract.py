"""
Extractor de listas de productos desde PDF, XLSX o CSV.
Uso: python extract.py archivo.pdf
     python extract.py --test   (self-check sin API)
"""
import argparse
import json
import os
import sys
import tempfile

from dotenv import load_dotenv

load_dotenv()


# ── 1. Lectura de archivos ───────────────────────────────────────────────────

def leer_archivo(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()

    if ext == ".csv":
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        lineas = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                lineas.append("\t".join("" if v is None else str(v) for v in row))
        return "\n".join(lineas)

    if ext == ".pdf":
        import pdfplumber
        partes = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                partes.append(page.extract_text() or "")
        texto = "\n".join(partes)
        if texto.strip():
            return texto
        # ponytail: OCR fallback para PDFs escaneados; reemplazar con visión LLM si se quiere evitar tesseract
        from pdf2image import convert_from_path
        import pytesseract
        imagenes = convert_from_path(path)
        return "\n".join(pytesseract.image_to_string(img, lang="spa") for img in imagenes)

    raise ValueError(f"Extensión no soportada: {ext!r}. Usá .pdf, .xlsx o .csv")


# ── 2. Extracción con LLM ────────────────────────────────────────────────────

CAMPOS = ["codigo", "nombre", "descripcion", "precio"]

SYSTEM_PROMPT = """\
Sos un extractor de datos de listas de productos.
Tu única tarea: dado un texto crudo (puede ser una tabla, un listado, etc.),
devolvé SOLO un JSON con la clave "items" cuyo valor es una lista de objetos.
Cada objeto debe tener exactamente estos campos: codigo, nombre, descripcion, precio.
Reglas de mapeo:
- "codigo": cualquier columna que sea código, cod, SKU, ref, art, id, número de artículo o similar.
- "nombre": cualquier columna que sea nombre, producto, descripción corta, artículo o similar.
- "descripcion": cualquier columna que sea descripción larga, detalle, observaciones o similar. Si no existe, repetí el nombre.
- "precio": cualquier columna que sea precio, importe, valor, costo o similar. Devolvé solo el número (sin símbolo de moneda).
Si un campo realmente no existe ni puede inferirse, usá null.
No inventes datos. No agregues campos extra. No des explicaciones."""


CHUNK_SIZE = 6000  # ponytail: 6k chars with explicit max_tokens=8192 → ~6 calls instead of 11


def _extraer_chunk(client, texto_chunk: str, campos: list[str]) -> list[dict]:
    user_msg = f"Campos a extraer: {campos}\n\nTexto:\n{texto_chunk}"
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=8192,
    )
    content = resp.choices[0].message.content
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # ponytail: response hit max_tokens and got truncated; discard partial chunk
        return []
    return data.get("items", [])


def extraer(texto: str, campos: list[str] = CAMPOS) -> list[dict]:
    from openai import OpenAI

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise EnvironmentError("Falta DEEPSEEK_API_KEY en el entorno o .env")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    if not texto.strip():
        raise ValueError("El texto extraído está vacío — el archivo puede ser una imagen escaneada sin OCR")

    chunks = [texto[i:i + CHUNK_SIZE] for i in range(0, len(texto), CHUNK_SIZE)]
    all_items: list[dict] = []
    for chunk in chunks:
        all_items.extend(_extraer_chunk(client, chunk, campos))

    for i, item in enumerate(all_items, 1):
        if not item.get("codigo"):
            item["codigo"] = str(i).zfill(3)
    return all_items


# ── 3. CLI ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Extrae productos de un PDF/XLSX/CSV")
    ap.add_argument("archivo", nargs="?", help="Ruta al archivo a procesar")
    ap.add_argument("--test", action="store_true", help="Corre el self-check sin API")
    ap.add_argument(
        "--campos",
        default=",".join(CAMPOS),
        help="Campos a extraer, separados por coma (default: codigo,nombre,descripcion,precio)",
    )
    args = ap.parse_args()

    if args.test:
        _self_check()
        return

    if not args.archivo:
        ap.print_help()
        sys.exit(1)

    texto = leer_archivo(args.archivo)
    campos = [c.strip() for c in args.campos.split(",")]
    items = extraer(texto, campos)
    print(json.dumps(items, ensure_ascii=False, indent=2))


# ── self-check (sin API) ─────────────────────────────────────────────────────

def _self_check():
    # CSV
    contenido_csv = "cod;detalle;precio\n001;Amoxicilina 500mg;1250.50\n002;Ibuprofeno 400mg;890"
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False, encoding="utf-8") as f:
        f.write(contenido_csv)
        path_csv = f.name
    texto = leer_archivo(path_csv)
    os.unlink(path_csv)
    assert "Amoxicilina" in texto, "CSV: no encontró 'Amoxicilina'"
    assert "1250.50" in texto, "CSV: no encontró el precio"

    # XLSX
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "producto", "precio"])
    ws.append(["A01", "Salame", "3500"])
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        path_xlsx = f.name
    wb.save(path_xlsx)
    texto = leer_archivo(path_xlsx)
    os.unlink(path_xlsx)
    assert "Salame" in texto, "XLSX: no encontró 'Salame'"

    print("✓ self-check OK (lectura de archivos)")


if __name__ == "__main__":
    main()
