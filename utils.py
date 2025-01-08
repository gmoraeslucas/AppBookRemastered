import json
import requests
from datetime import datetime, timedelta, timezone
import holidays
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv('DATADOG_API_KEY')
APP_KEY = os.getenv('DATADOG_APP_KEY')
BASE_URL = 'https://api.datadoghq.com/api/v1/query'
BASE_URL_RUM = 'https://api.datadoghq.com/api/v2/rum/events/search'

def to_timestamp(year, month, day, hour=0, minute=0, tz_offset=-3):
    """
    Retorna o tempo em formato de timestamp Unix ajustado para UTC.
    """
    dt = datetime(year, month, day, hour, minute) - timedelta(hours=tz_offset)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

def to_iso8601(year, month, day, hour=0, minute=0, tz_offset=-3):
    """
    Retorna o tempo em formato ISO 8601 (YYYY-MM-DDTHH:MM:SSZ) ajustado para UTC.
    """
    dt = datetime(year, month, day, hour, minute) - timedelta(hours=tz_offset)
    return dt.replace(tzinfo=timezone.utc).isoformat(timespec='seconds')

def sum_points(series):
    """
    Função para somar pontos de métricas padrão
    """
    if series and 'pointlist' in series[0]:
        return sum(point[1] for point in series[0]['pointlist'])
    else:
        return 0

def run_query(query, from_time, to_time):
    """
    Executa uma query e retorna os eventos correspondentes.
    """
    headers = {
        'DD-API-KEY': API_KEY,
        'DD-APPLICATION-KEY': APP_KEY
    }
    params = {
        'query': query,
        'from': from_time,
        'to': to_time
    }
    response = requests.get(BASE_URL, headers=headers, params=params)
    if response.status_code == 200:
        print("Query executada com sucesso!")
        return response.json()
    else:
        print(f"Erro ao executar a consulta: {response.status_code}")
        print(response.text)
        return {}  

def run_rum_query(query, from_time, to_time):
    """
    Executa uma consulta RUM e retorna os eventos correspondentes.
    """
    headers = {
        'DD-API-KEY': API_KEY,
        'DD-APPLICATION-KEY': APP_KEY,
        'Content-Type': 'application/json'
    }

    body = {
        "filter": {
            "from": f"{from_time}",
            "to": f"{to_time}",
            "query": query
        },
        "page": {
            "limit": 1000
        }
    }

    all_data = []
    while True:
        try:
            response = requests.post(BASE_URL_RUM, headers=headers, json=body)
            if response.status_code == 200:
                result = response.json()
                if 'data' in result:
                    all_data.extend(result['data'])
                if 'meta' in result and 'page' in result['meta'] and 'after' in result['meta']['page']:
                    body['page']['cursor'] = result['meta']['page']['after']
                else:
                    break
            else:
                print(f"Erro ao executar a consulta RUM: {response.status_code}")
                print(response.text)
                break
        except Exception as e:
            print(f"Erro ao processar a consulta RUM: {str(e)}")
            break

    if len(all_data) > 0:
        return {'data': all_data} 
    else:
        print(f"Sem eventos retornados para a query '{query}' no intervalo {from_time} - {to_time}.")
        return {'data': []} 


def ler_queries(arquivo):
    """
    Função para ler arquivos JSON com queries
    """
    with open(arquivo, 'r', encoding='utf-8') as f:
        queries = json.load(f)
    return queries

def gerar_intervalo_dias(data_inicio, data_fim):
    """
    Função para gerar intervalos de tempo
    """
    datas = []
    feriados_brasil = holidays.Brazil() 
    data_atual = data_inicio
    while data_atual <= data_fim:
        if data_atual.weekday() < 5 and data_atual not in feriados_brasil:
            start_time = datetime.combine(data_atual, datetime.min.time()) + timedelta(hours=7)
            end_time = datetime.combine(data_atual, datetime.min.time()) + timedelta(hours=19)
            datas.append((start_time, end_time))
        data_atual += timedelta(days=1)
    return datas
