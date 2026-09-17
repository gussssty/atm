"""
agente_sigma.py — Descarga el estado de terminales desde SIGMA Red Link
usando Selenium (Chrome headless).
Flujo: Login → navegar a vistaPorTerminal → click DESCARGAR → procesar Excel
"""

import os, io, json, time, glob
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

SIGMA_USER     = os.environ.get('SIGMA_USER', '')
SIGMA_PASSWORD = os.environ.get('SIGMA_PASSWORD', '')

URL_LOGIN   = 'https://sigma.redlink.com.ar/monitorhw/pages/login.xhtml'
URL_MONITOR = 'https://sigma.redlink.com.ar/monitorhw/pages/vistaPorTerminal.xhtml'

ESTADO_CONFIG = {
    'OK':                {'color':'#43A047','icono':'✓', 'label':'Operativo'},
    'ADVERTENCIA':       {'color':'#43A047','icono':'⚠', 'label':'Advertencia'},
    'INSUMOS':           {'color':'#43A047','icono':'📦','label':'Sin insumos'},
    'NO PAGA':           {'color':'#E53935','icono':'💸','label':'No dispensa'},
    'DEPOSITO':          {'color':'#43A047','icono':'🏦','label':'Falla depósito'},
    'FUERA DE SERVICIO': {'color':'#E53935','icono':'✗', 'label':'Fuera de servicio'},
    'SIN DATOS':         {'color':'#90A4AE','icono':'?', 'label':'Sin datos'},
}
DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']

def crear_driver():
    download_dir = os.path.abspath('.')
    opts = Options()
    opts.add_argument('--headless')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1920,1080')
    opts.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')
    opts.add_experimental_option('prefs', {
        'download.default_directory':    download_dir,
        'download.prompt_for_download':  False,
        'download.directory_upgrade':    True,
        'safebrowsing.enabled':          False,
    })
    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(30)
    return driver

def salvar_debug(driver, nombre='sigma_debug.html'):
    with open(nombre, 'w', encoding='utf-8', errors='replace') as f:
        f.write(f'<!-- URL: {driver.current_url} -->\n')
        f.write(driver.page_source)
    print(f'  Debug guardado: {nombre}')

def login(driver):
    print('🔐 Iniciando sesión en SIGMA...')
    driver.get(URL_LOGIN)
    wait = WebDriverWait(driver, 15)

    try:
        # Esperar campo usuario
        user_field = wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, 'input[type="text"], input[name*="usuario"], input[id*="usuario"]')))
        pass_field = driver.find_element(By.CSS_SELECTOR,
            'input[type="password"], input[name*="password"], input[name*="clave"]')

        user_field.clear(); user_field.send_keys(SIGMA_USER)
        pass_field.clear(); pass_field.send_keys(SIGMA_PASSWORD)
        print(f'  Credenciales ingresadas. Enviando...')

        # Buscar botón submit
        try:
            btn = driver.find_element(By.CSS_SELECTOR, 'input[type="submit"], button[type="submit"]')
            btn.click()
        except:
            pass_field.submit()

        time.sleep(4)
        url_actual = driver.current_url
        print(f'  URL post-login: {url_actual}')

        # Verificar login fallido
        if 'login' in url_actual.lower():
            src = driver.page_source.lower()
            if any(x in src for x in ['incorrecto','invalido','error','invalid','wrong']):
                print('  ✗ Credenciales incorrectas')
                return False
            print('  ⚠ Sigue en login pero sin error visible — continuando...')

        print('  ✓ Login completado')
        return True

    except Exception as e:
        print(f'  ✗ Error en login: {e}')
        salvar_debug(driver)
        return False

def descargar_excel(driver):
    print('📥 Navegando a Monitor de Hardware...')
    download_dir = os.path.abspath('.')

    # Registrar archivos existentes antes de descargar
    antes = set(glob.glob(os.path.join(download_dir, '*.xls*')) +
                glob.glob(os.path.join(download_dir, '*.csv')))

    driver.get(URL_MONITOR)
    time.sleep(5)
    print(f'  URL actual: {driver.current_url}')

    if 'login' in driver.current_url.lower():
        print('  ✗ Redirigido al login — sesión no válida')
        salvar_debug(driver)
        return None

    # Esperar que cargue la tabla de terminales
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'table, .rf-dt, [id*="terminal"]'))
        )
        print('  ✓ Tabla de terminales cargada')
    except:
        print('  ⚠ Tabla no detectada, intentando de todos modos...')

    salvar_debug(driver, 'sigma_monitor.html')

    # Buscar botón DESCARGAR — el verde con ícono Excel de la captura
    btn_descargar = None
    selectores = [
        'input[value*="DESCARGAR"]',
        'input[value*="Descargar"]',
        'input[value*="descargar"]',
        'button[value*="DESCARGAR"]',
        'a[title*="Excel"]',
        'a[title*="excel"]',
        'input[id*="excel"]',
        'input[id*="Excel"]',
        'button[id*="excel"]',
        '.x-excel-btn',
        'img[src*="excel"]',
        'input[src*="excel"]',
    ]

    for sel in selectores:
        try:
            elems = driver.find_elements(By.CSS_SELECTOR, sel)
            for e in elems:
                if e.is_displayed():
                    btn_descargar = e
                    print(f'  ✓ Botón DESCARGAR encontrado: {e.tag_name} — val="{e.get_attribute("value")}" id="{e.get_attribute("id")}"')
                    break
            if btn_descargar: break
        except: pass

    # Si no encontró, buscar por texto visible
    if not btn_descargar:
        print('  Buscando por texto visible...')
        for tag in ['input','button','a','span','div']:
            elems = driver.find_elements(By.TAG_NAME, tag)
            for e in elems:
                try:
                    txt = (e.text + ' ' + (e.get_attribute('value') or '') + ' ' + (e.get_attribute('title') or '')).upper()
                    if 'DESCARGAR' in txt or 'EXCEL' in txt or 'EXPORTAR' in txt:
                        if e.is_displayed():
                            btn_descargar = e
                            print(f'  ✓ Botón por texto: <{tag}> "{txt[:40]}"')
                            break
                except: pass
            if btn_descargar: break

    if not btn_descargar:
        print('  ✗ No se encontró el botón DESCARGAR')
        print('  Elementos interactivos visibles:')
        for tag in ['input','button','a']:
            for e in driver.find_elements(By.TAG_NAME, tag)[:8]:
                try:
                    if e.is_displayed():
                        print(f'    <{tag}> id="{e.get_attribute("id")}" val="{e.get_attribute("value")}" txt="{e.text[:30]}"')
                except: pass
        return None

    # Click en descargar
    print('  Clickeando DESCARGAR...')
    try:
        driver.execute_script("arguments[0].click();", btn_descargar)
    except:
        btn_descargar.click()

    # Esperar archivo nuevo en el directorio
    print('  Esperando descarga...')
    for i in range(20):
        time.sleep(2)
        despues = set(glob.glob(os.path.join(download_dir, '*.xls*')) +
                      glob.glob(os.path.join(download_dir, '*.csv')))
        nuevos = despues - antes
        # Ignorar archivos en progreso (.crdownload)
        nuevos = {f for f in nuevos if not f.endswith('.crdownload')}
        if nuevos:
            archivo = list(nuevos)[0]
            size = os.path.getsize(archivo)
            print(f'  ✓ Descargado: {os.path.basename(archivo)} ({size//1024} KB)')
            with open(archivo, 'rb') as f:
                return f.read(), os.path.basename(archivo)
        print(f'  Esperando... {(i+1)*2}s')

    print('  ✗ Timeout — no apareció el archivo descargado')
    return None

