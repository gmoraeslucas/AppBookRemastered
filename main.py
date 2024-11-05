from concurrent.futures import ThreadPoolExecutor
from utils import consultar_datadog, ler_queries, gerar_intervalo_dias
from datetime import datetime
import json

def coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos):
    # Inicializa a estrutura de resultados para cada serviço
    resultados_servicos = {service['name']: {"Requisições": 0, "Degradação": 0, "Indisponibilidade": 0}
                           for service in queries_req}

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []

        # Submete as consultas de "Requisições"
        for service in queries_req:
            for start_time, end_time in intervalos:
                for query in service['queries']:
                    futures.append((executor.submit(consultar_datadog, query, start_time, end_time), service['name'], 'Requisições'))

        # Submete as consultas de "Degradação"
        for service in queries_deg:
            for start_time, end_time in intervalos:
                for query in service['queries']:
                    futures.append((executor.submit(consultar_datadog, query, start_time, end_time), service['name'], 'Degradação'))

        # Submete as consultas de "Indisponibilidade"
        for service in queries_ind:
            for start_time, end_time in intervalos:
                for query in service['queries']:
                    futures.append((executor.submit(consultar_datadog, query, start_time, end_time), service['name'], 'Indisponibilidade'))

        # Processa os resultados das consultas
        for future, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                # Adicione a lógica para somar os valores retornados pela API
                resultados_servicos[service_name][query_type] += resultado.get('value', 0)

    return resultados_servicos

# Entrada do usuário
data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

# Leitura das queries dos arquivos JSON
queries_req = ler_queries('queries/queries_req.json')
queries_deg = ler_queries('queries/queries_deg.json')
queries_ind = ler_queries('queries/queries_ind.json')

# Geração de intervalos de datas
intervalos = gerar_intervalo_dias(data_inicio, data_fim)

# Coleta de dados usando multithreading
resultados_servicos = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

# Salvar os resultados em um arquivo JSON
with open('resultados_servicos.json', 'w', encoding='utf-8') as f:
    json.dump(resultados_servicos, f, indent=4, ensure_ascii=False)

print("Dados coletados e armazenados com sucesso!")
