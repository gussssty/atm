"""
agente_sigma.py — Descarga el estado de terminales desde SIGMA Red Link
usando Selenium (navegador headless) para manejar la sesión correctamente.

Corre automáticamente via GitHub Actions cada hora.
Las credenciales vienen de variables de entorno (GitHub Secrets).
"""

import os
import io
import json
import time
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Credenciales desde GitHub Secrets ────────────────────────────────────────
SIGMA_USER     = os.environ.get('SIGMA_USER', '')
SIGMA_PASSWORD = os.environ.get('SIGMA_PASSWORD', '')

# ── URLs SIGMA ────────────────────────────────────────────────────────────────
URL_LOGIN   = 'https://sigma.redlink.com.ar/monitorhw/pages/login.xhtml'
URL_MONITOR = 'https://sigma.redlink.com.ar/monitorhw/redlink/pages/vistaPorTerminal.xhtml'

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

def crear_driver():
    """Crea un navegador Chrome headless."""
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
    opts.add_experimental_option('prefs', {
        'download.default_directory': os.path.abspath('.'),
        'download.prompt_for_download': False,
        'download.directory_upgrade': True,
    })
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(30)
    return driver

def login(driver):
    """Hace login en SIGMA con Selenium."""
    print('🔐 Iniciando sesión en SIGMA...')
    driver.get(URL_LOGIN)
    wait = WebDriverWait(driver, 15)

    print(f'  URL login: {driver.current_url}')

    # Esperar que cargue el formulario
    try:
        # Buscar campo usuario
        user_field = None
        for selector in ['input[type="text"]', 'input[name*="usuario"]',
                         'input[name*="user"]', 'input[id*="usuario"]']:
            try:
                user_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                if user_field.is_displayed():
                    break
            except: pass

        if not user_field:
            print('  ✗ No se encontró el campo de usuario')
            driver.save_screenshot('sigma_debug.png')
            with open('sigma_debug.html','w',encoding='utf-8',errors='replace') as f:
                f.write(driver.page_source)
            return False

        # Buscar campo contraseña
        pass_field = None
        for selector in ['input[type="password"]', 'input[name*="password"]',
                         'input[name*="clave"]', 'input[id*="password"]']:
            try:
                pass_field = driver.find_element(By.CSS_SELECTOR, selector)
                if pass_field.is_displayed():
                    break
            except: pass

        if not pass_field:
            print('  ✗ No se encontró el campo de contraseña')
            return False

        # Completar formulario
        user_field.clear()
        user_field.send_keys(SIGMA_USER)
        pass_field.clear()
        pass_field.send_keys(SIGMA_PASSWORD)

        # Buscar y clickear botón de login
        btn = None
        for selector in ['input[type="submit"]', 'button[type="submit"]',
                         'input[value*="ngresar"]', 'button']:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, selector)
                if btn.is_displayed():
                    break
            except: pass

        if btn:
            btn.click()
        else:
            pass_field.submit()

        # Esperar navegación
        time.sleep(3)
        print(f'  URL post-login: {driver.current_url}')

        if 'login' in driver.current_url.lower():
            # Verificar si es error de credenciales
            page = driver.page_source.lower()
            if any(x in page for x in ['incorrecto','invalido','error','invalid']):
                print('  ✗ Login fallido — credenciales incorrectas')
                return False
            print('  ⚠ Sigue en login, esperando...')
            time.sleep(3)

        print(f'  ✓ Login OK — URL: {driver.current_url}')
        return True

    except Exception as e:
        print(f'  ✗ Error en login: {e}')
        with open('sigma_debug.html','w',encoding='utf-8',errors='replace') as f:
            f.write(driver.page_source)
        return False

