# SlabsEC2

**SlabsEC2** é uma ferramenta em Python para dimensionamento, verificação e auditoria de **lajes maciças de betão armado**, a partir de resultados de modelos estruturais com elementos de placa/casca.

A versão atual é **v2.16.0-rc1 (Release Candidate)** e tem como referência principal a **NP EN 1992-1-1:2010**, incluindo as correções e alterações aplicáveis da **AC:2012** e **A1:2019**.

> **Estado do projeto:** Release Candidate. A ferramenta inclui verificações internas extensivas, mas não constitui software certificado e não substitui a revisão técnica do projetista.

## Funcionalidades principais

- dimensionamento à flexão em faixas de 1 m, nas direções locais X/Y e nas duas faces da laje;
- tratamento de momentos `MXX`, `MYY` e `MXY` através de Wood-Armer ortogonal otimizado;
- suporte alternativo a momentos equivalentes `MXX+`, `MXX-`, `MYY+` e `MYY-`;
- verificação ELU por compatibilidade de extensões da secção;
- armadura mínima e controlo de `As,max`;
- controlo ELS de fendilhação com cálculo de `wk`;
- controlo de tensões ELS no âmbito implementado;
- consideração da posição física das camadas de armadura X/Y na determinação da altura útil;
- estratégia de dimensionamento **Base + reforço**;
- deteção e tratamento auditável de concentrações locais/picos FEM;
- rastreabilidade de painel, nó e combinação governante;
- zonamento espacial opcional quando existem coordenadas;
- exportação de resultados para **XLSX** e **PDF**;
- memória de cálculo principal e relatório técnico de auditoria separados.

## Armaduras automáticas

Diâmetros disponíveis:

`Ø10`, `Ø12`, `Ø16`, `Ø20`, `Ø25`, `Ø32`

Espaçamentos disponíveis:

`100`, `125`, `150`, `175`, `200 mm`

## Formato de entrada

A tabela de resultados deve identificar, no mínimo:

- painel;
- nó;
- combinação;
- esforços de flexão.

São aceites dois formatos de momentos, que não devem ser misturados na mesma tabela:

### Resultados RAW

```text
MXX, MYY, MXY
```

### Momentos equivalentes

```text
MXX+, MXX-, MYY+, MYY-
```

Os quatro campos equivalentes devem estar presentes em conjunto.

Podem ainda ser fornecidos `QXX`, `QYY`, `UGZ`, `NXX`, `NYY` e `NXY`. Na versão atual, `QXX/QYY` e `UGZ` são informativos; a interação completa `N-M` não é verificada automaticamente.

## Instalação

### Executável para Windows

O executável para Windows x64 é distribuído na secção [Releases](https://github.com/lutondatomalela/SlabsEC2/releases). Descarregar o ficheiro `.exe` e abrir; não é necessário instalar Python.

Consultar as [instruções de utilização e compilação para Windows](docs/WINDOWS.md).

### Execução a partir do código-fonte

Recomenda-se Python 3.10 ou superior.

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Linux/macOS:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

> Em algumas distribuições Linux, o `tkinter` é instalado separadamente através do gestor de pacotes do sistema.

## Validação

A Release Candidate inclui os seguintes controlos:

- **110/110** autotestes do núcleo;
- **45/45** verificações técnicas;
- **138/138** comparações numéricas independentes;
- **9114/9114** controlos determinísticos adicionais.

Execução:

```bash
python main.py --self-test
python main.py --validation-suite
python main.py --manual-validation
python main.py --audit
```

A documentação de validação está disponível em [`VALIDATION.md`](VALIDATION.md) e na pasta [`validation/`](validation/).

## Política para picos FEM

A política predefinida utiliza um **envelope distribuído baseado no P99 nodal**, preservando os valores RAW das concentrações locais para revisão específica. Esta política é um procedimento de pós-processamento de resultados FEM e não uma expressão normativa do Eurocódigo.

Regiões próximas de pilares, apoios, cargas concentradas, aberturas, alterações de geometria ou outras descontinuidades devem ser avaliadas pelo projetista antes da adoção da armadura final.

### Artigo técnico sobre o P99 nodal

O artigo **Tratamento estatístico P99 nodal no SlabsEC2** apresenta os fundamentos estatísticos, os critérios de seleção de nós, a preservação dos esforços RAW para verificação local e a interpretação dos resultados. Inclui exemplos numéricos reproduzíveis, limites de aplicação e referências bibliográficas em formato IEEE, com DOI quando disponível.

- [Consultar o artigo em PDF](docs/artigos/SlabsEC2_Artigo_P99_Nodal.pdf).

Documento de 16 de setembro de 2026, relativo à **v2.16.0-rc1**, revisão [`2fa4717`](https://github.com/lutondatomalela/SlabsEC2/tree/2fa4717c92eb8b5a17d5c7d64a4d51758090e01a).

> **Âmbito:** documentação técnica explicativa da política **P99 nodal + RAW local**. Os exemplos demonstram a lógica do algoritmo, não constituindo validação experimental do desempenho estrutural nem substituindo a verificação das zonas locais pelo projetista.

## Limitações atuais

Não estão incluídas, de forma automática, as seguintes verificações:

- corte unidirecional;
- punçoamento;
- interação completa `N-M` de elementos de casca;
- deformações normativas a curto e longo prazo;
- vibrações;
- verificação bidimensional específica da fendilhação quando a direção principal de tração não coincide com os eixos das armaduras;
- pormenorização final de amarrações, dispensas, prolongamentos e compatibilização local com apoios e aberturas.

## Estrutura do repositório

```text
SlabsEC2/
├── main.py
├── slabsec2/
│   ├── gui/
│   ├── geometry/
│   └── ...
├── validation/
├── docs/
│   ├── artigos/
│   └── WINDOWS.md
├── README.md
├── VALIDATION.md
├── CHANGELOG.md
├── requirements.txt
└── LICENSE
```

## Referências normativas

- NP EN 1992-1-1:2010 — Eurocódigo 2: Projeto de estruturas de betão — Parte 1-1: Regras gerais e regras para edifícios.
- NP EN 1992-1-1:2010/AC:2012.
- NP EN 1992-1-1:2010/A1:2019.

Os documentos normativos não são distribuídos com este repositório.

## Licença

Distribuído sob a licença MIT. Consultar [`LICENSE`](LICENSE).
