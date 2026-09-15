# Nota de cálculo independente — SlabsEC2 v2.9.0

## Objectivo

Esta nota documenta a campanha de validação independente usada para auditar o núcleo de flexão ELU e fendilhação ELS-QP. Os valores de referência de `LOCKED_REFERENCE_VALUES_v2_8_0.csv` são fixos e não são recalculados pelo núcleo durante o teste.

## Base normativa adoptada

- NP EN 1992-1-1:2010, 6.1 — flexão simples;
- NP EN 1992-1-1:2010, 7.1 — distinção entre secção não fendilhada e fendilhada;
- NP EN 1992-1-1:2010, 7.2 — limitação de tensões em serviço;
- NP EN 1992-1-1:2010, 7.3.2 — área efectiva de betão traccionado;
- NP EN 1992-1-1:2010, 7.3.4 — cálculo directo da largura de fendas;
- NP EN 1992-1-1:2010, 9.2.1.1 e 9.3.1.1 — armadura mínima e regras de lajes.

## Hipóteses da campanha bloqueada

- faixa rectangular `b = 1000 mm`;
- betões C25/30 a C50/60 nos valores bloqueados;
- aço `fyk = 500 MPa`, `gamma_s = 1,15`;
- `gamma_c = 1,50`, `alpha_cc = 1,00`;
- bloco rectangular equivalente para os casos bloqueados: `C = 0,8 b x fcd`, `z = d - 0,4x`;
- `Es = 200000 MPa`;
- `kt = 0,4` para ELS quase-permanente;
- `k1 = 0,8`, `k2 = 0,5`, `k3 = 3,4`, `k4 = 0,425`.

## Expressões de controlo

`d = h - cnom - phi_ort - phi_dir/2`

`As,min = max[0,26 fctm/fyk · b d_min ; 0,0013 b d_min]`

`MEd = As fyd [d - 0,4 As fyd/(0,8 b fcd)]`

Antes do cálculo de `wk`, determina-se o momento de fendilhação da secção bruta:

`Mcr = fctm · Wgross`

Para `M <= Mcr`, a secção é tratada como não fendilhada e `wk = 0`.

Para a secção fendilhada:

`hc,eff = min[2,5(h-d); (h-xcr)/3; h/2]`

`rho_p,eff = As/Ac,eff`

`wk = sr,max (eps_sm - eps_cm)`

Para `s <= 5(c + phi/2)`:

`sr,max = 3,4 c + 0,8·0,5·0,425·phi_eq/rho_p,eff`

Para `s > 5(c + phi/2)`:

`sr,max = 1,3(h-xcr)`

Quando existem diâmetros diferentes:

`phi_eq = sum(n_i phi_i^2) / sum(n_i phi_i)`

O recobrimento utilizado em `sr,max` é o recobrimento da família longitudinal efectivamente verificada. Para a posição interior conservadora adoptada:

`c_eff = h - d - phi_eq/2`

## Exemplo de auditoria — caso R06

Dados:

- `h = 250 mm`
- `cnom = 30 mm`
- `C30/37`
- `fyk = 500 MPa`
- armaduras ortogonais `phi12`
- `M = 35 kNm/m`
- armadura conhecida `phi12/150`

Resultados independentes bloqueados:

| Grandeza | Valor |
|---|---:|
| d | 202,000 mm |
| As,min | 322,319 mm²/m |
| As,req | 407,448 mm²/m |
| As(phi12/150) | 753,982 mm²/m |
| MRd | 63,533 kNm/m |
| x ULS | 20,489 mm |
| z | 193,805 mm |
| xcr ELS | 38,725 mm |
| sigma_s | 245,490 MPa |
| hc,eff | 70,425 mm |
| rho_p,eff | 0,0107062 |
| c_eff | 42,000 mm |
| sr,max | 333,344 mm |
| wk | 0,24550 mm |

## Casos de transição

- **R08:** `M = 50 kNm/m` e `Mcr ≈ 52,632 kNm/m`; a secção deve permanecer não fendilhada, com `wk = 0`.
- **R09:** mesma geometria, `M = 80 kNm/m`; a secção está fendilhada e o espaçamento elevado força o ramo 7.14 de `sr,max`.

## Cobertura da campanha

- R01–R07: ramo 7.11 de `sr,max`;
- R08: secção não fendilhada;
- R09: ramo 7.14;
- REQ: duas famílias `phi10/200 + phi8/200`, com `phi_eq = 9,111111 mm` e `s_eff = 100 mm`.

A campanha automática bloqueada executa 138 comparações e deve falhar se qualquer resultado do núcleo se afastar dos valores fixos para além da tolerância definida.
