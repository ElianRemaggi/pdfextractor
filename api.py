import os
import tempfile

from fastapi import FastAPI, File, UploadFile, Query
from fastapi.responses import JSONResponse, HTMLResponse
from dotenv import load_dotenv

load_dotenv()

from extract import leer_archivo, extraer, CAMPOS

app = FastAPI(title="PDF Extractor")


@app.get("/test", response_class=HTMLResponse)
async def test_ui():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>PDF Extractor – Test</title>
  <style>
    body { font-family: sans-serif; max-width: 640px; margin: 40px auto; padding: 0 16px; }
    input, textarea { width: 100%; box-sizing: border-box; margin: 6px 0 14px; padding: 8px; border: 1px solid #ccc; border-radius: 4px; }
    button { padding: 10px 24px; background: #2563eb; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    button:disabled { background: #93c5fd; }
    pre { background: #f4f4f4; padding: 16px; border-radius: 4px; overflow-x: auto; white-space: pre-wrap; }
    .error { color: #dc2626; }
  </style>
</head>
<body>
  <h2>PDF Extractor</h2>
  <label>Archivo (PDF, XLSX, CSV)</label>
  <input type="file" id="file" accept=".pdf,.xlsx,.csv">
  <label>Campos (separados por coma)</label>
  <input type="text" id="campos" value="codigo,nombre,descripcion,precio">
  <button id="btn" onclick="enviar()">Extraer</button>
  <pre id="out" style="display:none"></pre>
  <script>
    async function enviar() {
      const file = document.getElementById('file').files[0];
      if (!file) return alert('Seleccioná un archivo');
      const btn = document.getElementById('btn');
      btn.disabled = true; btn.textContent = 'Procesando...';
      const out = document.getElementById('out');
      out.style.display = 'none'; out.className = '';
      const fd = new FormData();
      fd.append('file', file);
      const campos = document.getElementById('campos').value.trim();
      const url = '/extract' + (campos ? '?campos=' + encodeURIComponent(campos) : '');
      try {
        const r = await fetch(url, { method: 'POST', body: fd });
        const data = await r.json();
        out.textContent = JSON.stringify(data, null, 2);
        if (!r.ok) out.className = 'error';
      } catch(e) {
        out.textContent = e.message; out.className = 'error';
      }
      out.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Extraer';
    }
  </script>
</body>
</html>"""


@app.post("/extract")
async def extract(
    file: UploadFile = File(...),
    campos: str = Query(default=",".join(CAMPOS)),
):
    ext = os.path.splitext(file.filename)[1].lower()
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        texto = leer_archivo(tmp_path)
        items = extraer(texto, [c.strip() for c in campos.split(",")])
    except Exception as e:
        os.unlink(tmp_path)
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return JSONResponse({"items": items})
