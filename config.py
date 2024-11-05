import os
from dotenv import load_dotenv

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

API_KEY = os.getenv('DATADOG_API_KEY')
APP_KEY = os.getenv('DATADOG_APP_KEY')
BASE_URL = 'https://api.datadoghq.com/api/v1/query'
