# Casos de referência — SlabsEC2 v2.8.3

Existem três camadas de teste:

| Camada | Conteúdo | Nº actual |
|---|---|---:|
| Regressão funcional | combinações, envelopes, picos, armaduras, domínio e comportamento ELS | 42 |
| Validação técnica | comparação com implementação analítica separada e auditoria fail-safe | 42 |
| Validação independente | comparação com valores numéricos bloqueados | 138 |
| **Total** |  | **222** |

## Casos independentes R01–R09

Os casos cobrem C25/30 a C50/60, espessuras de 180 a 300 mm, diferentes recobrimentos, diâmetros, espaçamentos e níveis de momento. Para cada caso são comparados: `d`, `As,min`, `As,req`, `As`, `MRd`, `x`, `z`, `xcr`, `sigma_s`, `hc,eff`, `rho_p,eff`, `c_eff`, `sr,max` e `wk`.

- R01–R07: secção fendilhada, ramo EC2 7.11 de `sr,max`;
- R08: caso abaixo de `Mcr`, devendo permanecer não fendilhado e com `wk = 0`;
- R09: secção fendilhada com espaçamento elevado, ramo EC2 7.14;
- REQ: diâmetro equivalente de duas famílias `Ø10//200 + Ø8//200`, com `phi_eq = 9,111111 mm`.

A validação técnica cobre adicionalmente C60/75 e o domínio resistente de secções simplesmente armadas.

Executar:

```bash
python main.py --self-test
python main.py --validation-suite
python main.py --manual-validation
```
