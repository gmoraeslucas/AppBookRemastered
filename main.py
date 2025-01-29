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
    Agrupamos os dados por 'system' -> 'name'. Exemplo do retorno:
    {
      "TESTE 1": {
        "Autorizações": {
          "Requisições": 0,
          "Degradação": 0,
          "Indisponibilidade": 0,
          "Views": 0,
          "Errors": 0,
          "Availability": 99.99
        },
        ...
      },
      "TESTE 2": {
        ...
      }
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

    # Pré-cria chaves (para serviços) a partir dos 3 arquivos de queries
    for service in queries_req:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    for service in queries_deg:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    for service in queries_ind:
        system = service.get('system', 'Desconhecido')
        service_name = service['name']
        init_resultados_servicos(system, service_name)

    with ThreadPoolExecutor(max_workers=10) as executor_query, ThreadPoolExecutor(max_workers=3) as executor_rum:
        futures = []

        # ============== Requisições e Views (Datadog) ==============
        for service in queries_req:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:view" in query:
                        # RUM => usa iso8601
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Views"
                        future_obj = executor_rum.submit(run_rum_query, query, from_time, to_time)
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Requisições"
                        future_obj = executor_query.submit(run_query, query, from_time, to_time)

                    # Armazena para processar depois
                    futures.append((future_obj, system, service_name, query_type))

        # ============== Degradação (Datadog) ==============
        for service in queries_deg:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    future_obj = executor_query.submit(run_query, query, from_time, to_time)
                    futures.append((future_obj, system, service_name, 'Degradação'))

        # ============== Indisponibilidade e Errors (Datadog) ==============
        for service in queries_ind:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:error" in query:
                        # RUM => iso8601
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Errors"
                        future_obj = executor_rum.submit(run_rum_query, query, from_time, to_time)
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Indisponibilidade"
                        future_obj = executor_query.submit(run_query, query, from_time, to_time)

                    futures.append((future_obj, system, service_name, query_type))

        # ============== Processar resultados ==============
        for future_obj, system, service_name, query_type in futures:
            resultado = future_obj.result()

            # Mantenha seus prints originais ou crie os que achar necessários
            if resultado:
                if query_type in ["Views", "Errors"]:
                    # RUM => contagem de eventos
                    if isinstance(resultado, dict) and 'data' in resultado:
                        pontos = len(resultado['data'])
                        print(f"Eventos retornados para {system} -> {service_name} ({query_type}): {pontos}")
                    elif isinstance(resultado, int):
                        pontos = resultado
                        print(f"Eventos retornados para {system} -> {service_name} ({query_type}): {pontos}")
                    else:
                        print(f"Erro ou nenhum dado para {system} -> {service_name} ({query_type}).")
                        pontos = 0
                else:
                    # Métrica Datadog => sum_points()
                    pontos = sum_points(resultado.get('series', []))
                    print(f"Dados somados para {system} -> {service_name} ({query_type}): {pontos}")

                resultados_servicos[system][service_name][query_type] += pontos
            else:
                print(f"Sem dados retornados para {system} -> {service_name} ({query_type})")

    return resultados_servicos

def coletar_dados_zabbix(intervalos):
    """
    Coleta os dados do Zabbix e calcula o SLA para cada host.
    Retorna algo como:
    {
      "hostA": {"SLA": 99.9},
      "hostB": {"SLA": 100},
      ...
    }
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
    # ============== 1) Leitura das datas ==============
    data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
    data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

    # ============== 2) Leitura das queries do JSON ==============
    queries_req = ler_queries('queries/queries_req.json')  # Requisições + Views
    queries_deg = ler_queries('queries/queries_deg.json')  # Degradação
    queries_ind = ler_queries('queries/queries_ind.json')  # Indisponibilidade + Errors

    # ============== 3) Geração de intervalos diários ==============
    intervalos = gerar_intervalo_dias(data_inicio, data_fim)

    # ============== 4) Coletar dados do Datadog ==============
    resultados_datadog = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

    # ============== 5) Calcular Availability por serviço ==============
    for system, servicos in resultados_datadog.items():
        for service_name, dados in servicos.items():
            req_views = dados["Requisições"] + dados["Views"]
            if req_views > 0:
                indisponibilidade_errors = dados["Indisponibilidade"] + dados["Errors"]
                availability = 100 - ((indisponibilidade_errors / req_views) * 100)
            else:
                availability = 100.0
            dados["Availability"] = availability

    # ============== 6) Coletar dados do Zabbix ==============
    resultados_zabbix = coletar_dados_zabbix(intervalos)

    # ============== 7) Montar e salvar o JSON principal ==============
    total_data = {
        "Datadog": resultados_datadog,
        "Zabbix": resultados_zabbix
    }

    with open('total_data.json', 'w', encoding='utf-8') as f:
        json.dump(total_data, f, indent=4, ensure_ascii=False)

    print("Dados coletados e armazenados em 'total_data.json'.")

    # =====================================================================
    #         8) Geração do segundo JSON: system_data_sla.json
    # =====================================================================

    # 8.1) Monta dicionário agrupado por sistema
    summary_service_data = {}

    # Percorremos cada 'system' em resultados_datadog
    for system_name, servicos in resultados_datadog.items():
        # Calcula média da Availability e conta quantos serviços tem
        soma_availability = 0.0
        count_servicos = 0

        for service_name, dados_service in servicos.items():
            soma_availability += dados_service["Availability"]
            count_servicos += 1

        if count_servicos > 0:
            media_sla = soma_availability / count_servicos
        else:
            media_sla = 100.0

        # Armazena no dicionário final, convertendo para string com "%"
        summary_service_data[system_name] = {
            "SLA_Total": f"{media_sla:.2f}%",
            "Quantidade de serviços": count_servicos
        }

    # 8.2) Agrupar SLAs do Zabbix em 3 categorias (PABX, SWITCH, FIREWALL)
    pabx_sum = 0.0
    pabx_count = 0

    firewall_sum = 0.0
    firewall_count = 0

    switch_sum = 0.0
    switch_count = 0

    for host_name, data_host in resultados_zabbix.items():
        sla_host = data_host.get("SLA", 0.0)

        if host_name.startswith("S"):
            # PABX
            pabx_sum += sla_host
            pabx_count += 1

        elif host_name.startswith(("cluster", "clt", "R")):
            # SWITCH
            switch_sum += sla_host
            switch_count += 1

        elif host_name.startswith("F"):
            # FIREWALL
            firewall_sum += sla_host
            firewall_count += 1

    # Média de cada grupo
    pabx_avg = pabx_sum / pabx_count if pabx_count > 0 else 0
    switch_avg = switch_sum / switch_count if switch_count > 0 else 0
    firewall_avg = firewall_sum / firewall_count if firewall_count > 0 else 0

    # Monta a estrutura Zabbix
    zabbix_group_availability = {
        "group_availability": {
            "PABX": f"{pabx_avg:.2f}%",
            "SWITCH": f"{switch_avg:.2f}%",
            "FIREWALL": f"{firewall_avg:.2f}%"
        }
    }

    # 8.3) Adiciona a chave "Zabbix" ao dicionário final
    summary_service_data["Zabbix"] = zabbix_group_availability

    # 8.4) Salva em outro arquivo JSON
    path_rede = '\\unimed02\GovernancaTI$\summary_service_data.json'
    with open(path_rede, 'w', encoding='utf-8') as f2:
        json.dump(summary_service_data, f2, indent=4, ensure_ascii=False)

    print("Arquivo 'summary_service_data.json' gerado com sucesso!")