def procesar_excel(resultado):
    contenido, nombre = resultado
    print(f'  Procesando: {nombre}')
    data = io.BytesIO(contenido)
    inicio = contenido[:100]

    df = None
    # HTML disfrazado de Excel (muy común en JSF)
    if b'<' in inicio[:10] or b'html' in inicio.lower():
        print('  Formato: HTML')
        try:
            tablas = pd.read_html(io.BytesIO(contenido), encoding='latin1')
            for t in tablas:
                cols = [str(c).lower() for c in t.columns]
                if any('terminal' in c or 'nro' in c for c in cols):
                    df = t; break
            if df is None and tablas: df = tablas[0]
        except Exception as e:
            print(f'  HTML parse error: {e}')

    if df is None:
        for engine in ['xlrd', 'openpyxl']:
            try:
                data.seek(0)
                df = pd.read_excel(data, header=0, engine=engine)
                print(f'  Formato: Excel ({engine})')
                break
            except Exception as e:
                print(f'  {engine} falló: {e}')

    if df is None:
        raise ValueError('No se pudo parsear el archivo')

    # Normalizar nombres de columnas
    df.columns = [str(c).strip() for c in df.columns]
    print(f'  {len(df)} filas | Cols: {list(df.columns)[:6]}')

    estado_atms = {}
    col_terminal = next((c for c in df.columns if 'terminal' in c.lower() or 'nro' in c.lower()), df.columns[0])
    col_estado   = next((c for c in df.columns if 'estado' in c.lower() and 'fisic' in c.lower()), None)
    col_falla    = next((c for c in df.columns if 'falla' in c.lower()), None)
    col_fecha    = next((c for c in df.columns if 'fecha' in c.lower() and 'fisic' in c.lower()), None)
    col_conect   = next((c for c in df.columns if 'conectiv' in c.lower()), None)
    col_carga    = next((c for c in df.columns if 'carga' in c.lower()), None)

    print(f'  Columnas mapeadas: terminal={col_terminal}, estado={col_estado}, falla={col_falla}')

    for _, row in df.iterrows():
        terminal = str(row[col_terminal]).strip().lstrip('0')
        if not terminal or not terminal.isdigit(): continue
        try: atm_id = int(terminal)
        except: continue

        estado_raw  = str(row[col_estado] if col_estado else '').strip().upper()
        falla       = str(row[col_falla]  if col_falla  else '').strip()
        fecha       = str(row[col_fecha]  if col_fecha  else '').strip()
        cfg         = ESTADO_CONFIG.get(estado_raw, ESTADO_CONFIG['SIN DATOS'])
        falla_corta = falla.split(' - ')[-1].strip() if ' - ' in falla else falla
        falla_cat   = falla.split(' - ')[0].strip()  if ' - ' in falla else ''

        estado_atms[atm_id] = {
            'estado': estado_raw, 'label': cfg['label'], 'color': cfg['color'],
            'icono': cfg['icono'], 'falla': falla, 'falla_corta': falla_corta,
            'falla_cat': falla_cat,
            'fecha':    fecha[:16] if len(fecha) >= 16 else fecha,
            'conectiv': str(row[col_conect] if col_conect else '').strip(),
            'carga':    str(row[col_carga]  if col_carga  else '').strip(),
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
    print(f'\n✓ {ruta} — {ahora}')
    iconos = {'Operativo':'✓','Advertencia':'⚠','Sin insumos':'📦',
              'No dispensa':'💸','Falla depósito':'🏦','Fuera de servicio':'✗'}
    for label, count in sorted(resumen.items(), key=lambda x: -x[1]):
        print(f'  {iconos.get(label,"•")} {label:<22} {count}')

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
        print('\n⚙️  Procesando archivo...')
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
