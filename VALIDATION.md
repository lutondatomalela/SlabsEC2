# Validação — SlabsEC2 v2.16.0-rc1

Esta versão candidata a lançamento centra-se na apresentação dos relatórios. O motor de cálculo mantém a base da v2.15.3.

## Regressões do núcleo

As quatro baterias incluídas foram executadas na preparação da publicação de 15 de setembro de 2026. Os autotestes emitiram avisos de desempenho do pandas relativos à fragmentação de tabelas; todos os testes concluíram com sucesso.

- Self-test: 110/110
- Validation suite: 45/45
- Manual/independent validation: 138/138
- Deterministic audit: 9114/9114

## Histórico de verificação dos relatórios

A preparação original desta Release Candidate registou os seguintes resultados com um conjunto de dados de projeto:
- 197 496 linhas processadas
- 3 painéis no dataset de regressão
- memória principal PDF gerada com sucesso
- auditoria técnica PDF gerada com sucesso
- PDF principal: índice automático + bookmarks
- PDF auditoria: bookmarks
- preflight: PDFs abertos com sucesso, não encriptados e pesquisáveis
- renderização verificada visualmente em PNG: capa, índice, resumo, ficha de painel e quadros de auditoria
- tabelas largas de auditoria foram separadas para não exceder a largura útil A4 paisagem

Os dados de projeto não são distribuídos. A verificação de exportação acima não foi repetida na presente publicação. Os documentos da pasta `validation/` identificam a versão em que os respetivos referenciais foram introduzidos.

## Limitação
A RC não constitui certificação externa. Corte, punçoamento, deformação normativa e interação N-M continuam fora do âmbito automático atual.
