from concurrent.futures import ThreadPoolExecutor
from utils import run_query, sum_points, ler_queries, to_timestamp, gerar_intervalo_dias
from datetime import datetime
import json

def coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos):
    resultados_servicos = {service['name']: {"Requisições": 0, "Degradação": 0, "Indisponibilidade": 0}
                           for service in queries_req}

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = []

        for service in queries_req:
            if not service['queries']:  
                continue
            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor.submit(run_query, query, from_time, to_time), service['name'], 'Requisições'))

        for service in queries_deg:
            if not service['queries']: 
                continue
            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor.submit(run_query, query, from_time, to_time), service['name'], 'Degradação'))

        for service in queries_ind:
            if not service['queries']:
                continue
            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor.submit(run_query, query, from_time, to_time), service['name'], 'Indisponibilidade'))

        for future, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                pontos = sum_points(resultado['series'])
                print(f"Dados coletados para {service_name} ({query_type}): {pontos}")
                resultados_servicos[service_name][query_type] += pontos
            else:
                print(f"Sem dados retornados para {service_name} ({query_type})")

    return resultados_servicos

data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

queries_req = ler_queries('queries/queries_req.json')
queries_deg = ler_queries('queries/queries_deg.json')
queries_ind = ler_queries('queries/queries_ind.json')

intervalos = gerar_intervalo_dias(data_inicio, data_fim)

resultados_servicos = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

with open('resultados_servicos.json', 'w', encoding='utf-8') as f:
    json.dump(resultados_servicos, f, indent=4, ensure_ascii=False)

print("Dados coletados e armazenados com sucesso!")
