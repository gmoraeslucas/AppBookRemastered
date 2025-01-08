from concurrent.futures import ThreadPoolExecutor
from utils import run_query, run_rum_query, sum_points, ler_queries, to_timestamp, to_iso8601, gerar_intervalo_dias
from datetime import datetime
import json

def coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos):
    resultados_servicos = {service['name']: {"Requisições": 0, "Degradação": 0, "Indisponibilidade": 0, "Views": 0, "Errors": 0}
                           for service in queries_req}
    
    with ThreadPoolExecutor(max_workers = 10) as executor_query, ThreadPoolExecutor(max_workers = 3) as executor_rum:
        futures = []

        # Requisições e Views
        for service in queries_req:
            if not service['queries']:
                continue
            for start_time, end_time in intervalos:
                if any("@type:view" in query for query in service['queries']):
                    from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                    to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                else:
                    from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                    to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)

                for query in service['queries']:
                    query_type = "Views" if "@type:view" in query else "Requisições"
                    if "@type:view" in query:
                        futures.append((executor_rum.submit(run_rum_query, query, from_time, to_time), service['name'], query_type))
                    else:
                        futures.append((executor_query.submit(run_query, query, from_time, to_time), service['name'], query_type))

        # Degradação
        for service in queries_deg:
            if not service['queries']:
                continue
            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor_query.submit(run_query, query, from_time, to_time), service['name'], 'Degradação'))

        # Indisponibilidade e Errors
        for service in queries_ind:
            if not service['queries']:
                continue
            for start_time, end_time in intervalos:
                if any("@type:error" in query for query in service['queries']):
                    from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                    to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                else:
                    from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                    to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)

                for query in service['queries']:
                    query_type = "Errors" if "@type:error" in query else "Indisponibilidade"
                    if "@type:error" in query:
                        futures.append((executor_rum.submit(run_rum_query, query, from_time, to_time), service['name'], query_type))
                    else:
                        futures.append((executor_query.submit(run_query, query, from_time, to_time), service['name'], query_type))

        # Processar resultados
        for future, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                if query_type in ["Views", "Errors"]: 
                    if isinstance(resultado, dict) and 'data' in resultado:
                        print(f"Eventos retornados: {len(resultado['data'])}")
                        pontos = len(resultado['data'])
                    elif isinstance(resultado, int): 
                        pontos = resultado
                    else:
                        print("Nenhum dado encontrado ou erro ao processar a query.")
                        pontos = 0
                else:
                    pontos = sum_points(resultado['series'])
                print(f"Dados coletados para {service_name} ({query_type}): {pontos}")
                resultados_servicos[service_name][query_type] += pontos
            else:
                print(f"Sem dados retornados para {service_name} ({query_type})")

    return resultados_servicos

# Entrada de datas
data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

# Carregar queries
queries_req = ler_queries('queries/queries_req.json')
queries_deg = ler_queries('queries/queries_deg.json')
queries_ind = ler_queries('queries/queries_ind.json')

# Gerar intervalos
intervalos = gerar_intervalo_dias(data_inicio, data_fim)

# Coletar dados
resultados_servicos = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

# Salvar resultados
with open('resultados_servicos.json', 'w', encoding='utf-8') as f:
    json.dump(resultados_servicos, f, indent=4, ensure_ascii=False)

print("Dados coletados e armazenados com sucesso!")
