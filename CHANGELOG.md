# Changelog

## v2.16.0-rc1 - Reporting profissional
- Preparação da distribuição autónoma Windows x64, compilada e testada pelo GitHub Actions.
- Ícone original integrado no executável e na janela, com resoluções de 16 a 256 píxeis.
- Arranque sem consola, registo de erros e exportação dos resultados dos testes para ficheiro.
- Verificação do binário com interface, importação CSV/XLSX, cálculo e exportação PDF/XLSX.
- Memória principal redesenhada em A4 vertical.
- PDF de auditoria separado e gerado automaticamente.
- Índice e bookmarks.
- Fichas por painel com resultados e governantes.
- Resumo executivo simplificado.
- Tabelas de auditoria divididas para garantir legibilidade.
- Motor estrutural mantido sem alterações funcionais relativamente à v2.15.3.

## v2.15.3

- Corrigida coerência entre envelope distribuído, picos locais, ELS/tensões e solução Base+reforço.
- Adicionado controlo de espessura vs nome do ficheiro e estado local explícito.

## v2.15.2 — 2026-09-03

Release correctiva após análise de resultados reais multi-painel.

### Cálculo e harmonização
- Fecho final conjunto X/Y por face após cálculo da profundidade útil física das camadas.
- Pesquisa finita de soluções admissíveis impede que o modo automático termine com `MEd > MRd` quando existe uma solução na grelha configurada.
- Base + reforços mantém a base e a modulação definida pelo utilizador durante o fecho final.

### ELS / picos FEM
- Diagnóstico global de `wk` exclui nós retirados do envelope distribuído.
- Utilização ELU e `wk/wmax` RAW dos nós locais continuam guardados e são apresentados como verificação local.
- Elimina-se a contradição em que o resumo apresentava `wk/wmax < 1` mas o diagnóstico voltava a declarar o painel não conforme devido a um pico RAW.

### Combinações e diagnóstico
- Combinações `Outro` permanecem exclusivamente `Informativo`, incluindo quando coincidem com um nó de pico.
- Diagnóstico de unidades separa o máximo das combinações classificadas do máximo RAW incluindo combinações `Outro`.

### Validação
- 108/108 autotestes.
- 45/45 verificações técnicas do núcleo.
- 138/138 comparações numéricas independentes bloqueadas.
- 9114/9114 controlos determinísticos adicionais.
- Regressão de 197 496 linhas aprovada: zero falhas de integridade, zero `wk/wmax > 1` no envelope ELS-QP distribuído e `Outro` apenas informativo.

## v2.15.1 — 2026-09-03

Correcção de regressão detectada em dados reais de lajes de 250 mm.

### Cálculo
- Flexão resistente reformulada por compatibilidade de extensões; o aço pode trabalhar com `σs < fyd` sem transformar a secção em falsa não conformidade.
- `MRd` deixa de ser truncado no limite em que a armadura traccionada deixa de atingir `fyd`.
- Estratégia Base + reforços revista para não fazer um máximo nodal altamente localizado definir a malha distribuída de todo o painel.
- Nova política predefinida `P99 nodal + RAW local`, com critérios complementares max/P95, max/P99 e fracção nodal.
- Opção `RAW integral` preservada para dimensionamento conservador pelo máximo absoluto.
- Os nós separados do envelope distribuído mantêm MEd RAW, ficam `Verificar localmente` e impedem `OK` automático do painel.

### Entrada / auditoria
- Campos opcionais QXX/QYY, UGZ e NXX/NYY/NXY distinguem agora `Não fornecido` de valor zero.
- Resumos identificam política de envelope, número de nós locais e utilização RAW máxima desses nós.

### Regressão real
- 197 496 linhas, 3 painéis, h=250 mm, cnom=30 mm.
- ELU 101–133; ELS característica 205–220; frequente 202; quase-permanente 203.
- Com base Ø12//200, a armadura distribuída encontrada fica na gama Ø10/Ø12/Ø16//200, mantendo os picos RAW para verificação local.

### Validação
- 105/105 autotestes.
- 45/45 verificações técnicas do núcleo.
- 138/138 comparações numéricas independentes bloqueadas.
- 9114/9114 controlos determinísticos adicionais.

## v2.15.0 — 2026-09-03

Revisão de fiabilidade do núcleo, com prioridade a comportamento fail-safe e rastreabilidade.

### Cálculo
- Wood-Armer RAW substituído pela formulação ortogonal optimizada por ramos.
- Convenção RAW `M>0` configurável por face física.
- Profundidade útil calculada pela ordem física configurada das malhas X/Y.
- Armadura mínima de flexão calculada por face/direcção com o `d` correspondente.
- Correcção de `As,max`: controlo por face/direcção; a soma superior+inferior é apenas diagnóstica.
- Grelha automática: Ø10/12/16/20/25/32 e s=100/125/150/175/200 mm.
- Estratégia Base + reforços mantém a base invariável e uma única família adicional com a mesma modulação.
- Unidade de NXX/NYY/NXY explicitada; interacção N-M não implementada devolve `Verificar`.
- Auditoria reforçada para impedir `OK` quando As,prov < As,req ou quando a resistência/domínio é inválido.

### Entrada e relatórios
- Importação rejeita formatos de momento parciais e RAW+equivalentes simultâneos.
- Textos de profundidade útil e faces físicas alinhados com o cálculo.
- XLSX divide automaticamente tabelas que excedam o limite de linhas por folha, incluindo o modo de grandes tabelas.
- QXX/QYY explicitamente identificados como informação FEM, não como verificação de corte.
- Metadados de exportação usam o repositório do projecto em vez de identificação pessoal do autor.

### Validação congelada
- 91/91 autotestes.
- 45/45 verificações técnicas do núcleo.
- 138/138 comparações numéricas independentes bloqueadas.
- 9114/9114 controlos determinísticos adicionais da v2.15.0.
- Stress test sintético de 100 000 linhas: 100 000 linhas preservadas e zero falhas de integridade interna.

Consultar `VALIDATION.md` e a pasta `validation/` para o âmbito e limitações da versão atual.
