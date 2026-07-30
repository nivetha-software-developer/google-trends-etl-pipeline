import pandas as pd
import re
from urllib.parse import urlparse, parse_qs


class Custom_DataValidator:
    def __init__(self, df: pd.DataFrame, prev_df: pd.DataFrame = None):
        self.df = df
        self.errors = []
        self.warnings = []

    # -------------------------------------------------------
    # Helper: Extract cs= parameter safely
    # -------------------------------------------------------
    def extract_cs_param(self, url: str):
        try:
            query = urlparse(url).query
            params = parse_qs(query)
            cs_values = params.get("cs")
            if cs_values:
                return cs_values[0]
            return None
        except Exception:
            return None

    # -------------------------------------------------------
    # 1. Schema Validation
    # -------------------------------------------------------
    def validate_schema(self):
        required_columns = [
            "Date_Scraped", "Date", "Country",
            "Ticker", "Keyword", "Value"
        ]

        missing = [col for col in required_columns if col not in self.df.columns]
        if missing:
            self.errors.append(f"Missing required columns: {missing}")

        print("✅ Schema validation completed.")


    # -----------------------------------------
    #  Validate missing values in required fields
    # -----------------------------------------

    def Validate_missing_values(self):
        """
        Check if required keyword columns are missing or contain empty values.
        """

        # 🔹 REQUIRED KEYWORDS (Modify as needed)
        required_keywords = ["Ticker", "Keyword", "Value"]

        # 1️⃣ Check missing columns
        for key in required_keywords:
            if key not in self.df.columns:
                self.errors.append(f"Missing required keyword column: {key}")
                continue

            # 2️⃣ Check missing or empty values inside the column
            missing_rows = self.df[self.df[key].isna() | (self.df[key].astype(str).str.strip() == "")]
            if not missing_rows.empty:
                row_nums = missing_rows.index.tolist()
                self.errors.append(
                    f"Missing value in '{key}' at rows: {row_nums}"
                )

    # -------------------------------------------------------
    # 8. Full run
    # -------------------------------------------------------
    def run_all(self):
        self.validate_schema()
        self.Validate_missing_values()

        return self.df, self.errors, self.warnings
