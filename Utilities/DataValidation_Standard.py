import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dateutil import parser as dateutil_parser


class Standard_DataValidator:
    def __init__(self, df: pd.DataFrame, prev_df: pd.DataFrame = None):
        self.df = df.copy()
        self.prev_df = prev_df
        self.errors = []
        self.warnings = []

    # ============================================================
    # Data Completeness
    # ============================================================
    def check_column_schema(self, expected_columns: list):
        """Check that dataframe follows expected column schema

        Args:
            expected_columns (list): List of column names that should be present in the dataframe
        """
        if not isinstance(expected_columns, list):
            self.errors.append("Expected columns must be provided as a list")
            return

        current_columns = set(self.df.columns)
        expected_columns_set = set(expected_columns)

        # Check for missing columns
        missing_columns = expected_columns_set - current_columns
        if missing_columns:
            self.errors.append(f"Missing required columns: {sorted(list(missing_columns))}")

        # Check for extra columns
        extra_columns = current_columns - expected_columns_set
        if extra_columns:
            self.warnings.append(f"Unexpected columns found: {sorted(list(extra_columns))}")

        # Check column order (if all required columns are present)
        if not missing_columns:
            current_order = [col for col in self.df.columns if col in expected_columns_set]
            expected_order = [col for col in expected_columns if col in current_columns]

            if current_order != expected_order:
                self.warnings.append(f"Column order mismatch. Expected: {expected_order}, Found: {current_order}")

    def check_number_of_rows(self, min_perc: float = None, max_perc: float = None):
        """Check if current dataframe row count is within percentage range of previous dataframe

        Args:
            min_perc (float, optional): Minimum percentage of previous dataframe rows (e.g., 90 for 90%)
            max_perc (float, optional): Maximum percentage of previous dataframe rows (e.g., 120 for 120%)
        """
        if self.prev_df is None:
            self.warnings.append("Cannot check row count: no previous dataframe provided")
            return

        prev_row_count = len(self.prev_df)
        curr_row_count = len(self.df)

        if prev_row_count == 0:
            self.warnings.append("Cannot check row count: previous dataframe is empty")
            return

        # Calculate percentage of current vs previous
        percentage = curr_row_count / prev_row_count

        # Check minimum percentage
        if min_perc is not None:
            min_threshold = min_perc / 100.0
            if percentage < min_threshold:
                self.warnings.append(
                    f"Row count too low: {curr_row_count} rows ({percentage:.1%} of previous {prev_row_count}), "
                    f"minimum expected: {min_perc}%"
                )

        # Check maximum percentage
        if max_perc is not None:
            max_threshold = max_perc / 100.0
            if percentage > max_threshold:
                self.warnings.append(
                    f"Row count too high: {curr_row_count} rows ({percentage:.1%} of previous {prev_row_count}), "
                    f"maximum expected: {max_perc}%"
                )

    def check_missing_values(self, columns: list, percentage_threshold: float = 0):
        """Check if percentage of missing values in specified columns is within threshold

        Args:
            columns (list): List of column names to check for missing values
            percentage_threshold (float): Maximum allowed percentage of missing values (default: 0)
        """
        if not isinstance(columns, list):
            self.errors.append("Columns for missing value check must be provided as a list")
            return

        # Check if all specified columns exist
        missing_columns = [col for col in columns if col not in self.df.columns]
        if missing_columns:
            self.warnings.append(f"Cannot check missing values: columns not found: {missing_columns}")
            return

        if len(self.df) == 0:
            return

        total_rows = len(self.df)

        for column in columns:
            if column not in self.df.columns:
                continue

            # Count missing values (NaN, None, empty strings)
            missing_mask = self.df[column].isna() | (self.df[column] == "") | (
                        self.df[column].astype(str).str.strip() == "")
            missing_count = missing_mask.sum()
            missing_percentage = (missing_count / total_rows) * 100

            if missing_percentage > percentage_threshold:
                self.errors.append(
                    f"Column '{column}': {missing_percentage:.1f}% missing values "
                    f"({missing_count}/{total_rows} rows), threshold: {percentage_threshold}%"
                )

    # ============================================================
    # Data Consistency
    # ============================================================
    def check_consistent_values(self, column: str, threshold: int = 0):
        """Check overlap of unique values between current and previous dataframes

        Args:
            column (str): Column name to check for consistent values
            threshold (int): Maximum number of missing values allowed (default: 0)
        """
        if self.prev_df is not None and column in self.df.columns and column in self.prev_df.columns:
            prev_unique = set(self.prev_df[column].unique())
            curr_unique = set(self.df[column].unique())

            # Calculate overlap
            overlap = len(prev_unique.intersection(curr_unique))
            prev_count = len(prev_unique)
            curr_count = len(curr_unique)

            # Calculate missing values
            missing_from_current = prev_unique - curr_unique
            missing_count = len(missing_from_current)

            # Check if missing count exceeds threshold
            if missing_count > threshold:
                self.warnings.append(
                    f"Completeness Warning: {missing_count} {column} values missing from current run "
                    f"(threshold: {threshold}, overlap: {overlap}/{prev_count})"
                )
                if missing_count <= 10:  # Show details for small numbers
                    self.warnings.append(f"Missing {column} values: {sorted(list(missing_from_current))}")
        elif self.prev_df is not None:
            self.warnings.append(f"Cannot check completeness: column '{column}' not found in one or both dataframes")

    def check_date_within_range(self, column: str, minimum_date: str = None, maximum_date: str = None,
                                offset_before_current_date: pd.DateOffset = None,
                                offset_after_current_date: pd.DateOffset = None):
        """Check if dates in specified column fall within defined range

        Args:
            column (str): Column name containing dates to validate
            minimum_date (str, optional): Minimum allowed date in string format (e.g., '2020-01-01')
            maximum_date (str, optional): Maximum allowed date in string format (e.g., '2025-12-31')
            offset_before_current_date (pd.DateOffset, optional): Offset from current date for minimum (e.g., pd.DateOffset(years=2))
            offset_after_current_date (pd.DateOffset, optional): Offset from current date for maximum (e.g., pd.DateOffset(days=30))
        """
        if column not in self.df.columns:
            self.warnings.append(f"Cannot check date range: column '{column}' not found")
            return

        # Convert column to datetime safely
        dates = pd.to_datetime(self.df[column], errors="coerce")
        today = pd.Timestamp.today()

        # Determine minimum date
        min_date = None
        if minimum_date is not None:
            min_date = pd.to_datetime(minimum_date)
        elif offset_before_current_date is not None:
            min_date = today - offset_before_current_date

        # Determine maximum date
        max_date = None
        if maximum_date is not None:
            max_date = pd.to_datetime(maximum_date)
        elif offset_after_current_date is not None:
            max_date = today + offset_after_current_date

        # Check for invalid dates
        invalid_mask = pd.Series([False] * len(dates), index=dates.index)

        if min_date is not None:
            below_min = dates < min_date
            invalid_mask |= below_min
            for idx in self.df[below_min].index:
                self.errors.append(
                    f"Row {idx}: Date {self.df.loc[idx, column]} is before minimum allowed date {min_date.date()}")

        if max_date is not None:
            above_max = dates > max_date
            invalid_mask |= above_max
            for idx in self.df[above_max].index:
                self.errors.append(
                    f"Row {idx}: Date {self.df.loc[idx, column]} is after maximum allowed date {max_date.date()}")

        # Clear invalid values
        if invalid_mask.any():
            self.df.loc[invalid_mask, column] = ""

    def check_num_value_within_range(self, column: str, minimum_value: float = None, maximum_value: float = None):
        """Check if numeric values in specified column fall within defined range

        Args:
            column (str): Column name containing numeric values to validate
            minimum_value (float, optional): Minimum allowed numeric value
            maximum_value (float, optional): Maximum allowed numeric value
        """
        if column not in self.df.columns:
            self.warnings.append(f"Cannot check numeric range: column '{column}' not found")
            return

        # Convert column to numeric safely
        numeric_values = pd.to_numeric(self.df[column], errors="coerce")

        # Check for invalid numeric conversions first
        conversion_failures = numeric_values.isna() & self.df[column].notna()
        if conversion_failures.any():
            failed_count = conversion_failures.sum()
            self.warnings.append(f"Column '{column}': {failed_count} values could not be converted to numeric")

        # Only check ranges for successfully converted numeric values
        valid_numeric_mask = ~numeric_values.isna()
        valid_numeric_values = numeric_values[valid_numeric_mask]

        if len(valid_numeric_values) == 0:
            return

        # Check for values below minimum
        invalid_mask = pd.Series([False] * len(self.df), index=self.df.index)

        if minimum_value is not None:
            below_min = (valid_numeric_mask) & (numeric_values < minimum_value)
            invalid_mask |= below_min
            below_min_count = below_min.sum()
            if below_min_count > 0:
                sample_values = numeric_values[below_min].head(5).tolist()
                self.errors.append(
                    f"Column '{column}': {below_min_count} values below minimum {minimum_value}. "
                    f"Sample values: {sample_values}"
                )

        # Check for values above maximum
        if maximum_value is not None:
            above_max = (valid_numeric_mask) & (numeric_values > maximum_value)
            invalid_mask |= above_max
            above_max_count = above_max.sum()
            if above_max_count > 0:
                sample_values = numeric_values[above_max].head(5).tolist()
                self.errors.append(
                    f"Column '{column}': {above_max_count} values above maximum {maximum_value}. "
                    f"Sample values: {sample_values}"
                )

        # Clear invalid values
        if invalid_mask.any():
            self.df.loc[invalid_mask, column] = ""

    # ============================================================
    # Format Validation
    # ============================================================
    
    @staticmethod
    def _is_parseable_date(val):
        if val == "" or (isinstance(val, float) and pd.isna(val)):
            return True

        # For dates above upper bound limit
        try:
            dateutil_parser.parse(str(val))
            return True
        except (ValueError, OverflowError):
            pass

        # For date formats like 20230115
        try:
            pd.to_datetime(str(val), format='mixed')
            return True
        except (ValueError, OverflowError):
            return False
            
    def check_column_format(self, column_types: dict, exception_values: list = None):
        """Check if columns can be transformed to their expected types

        Args:
            column_types (dict): Dictionary mapping column names to expected types
                               Valid types: 'datetime', 'numeric', 'string', 'boolean'
                               Example: {'Date': 'datetime', 'Revenue': 'numeric'}
            exception_values (list, optional): List of values to treat as empty/missing
                                             Example: ['-', 'N/A', 'TBD', 'null']
        """
        if not isinstance(column_types, dict):
            self.errors.append("Column types must be provided as a dictionary")
            return

        if exception_values is None:
            exception_values = []

        for column, expected_type in column_types.items():
            if column not in self.df.columns:
                self.warnings.append(f"Column '{column}' not found in dataframe")
                continue

            # Replace exception values with empty strings
            exception_mask = self.df[column].isin(exception_values)
            if exception_mask.any():
                self.df.loc[exception_mask, column] = ""

            total_rows = len(self.df[column])
            if total_rows == 0:
                continue

            # Try to convert to expected type
            if expected_type == 'datetime':
                invalid_mask = ~self.df[column].apply(self._is_parseable_date)
            elif expected_type == 'numeric':
                converted = pd.to_numeric(self.df[column], errors="coerce")
                invalid_mask = converted.isna() & (self.df[column] != "")
            elif expected_type == 'string':
                # String conversion should always work
                invalid_mask = pd.Series([False] * total_rows, index=self.df.index)
            elif expected_type == 'boolean':
                # Try to convert to boolean
                try:
                    converted = self.df[column].astype('boolean', errors='ignore')
                    invalid_mask = pd.Series([False] * total_rows, index=self.df.index)
                except:
                    invalid_mask = pd.Series([True] * total_rows, index=self.df.index) & (self.df[column] != "")
            else:
                self.warnings.append(f"Unknown expected type '{expected_type}' for column '{column}'")
                continue

            # Count and report conversion failures
            invalid_count = invalid_mask.sum()
            valid_count = total_rows - invalid_count

            if invalid_count > 0:
                # Get sample of invalid values (up to 5)
                invalid_values = self.df.loc[invalid_mask, column].head(5).tolist()

                self.errors.append(
                    f"Column '{column}' format validation failed: "
                    f"{valid_count}/{total_rows} entries can be converted to {expected_type}. "
                    f"Sample invalid values: {invalid_values}"
                )

                # Clear invalid values
                self.df.loc[invalid_mask, column] = ""

    # ============================================================
    # Duplicate Data Detection
    # ============================================================
    def check_duplicates(self, columns: list):
        """Check for duplicate rows based on specified columns

        Args:
            columns (list): List of column names to check for duplicates
                          Example: ['Ticker', 'Date'] or ['Company_Name']
        """
        if not isinstance(columns, list):
            self.errors.append("Columns for duplicate check must be provided as a list")
            return

        # Check if all specified columns exist
        missing_columns = [col for col in columns if col not in self.df.columns]
        if missing_columns:
            self.warnings.append(f"Cannot check duplicates: columns not found: {missing_columns}")
            return

        if len(self.df) == 0:
            return

        # Find duplicates based on specified columns
        duplicated_mask = self.df.duplicated(subset=columns, keep=False)
        duplicate_count = duplicated_mask.sum()

        if duplicate_count > 0:
            # Get unique duplicate groups
            duplicate_groups = self.df[duplicated_mask].groupby(columns).size()
            num_groups = len(duplicate_groups)

            # Get sample of duplicate values (up to 5 groups)
            sample_duplicates = []
            for group_key, count in duplicate_groups.head(5).items():
                if isinstance(group_key, tuple):
                    key_str = dict(zip(columns, group_key))
                else:
                    key_str = {columns[0]: group_key}
                sample_duplicates.append(f"{key_str} ({count} occurrences)")

            self.errors.append(
                f"Found {duplicate_count} duplicate rows across {num_groups} groups "
                f"when checking columns {columns}. "
                f"Sample duplicates: {sample_duplicates}"
            )

    # ============================================================
    # Run All Validations
    # ============================================================
    def run_all(self):
        """Run all validation functions with their respective arguments for Taiwan dataset"""

        # =========================
        # Data Completeness
        # =========================
        self.check_column_schema([
            "Date_Scraped", "Date", "Country", "Ticker", "Keyword", "Value"
        ])

        self.check_number_of_rows(min_perc=90, max_perc=120)

        self.check_missing_values([
            "Date_Scraped", "Date", "Country", "Ticker", "Keyword", "Value"
        ], percentage_threshold=0)

        # =========================
        # Data Consistency
        # =========================
        self.check_consistent_values("Country", threshold=2)

        # =========================
        # Format Validation
        # =========================
        self.check_column_format({
            "Date_Scraped": "datetime",
            "Date": "datetime",
            "Country": "string",
            "Ticker": "string",
            "Keyword": "string",
            "Value": "string"
        }, exception_values=["-", "N/A"])

        # =========================
        # Duplicate Detection
        # =========================
        self.check_duplicates([
            "Date_Scraped", "Date", "Country", "Ticker", "Keyword", "Value"
        ])
        return self.df, self.errors, self.warnings