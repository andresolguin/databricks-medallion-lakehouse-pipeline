"""Render the architecture and concise technical PDF. Install the docs extra."""

import re
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
NAVY, TEAL = "#16324f", "#167d8d"


def diagram():
    plt.rcParams["svg.fonttype"] = "none"
    fig, ax = plt.subplots(figsize=(12, 6.7), facecolor="#f5f8fc")
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    ax.text(0.04, 0.95, "Iowa Liquor Sales Lakehouse", fontsize=21, color=NAVY, weight="bold")
    ax.text(
        0.04,
        0.90,
        "PySpark + Delta Lake | One implementation: local or Unity Catalog",
        fontsize=11,
        color="#52667a",
    )
    nodes = {
        "process": (0.04, 0.69, "Delivered CSV", "Process / country / delivery date"),
        "staging": (0.375, 0.69, "Verified staging", "Immutable copy + SHA-256"),
        "bronze": (0.71, 0.69, "Bronze", "Raw MERGE + file manifest"),
        "silver": (0.71, 0.41, "Silver", "Typed decision snapshot"),
        "gold": (0.375, 0.41, "Gold star schema", "Calendar + Type I dims + fact"),
        "archive": (0.04, 0.41, "Verified archive", "Staged source files + SHA-256"),
        "analytics": (0.375, 0.13, "Business analytics", "Sales, rankings and gross margin"),
        "decisions": (0.71, 0.13, "Auditable dispositions", "Rejected / duplicate / superseded"),
    }
    w, h = 0.25, 0.15
    for name, (x, y, title, text) in nodes.items():
        fill = "#e7f3f2" if name in {"silver", "gold"} else "white"
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0.008,rounding_size=0.015",
                facecolor=fill,
                edgecolor="#a5bdca",
                linewidth=1.1,
            )
        )
        ax.text(x + w / 2, y + 0.098, title, ha="center", va="center", fontsize=12, color=NAVY, weight="bold")
        ax.text(x + w / 2, y + 0.047, text, ha="center", va="center", fontsize=8.8, color="#40566b")

    def arrow(start, end, label, label_at):
        ax.add_patch(
            FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=13, linewidth=1.5, color=TEAL)
        )
        ax.text(*label_at, label, fontsize=8.7, ha="center", color=TEAL)

    arrow((0.30, 0.765), (0.36, 0.765), "stage", (0.332, 0.80))
    arrow((0.635, 0.765), (0.698, 0.765), "ingest", (0.666, 0.80))
    arrow((0.835, 0.68), (0.835, 0.575), "classify", (0.89, 0.625))
    arrow((0.70, 0.485), (0.637, 0.485), "CURRENT", (0.667, 0.52))
    arrow((0.365, 0.485), (0.302, 0.485), "publish gate", (0.332, 0.52))
    arrow((0.50, 0.40), (0.50, 0.295), "published facts", (0.575, 0.345))
    arrow((0.835, 0.40), (0.835, 0.295), "retain", (0.89, 0.345))
    ax.text(
        0.04,
        0.045,
        "Archive runs after publication checks. Gold commits are atomic per table; the star is not a multi-table transaction.",
        fontsize=9.1,
        color="#52667a",
    )
    fig.savefig(
        ROOT / "docs/diagrams/Diagrama01.png", dpi=180, bbox_inches="tight", facecolor=fig.get_facecolor()
    )
    fig.savefig(ROOT / "docs/diagrams/architecture.svg", bbox_inches="tight", metadata={"Date": None})
    svg_path = ROOT / "docs/diagrams/architecture.svg"
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text().splitlines()) + "\n")
    plt.close(fig)


