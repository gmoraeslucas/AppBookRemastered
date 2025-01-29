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
    Agrupa por 'system' -> 'name'. Exemplo:
    {
      "TESTE 1": {
        "Autorizações": {
          "Requisições": 0,
          "Degradação": 0,
          "Indisponibilidade": 0,
          "Views": 0,
          "Errors": 0,
          "Availability": 99.99  # calculado no pós-processamento
        },
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

    # Pré-cria chaves (Requisições, Degradação, Indisponibilidade)
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

    # Execução paralela
    with ThreadPoolExecutor(max_workers=10) as executor_query, ThreadPoolExecutor(max_workers=3) as executor_rum:
        futures = []

        # Requisições e Views
        for service in queries_req:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:view" in query:
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Views"
                        futures.append((
                            executor_rum.submit(run_rum_query, query, from_time, to_time),
                            system, service_name, query_type
                        ))
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Requisições"
                        futures.append((
                            executor_query.submit(run_query, query, from_time, to_time),
                            system, service_name, query_type
                        ))

        # Degradação
        for service in queries_deg:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                for query in service['queries']:
                    futures.append((
                        executor_query.submit(run_query, query, from_time, to_time),
                        system, service_name, 'Degradação'
                    ))

        # Indisponibilidade e Errors
        for service in queries_ind:
            system = service.get('system', 'Desconhecido')
            service_name = service['name']
            if not service['queries']:
                continue

            for start_time, end_time in intervalos:
                for query in service['queries']:
                    if "@type:error" in query:
                        from_time = to_iso8601(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_iso8601(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Errors"
                        futures.append((
                            executor_rum.submit(run_rum_query, query, from_time, to_time),
                            system, service_name, query_type
                        ))
                    else:
                        from_time = to_timestamp(start_time.year, start_time.month, start_time.day, 7)
                        to_time = to_timestamp(end_time.year, end_time.month, end_time.day, 19)
                        query_type = "Indisponibilidade"
                        futures.append((
                            executor_query.submit(run_query, query, from_time, to_time),
                            system, service_name, query_type
                        ))

        # Processar resultados
        for future, system, service_name, query_type in futures:
            resultado = future.result()
            if resultado:
                if query_type in ["Views", "Errors"]:
                    # RUM => contagem de eventos
                    if isinstance(resultado, dict) and 'data' in resultado:
                        pontos = len(resultado['data'])
                    elif isinstance(resultado, int):
                        pontos = resultado
                    else:
                        pontos = 0
                else:
                    # Métrica Datadog => sum_points()
                    pontos = sum_points(resultado.get('series', []))
                resultados_servicos[system][service_name][query_type] += pontos

    return resultados_servicos


def coletar_dados_zabbix(intervalos):
    """
    Coleta os dados do Zabbix e calcula o SLA para cada host.
    Retorna algo como:
    {
      "nomeDoHost": {"SLA": 99.9},
      "nomeDoHost2": {"SLA": 100},
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
    # Leitura de datas
    data_inicio = datetime.strptime(input("Digite a data de início (YYYY-MM-DD): "), "%Y-%m-%d")
    data_fim = datetime.strptime(input("Digite a data de fim (YYYY-MM-DD): "), "%Y-%m-%d")

    # Leitura dos JSON com queries
    queries_req = ler_queries('queries/queries_req.json')   # Requisições + Views
    queries_deg = ler_queries('queries/queries_deg.json')   # Degradação
    queries_ind = ler_queries('queries/queries_ind.json')   # Indisponibilidade + Errors

    # Intervalos diários
    intervalos = gerar_intervalo_dias(data_inicio, data_fim)

    # 1) Coleta dados do Datadog
    resultados_datadog = coletar_dados_multithread(queries_req, queries_deg, queries_ind, intervalos)

    # 2) Calcula "Availability" para cada serviço
    for system, servicos in resultados_datadog.items():
        for service_name, dados in servicos.items():
            req_views = dados["Requisições"] + dados["Views"]
            if req_views > 0:
                indisponibilidade_errors = dados["Indisponibilidade"] + dados["Errors"]
                availability = 100 - ((indisponibilidade_errors / req_views) * 100)
            else:
                availability = 100.0
            # Armazena no próprio dicionário
            dados["Availability"] = availability

    # 3) Coleta dados do Zabbix
    resultados_zabbix = coletar_dados_zabbix(intervalos)

    # 4) Monta o JSON principal (continua igual)
    summary_service_data = {
        "Datadog": resultados_datadog,
        "Zabbix": resultados_zabbix
    }

    with open('summary_service_data.json', 'w', encoding='utf-8') as f:
        json.dump(summary_service_data, f, indent=4, ensure_ascii=False)

    print("Dados coletados e armazenados em 'summary_service_data.json'.")

    # ======================================================================
    #                  5) GERA O NOVO JSON: system_data_sla
    # ======================================================================

    # Dicionário fixo com os sistemas que você deseja exibir
    system_data_sla = {
        "TOP SAÚDE": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "E-PREV": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "DROOLS": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "UNISERVICES": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "CALCULE+": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "PORTAL DA SEGUROS": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "PORTAL INST / PF / SUPER APP": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "SIEBEL": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "E-RE": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "TOP DENTAL": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        "E-VIDA": {
            "SLA_Total": "0%",
            "Quantidade de serviços": 0
        },
        # Ao final adicionaremos a chave "Zabbix" abaixo
    }

    # === 5.1) Pegar SLA de cada sistema a partir do `resultados_datadog` ===
    # Supondo que, no JSON de queries, você colocou esses nomes EXATAMENTE
    # nos campos "system". Caso esteja usando outros nomes, ajuste este loop.
    for system_name, servicos in resultados_datadog.items():
        if system_name in system_data_sla:
            # Conta quantos serviços existem e faz média das Availability
            soma_availability = 0.0
            count_servicos = 0
            for service_name, dados_service in servicos.items():
                soma_availability += dados_service["Availability"]
                count_servicos += 1

            if count_servicos > 0:
                media_sla = soma_availability / count_servicos
                system_data_sla[system_name]["SLA_Total"] = f"{media_sla:.2f}%"
                system_data_sla[system_name]["Quantidade de serviços"] = count_servicos

    # === 5.2) Agrupar SLAs do Zabbix em 3 categorias ===
    # Categorias definidas pelo startswith no nome do host:
    # - "S"       => PABX
    # - "F"       => FIREWALL
    # - "cluster", "clt", "R" => SWITCH

    pabx_sum = 0.0
    pabx_count = 0

    firewall_sum = 0.0
    firewall_count = 0

    switch_sum = 0.0
    switch_count = 0

    for host_name, data_host in resultados_zabbix.items():
        sla_host = data_host.get("SLA", 0)

        if host_name.startswith("S"):
            pabx_sum += sla_host
            pabx_count += 1
        elif host_name.startswith(("cluster", "clt", "R")):
            switch_sum += sla_host
            switch_count += 1
        elif host_name.startswith("F"):
            firewall_sum += sla_host
            firewall_count += 1

    # Calcula média (ou zero se não houver hosts)
    pabx_avg = pabx_sum / pabx_count if pabx_count else 0
    firewall_avg = firewall_sum / firewall_count if firewall_count else 0
    switch_avg = switch_sum / switch_count if switch_count else 0

    # Monta dicionário Zabbix
    zabbix_availability = {
        "group_availability": {
            "PABX": f"{pabx_avg:.2f}%",
            "FIREWALL": f"{firewall_avg:.2f}%",
            "SWITCH": f"{switch_avg:.2f}%"
        }
    }

    # === 5.3) Adiciona o Zabbix no `system_data_sla` ===
    system_data_sla["Zabbix"] = zabbix_availability

    # === 5.4) Salva o novo JSON ===
    with open('system_data_sla.json', 'w', encoding='utf-8') as f2:
        json.dump(system_data_sla, f2, indent=4, ensure_ascii=False)

    print("Arquivo 'system_data_sla.json' gerado com sucesso!")
