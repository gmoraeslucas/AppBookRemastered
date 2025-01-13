import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

ZABBIX_URL = os.getenv('ZABBIX_URL')
ZABBIX_TOKEN = os.getenv('ZABBIX_TOKEN')
group_name = "UMS/APP/PRD/REDE-SEGURANCA"

def get_hostgroup_id():
    payload = {
        "jsonrpc": "2.0",
        "method": "hostgroup.get",
        "params": {
            "output": ["groupid"],
            "filter": {
                "name": [group_name]
            }
        },
        "auth": ZABBIX_TOKEN,
        "id": 1
    }
    try:
        response = requests.post(ZABBIX_URL, data=json.dumps(payload), headers={'Content-Type': 'application/json-rpc'}, verify=False)
        response.raise_for_status()
        result = response.json().get('result')
        if result:
            return result[0].get('groupid')
    except requests.exceptions.RequestException as e:
        print(f"Erro na solicitação HTTP: {e}")
    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar JSON: {e}")
    return None

def get_hosts(groupid):
    payload = {
        "jsonrpc": "2.0",
        "method": "host.get",
        "params": {
            "output": ["hostid", "name", "status"],
            "groupids": groupid,
            "filter": {
                "status": "0"
            }
        },
        "auth": ZABBIX_TOKEN,
        "id": 1
    }
    try:
        response = requests.post(ZABBIX_URL, data=json.dumps(payload), headers={'Content-Type': 'application/json-rpc'}, verify=False)
        response.raise_for_status()
        return response.json().get('result')
    except requests.exceptions.RequestException as e:
        print(f"Erro na solicitação HTTP: {e}")
    except json.JSONDecodeError as e:
        print(f"Erro ao decodificar JSON: {e}")
    return None

def get_events(hostid, start_date, end_date):
    total_events = []
    current_date = start_date
    while current_date <= end_date:
        period_start = current_date.replace(hour=0, minute=0, second=0)
        period_end = current_date.replace(hour=23, minute=59, second=59)

        payload = {
            "jsonrpc": "2.0",
            "method": "event.get",
            "params": {
                "output": ["eventid", "clock", "value"],
                "hostids": hostid,
                "time_from": int(period_start.timestamp()),
                "time_till": int(period_end.timestamp()),
                "sortfield": ["clock"],
                "sortorder": "ASC",
                "value": [0, 1] 
            },
            "auth": ZABBIX_TOKEN,
            "id": 1
        }
        try:
            response = requests.post(ZABBIX_URL, data=json.dumps(payload), headers={'Content-Type': 'application/json-rpc'}, verify=False)
            response.raise_for_status()
            total_events.extend(response.json().get('result'))
        except requests.exceptions.RequestException as e:
            print(f"Erro na solicitação HTTP: {e}")
        except json.JSONDecodeError as e:
            print(f"Erro ao decodificar JSON: {e}")

        current_date += timedelta(days=1)

    return total_events
