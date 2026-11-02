"""As lojas de demonstração têm cópias do bot (inclusive testes internos).

Elas não fazem parte da suíte do projeto: ignoramos a pasta inteira na coleta
para os testes do repositório continuarem limpos.
"""

collect_ignore_glob = ["*"]
