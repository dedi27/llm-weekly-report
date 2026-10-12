#!/usr/bin/env python3
"""
Relatório semanal de uso de LLMs em PDF.

Lê os logs locais dos agentes de coding via `ccusage` (npm install -g ccusage)
e gera um PDF com:
  1. Resumo da semana por agente (tokens e custo)
  2. Uso diário por agente
  3. Detalhe por modelo
  4. Gráfico de barras: tokens por dia

Uso:
  python llm_weekly_report.py                    # semana atual
  python llm_weekly_report.py --week 2026-09-28  # semana que contém essa data
  python llm_weekly_report.py --out /caminho.pdf # saída customizada

Requisitos:
  - ccusage instalado globalmente (npm install -g ccusage)
  - fpdf2 dentro de uma venv (já criada em /home/dedi/pyenvs/llm-report)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from fpdf import FPDF, FontFace, XPos, YPos

# ---------------------------------------------------------------------------
# Coleta de dados (ccusage)
# ---------------------------------------------------------------------------

SOURCES = [
    ("claude", "Claude Code"),
    ("opencode", "OpenCode"),
    ("copilot", "Copilot CLI"),
]

WEEKDAYS_PT = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# Cores (RGB) usadas no layout
DARK = (30, 41, 59)
MID = (100, 116, 139)
LIGHT_BG = (241, 245, 249)
LIGHT_BORDER = (203, 213, 225)
BLUE = (59, 130, 246)

# Cores para os modelos no gráfico por LLM
MODEL_COLORS = [
    (59, 130, 246),    # azul
    (139, 92, 246),    # roxo
    (34, 197, 94),     # verde
    (249, 115, 22),    # laranja
    (239, 68, 68),     # vermelho
    (8, 145, 178),     # ciano
]


def week_range(anchor: date) -> tuple[date, date]:
    """Retorna (segunda, domingo) da semana que contém `anchor`."""
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def fetch_daily(source: str, since: date, until_exclusive: date) -> dict | None:
    """Roda `ccusage <source> daily --json` para o período. None se não houver dados."""
    cmd = [
        "ccusage", source, "daily",
        "--since", since.isoformat(),
        "--until", until_exclusive.isoformat(),
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        sys.exit("Erro: `ccusage` não encontrado. Instale com: npm install -g ccusage")
    except subprocess.TimeoutExpired:
        print(f"  aviso: ccusage {source} estourou o timeout; ignorando", file=sys.stderr)
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not data.get("daily"):
        return None
    return data


# ---------------------------------------------------------------------------
# Formatação
# ---------------------------------------------------------------------------

def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M".replace(".", ",")
    if n >= 1_000:
        return f"{n // 1_000}k"
    return fmt_int(n)


def fmt_usd(v: float | None) -> str:
    if not v or v <= 0:
        return "-"
    s = f"{v:,.2f}"
    return "US$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date_short(d: date) -> str:
    return f"{d:%d/%m} {WEEKDAYS_PT[d.weekday()]}"


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

class ReportPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(
            0, 10,
            f"Gerado em {datetime.now():%d/%m/%Y %H:%M}  |  página {self.page_no()}",
            align="R",
        )


def ensure_space(pdf: FPDF, needed: float = 60) -> None:
    if pdf.get_y() + needed > pdf.h - 25:
        pdf.add_page()


def draw_header(pdf: FPDF, monday: date, sunday: date) -> None:
    pdf.set_fill_color(*DARK)
    pdf.rect(0, 0, 210, 30, "F")
    pdf.set_xy(15, 9)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 10, "Relatório Semanal de Uso de LLMs")
    pdf.set_xy(15, 20)
    pdf.set_font("helvetica", "", 10)
    pdf.cell(0, 8,
             f"Período: {monday:%d/%m/%Y} a {sunday:%d/%m/%Y}   |   Fonte: ccusage (logs locais)")
    pdf.set_y(38)
    pdf.set_text_color(30, 30, 30)


def section_title(pdf: FPDF, text: str) -> None:
    ensure_space(pdf, 50)
    pdf.set_font("helvetica", "B", 13)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_draw_color(*DARK)
    pdf.set_line_width(0.4)
    y_line = pdf.get_y() - 2
    pdf.line(15, y_line, 195, y_line)
    pdf.ln(4)


def subsection(pdf: FPDF, text: str) -> None:
    ensure_space(pdf, 35)
    pdf.ln(2)
    pdf.set_font("helvetica", "B", 11)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(0, 7, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def build_summary(pdf: FPDF, reports: dict) -> None:
    section_title(pdf, "1. Resumo da semana")
    headers = ["Agente", "Input", "Output", "Cache (criação)", "Cache (leitura)", "Total tokens", "Custo"]
    widths = (30, 24, 24, 28, 28, 30, 16)  # soma = 180 mm (largura útil da página)

    rows = []
    tot = {"in": 0, "out": 0, "cc": 0, "cr": 0, "tot": 0}
    cost = 0.0
    for key, name in SOURCES:
        rep = reports.get(key)
        if not rep:
            continue
        t = rep["totals"]
        rows.append([
            name,
            fmt_int(t["inputTokens"]),
            fmt_int(t["outputTokens"]),
            fmt_int(t["cacheCreationTokens"]),
            fmt_int(t["cacheReadTokens"]),
            fmt_int(t["totalTokens"]),
            fmt_usd(t["totalCost"]),
        ])
        tot["in"] += t["inputTokens"]
        tot["out"] += t["outputTokens"]
        tot["cc"] += t["cacheCreationTokens"]
        tot["cr"] += t["cacheReadTokens"]
        tot["tot"] += t["totalTokens"]
        cost += t["totalCost"]

    pdf.set_font("helvetica", "", 8)
    with pdf.table(
        [headers] + rows,
        first_row_as_headings=True,
        headings_style=FontFace(emphasis="B",
                                color=(255, 255, 255), fill_color=DARK),
        col_widths=widths,
    ):
        pass

    # Linha TOTAL (manual, para garantir negrito + fundo)
    values = ["TOTAL", fmt_int(tot["in"]), fmt_int(tot["out"]), fmt_int(tot["cc"]),
              fmt_int(tot["cr"]), fmt_int(tot["tot"]), fmt_usd(cost)]
    y = pdf.get_y()
    x = pdf.l_margin
    pdf.set_fill_color(*LIGHT_BG)
    pdf.set_draw_color(*LIGHT_BORDER)
    pdf.set_text_color(*DARK)
    for w, v in zip(widths, values):
        pdf.rect(x, y, w, 7, "DF")
        pdf.set_font("helvetica", "B", 8)
        pdf.set_xy(x + 2, y + 1.8)
        pdf.cell(w - 4, 5, v)
        x += w
    pdf.ln(10)


def build_daily(pdf: FPDF, reports: dict) -> None:
    section_title(pdf, "2. Uso diário")
    idx = 0
    for key, name in SOURCES:
        rep = reports.get(key)
        if not rep:
            continue
        idx += 1
        subsection(pdf, f"2.{idx} {name}")

        headers = ["Data", "Input", "Output", "Cache (cria/leitura)", "Total tokens", "Custo", "Modelos"]
        widths = (24, 24, 22, 34, 26, 20, 30)  # soma = 180 mm
        rows = []
        for day in rep["daily"]:
            d = date.fromisoformat(day.get("period") or day["date"])
            cache = f"{fmt_int(day['cacheCreationTokens'])} / {fmt_int(day['cacheReadTokens'])}"
            models = ", ".join(day["modelsUsed"])
            rows.append([
                fmt_date_short(d),
                fmt_int(day["inputTokens"]),
                fmt_int(day["outputTokens"]),
                cache,
                fmt_int(day["totalTokens"]),
                fmt_usd(day["totalCost"]),
                models,
            ])
        pdf.set_font("helvetica", "", 8)
        with pdf.table(
            [headers] + rows,
            first_row_as_headings=True,
            headings_style=FontFace(emphasis="B",
                                    color=(255, 255, 255), fill_color=DARK),
            col_widths=widths,
        ):
            pass
        pdf.ln(3)


def build_models(pdf: FPDF, reports: dict) -> None:
    section_title(pdf, "3. Detalhe por modelo")
    headers = ["Agente", "Modelo", "Input", "Output", "Total tokens", "Custo"]
    widths = (30, 50, 28, 24, 28, 20)  # soma = 180 mm

    rows = []
    has_unpriced = False
    for key, name in SOURCES:
        rep = reports.get(key)
        if not rep:
            continue
        agg: dict[str, dict] = {}
        for day in rep["daily"]:
            for mb in day.get("modelBreakdowns", []):
                a = agg.setdefault(mb["modelName"],
                                   {"in": 0, "out": 0, "cc": 0, "cr": 0, "cost": 0.0, "unpr": False})
                a["in"] += mb.get("inputTokens", 0)
                a["out"] += mb.get("outputTokens", 0)
                a["cc"] += mb.get("cacheCreationTokens", 0)
                a["cr"] += mb.get("cacheReadTokens", 0)
                a["cost"] += mb.get("cost", 0.0)
                a["unpr"] = a["unpr"] or bool(mb.get("missingPricing"))
        for model, a in sorted(agg.items()):
            total = a["in"] + a["out"] + a["cc"] + a["cr"]
            rows.append([
                name, model,
                fmt_int(a["in"]), fmt_int(a["out"]), fmt_int(total),
                fmt_usd(a["cost"]),
            ])
            if a["unpr"] and total > 0:
                has_unpriced = True

    pdf.set_font("helvetica", "", 8)
    with pdf.table(
        [headers] + rows,
        first_row_as_headings=True,
        headings_style=FontFace(emphasis="B",
                                color=(255, 255, 255), fill_color=DARK),
        col_widths=widths,
    ):
        pass
    if has_unpriced:
        pdf.set_font("helvetica", "I", 8)
        pdf.set_text_color(*MID)
        pdf.cell(0, 5, "* custo não calculado: modelo sem tabela de preços (local/self-hosted)")
        pdf.ln(8)


def build_chart(pdf: FPDF, monday: date, reports: dict) -> None:
    section_title(pdf, "4. Tokens por dia (todos os agentes)")
    days: dict[str, int] = {}
    for rep in reports.values():
        for day in rep["daily"]:
            key = day.get("period") or day["date"]
            days[key] = days.get(key, 0) + day["totalTokens"]

    ensure_space(pdf, 85)
    x0, y0 = 25, pdf.get_y() + 5
    width, height = 160, 55
    maxv = max(days.values()) if days else 0
    slot = width / 7
    bar_w = slot * 0.55

    pdf.set_draw_color(*LIGHT_BORDER)
    pdf.set_line_width(0.3)
    pdf.line(x0, y0 + height, x0 + width, y0 + height)

    for i in range(7):
        d = monday + timedelta(days=i)
        v = days.get(d.isoformat(), 0)
        h = (v ** 0.5 / (maxv ** 0.5)) * (height - 8) if maxv else 0
        bx = x0 + i * slot + (slot - bar_w) / 2
        if v > 0:
            pdf.set_fill_color(*BLUE)
            pdf.rect(bx, y0 + height - h, bar_w, h, "F")
        # rótulo do valor (acima da barra)
        pdf.set_xy(bx - 5, y0 + height - h - 6)
        pdf.set_font("helvetica", "B", 7)
        pdf.set_text_color(*DARK)
        pdf.cell(slot + 10, 5, fmt_tokens(v) if v else "", align="C")
        # rótulo do dia (abaixo da linha base)
        pdf.set_xy(bx - 5, y0 + height + 2)
        pdf.set_font("helvetica", "", 7)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(slot + 10, 5, f"{d:%d} {WEEKDAYS_PT[d.weekday()]}", align="C")

    pdf.set_y(y0 + height + 12)
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(*MID)
    pdf.cell(0, 5, "Escala: raiz quadrada do total de tokens (destaque para dias de menor uso).")
    pdf.ln(8)


def build_chart_by_model(pdf: FPDF, monday: date, reports: dict) -> None:
    section_title(pdf, "5. Uso diário por agente")
    # Coleta: por dia -> por agente -> total de tokens (modelos somados por agente)
    per_day: dict[str, dict[str, int]] = {}
    for key, name in SOURCES:
        rep = reports.get(key)
        if not rep:
            continue
        for day in rep["daily"]:
            day_key = day.get("period") or day["date"]
            for mb in day.get("modelBreakdowns", []):
                total = (
                    mb.get("inputTokens", 0)
                    + mb.get("outputTokens", 0)
                    + mb.get("cacheCreationTokens", 0)
                    + mb.get("cacheReadTokens", 0)
                )
                if total:
                    per_day.setdefault(day_key, {}).setdefault(name, 0)
                    per_day[day_key][name] += total

    # Agentes ordenados por total da semana (desc)
    agent_totals: dict[str, int] = {}
    for agents in per_day.values():
        for a, v in agents.items():
            agent_totals[a] = agent_totals.get(a, 0) + v
    agents = [a for a, _ in sorted(agent_totals.items(), key=lambda kv: -kv[1])]

    day_totals = {k: sum(v.values()) for k, v in per_day.items()}
    maxv = max(day_totals.values()) if day_totals else 0
    needed = 85 + 6 * len(agents)
    ensure_space(pdf, needed)

    x0, y0 = 25, pdf.get_y() + 5
    width, height = 160, 55
    slot = width / 7
    bar_w = slot * 0.5
    baseline = y0 + height

    pdf.set_draw_color(*LIGHT_BORDER)
    pdf.set_line_width(0.3)
    pdf.line(x0, baseline, x0 + width, baseline)

    for i in range(7):
        d = monday + timedelta(days=i)
        today = per_day.get(d.isoformat(), {})
        day_total = sum(today.values())
        bx = x0 + i * slot + (slot - bar_w) / 2
        if day_total:
            # altura total da coluna: escala raiz quadrada;
            # fatias: proporção de cada agente no total do dia.
            # Obs.: pdf.rect desenha de (x, y) para BAIXO -> cada fatia
            # deve começar em y_cursor - h_seg para empilhar corretamente.
            h_total = (day_total ** 0.5 / maxv ** 0.5) * (height - 8)
            y_cursor = baseline
            for j, a in enumerate(agents):
                v = today.get(a, 0)
                if not v:
                    continue
                h_seg = h_total * (v / day_total)
                pdf.set_fill_color(*MODEL_COLORS[j % len(MODEL_COLORS)])
                pdf.rect(bx, y_cursor - h_seg, bar_w, h_seg, "F")
                y_cursor -= h_seg
            # rótulo do total do dia
            pdf.set_xy(bx - 5, y_cursor - 6)
            pdf.set_font("helvetica", "B", 7)
            pdf.set_text_color(*DARK)
            pdf.cell(slot + 10, 5, fmt_tokens(day_total), align="C")
        # rótulo do dia
        pdf.set_xy(bx - 5, baseline + 2)
        pdf.set_font("helvetica", "", 7)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(slot + 10, 5, f"{d:%d} {WEEKDAYS_PT[d.weekday()]}", align="C")

    # Legenda (uma linha por agente)
    ly = baseline + 10
    pdf.set_font("helvetica", "", 8)
    for j, a in enumerate(agents):
        pdf.set_xy(x0, ly)
        pdf.set_fill_color(*MODEL_COLORS[j % len(MODEL_COLORS)])
        pdf.rect(x0, ly + 1, 4, 4, "F")
        pdf.set_xy(x0 + 6, ly)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 6, f"{a}  ({fmt_int(agent_totals[a])} tokens na semana)")
        ly += 7

    pdf.set_y(ly + 4)
    pdf.set_font("helvetica", "I", 8)
    pdf.set_text_color(*MID)
    pdf.multi_cell(
        0, 5,
        "Cada coluna é um dia; as fatias coloridas mostram a participação de cada agente "
        "(modelos somados dentro do agente). Altura da coluna: raiz quadrada do total do dia.",
        align="LEFT",
    )
    pdf.ln(3)


def build_pdf(out: Path, monday: date, sunday: date, reports: dict) -> None:
    pdf = ReportPDF(format="A4")
    pdf.set_auto_page_break(True, 22)
    pdf.add_page()
    draw_header(pdf, monday, sunday)

    if not reports:
        pdf.set_font("helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, "Nenhum dado de uso encontrado no período.")
    else:
        build_summary(pdf, reports)
        build_daily(pdf, reports)
        build_models(pdf, reports)
        build_chart(pdf, monday, reports)
        build_chart_by_model(pdf, monday, reports)

    pdf.output(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gera um relatório semanal de uso de LLMs em PDF (via ccusage)."
    )
    ap.add_argument("--week",
                    help="Data (AAAA-MM-DD) dentro da semana desejada. Padrão: semana atual.")
    ap.add_argument("--out",
                    help="Caminho do PDF de saída. Padrão: <script>/reports/relatorio-semanal-<segunda>.pdf")
    args = ap.parse_args()

    anchor = date.fromisoformat(args.week) if args.week else date.today()
    monday, sunday = week_range(anchor)
    until_exclusive = monday + timedelta(days=7)

    print(f"Coletando dados de {monday:%d/%m/%Y} a {sunday:%d/%m/%Y} ...")
    reports: dict = {}
    for key, name in SOURCES:
        data = fetch_daily(key, monday, until_exclusive)
        if data:
            reports[key] = data
            print(f"  [ok] {name}: {len(data['daily'])} dia(s) com uso")
        else:
            print(f"  [--] {name}: sem dados no período")

    if args.out:
        out = Path(args.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = (Path(__file__).resolve().parent / "reports"
               / f"relatorio-semanal-{monday.isoformat()}.pdf")
        out.parent.mkdir(parents=True, exist_ok=True)

    build_pdf(out, monday, sunday, reports)
    print(f"PDF gerado: {out}")


if __name__ == "__main__":
    main()