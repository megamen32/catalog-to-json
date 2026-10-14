"""Evidence coverage for drawing relationships, never a geometry accuracy oracle."""
import re
import unicodedata
from .schema import Model
from pydantic import Field,field_validator
from typing import Literal

class DimensionReview(Model):
    source_figure_index: int = Field(ge=0)
    source_label_index: int = Field(ge=0)
    figure_index: int = Field(ge=0)
    label_index: int = Field(ge=0)
    view: str = Field(min_length=1)
    relation: Literal['linear','diameter','leader','annotation']
    source_box: list[float] = Field(min_length=4,max_length=4)
    feature_box: list[float] = Field(min_length=4,max_length=4)
    tip_points: list[list[float]] = Field(max_length=2)
    path_ids: list[str] = Field(default_factory=list)
    source_feature: str = Field(min_length=1)
    candidate_feature_quote: str = Field(min_length=1)
    agrees_with_candidate: bool
    evidence: str = Field(min_length=1)
    correction_reason: str = ''

    @field_validator('view','source_feature','candidate_feature_quote','evidence')
    @classmethod
    def meaningful(cls,value):
        if not value.strip():raise ValueError('An actual source/view/feature quotation is required')
        return value.strip()

def dimension_targets(content,supporting_annotations=False):
    targets=[]
    for fi,figure in enumerate(content.figures):
        for li,label in enumerate(figure.labels):
            # Candidate naming or extra prose must not hide a numeric annotation.
            # Non-dimensional numbers need an explicit source-bound classification.
            inspected_label=unicodedata.normalize('NFKC',label)
            if re.search(r'\d',inspected_label) or re.fullmatch(r'\s*[DFHLRSTV]\s*',inspected_label):
                # Only a separately confirmed supporting-document context can
                # classify metadata as annotations. Bare numbers, tolerances,
                # engineering units and geometric signs remain strict targets.
                if supporting_annotations and not re.search(r'[Øø⌀∅φΦ±]|\d\s*[xх×]\s*\d|\d\s*[+−]\s*\d|\b(?:мм|см|кН|МПа|mm|cm|kN|MPa)\b|^\s*[+−-]?\d+(?:[.,]\d+)?(?:\s*[/+−-]\s*\d+(?:[.,]\d+)?)*\s*$',inspected_label):
                    continue
                targets.append({'figure_index':fi,'label_index':li,'figure_title':figure.title,'label':label})
    return targets

def missing_dimension_evidence(content,records,candidate_sha256,observed=None,observation_sha256=None,supporting_annotations=False):
    records=[r for r in records if r.get('candidate_sha256')==candidate_sha256 and r.get('agrees_with_candidate') is True
             and (observed is None or r.get('observation_sha256')==observation_sha256)]
    valid={(r['figure_index'],r['label_index']) for r in records}
    missing=[target|{'inventory':'candidate'} for target in dimension_targets(content,supporting_annotations) if (target['figure_index'],target['label_index']) not in valid]
    if observed is not None:
        source_valid={(r.get('source_figure_index'),r.get('source_label_index')) for r in records}
        missing.extend(target|{'inventory':'source'} for target in dimension_targets(observed,supporting_annotations) if (target['figure_index'],target['label_index']) not in source_valid)
    return missing