def descargar_excel(driver):
    """Navega al monitor y descarga el Excel."""
    print('📥 Accediendo a Monitor de Hardware...')

    driver.get(URL_MONITOR)
    time.sleep(3)
    print(f'  URL monitor: {driver.current_url}')

    if 'login' in driver.current_url.lower():
        print('  ✗ Redirigido al login — sesión no válida')
        with open('sigma_debug.html','w',encoding='utf-8',errors='replace') as f:
            f.write(driver.page_source)
        return None

    # Guardar HTML del monitor para diagnóstico
    with open('sigma_monitor.html','w',encoding='utf-8',errors='replace') as f:
        f.write(driver.page_source)
    print('  sigma_monitor.html guardado')

    # Buscar botón de exportar Excel
    export_btn = None
    for selector in [
        'input[value*="xcel"]', 'input[value*="Excel"]',
        'button[value*="xcel"]', 'button[value*="Excel"]',
        'a[href*="xcel"]', 'a[href*="export"]',
        'input[id*="export"]', 'button[id*="export"]',
        'input[title*="Excel"]', 'span[title*="Excel"]',
    ]:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, selector)
            for b in btns:
                if b.is_displayed():
                    export_btn = b
                    print(f'  Botón export: {b.tag_name} id={b.get_attribute("id")} val={b.get_attribute("value")} txt={b.text[:30]}')
                    break
            if export_btn: break
        except: pass

    # Si no encontró por selector, buscar por texto
    if not export_btn:
        for tag in ['input','button','a','span']:
            try:
                elems = driver.find_elements(By.TAG_NAME, tag)
                for e in elems:
                    txt = (e.text + e.get_attribute('value') or '' + e.get_attribute('title') or '').lower()
                    if any(x in txt for x in ['excel','xls','export','exportar','descargar']):
                        if e.is_displayed():
                            export_btn = e
                            print(f'  Botón export por texto: {e.tag_name} — "{e.text or e.get_attribute("value")}"')
                            break
                if export_btn: break
            except: pass

    if not export_btn:
        print('  ✗ No se encontró botón de exportar')
        print('  Elementos visibles en página:')
        for tag in ['input','button','a']:
            elems = driver.find_elements(By.TAG_NAME, tag)
            for e in elems[:5]:
                if e.is_displayed():
                    print(f'    {e.tag_name}: id={e.get_attribute("id")} val={e.get_attribute("value")} txt={e.text[:30]}')
        return None

    # Configurar directorio de descarga y clickear
    download_dir = os.path.abspath('.')
    print(f'  Descargando en: {download_dir}')
    export_btn.click()
    
    # Esperar que aparezca el archivo descargado
    print('  Esperando descarga...')
    for i in range(15):
        time.sleep(2)
        archivos = [f for f in os.listdir(download_dir) 
                    if f.endswith(('.xls','.xlsx','.csv')) and 'estado_atms' not in f]
        if archivos:
            archivo = max(archivos, key=lambda f: os.path.getmtime(os.path.join(download_dir, f)))
            ruta = os.path.join(download_dir, archivo)
            print(f'  ✓ Descargado: {archivo} ({os.path.getsize(ruta)//1024} KB)')
            with open(ruta,'rb') as f:
                return f.read(), archivo
        print(f'  Esperando... ({(i+1)*2}s)')

    print('  ✗ Timeout esperando descarga')
    return None

