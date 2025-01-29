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
    total_periodo = len(eventos)
    indisponibilidades = sum(1 for evento in eventos if evento['value'] == 1)

    if total_periodo > 0:
        sla = ((total_periodo - indisponibilidades) / total_periodo) * 100
    else:
        sla = 100.0
    return sla

def coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos):
    """
    Agora agrupamos os dados por 'system' e depois por 'name'. Ou seja:
    resultados_servicos[system][service_name] = {
        "Requisições": 0,
        "Degradação": 0,
        "Indisponibilidade": 0,
        "Views": 0,
        "Errors": 0
    }
    """
    resultados_servicos = {}

    def init_resultados_servicos(system, service_name):
        if system not in resultados_servicos:
            resultados_servicos[system] = {}
        if service_name not in resultados_servicos[system]:
            resultados_servicos[system][service_name] = {
                "Requisições": 0,
                "Degradação": 0,
                "Indisponibilidade": 0,
                "Views": 0,
                "Errors": 0
            }

    # 1) Pré-cria chaves para Requisições e Views
    for service in queries_req:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    # 2) Pré-cria chaves para Degradação
    for service in queries_deg:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    # 3) Pré-cria chaves para Indisponibilidade e Errors
    for service in queries_ind:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    with ThreadPoolExecutor(max_workers=10) as executor_query, ThreadPoolExecutor(max_workers=3) as executor_rum:
        futures = []

        # Requisições e Views (Datadog)
        for service in queries_req:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:view" in query:
                        # RUM (iso8601)
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Views"
                        futures.append((executor_rum.submit(run_rum_query, query, from_time, to_time),
                                        system, service_name, query_type))
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Requisições"
                        futures.append((executor_query.submit(run_query, query, from_time, to_time),
                                        system, service_name, query_type))

        # Degradação (Datadog)
        for service in queries_deg:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((executor_query.submit(run_query, query, from_time, to_time),
                                    system, service_name, 'Degradação'))

        # Indisponibilidade e Errors (Datadog)
        for service in queries_ind:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:error" in query:
                        # RUM (iso8601)
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Errors"
                        futures.append((executor_rum.submit(run_rum_query, query, from_time, to_time),
                                        system, service_name, query_type))
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Indisponibilidade"
                        futures.append((executor_query.submit(run_query, query, from_time, to_time),
                                        system, service_name, query_type))

        # Processar resultados (Datadog)
        for future, system, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                if query_type in ["Views", "Errors"]:
                    # Para RUM, normalmente conta de eventos
                    if isinstance(resultado, dict) and 'data' in resultado:
                        pontos = len(resultado['data'])
                        print(f"Eventos retornados para {system} -> {service_name} ({query_type}): {pontos}")
                    elif isinstance(resultado, int):
                        pontos = resultado
                        print(f"Eventos retornados para {system} -> {service_name} ({query_type}): {pontos}")
                    else:
                        print(f"Nenhum dado encontrado ou erro ao processar a query para {system} -> {service_name} ({query_type}).")
                        pontos = 0
                else:
                    # Para as métricas do Datadog (trace, etc.)
                    pontos = sum_points(resultado.get('series', []))
                    print(f"Dados somados para {system} -> {service_name} ({query_type}): {pontos}")

                resultados_servicos[system][service_name][query_type] += pontos
            else:
                print(f"Sem dados retornados para {system} -> {service_name} ({query_type})")

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

if __name__ == "__main__":
    # Leitura de datas
    data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
    data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

    # Leitura dos JSON com queries
    queries_req = ler_queries('queries/queries_req.json')  # Requisições + Views
    queries_deg = ler_queries('queries/queries_deg.json')  # Degradação
    queries_ind = ler_queries('queries/queries_ind.json')  # Indisponibilidade + Errors

    # Intervalos diários
    intervalos = gerar_intervalo_dias(data_inicio, data_fim)

    # Coleta dados do Datadog
    resultados_datadog = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

    # === Cálculo da Disponibilidade por serviço ===
    # Para cada 'system' e cada 'service_name', adicionamos a chave 'Availability'
    for system, servicos in resultados_datadog.items():
        for service_name, dados in servicos.items():
            req_views = dados["Requisições"] + dados["Views"]
            if req_views > 0:
                indisponibilidade_errors = dados["Indisponibilidade"] + dados["Errors"]
                availability = 100 - ((indisponibilidade_errors / req_views) * 100)
            else:
                # Se não houve requisições + views, podemos definir 100 ou 0, dependendo do critério de negócio
                availability = 100
            # Armazena no próprio dicionário
            dados["Availability"] = f"{availability}%"

    # Coleta dados do Zabbix
    resultados_zabbix = coletar_dados_zabbix(intervalos)

    # Monta o JSON final
    summary_service_data = {
        "Datadog": resultados_datadog,
        "Zabbix": resultados_zabbix
    }

    # Salva em arquivo
    with open('summary_service_data.json', 'w', encoding='utf-8') as f:
        json.dump(summary_service_data, f, indent=4, ensure_ascii=False)

    print("Dados coletados e armazenados com sucesso no arquivo 'summary_service_data.json'.")
