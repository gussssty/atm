"""
agente_jira.py — Consulta tickets abiertos de ATMs desde Jira Service Desk BPN
y genera tickets_atms.json para mostrar en la app HTML.

Corre automáticamente via GitHub Actions (junto con agente_sigma.py).
Credenciales via GitHub Secrets: JIRA_EMAIL, JIRA_TOKEN
"""

import os
import json
import re
import requests
from datetime import datetime, timezone, timedelta

# ── Credenciales desde GitHub Secrets ────────────────────────────────────────
JIRA_EMAIL  = os.environ.get('JIRA_EMAIL', '')
JIRA_TOKEN  = os.environ.get('JIRA_TOKEN', '')
JIRA_DOMAIN = 'servicedeskbpn.atlassian.net'
PROJECT_KEY = 'SIT'

# ── Timezone Argentina ────────────────────────────────────────────────────────
ARG  = timezone(timedelta(hours=-3))
DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']

# ── Tipos de request válidos (Reporte de errores / Fallas) ───────────────────
REQUEST_TYPES_VALIDOS = ['reporte de error', 'falla']

# ── Regex para extraer número de ATM del campo resumen ───────────────────────
# Formato: "ATM XXXXX — descripción" o "ATM XXXXX descripción"
PATRON_ATM = re.compile(r'\bATM\s+(\d{4,6})\b', re.IGNORECASE)

def get_headers():
    import base64
    creds = base64.b64encode(f'{JIRA_EMAIL}:{JIRA_TOKEN}'.encode()).decode()
    return {
        'Authorization': f'Basic {creds}',
        'Accept':        'application/json',
        'Content-Type':  'application/json',
    }

def buscar_tickets():
    """Consulta Jira API v3 para obtener tickets abiertos de ATMs."""
    print('🔍 Consultando Jira Service Desk...')

    base_url = f'https://{JIRA_DOMAIN}/rest/api/3'
    headers  = get_headers()

    # JQL: proyecto SIT, no resueltos, ordenados por fecha de creación
    jql = (
        f'project = {PROJECT_KEY} '
        f'AND resolution = Unresolved '
        f'AND statusCategory != Done '
        f'ORDER BY created DESC'
    )

    tickets   = []
    omitidos  = []
    start_at  = 0
    max_results = 100

    while True:
        params = {
            'jql':        jql,
            'startAt':    start_at,
            'maxResults': max_results,
            'fields':     'summary,status,created,updated,priority,issuetype,customfield_10010,customfield_10014',
        }

        resp = requests.get(
            f'{base_url}/search/jql',
            headers=headers,
            params=params,
            timeout=30,
        )

        if resp.status_code == 401:
            print('  ✗ Error de autenticación — verificá JIRA_EMAIL y JIRA_TOKEN en GitHub Secrets')
            return None
        if resp.status_code == 403:
            print('  ✗ Sin permisos — verificá que el token tenga acceso al proyecto SIT')
            return None
        if resp.status_code != 200:
            print(f'  ✗ Error {resp.status_code}: {resp.text[:300]}')
            return None

        data   = resp.json()
        issues = data.get('issues', [])
        total  = data.get('total', 0)

        print(f'  Página {start_at//max_results + 1}: {len(issues)} issues (total en cola: {total})')

        for issue in issues:
            fields  = issue.get('fields', {})
            summary = fields.get('summary', '') or ''

            # ── Extraer número de ATM del resumen ────────────────────────────
            match = PATRON_ATM.search(summary)
            if not match:
                omitidos.append(f'{issue.get("key")} — sin ATM en resumen: "{summary[:50]}"')
                continue
            atm_id = int(match.group(1))

            # ── Determinar request type ───────────────────────────────────────
            req_type = ''
            # Campo customfield_10010 = campo de Jira Service Management
            cf = fields.get('customfield_10010') or {}
            if isinstance(cf, dict):
                rt = cf.get('requestType') or {}
                req_type = rt.get('name', '') if isinstance(rt, dict) else ''

            # Fallback: issuetype
            if not req_type:
                it = fields.get('issuetype') or {}
                req_type = it.get('name', '') if isinstance(it, dict) else ''

            # Filtrar por tipo válido
            req_lower = req_type.lower()
            es_valido = any(t in req_lower for t in REQUEST_TYPES_VALIDOS)

            if not es_valido and req_type:
                omitidos.append(f'{issue.get("key")} ATM {atm_id} — tipo "{req_type}" no incluido')
                continue

            # ── Parsear fecha de creación ─────────────────────────────────────
            created_raw = fields.get('created', '')
            try:
                dt      = datetime.fromisoformat(created_raw.replace('Z', '+00:00'))
                dt_arg  = dt.astimezone(ARG)
                created = dt_arg.strftime('%d/%m/%Y %H:%M')
            except Exception:
                created = created_raw[:10] if created_raw else ''

            estado    = (fields.get('status')   or {}).get('name',  '') if isinstance(fields.get('status'),   dict) else ''
            prioridad = (fields.get('priority')  or {}).get('name',  '') if isinstance(fields.get('priority'), dict) else ''

            # Descripción limpia (quitar "ATM XXXXX" del inicio)
            desc = PATRON_ATM.sub('', summary).strip().lstrip('—- ').strip()

            tickets.append({
                'key':      issue.get('key', ''),
                'atm_id':   atm_id,
                'resumen':  summary,
                'desc':     desc,
                'estado':   estado,
                'tipo':     req_type,
                'prioridad':prioridad,
                'creado':   created,
                'url':      f'https://{JIRA_DOMAIN}/browse/{issue.get("key", "")}',
            })

        start_at += max_results
        if start_at >= total:
            break

    print(f'  ✓ {len(tickets)} tickets de ATMs incluidos')
    if omitidos:
        print(f'  ℹ {len(omitidos)} omitidos (sin ATM o tipo no válido):')
        for o in omitidos[:5]:
            print(f'    {o}')
        if len(omitidos) > 5:
            print(f'    ...y {len(omitidos)-5} más')

    return tickets

