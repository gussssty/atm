"""
agente_alertas.py — Envía alerta por email con cajeros fuera de servicio
que NO tienen ticket abierto en Jira.

Corre 2 veces por día via GitHub Actions (8:05 y 14:45 ARG).
Secrets: GMAIL_USER, GMAIL_PASS
Destinatario: atms@bpn.com.ar
"""

import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# ── Config ────────────────────────────────────────────────────────────────────
GMAIL_USER  = os.environ.get('GMAIL_USER', '')
GMAIL_PASS  = os.environ.get('GMAIL_PASS', '')
DESTINATARIOS = ['atms@bpn.com.ar']

ARG  = timezone(timedelta(hours=-3))
DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']

ESTADOS_PROBLEMA = {'FUERA DE SERVICIO', 'NO PAGA'}

# ── Cargar datos ──────────────────────────────────────────────────────────────
def cargar_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f'  ✗ No se pudo leer {path}: {e}')
        return None

def analizar():
    sigma = cargar_json('estado_atms.json')
    jira  = cargar_json('tickets_atms.json')

    if not sigma:
        print('Sin estado_atms.json — no se puede analizar')
        return None, None, None

    tickets_por_atm = {}
    if jira:
        tickets_por_atm = jira.get('tickets', {})

    sin_ticket = []   # caídos sin ticket
    con_ticket = []   # caídos con ticket

    for atm_id_str, est in sigma.get('atms', {}).items():
        estado = (est.get('estado') or '').upper()
        if estado not in ESTADOS_PROBLEMA:
            continue

        atm_id  = int(atm_id_str)
        label   = est.get('label') or estado
        nombre  = est.get('nombre', '')
        ciudad  = est.get('ciudad', '')
        desde   = est.get('fecha', '')[:16] if est.get('fecha') else ''

        ts = tickets_por_atm.get(atm_id_str, [])
        info = {
            'id':     atm_id,
            'nombre': nombre,
            'ciudad': ciudad,
            'estado': label,
            'desde':  desde,
            'tickets': ts,
        }

        if ts:
            con_ticket.append(info)
        else:
            sin_ticket.append(info)

    return sin_ticket, con_ticket, sigma.get('actualizado', '')

# ── Armar email ───────────────────────────────────────────────────────────────
def armar_cuerpo(sin_ticket, con_ticket, actualizado):
    ahora_dt = datetime.now(ARG)
    ahora    = f"{DIAS[ahora_dt.weekday()]} {ahora_dt.strftime('%d/%m/%Y %H:%M')}hs"

    total_problema = len(sin_ticket) + len(con_ticket)

    lineas = [
        f'Estado al: {ahora}',
        f'Datos SIGMA: {actualizado}',
        '',
    ]

    if total_problema == 0:
        lineas += [
            '✅ Todos los cajeros operativos.',
            'No hay cajeros fuera de servicio ni sin pago.',
        ]
    else:
        if sin_ticket:
            lineas.append(f'🔴 SIN TICKET TÉCNICO ({len(sin_ticket)} cajero{"s" if len(sin_ticket)>1 else ""}):')
            for a in sorted(sin_ticket, key=lambda x: x['id']):
                linea = f'  • ATM {a["id"]} — {a["nombre"]} ({a["ciudad"]}) — {a["estado"]}'
                if a['desde']:
                    linea += f' desde {a["desde"]}'
                lineas.append(linea)
            lineas.append('')

        if con_ticket:
            lineas.append(f'⚠️  CON TICKET ABIERTO EN JIRA ({len(con_ticket)} cajero{"s" if len(con_ticket)>1 else ""}):')
            for a in sorted(con_ticket, key=lambda x: x['id']):
                keys = ', '.join(t['key'] for t in a['tickets'])
                linea = f'  • ATM {a["id"]} — {a["nombre"]} ({a["ciudad"]}) — {a["estado"]} [{keys}]'
                lineas.append(linea)
            lineas.append('')

        lineas += [
            '─' * 50,
            f'Total fuera de servicio: {total_problema}',
            f'  Sin pedido técnico: {len(sin_ticket)}',
            f'  Con pedido técnico: {len(con_ticket)}',
        ]

    lineas += [
        '',
        '─' * 50,
        'ATM BPN — Alerta automática',
        'Este mensaje se genera automáticamente 2 veces por día.',
    ]

    return '\n'.join(lineas)

def armar_asunto(sin_ticket, con_ticket):
    ahora = datetime.now(ARG).strftime('%d/%m %H:%M')
    total = len(sin_ticket) + len(con_ticket)
    if total == 0:
        return f'✅ ATMs BPN — Todo operativo ({ahora})'
    if sin_ticket:
        return f'🔴 ATMs BPN — {len(sin_ticket)} sin ticket técnico ({ahora})'
    return f'⚠️ ATMs BPN — {len(con_ticket)} con falla y ticket ({ahora})'

# ── Enviar email ──────────────────────────────────────────────────────────────
def enviar(asunto, cuerpo):
    msg = MIMEMultipart()
    msg['From']    = f'ATM BPN Alertas <{GMAIL_USER}>'
    msg['To']      = ', '.join(DESTINATARIOS)
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'plain', 'utf-8'))

    print(f'  Enviando a: {", ".join(DESTINATARIOS)}')
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASS)
        server.sendmail(GMAIL_USER, DESTINATARIOS, msg.as_string())
    print('  ✓ Email enviado')

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    sep = '=' * 56
    print(f'\n{sep}')
    print(f'  AGENTE ALERTAS — ATMs BPN')
    print(f'  {datetime.now(ARG).strftime("%d/%m/%Y %H:%M:%S")} (ARG)')
    print(f'{sep}\n')

    if not GMAIL_USER or not GMAIL_PASS:
        print('✗ Configurá GMAIL_USER y GMAIL_PASS en GitHub Secrets.')
        exit(1)

    sin_ticket, con_ticket, actualizado = analizar()
    if sin_ticket is None:
        exit(1)

    print(f'  Cajeros fuera de servicio: {len(sin_ticket)+len(con_ticket)}')
    print(f'    Sin ticket: {len(sin_ticket)}')
    print(f'    Con ticket: {len(con_ticket)}')

    # Solo enviar si hay cajeros con problemas sin ticket
    # (siempre envía para tener registro, comentar la línea de abajo para enviar solo si hay problemas)
    asunto = armar_asunto(sin_ticket, con_ticket)
    cuerpo = armar_cuerpo(sin_ticket, con_ticket, actualizado)

    print(f'\n  Asunto: {asunto}')
    enviar(asunto, cuerpo)

    print(f'\n  ✅ COMPLETADO\n')

if __name__ == '__main__':
    main()