def procesar_excel(contenido, nombre_archivo=''):
    """Procesa el archivo descargado."""
    if isinstance(contenido, tuple):
        contenido, nombre_archivo = contenido

    if isinstance(contenido, bytes):
        data = io.BytesIO(contenido)
    else:
        data = contenido

    # Detectar formato
    inicio = contenido[:50] if isinstance(contenido, bytes) else b''
    print(f'  Formato detectado por primeros bytes: {inicio[:20]}')

    df = None
    # HTML disfrazado de Excel
    if b'<' in inicio or b'html' in inicio.lower():
        print('  Parseando como HTML...')
        tablas = pd.read_html(data, encoding='latin1')
        for t in tablas:
            cols = [str(c).lower() for c in t.columns]
            if any('terminal' in c for c in cols):
                df = t
                break
        if df is None and tablas:
            df = tablas[0]
    
    if df is None:
        for engine in ['xlrd', 'openpyxl']:
            try:
                if isinstance(data, io.BytesIO): data.seek(0)
                df = pd.read_excel(data, header=0, engine=engine)
                print(f'  Parseado como Excel ({engine})')
                break
            except: pass

    if df is None:
        raise ValueError('No se pudo parsear el archivo')

    print(f'  📊 {len(df)} filas | Columnas: {list(df.columns)[:6]}')

    estado_atms = {}
    for _, row in df.iterrows():
        terminal = str(row.get('Terminal', row.iloc[0] if len(row) > 0 else '')).strip().lstrip('0')
        if not terminal or not terminal.isdigit(): continue
        try: atm_id = int(terminal)
        except: continue

        estado_raw  = str(row.get('Estado Fisico', row.get('Estado Físico',''))).strip().upper()
        falla       = str(row.get('FallaPrincipal', row.get('Falla Principal',''))).strip()
        fecha       = str(row.get('Fecha Fisico', row.get('Fecha Físico',''))).strip()
        cfg         = ESTADO_CONFIG.get(estado_raw, ESTADO_CONFIG['SIN DATOS'])
        falla_corta = falla.split(' - ')[-1].strip() if ' - ' in falla else falla
        falla_cat   = falla.split(' - ')[0].strip()  if ' - ' in falla else ''

        estado_atms[atm_id] = {
            'estado': estado_raw, 'label': cfg['label'], 'color': cfg['color'],
            'icono': cfg['icono'], 'falla': falla, 'falla_corta': falla_corta,
            'falla_cat': falla_cat,
            'fecha': fecha[:16] if len(fecha) >= 16 else fecha,
            'conectiv': str(row.get('Conectividad','')).strip(),
            'carga':    str(row.get('Estado Carga','')).strip(),
        }
    return estado_atms

def generar_json(estado_atms, ruta='estado_atms.json'):
    ahora_dt = datetime.now()
    ahora    = f"{DIAS[ahora_dt.weekday()]} {ahora_dt.strftime('%d/%m/%Y %H:%M')}hs"
    resumen  = {}
    for cfg in ESTADO_CONFIG.values():
        count = sum(1 for v in estado_atms.values() if v['label'] == cfg['label'])
        if count: resumen[cfg['label']] = count

    output = {'actualizado': ahora, 'total': len(estado_atms),
               'resumen': resumen, 'atms': {str(k): v for k,v in estado_atms.items()}}

    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f'\n✓ {ruta} generado — {ahora}')
    for label, count in sorted(resumen.items(), key=lambda x: -x[1]):
        iconos = {'Operativo':'✓','Advertencia':'⚠','Sin insumos':'📦',
                  'No dispensa':'💸','Falla depósito':'🏦','Fuera de servicio':'✗'}
        print(f'  {iconos.get(label,"•")} {label:<22} {count}')
    return output

def main():
    sep = '=' * 56
    print(f'\n{sep}')
    print(f'  AGENTE SIGMA — ATMs BPN')
    print(f'  {datetime.now().strftime("%d/%m/%Y %H:%M:%S")}')
    print(f'{sep}\n')

    if not SIGMA_USER or not SIGMA_PASSWORD:
        print('✗ Configurá SIGMA_USER y SIGMA_PASSWORD en GitHub Secrets.')
        exit(1)

    driver = crear_driver()
    try:
        if not login(driver):
            exit(1)

        resultado = descargar_excel(driver)
        if not resultado:
            exit(1)

        estado_atms = procesar_excel(resultado)
        if not estado_atms:
            print('✗ Sin datos válidos.')
            exit(1)

        generar_json(estado_atms)
        print(f'\n{sep}')
        print('  ✅  COMPLETADO')
        print(f'{sep}\n')

    finally:
        driver.quit()

if __name__ == '__main__':
    main()
