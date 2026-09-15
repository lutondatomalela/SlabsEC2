# -*- coding: utf-8 -*-

APP_NAME = "SlabsEC2"
VERSION = "2.16.0-rc1"
APP_VERSION = f"v{VERSION}"
APP_TITLE = f"SlabsEC2 {APP_VERSION} - Lajes Maciças de Betão Armado (EC2)"
APP_AUTHOR = "https://github.com/lutondatomalela/SlabsEC2"
APP_SUBJECT = "Dimensionamento e verificação de lajes maciças de betão armado segundo o Eurocódigo 2"
APP_KEYWORDS = "SlabsEC2, Eurocódigo 2, EC2, NP EN 1992-1-1, lajes maciças, armaduras, flexão, fendilhação, ELS, Wood & Armer"
APP_CATEGORY = "Structural Engineering / Reinforced Concrete Design"
APP_XLSX_DESCRIPTION = (
    "Workbook de cálculo com dados de entrada, classificação de combinações, resultados por painel de laje, "
    "solução harmonizada, flexão ELU, domínio da secção, fendilhação ELS, limitação de tensões ELS, "
    "auditoria de integridade, diagnóstico FEM, parâmetros EC2 avançados auditáveis, Wood-Armer ortogonal optimizado, entrada fail-safe, camadas físicas X/Y, base global fixa + reforços, rastreabilidade, envelope distribuído P99 + RAW local auditável e zonamento espacial. QXX/QYY e UGZ são informativos quando fornecidos; interação N-M não é verificada."
)
GITHUB_URL = "https://github.com/lutondatomalela/SlabsEC2"
MAX_PREVIEW_ROWS = 20000

# Limiares de desempenho para grandes tabelas FEM.
LARGE_DATASET_THRESHOLD = 100000
LARGE_DERIVED_MAX_ROWS = 10000
LARGE_PREVIEW_ROWS = 5000
