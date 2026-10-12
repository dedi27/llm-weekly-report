# LLM Weekly Report

Gera um **relatório semanal em PDF** do uso de LLMs em agentes de coding
(Claude Code, OpenCode, Copilot CLI), lendo os logs locais via
[ccusage](https://github.com/ccusage/ccusage).

## Requisitos

- [ccusage](https://ccusage.com) instalado globalmente:
  ```bash
  npm install -g ccusage
  ```
- venv Python com `fpdf2` (já criada em `pyenvs/llm-report` na máquina original):
  ```bash
  python3 -m venv $HOME/pyenvs/llm-report
  $HOME/pyenvs/llm-report/bin/pip install fpdf2
  ```

## Uso

```bash
$HOME/pyenvs/llm-report/bin/python llm_weekly_report.py
```

### Opções

| Flag | Descrição |
|---|---|
| `--week AAAA-MM-DD` | Semana que contém a data informada (padrão: semana atual) |
| `--out /caminho.pdf` | Caminho de saída do PDF (padrão: `reports/relatorio-semanal-<segunda>.pdf`) |

O PDF é salvo em `reports/` (fora do versionamento — ver `.gitignore`).

## O que o relatório contém

1. **Resumo da semana** por agente (input, output, cache, total e custo)
2. **Uso diário** por agente, com os modelos utilizados
3. **Detalhe por modelo** (modelos locais/self-hosted aparecem sem custo)
4. **Gráfico de barras** — tokens por dia (todos os agentes somados)
5. **Gráfico de barras** — uso diário por agente, com fatias empilhadas por agente

> Os custos dos modelos locais (ex.: vLLM) não são calculados pelo ccusage
> (sem tabela de preços); o relatório marca esses itens com `-`.

## Estrutura

```
llm_weekly_report.py   # script principal (argparse + fpdf2)
reports/               # PDFs gerados (ignorado no git)
.gitignore
```