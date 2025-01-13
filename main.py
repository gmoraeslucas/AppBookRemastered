from concurrent.futures import ThreadPoolExecutor
from utils_datadog import run_query, run_rum_query, sum_points, ler_queries, to_timestamp, to_iso8601, gerar_intervalo_dias
from utils_zabbix import get_hostgroup_id, get_hosts, get_events
from datetime import datetime
import json

def calcular_sla(eventos):
    """
    Calcula o SLA com base nos eventos retornados pelo Zabbix.
    Considera que eventos com `value=1` representam indisponibilidade.
    """
    total_periodo = len(eventos)  # Total de registros de eventos no período
    indisponibilidades = sum(1 for evento in eventos if evento['value'] == 1)

    if total_periodo > 0:
        sla = ((total_periodo - indisponibilidades) / total_periodo) * 100
    else:
        sla = 100.0  # Sem eventos significa 100% de SLA
    return sla

def coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos):
    resultados_servicos = {service['name']: {"Requisições": 0, "Degradação": 0, "Indisponibilidade": 0, "Views": 0, "Errors": 0}
                           for service in queries_req}
    
    with ThreadPoolExecutor(max_workers=10) as executor_query, ThreadPoolExecutor(max_workers=3) as executor_rum:
        futures = []

        # Requisições e Views (Datadog)
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

        # Degradação (Datadog)
        for service in queries_deg:
            if not service['queries']:
                continue
            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor_query.submit(run_query, query, from_time, to_time), service['name'], 'Degradação'))

        # Indisponibilidade e Errors (Datadog)
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

        # Processar resultados (Datadog)
        for future, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                if query_type in ["Views", "Errors"]: 
                    if isinstance(resultado, dict) and 'data' in resultado:
                        pontos = len(resultado['data'])
                        print(f"Eventos retornados para {service_name} ({query_type}): {pontos}")
                    elif isinstance(resultado, int): 
                        pontos = resultado
                        print(f"Eventos retornados para {service_name} ({query_type}): {pontos}")
                    else:
                        print(f"Nenhum dado encontrado ou erro ao processar a query para {service_name} ({query_type}).")
                        pontos = 0
                else:
                    pontos = sum_points(resultado['series'])
                    print(f"Dados somados para {service_name} ({query_type}): {pontos}")
                resultados_servicos[service_name][query_type] += pontos
            else:
                print(f"Sem dados retornados para {service_name} ({query_type})")

    return resultados_servicos

def coletar_dados_zabbix(intervalos):
    """
    Coleta os dados do Zabbix e calcula o SLA para cada host.
    """
    group_id = get_hostgroup_id()
    if not group_id:
        print("Grupo não encontrado no Zabbix.")
        return {}

    hosts = get_hosts(group_id)
    if not hosts:
        print("Nenhum host encontrado no Zabbix.")
        return {}

    resultados_zabbix = {}
    for host in hosts:
        eventos = []
        for start_time, end_time in intervalos:
            eventos_diarios = get_events(host['hostid'], start_time, end_time)
            eventos.extend(eventos_diarios)

        sla = calcular_sla(eventos)
        resultados_zabbix[host['name']] = {"SLA": sla}

    return resultados_zabbix

# Entrada de datas
data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

# Coletar dados do Datadog
queries_req = ler_queries('queries/queries_req.json')
queries_deg = ler_queries('queries/queries_deg.json')
queries_ind = ler_queries('queries/queries_ind.json')
intervalos = gerar_intervalo_dias(data_inicio, data_fim)

resultados_datadog = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

# Coletar dados do Zabbix
resultados_zabbix = coletar_dados_zabbix(intervalos)

# Combinar os resultados e salvar no arquivo JSON
summary_service_data = {
    "Datadog": resultados_datadog,
    "Zabbix": resultados_zabbix
}

with open('summary_service_data.json', 'w', encoding='utf-8') as f:
    json.dump(summary_service_data, f, indent=4, ensure_ascii=False)

print("Dados coletados e armazenados com sucesso no arquivo 'summary_service_data.json'.")
