import json
import requests
from config import API_KEY, APP_KEY, BASE_URL
from datetime import datetime, timedelta, timezone
import holidays

def to_timestamp(year, month, day, hour=0, minute=0, tz_offset=-3):
    dt = datetime(year, month, day, hour, minute) - timedelta(hours=tz_offset)
    return int(dt.replace(tzinfo=timezone.utc).timestamp())

def sum_points(series):
    if series and 'pointlist' in series[0]:
        return sum(point[1] for point in series[0]['pointlist'])
    else:
        return 0

def run_query(query, from_time, to_time):
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
        print(f"Query executada com sucesso!")
        return response.json()
    else:
        print(f'Erro ao executar a consulta: {response.status_code}')
        print(response.text)
        return None

def ler_queries(arquivo):
    with open(arquivo, 'r', encoding='utf-8') as f:
        queries = json.load(f)
    return queries

def gerar_intervalo_dias(data_inicio, data_fim):
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
