"""
agente_sigma.py — Descarga el estado de terminales desde SIGMA Red Link
y genera estado_atms.json para la app ATMs BPN.

Corre automáticamente via GitHub Actions cada hora.
Las credenciales vienen de variables de entorno (GitHub Secrets).
"""

import os
import io
import json
import time
import requests
import pandas as pd
from datetime import datetime
from bs4 import BeautifulSoup

# ── Credenciales desde GitHub Secrets ────────────────────────────────────────
SIGMA_USER     = os.environ.get('SIGMA_USER', '')
SIGMA_PASSWORD = os.environ.get('SIGMA_PASSWORD', '')

# ── URLs SIGMA ────────────────────────────────────────────────────────────────
BASE_URL     = 'https://sigma.redlink.com.ar'
URL_LOGIN    = f'{BASE_URL}/monitorhw/pages/login.xhtml'
URL_MONITOR  = f'{BASE_URL}/monitorhw/pages/vistaPorTerminal.xhtml'
URL_HOME     = f'{BASE_URL}/monitorhw/pages/home.xhtml'

# ── Paleta de estados ─────────────────────────────────────────────────────────
ESTADO_CONFIG = {
    'OK':                {'color': '#43A047', 'icono': '✓',  'label': 'Operativo'},
    'ADVERTENCIA':       {'color': '#43A047', 'icono': '⚠',  'label': 'Advertencia'},
    'INSUMOS':           {'color': '#43A047', 'icono': '📦', 'label': 'Sin insumos'},
    'NO PAGA':           {'color': '#E53935', 'icono': '💸', 'label': 'No dispensa'},
    'DEPOSITO':          {'color': '#43A047', 'icono': '🏦', 'label': 'Falla depósito'},
    'FUERA DE SERVICIO': {'color': '#E53935', 'icono': '✗',  'label': 'Fuera de servicio'},
    'SIN DATOS':         {'color': '#90A4AE', 'icono': '?',  'label': 'Sin datos'},
}

DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']

def get_viewstate(html_text):
    """Extrae el ViewState de JSF de una página."""
    soup = BeautifulSoup(html_text, 'html.parser')
    vs = soup.find('input', {'name': 'javax.faces.ViewState'})
    return vs['value'] if vs else ''

def get_form_id(html_text):
    """Extrae el ID del formulario principal."""
    soup = BeautifulSoup(html_text, 'html.parser')
    form = soup.find('form')
    return form.get('id', '') if form else ''

