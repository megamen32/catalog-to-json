from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

CHECKS = {"text_completeness", "table_count", "row_coverage", "column_coverage", "values", "units", "merged_cells", "blank_cells", "rotated_labels", "figures", "provenance"}

class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")

class TextBlock(Model):
    kind: Literal["heading", "paragraph", "branding", "footer"]
    text: str

class Column(Model):
    id: str
    label: str
    unit: str | None = None
    group: str | None = None

class Cell(Model):
    column_id: str
    value: str | int | float | None
    state: Literal["value", "blank", "unknown"] = "value"

    @model_validator(mode="after")
    def state_matches_value(self):
        if self.state in {"blank", "unknown"} and self.value is not None:
            raise ValueError("Blank and unknown cells must have null values")
        if self.state == "value" and self.value is None:
            raise ValueError("Null cells must explicitly identify blank or unknown")
        return self

class Row(Model):
    cells: list[Cell]

class Table(Model):
    id: str
    title: str
    columns: list[Column]
    rows: list[Row]

    @model_validator(mode="after")
    def rectangular(self):
        ids=[c.id for c in self.columns]
        if not ids or len(ids)!=len(set(ids)):
            raise ValueError("Column IDs must be nonempty and unique")
        for row in self.rows:
            row_ids=[c.column_id for c in row.cells]
            if len(row_ids)!=len(set(row_ids)) or set(row_ids)!=set(ids):
                raise ValueError("Every row must contain exactly one cell for every column")
        return self

class Figure(Model):
    title: str
    description: str
    labels: list[str]

class PageContent(Model):
    title: str
    printed_page: str | None = None
    text_blocks: list[TextBlock]
    tables: list[Table]
    figures: list[Figure]
    source_notes: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)

class Issue(Model):
    severity: Literal["error", "warning"]
    path: str
    message: str

class Check(Model):
    category: str
    passed: bool
    evidence: str

class Review(Model):
    verdict: Literal["pass", "revise", "uncertain"]
    checks: list[Check]
    issues: list[Issue]
    observed_table_count: int = Field(ge=0)
    observed_row_counts: list[int]
    observed_column_counts: list[int]

    def accepts(self, content: PageContent) -> bool:
        categories=[c.category for c in self.checks]
        return (self.verdict=="pass" and set(categories)==CHECKS and len(categories)==len(CHECKS)
                and all(c.passed and c.evidence.strip() for c in self.checks)
                and not self.issues and not content.uncertainties
                and self.observed_table_count==len(content.tables)
                and self.observed_row_counts==[len(t.rows) for t in content.tables]
                and self.observed_column_counts==[len(t.columns) for t in content.tables]
                and not any(c.state=="unknown" for t in content.tables for r in t.rows for c in r.cells))