def generar_json(tickets, ruta='tickets_atms.json'):
    """Agrupa tickets por ATM y guarda el JSON."""
    ahora_dt = datetime.now(ARG)
    ahora    = f"{DIAS[ahora_dt.weekday()]} {ahora_dt.strftime('%d/%m/%Y %H:%M')}hs"

    # Agrupar por ATM (puede haber más de un ticket por cajero)
    por_atm = {}
    for t in tickets:
        key = str(t['atm_id'])
        if key not in por_atm:
            por_atm[key] = []
        por_atm[key].append(t)

    output = {
        'actualizado':      ahora,
        'total_tickets':    len(tickets),
        'atms_con_tickets': len(por_atm),
        'tickets':          por_atm,
    }

    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    sep = '=' * 56
    print(f'\n{sep}')
    print(f'  ✓ {ruta} generado — {ahora}')
    print(f'  {len(tickets)} tickets en {len(por_atm)} cajeros')
    print(sep)

    if por_atm:
        print('\n  ATMs con tickets abiertos:')
        for atm_id, ts in sorted(por_atm.items(), key=lambda x: int(x[0])):
            for t in ts:
                print(f'    ATM {int(atm_id):>6}  [{t["key"]:>12}]  {t["estado"]:<18}  {t["desc"][:40]}')

    return output

def main():
    sep = '=' * 56
    print(f'\n{sep}')
    print(f'  AGENTE JIRA — Tickets ATMs BPN')
    print(f'  {datetime.now(ARG).strftime("%d/%m/%Y %H:%M:%S")} (ARG)')
    print(f'{sep}\n')

    if not JIRA_EMAIL or not JIRA_TOKEN:
        print('✗ Configurá JIRA_EMAIL y JIRA_TOKEN en GitHub Secrets.')
        exit(1)

    tickets = buscar_tickets()
    if tickets is None:
        exit(1)

    generar_json(tickets)

    print('\n  ✅  COMPLETADO\n')

if __name__ == '__main__':
    main()
