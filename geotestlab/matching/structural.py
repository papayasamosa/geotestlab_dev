"""Structural matching feature preparation.

Pure functions (no Streamlit): market-dataframe cleaning/standardisation,
numeric-metric detection, weighted aggregation, and median imputation.  The
live app keeps thin cached wrappers around these.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import ADOBE_COL, POPULATION_COL, POPULATION_COL_RAW


def normalise_column_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.contains("^Unnamed", case=False, na=False)]
    return df


def get_population_column(df: pd.DataFrame) -> str:
    if POPULATION_COL_RAW in df.columns:
        return POPULATION_COL_RAW
    if POPULATION_COL in df.columns:
        return POPULATION_COL
    candidates = [c for c in df.columns if c.strip().lower() in ["total population", "population"]]
    if candidates:
        return candidates[0]
    raise ValueError(
        "Could not find a population column. Expected 'Total Population' or 'Population'."
    )


def get_base_geography_column(df: pd.DataFrame) -> str:
    non_market_cols = [c for c in df.columns if c != "Market"]
    if not non_market_cols:
        raise ValueError("Could not identify a base geography column.")
    return non_market_cols[0]


def get_grouping_columns(df: pd.DataFrame) -> list[str]:
    pop_col = get_population_column(df)
    pop_idx = list(df.columns).index(pop_col)
    pre_population_cols = list(df.columns[:pop_idx])
    grouping_cols = [c for c in pre_population_cols if c not in ["Market", ADOBE_COL]]
    grouping_cols = [c for c in grouping_cols if not c.lower().startswith("adobe")]
    if not grouping_cols:
        grouping_cols = [get_base_geography_column(df)]
    return grouping_cols


def standardise_population_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pop_col = get_population_column(df)
    if pop_col != POPULATION_COL:
        df = df.rename(columns={pop_col: POPULATION_COL})
    return df


def get_numeric_metric_columns(df: pd.DataFrame, grouping_cols: list[str]) -> list[str]:
    categorical_keywords = [
        "area",
        "region",
        "county",
        "city",
        "district",
        "borough",
        "territory",
        "province",
        "state",
        "country",
        "name",
        "code",
    ]
    excluded = set(grouping_cols + ["Market", ADOBE_COL, POPULATION_COL, POPULATION_COL_RAW])
    numeric_cols = []
    for c in df.columns:
        if c in excluded:
            continue
        if any(keyword in c.lower() for keyword in categorical_keywords):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            numeric_cols.append(c)
        else:
            numeric_attempt = pd.to_numeric(df[c], errors="coerce")
            if numeric_attempt.notna().sum() > len(df[c]) * 0.5:
                numeric_cols.append(c)
    return numeric_cols


def prepare_market_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = standardise_population_column(df)
    if POPULATION_COL not in df.columns:
        raise ValueError("Population column not found after standardisation.")
    df[POPULATION_COL] = pd.to_numeric(df[POPULATION_COL], errors="coerce")
    grouping_cols = get_grouping_columns(df)
    excluded_cols = set(grouping_cols + ["Market", ADOBE_COL, POPULATION_COL])
    for c in df.columns:
        if c not in excluded_cols and c != POPULATION_COL:
            sample = df[c].dropna().head(10)
            if len(sample) > 0:
                sample_str = sample.astype(str)
                looks_numeric = sample_str.str.match(r"^[\d\-\.\,]+$").all()
                if looks_numeric:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=[POPULATION_COL])
    df = df[df[POPULATION_COL] > 0]
    return df


def weighted_average_vectorized(
    df: pd.DataFrame, value_cols: list[str], weight_col: str
) -> pd.Series:
    result_dict = {}
    if not value_cols:
        result_dict[weight_col] = df[weight_col].sum()
        return pd.Series(result_dict)
    weights = df[weight_col].values.reshape(-1, 1)
    values = df[value_cols].values
    valid_mask = pd.notna(df[value_cols]).values
    weighted_sums = np.where(valid_mask, values * weights, 0).sum(axis=0)
    weight_sums = np.where(valid_mask, weights, 0).sum(axis=0)
    results = np.divide(
        weighted_sums,
        weight_sums,
        out=np.full(weighted_sums.shape, np.nan, dtype=float),
        where=weight_sums != 0,
    )
    result_dict.update(dict(zip(value_cols, results)))
    result_dict[weight_col] = df[weight_col].sum()
    return pd.Series(result_dict)


def aggregate_market_data(
    market_df: pd.DataFrame,
    grouping_col: str,
    numeric_metric_cols: list[str],
    population_col: str = POPULATION_COL,
) -> pd.DataFrame:
    keep_cols = ["Market", grouping_col, population_col] + numeric_metric_cols
    keep_cols = [c for c in keep_cols if c in market_df.columns]
    df = market_df[keep_cols].copy()
    df = df.dropna(subset=[grouping_col, population_col])
    agg_df = (
        df.groupby(grouping_col, dropna=True)
        .apply(lambda x: weighted_average_vectorized(x, numeric_metric_cols, population_col))
        .reset_index()
    )
    agg_df["Market"] = market_df["Market"].iloc[0]
    ordered_cols = ["Market", grouping_col, population_col] + numeric_metric_cols
    ordered_cols = [c for c in ordered_cols if c in agg_df.columns]
    return agg_df[ordered_cols]


def impute_missing_features(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in feature_cols:
        if c in df.columns:
            median_val = df[c].median()
            if pd.isna(median_val):
                median_val = 0
            df[c] = df[c].fillna(median_val)
    return df
