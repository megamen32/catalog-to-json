"""Reject conflicting source-observation and final-review structure, not source data."""

def structural_disagreements(observed, review):
    counts = {
        'table_count': (len(observed.tables), review.observed_table_count),
        'row_coverage': ([len(t.rows) for t in observed.tables], review.observed_row_counts),
        'column_coverage': ([len(t.columns) for t in observed.tables], review.observed_column_counts),
    }
    return [{'category': category, 'independent_observation': source, 'final_review': final}
            for category, (source, final) in counts.items()
            if source != final]