def login(session):
    """Hace login en SIGMA. Devuelve True si fue exitoso."""
    print('🔐 Iniciando sesión en SIGMA...')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'es-AR,es;q=0.9',
    }
    session.headers.update(headers)

    # GET login page
    try:
        resp = session.get(URL_LOGIN, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        # Intentar URL alternativa
        try:
            resp = session.get(f'{BASE_URL}/portal/pages/login.xhtml', timeout=20)
            resp.raise_for_status()
        except Exception as e2:
            print(f'  ✗ No se pudo acceder al login: {e2}')
            return False

    viewstate = get_viewstate(resp.text)
    form_id   = get_form_id(resp.text)

    # Detectar campos del formulario
    soup = BeautifulSoup(resp.text, 'html.parser')
    inputs = {inp.get('name',''): inp.get('value','') for inp in soup.find_all('input')}

    # Construir payload de login
    payload = {}
    for name, val in inputs.items():
        payload[name] = val

    # Buscar campos de usuario y contraseña
    user_field = next((n for n in inputs if 'usuario' in n.lower() or 'user' in n.lower() or 'login' in n.lower()), None)
    pass_field = next((n for n in inputs if 'password' in n.lower() or 'clave' in n.lower() or 'pass' in n.lower()), None)

    if user_field:
        payload[user_field] = SIGMA_USER
    if pass_field:
        payload[pass_field] = SIGMA_PASSWORD

    # Buscar botón de submit
    btn = soup.find('input', {'type': 'submit'}) or soup.find('button', {'type': 'submit'})
    if btn and btn.get('name'):
        payload[btn['name']] = btn.get('value', 'Ingresar')

    payload['javax.faces.ViewState'] = viewstate
    if form_id:
        payload[form_id] = form_id

    print(f'  Enviando credenciales...')
    resp2 = session.post(resp.url, data=payload, timeout=20, allow_redirects=True)

    # Verificar éxito
    if 'login' in resp2.url.lower() and 'error' in resp2.text.lower():
        print('  ✗ Login fallido — verificá las credenciales en GitHub Secrets')
        return False

    print(f'  ✓ Login exitoso ({resp2.url})')
    return True

def descargar_excel(session):
    """Navega a Monitor de Hardware y descarga el Excel."""
    print('📥 Accediendo a Monitor de Hardware...')

    try:
        resp = session.get(URL_MONITOR, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f'  ✗ No se pudo acceder al monitor: {e}')
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    viewstate = get_viewstate(resp.text)
    form_id   = get_form_id(resp.text)

    # Buscar botón/link de exportar Excel
    export_btn = None
    for tag in soup.find_all(['input', 'button', 'a', 'span']):
        txt = (tag.get_text(strip=True) + tag.get('value','') + tag.get('title','')).lower()
        if any(x in txt for x in ['excel', 'xls', 'export', 'descargar', 'exportar']):
            export_btn = tag
            print(f'  Botón export encontrado: {tag.get("id","?")} — "{tag.get_text(strip=True)}"')
            break

    if export_btn:
        # Si es un link directo
        href = export_btn.get('href', '')
        if href and href not in ('#', 'javascript:void(0)', ''):
            url_export = href if href.startswith('http') else BASE_URL + href
            r = session.get(url_export, timeout=30)
            ct = r.headers.get('Content-Type', '')
            if 'application' in ct or 'excel' in ct or len(r.content) > 3000:
                print(f'  ✓ Excel descargado via GET ({len(r.content)//1024} KB)')
                return r.content

        # Si es un botón POST (JSF)
        btn_id   = export_btn.get('id') or export_btn.get('name', '')
        btn_name = export_btn.get('name') or btn_id

        payload = {
            form_id: form_id,
            'javax.faces.ViewState': viewstate,
        }
        if btn_name:
            payload[btn_name] = export_btn.get('value', '')

        # JSF partial request para trigger del botón
        payload['javax.faces.partial.ajax']   = 'true'
        payload['javax.faces.partial.execute'] = '@all'
        payload['javax.faces.partial.render']  = '@all'
        payload['javax.faces.source']          = btn_id

        r = session.post(resp.url, data=payload, timeout=30)
        ct = r.headers.get('Content-Type', '')

        if 'application' in ct or 'excel' in ct or (len(r.content) > 3000 and b'<html' not in r.content[:100].lower()):
            print(f'  ✓ Excel descargado via POST JSF ({len(r.content)//1024} KB)')
            return r.content

        # Buscar redirect a archivo en la respuesta
        if b'window.location' in r.content or b'redirect' in r.content.lower():
            soup2 = BeautifulSoup(r.text, 'html.parser')
            for sc in soup2.find_all('script'):
                if 'location' in sc.text:
                    import re
                    match = re.search(r"location['\s]*=\s*['\"]([^'\"]+)['\"]", sc.text)
                    if match:
                        url2 = match.group(1)
                        if not url2.startswith('http'):
                            url2 = BASE_URL + url2
                        r2 = session.get(url2, timeout=30)
                        if len(r2.content) > 3000:
                            print(f'  ✓ Excel descargado via redirect ({len(r2.content)//1024} KB)')
                            return r2.content

    # Intentar URL directa conocida de SIGMA
    urls_intento = [
        f'{BASE_URL}/monitorhw/pages/vistaPorTerminal.xhtml?export=xls',
        f'{BASE_URL}/monitorhw/exportarTerminales.xhtml',
        f'{BASE_URL}/monitorhw/pages/exportarTerminales.xhtml',
    ]
    for url in urls_intento:
        try:
            r = session.get(url, timeout=20)
            ct = r.headers.get('Content-Type', '')
            if 'application' in ct or 'excel' in ct or (len(r.content) > 3000 and b'<html' not in r.content[:200].lower()):
                print(f'  ✓ Excel descargado desde {url} ({len(r.content)//1024} KB)')
                return r.content
        except:
            pass

    print('  ✗ No se pudo descargar el Excel automáticamente')
    print('  → Guardá el HTML de la página para diagnóstico')
    with open('sigma_debug.html', 'w', encoding='utf-8') as f:
        f.write(resp.text)
    print('  → Guardado: sigma_debug.html')
    return None

def procesar_excel(contenido):
    """Procesa el archivo descargado de SIGMA (Excel o HTML) y devuelve dict con estado por ATM."""
    if not isinstance(contenido, bytes):
        with open(contenido, 'rb') as f:
            contenido = f.read()

    # Detectar formato real por los primeros bytes
    inicio = contenido[:20].strip()
    print(f'  Primeros bytes: {contenido[:60]}')

    df = None

    # 1. Intentar como HTML (SIGMA suele devolver HTML con extensión .xls)
    if inicio.startswith(b'<') or b'<html' in contenido[:500].lower() or b'<table' in contenido[:500].lower():
        print('  Formato detectado: HTML')
        try:
            tablas = pd.read_html(io.BytesIO(contenido), encoding='utf-8')
            if not tablas:
                tablas = pd.read_html(io.BytesIO(contenido), encoding='latin1')
            # Buscar la tabla que tenga columna Terminal
            for tabla in tablas:
                cols = [str(c).lower() for c in tabla.columns]
                if any('terminal' in c for c in cols):
                    df = tabla
                    # Renombrar columnas si están en minúsculas
                    df.columns = [str(c).strip() for c in df.columns]
                    print(f'  Tabla encontrada: {len(df)} filas, cols: {list(df.columns)[:6]}')
                    break
            if df is None and tablas:
                df = tablas[0]
                print(f'  Usando primera tabla: {len(df)} filas')
        except Exception as e:
            print(f'  Error parseando HTML: {e}')

    # 2. Intentar como XLS binario
    if df is None:
        print('  Intentando como XLS binario...')
        try:
            df = pd.read_excel(io.BytesIO(contenido), header=0, engine='xlrd')
        except Exception as e:
            print(f'  XLS falló: {e}')

    # 3. Intentar como XLSX
    if df is None:
        print('  Intentando como XLSX...')
        try:
            df = pd.read_excel(io.BytesIO(contenido), header=0, engine='openpyxl')
        except Exception as e:
            print(f'  XLSX falló: {e}')

    # 4. Intentar como CSV
    if df is None:
        print('  Intentando como CSV...')
        try:
            import csv as csv_mod
            for sep in [';', ',', '\t']:
                try:
                    df = pd.read_csv(io.BytesIO(contenido), sep=sep, encoding='latin1')
                    if len(df.columns) > 3:
                        print(f'  CSV con sep={sep!r}: {len(df)} filas')
                        break
                except: pass
        except Exception as e:
            print(f'  CSV falló: {e}')

    if df is None:
        # Guardar para diagnóstico
        with open('sigma_raw_download', 'wb') as f:
            f.write(contenido)
        raise ValueError('No se pudo parsear el archivo descargado de SIGMA. Guardado como sigma_raw_download para diagnóstico.')

    print(f'  📊 {len(df)} terminales | Estados: {df["Estado Fisico"].value_counts().to_dict()}')

    estado_atms = {}
    for _, row in df.iterrows():
        terminal = str(row.get('Terminal', '')).strip().lstrip('0')
        if not terminal: continue
        try: atm_id = int(terminal)
        except: continue

        estado_raw  = str(row.get('Estado Fisico', '')).strip().upper()
        falla       = str(row.get('FallaPrincipal', '')).strip()
        fecha       = str(row.get('Fecha Fisico', '')).strip()
        conectiv    = str(row.get('Conectividad', '')).strip()
        carga       = str(row.get('Estado Carga', '')).strip()

        cfg         = ESTADO_CONFIG.get(estado_raw, ESTADO_CONFIG['SIN DATOS'])
        falla_corta = falla.split(' - ')[-1].strip() if ' - ' in falla else falla
        falla_cat   = falla.split(' - ')[0].strip()  if ' - ' in falla else ''

        estado_atms[atm_id] = {
            'estado':      estado_raw,
            'label':       cfg['label'],
            'color':       cfg['color'],
            'icono':       cfg['icono'],
            'falla':       falla,
            'falla_corta': falla_corta,
            'falla_cat':   falla_cat,
            'fecha':       fecha[:16] if len(fecha) >= 16 else fecha,
            'conectiv':    conectiv,
            'carga':       carga,
        }
    return estado_atms

def generar_json(estado_atms, ruta='estado_atms.json'):
    """Guarda el JSON con timestamp de ejecución."""
    ahora_dt = datetime.now()
    ahora    = f"{DIAS[ahora_dt.weekday()]} {ahora_dt.strftime('%d/%m/%Y %H:%M')}hs"

    resumen = {}
    for cfg in ESTADO_CONFIG.values():
        count = sum(1 for v in estado_atms.values() if v['label'] == cfg['label'])
        if count: resumen[cfg['label']] = count

    output = {
        'actualizado': ahora,
        'total':       len(estado_atms),
        'resumen':     resumen,
        'atms':        {str(k): v for k, v in estado_atms.items()},
    }

    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n✓ {ruta} generado — {ahora}')
    print(f'  Total: {len(estado_atms)} ATMs')
    for label, count in sorted(resumen.items(), key=lambda x: -x[1]):
        iconos = {'Operativo':'✓','Advertencia':'⚠','Sin insumos':'📦',
                  'No dispensa':'💸','Falla depósito':'🏦','Fuera de servicio':'✗'}
        print(f'  {iconos.get(label,"•")} {label:<22} {count}')

    return output

# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    sep = '=' * 56
    print(f'\n{sep}')
    print(f'  AGENTE SIGMA — ATMs BPN')
    print(f'  {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    print(f'{sep}\n')

    if not SIGMA_USER or not SIGMA_PASSWORD:
        print('✗ Credenciales no configuradas.')
        print('  Configurá SIGMA_USER y SIGMA_PASSWORD en GitHub Secrets.')
        exit(1)

    session = requests.Session()

    # Login
    if not login(session):
        exit(1)

    # Descargar Excel
    print('\n📥 Descargando datos...')
    contenido = descargar_excel(session)

    if not contenido:
        print('\n✗ No se pudo obtener el Excel de SIGMA.')
        exit(1)

    # Procesar
    print('\n⚙️  Procesando...')
    estado_atms = procesar_excel(contenido)

    if not estado_atms:
        print('✗ No se obtuvieron datos válidos del Excel.')
        exit(1)

    # Guardar JSON
    generar_json(estado_atms)

    print(f'\n{sep}')
    print('  ✅  COMPLETADO — estado_atms.json listo para subir')
    print(f'{sep}\n')

if __name__ == '__main__':
    main()