def pdf():
    import reportlab

    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, filename in [("ProjectSans", "Vera.ttf"), ("ProjectSansBold", "VeraBd.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily("ProjectSans", normal="ProjectSans", bold="ProjectSansBold")
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="TitleCustom",
            fontName="ProjectSansBold",
            fontSize=26,
            leading=31,
            textColor=colors.HexColor(NAVY),
            spaceAfter=14,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionCustom",
            fontName="ProjectSansBold",
            fontSize=15,
            leading=19,
            textColor=colors.HexColor(TEAL),
            spaceBefore=12,
            spaceAfter=9,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyCustom",
            fontName="ProjectSans",
            fontSize=10,
            leading=15,
            spaceAfter=9,
            alignment=TA_LEFT,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeCustom",
            fontName="Courier",
            fontSize=8.1,
            leading=12,
            backColor=colors.HexColor("#edf2f7"),
            borderPadding=8,
            spaceAfter=12,
        )
    )
    story = []

    def para(text, style="BodyCustom"):
        story.append(Paragraph(text, styles[style]))

    def heading(text):
        para(text, "SectionCustom")

    def table(rows, widths):
        data = [[Paragraph(escape(str(cell)), styles["BodyCustom"]) for cell in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4eef4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor(TEAL)),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#ccd9e3")),
                ]
            )
        )
        story.extend([t, Spacer(1, 10)])

    para("Iowa Liquor Sales<br/>Lakehouse", "TitleCustom")
    para(
        "Andres Olguin | Data Engineering Portfolio<br/>PySpark - Spark SQL - Delta Lake - Databricks - Unity Catalog"
    )
    para(
        "A reproducible batch pipeline for delivered invoice-line data: immutable raw ingestion, explicit quality decisions, a star schema and verified source archival."
    )
    story.append(Image(str(ROOT / "docs/diagrams/Diagrama01.png"), width=7.1 * inch, height=3.96 * inch))
    heading("Execution and delivery")
    para(
        "One tested Python package serves local Delta execution, interactive notebooks and a versioned Databricks job. The job executes Bronze, Silver, Gold and Archive sequentially, with one active run per job."
    )
    para(
        'Repository: <link href="https://github.com/andresolguin/databricks-medallion-lakehouse-pipeline" color="#167d8d">github.com/andresolguin/databricks-medallion-lakehouse-pipeline</link>'
    )
    story.append(PageBreak())

    para("Data model and contracts", "TitleCustom")
    table(
        [
            ("Gold object", "Logical key", "Role"),
            ("dim_time", "date_key", "Continuous calendar"),
            ("dim_store", "country, store_id", "Current store attributes, Type I"),
            ("dim_item", "country, item_no", "Current item/category/vendor, Type I"),
            ("fact_sales", "country, invoice_line_no", "Measures, dimension keys, source lineage"),
        ],
        [110, 158, 242],
    )
    para(
        "Fact partitions use the actual sale year/month. Measures use decimal types; ZIP codes remain strings. Keys are checked for uniqueness, non-null values and dimension coverage."
    )
    heading("Acceptance rules")
    para(
        "Valid sale date; positive store/item identifiers; positive whole pack, bottle-volume and bottle-count fields; positive cost, retail, revenue and sold volumes; retail at least cost. Optional descriptive attributes can be unknown."
    )
    para(
        "Per-line balance tolerances: USD 0.05 for revenue versus bottles x retail; 0.02 L for volume versus bottles x bottle size; 0.02 US gal for liters/gallons conversion. The supported scope is positive sales; returns are quarantined."
    )
    heading("Corrections and dispositions")
    para(
        "The complete invoice-line key is retained. Latest delivery date determines the current observation. Equivalent latest-day observations deduplicate; different payloads on that date are quarantined as conflicts. Older deliveries arriving late cannot override newer observations."
    )
    para(
        "One Silver Delta table contains CURRENT, REJECTED, DUPLICATE and SUPERSEDED observations. Rejected rows retain reason codes and raw payloads. Occurrence counts preserve physical duplicates, enabling complete row accounting."
    )
    para(
        "Gold reconciles its fact from the complete current Silver snapshot. A later invalid correction removes the corresponding current fact when a nonempty valid snapshot can be published. An entirely invalid snapshot blocks publication."
    )
    story.append(PageBreak())

    para("Reproduce and verify", "TitleCustom")
    heading("Local example")
    for command in [
        'python -m pip install -e ".[local,dev]"',
        "python examples/generate_inputs.py --root .state/demo",
        "python -m iowa_lakehouse --local-root .state/demo --process-date 20251018",
        "python -m iowa_lakehouse --local-root .state/demo --process-date 20251019",
        "pytest -q",
    ]:
        para(command.replace("&", "&amp;"), "CodeCustom")
    para(
        "Use Python 3.12 and Java 17. Local tests use Spark 4.0.1 with Delta Lake 4.0.0. Initial dependency downloads require internet access. The generated files are entirely synthetic."
    )
    table(
        [
            ("Delivery", "Current facts", "Published sales"),
            ("20251018", "3", "USD 270.00"),
            ("Replay 20251018", "3", "USD 270.00"),
            ("20251019", "4", "USD 366.00"),
        ],
        [190, 145, 175],
    )
    validation = (ROOT / "docs/validation.md").read_text()
    count = re.search(r"(\d+) passed", validation)
    heading("Verification scope")
    para(
        f"Local automated suite: {count.group(0) if count else 'see docs/validation.md'}. The tests cover real Delta writes/MERGE, replay, corrections, backfills, conflicting records, field rejection, calendar analytics, partial archival and recovery between raw/manifest commits."
    )
    para(
        "Databricks deployment configuration and commands are included. Workspace authentication, Unity Catalog privileges, serverless execution and target-volume performance require validation in that workspace. Local results do not certify those cloud properties."
    )
    story.append(PageBreak())

    para("Operations and analytics", "TitleCustom")
    heading("Verified archival and restart")
    para(
        "Content SHA-256 plus country/delivery identifies each file. Raw merges are insert-only by deterministic row ID; receipts record staged/archive paths and status. Retry after an interrupted manifest registration does not reinsert raw rows."
    )
    para(
        "Archive runs after publication verification. It copies staged sources, verifies their hashes, then removes matching inputs and marks receipts complete. A partial archive copy can be repaired from verified Staging. Exceptions fail the task and preserve recoverable inputs."
    )
    heading("Analytical outputs")
    para(
        "Calendar-based monthly windows; YoY joins to the exact prior-year month; store/category rankings; item gross margins. Annual completeness is supplied as an explicit source watermark. Type I attributes classify historical facts using current dimension values."
    )
    para(
        "Price-volume analysis aggregates one observation per item/month and requires six distinct months with price/quantity variation. Its log-log association is descriptive and does not identify causal demand response or recommend prices."
    )
    heading("Design boundaries")
    para(
        "Delta atomicity is per table. Gold dimensions and facts have separate commits; Type I changes can be visible before the fact commit. One writer per namespace is required. Silver scans retained Bronze to build its full decision snapshot; this is not a streaming or fully incremental Silver implementation."
    )
    para(
        "Throughput and large-volume capacity are not inferred from the synthetic examples. Measure them on the target runtime and an identified source extract. The project does not make a production-service or cross-table transaction guarantee."
    )
    heading("Detailed references")
    para(
        "README.md - docs/architecture.md - docs/data_contract.md - docs/runbook.md - docs/validation.md - tests/ - resources/pipeline.job.yml"
    )
    para(
        "Domain source: Iowa Data Hub, Iowa Liquor Sales. No third-party source dataset is committed. Project code, documentation and synthetic examples are MIT licensed."
    )

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor(TEAL))
        canvas.line(42, 35, 570, 35)
        canvas.setFont("ProjectSans", 8)
        canvas.setFillColor(colors.HexColor(NAVY))
        canvas.drawString(42, 22, "Andres Olguin | Iowa Liquor Sales Lakehouse")
        canvas.drawRightString(570, 22, str(doc.page))

    SimpleDocTemplate(
        str(ROOT / "docs/final_project.pdf"),
        pagesize=(612, 792),
        leftMargin=42,
        rightMargin=42,
        topMargin=38,
        bottomMargin=48,
        title="Iowa Liquor Sales Lakehouse",
        author="Andres Olguin",
    ).build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    diagram()
    pdf()
    print("Rendered architecture and technical overview")
