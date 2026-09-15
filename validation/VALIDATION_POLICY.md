# Política de validação — SlabsEC2 v2.8.3

A v2.8.3 mantém o núcleo obrigatório independente de informação geométrica adicional e reforça a validação de flexão ELU, domínio resistente e ELS.

## Princípios

1. O dimensionamento obrigatório funciona apenas com tabela de esforços + geometria/material da laje.
2. Tabelas adicionais de nós/barras são opcionais e destinam-se apenas a diagnóstico espacial de picos.
3. A solução final é única por painel, face e direcção e é reavaliada nos casos ELU, ELS-QP e, quando fornecida, ELS característica.
4. Nenhum estado `OK`/`OK*` pode coexistir com `MEd/MRd > 1`, domínio simplesmente armado inválido ou, quando aplicável, `wk/wmax > 1`.
5. Quando a limitação de tensões ELS está activa, a auditoria bloqueia estados incompatíveis com os limites implementados.
6. Nenhuma solução automática pode ultrapassar `Ømax` ou `As,max` sem ser explicitamente marcada como não conforme.
7. A auditoria final recalcula `MRd` por uma formulação independente da rotina de optimização.
8. Os testes funcionais verificam regressões de comportamento.
9. A validação técnica compara o núcleo com uma implementação analítica separada.
10. A validação independente compara o núcleo com valores numéricos previamente calculados e bloqueados.
11. Alterações a fórmulas obrigam à revisão explícita dos valores de referência e ao registo no `CHANGELOG.md`.

## Âmbito validado nesta fase

- profundidade útil conservadora;
- propriedades de materiais;
- coeficientes do bloco rectangular equivalente até C90/105;
- As,min de flexão;
- As,req por equilíbrio de secção rectangular;
- MRd, x, z, x/d e domínio da secção simplesmente armada;
- escolha de Ø/s e respeito de Ømin/Ømax;
- preferência por espaçamentos construtivos correntes;
- transição secção não fendilhada/fendilhada por `Mcr`;
- secção fendilhada em ELS;
- Ac,eff, rho_p,eff, sigma_s, sigma_c, sr,max e wk;
- recobrimento efectivo da família longitudinal verificada;
- diâmetro equivalente para famílias com diâmetros diferentes;
- ramos 7.11 e 7.14 de sr,max;
- limitação de tensão do aço em ELS característica;
- sinalização dos limites de tensão do betão em ELS característica/quase-permanente;
- múltiplas combinações ELU, ELS característica, frequente e ELS-QP;
- solução única e reavaliação de todos os casos;
- bloqueio de falsos estados OK e divergências internas de MRd.

## Fora do âmbito

Punçoamento, corte unidireccional, deformação normativa, vibração, ancoragens, sobreposições, armadura de compressão calculada automaticamente e pormenorização local continuam fora do núcleo validado nesta fase.
