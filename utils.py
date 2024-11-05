import json
import requests
from config import API_KEY, APP_KEY, BASE_URL
from datetime import datetime, timedelta
import time

# Função para fazer a consulta à API do Datadog
def consultar_datadog(query, start_time, end_time):
    # Converter datas para timestamp Unix em segundos
    start_time_unix = int(time.mktime(start_time.timetuple()))
    end_time_unix = int(time.mktime(end_time.timetuple()))

    params = {
        'query': query,
        'from': start_time_unix,
        'to': end_time_unix
    }
    headers = {
        'DD-API-KEY': API_KEY,
        'DD-APPLICATION-KEY': APP_KEY
    }

    try:
        response = requests.get(BASE_URL, headers=headers, params=params, verify= False)
        if response.status_code == 200:
            print(f"Query executada com sucesso")
            return response.json()
        else:
            print(f"Erro na execução da query")
            return None
    except Exception as e:
        print(f"Erro inesperado na execução da query | Erro: {e}")
        return None

# Função para ler queries de um arquivo
def ler_queries(arquivo):
    with open(arquivo, 'r', encoding='utf-8') as f:  # Adicionado encoding='utf-8'
        queries = json.load(f)
    return queries

# Função para gerar intervalos de datas das 07 am até as 07 pm
def gerar_intervalo_dias(data_inicio, data_fim):
    datas = []
    data_atual = data_inicio
    while data_atual <= data_fim:
        start_time = datetime.combine(data_atual, datetime.min.time()) + timedelta(hours=7)
        end_time = datetime.combine(data_atual, datetime.min.time()) + timedelta(hours=19)
        datas.append((start_time, end_time))
        data_atual += timedelta(days=1)
    return datas
