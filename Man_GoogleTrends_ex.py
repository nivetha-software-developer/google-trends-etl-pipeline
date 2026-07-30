import traceback
import pandas as pd
import paramiko
from postmarker.core import PostmarkClient
from pytrends.request import TrendReq
from random import randint
from time import sleep
from urllib3.util import Retry
import inspect
import json
from dotenv import load_dotenv
from Utilities.DataValidation_Standard import Standard_DataValidator
from Utilities.DataValidation_Custom import Custom_DataValidator
from Utilities.Logger import Logger
from HelperFunctions import root_folder, todayDate,yesterdayDate,currentDatetime, todayDateInDash, formatted_date
import os
from datetime import datetime, timedelta
import subprocess
import time
from dateutil.relativedelta import relativedelta


# urllib3 fix
if 'method_whitelist' in inspect.signature(Retry.__init__).parameters:
    pass
else:
    old_init = Retry.__init__
    def new_init(self, *args, **kwargs):
        kwargs.pop('method_whitelist', None)
        return old_init(self, *args, **kwargs)
    Retry.__init__ = new_init



# ================================
# EMAIL CONTROL FLAGS
# ================================
SEND_ERROR_EMAIL = True
SEND_WARNING_EMAIL = True
SEND_CLIENT_EMAIL = True
SEND_TEAM_EMAIL = True
SEND_FAILURE_EMAIL = True
DataScraper_sftp_enabled = True

# ============================================================
# 1. LOGGER INITIALIZATION
# ============================================================
logger_man = Logger('Google_trends', root_folder=root_folder, todayDate=todayDate)

OUTPUT_FILE = os.path.join(root_folder, "Data", f"GoogleTrends_{todayDate}.csv")
PREV_OUTPUT_FILE = os.path.join(root_folder, "Data", f"GoogleTrends_{yesterdayDate}.csv")
OUTPUT_PARQUET_FILE = os.path.join(root_folder, "Data", f"Table_1_{currentDatetime}.parquet")
INPUT_PARQUET_FILE = os.path.join(root_folder, "Inputs", f"TABLE_1_{currentDatetime}.parquet")
INPUT_FILE = os.path.join(root_folder, "Inputs", f"keywords.csv")

app_setting_json = os.path.join(root_folder, "Appsettings.json")
env_file = os.path.join(root_folder, "SFTP", "env")

error_log = os.path.join(logger_man.logs_dir, f"Google_trends_error_{todayDate}.log")
warning_log = os.path.join(logger_man.logs_dir, f"Google_trends_warning_{todayDate}.log")

# ========================
# 4. EMAIL SETTINGS
# ========================
with open(app_setting_json, "r") as f:
    settings = json.load(f)

FROM_EMAIL = settings["SENDER_EMAIL"]
TO_EMAIL = settings["RECIPIENT_EMAIL"]
TO_EMAIL_LOG_ERROR = settings["RECIPIENT_EMAIL_LOG_ERROR"]
TO_EMAIL_FAILURE = settings["RECIPIENT_EMAIL_FAILURE"]
CC_EMAIL = settings["CC_EMAIL"]
CC_EMAIL_FAILURE = settings["CC_EMAIL_FAILURE"]
SUBJECT = settings["EMAIL_SUBJECT"]
SUBJECT_FAILURE = settings["EMAIL_SUBJECT_FAILURE"]
SUBJECT_FAILURE_ERROR = settings["EMAIL_SUBJECT_FAILURE_ERROR"]

# ========================
# 5. ENVIRONMENT VARIABLES
# ========================
load_dotenv(dotenv_path=env_file)

SFTP_HOST_NAME = os.getenv('SFTP_UPLOAD_HOST')
SFTP_USER_NAME = os.getenv('SFTP_UPLOAD_USERNAME')
SFTP_PASSWORD = os.getenv('SFTP_UPLOAD_PASSWORD')
SFTP_PORT = os.getenv('SFTP_UPLOAD_PORT')
SFTP_FILE_UPLOAD_PATH = os.getenv('SFTP_UPLOAD_PATH')
SFTP_LOG_UPLOAD_PATH = os.getenv("SFTP_LOG_UPLOAD_PATH")
SFTP_INPUT_DOWNLOAD_PATH = os.getenv("SFTP_INPUT_DOWNLOAD_PATH")
SFTP_ERROR_FILE_UPLOAD_PATH = os.getenv("SFTP_ERROR_FILE_UPLOAD_PATH")
POSTMARK_SERVER_TOKEN = os.getenv('POSTMARK_API_TOKEN')
postmark = PostmarkClient(server_token=POSTMARK_SERVER_TOKEN)

# ================================
# VPN Helpers (Single VPN)
# ================================

VPN_US_CONNECT = "/opt/apps/ExpressVPN/vpn-connect-usal3.sh"
VPN_UK_CONNECT = "/opt/apps/ExpressVPN/vpn-connect-ukud.sh"
VPN_DISCONNECT_SCRIPT = "/opt/apps/ExpressVPN/vpn-disconnect-with-DNS-Reset.sh"

def connect_us_vpn():
    try:
        logger_man.log(f"Trying VPN: {VPN_US_CONNECT}", logger_man.INFO)
        subprocess.run([VPN_US_CONNECT], check=True)
        logger_man.log("VPN connected successfully.", logger_man.SUCCESS)
        time.sleep(30)  # wait for VPN to stabilize
        return True
    except subprocess.CalledProcessError as e:
        logger_man.log(f"Failed to connect VPN: {e}", logger_man.INFO)
        return False

def connect_uk_vpn():
    try:
        logger_man.log(f"Trying VPN: {VPN_UK_CONNECT}", logger_man.INFO)
        subprocess.run([VPN_UK_CONNECT], check=True)
        logger_man.log("VPN connected successfully.", logger_man.SUCCESS)
        time.sleep(30)  # wait for VPN to stabilize
        return True
    except subprocess.CalledProcessError as e:
        logger_man.log(f"Failed to connect VPN: {e}", logger_man.INFO)
        return False


def disconnect_vpn():
    try:
        subprocess.run([VPN_DISCONNECT_SCRIPT], check=True)
        logger_man.log("VPN disconnected.", logger_man.INFO)
        time.sleep(30)
    except subprocess.CalledProcessError as e:
        logger_man.log(f"Error disconnecting VPN: {e}", logger_man.INFO)

# ================================
# Helper: Upload file with progress logging
# ================================
def upload_with_progress(sftp, local_path, remote_path, logger_man):
    """Upload a file via SFTP with progress percentage, time, and speed."""
    file_size = os.path.getsize(local_path)
    uploaded = [0]  # Mutable counter

    def progress_callback(transferred, total):
        uploaded[0] = transferred
        percent = (transferred / total) * 100
        # Log every 10% or on completion
        if int(percent) % 10 == 0 or transferred == total:
            logger_man.log(f"  Progress: {percent:.0f}% ({transferred:,}/{total:,} bytes)", logger_man.INFO)

    logger_man.log(f"Starting upload: {os.path.basename(local_path)} ({file_size:,} bytes)", logger_man.INFO)
    start_time = time.time()

    sftp.put(local_path, remote_path, callback=progress_callback)

    elapsed = time.time() - start_time
    speed = (file_size / (1024 * 1024)) / elapsed if elapsed > 0 else 0

    logger_man.log(
        f"✓ Upload complete: {remote_path}\n"
        f"  Size: {file_size:,} bytes\n"
        f"  Time: {elapsed:.2f}s\n"
        f"  Speed: {speed:.2f} MB/s",
        logger_man.SUCCESS
    )

# -----------------------------------
# GOOGLE TRENDS FETCH
# -----------------------------------
def fetch_trends(country, keywords, ticker):
    try:
        pytrends = TrendReq(
            hl='en-US', tz=360,
            timeout=(10, 30),
            retries=5,
            backoff_factor=0.3,
            requests_args={'headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
            }}
        )

        """Fetch 10 years of Google Trends by splitting into two 5-year ranges"""

        def range_str(start, end):
            return f"{start.strftime('%Y-%m-%d')} {end.strftime('%Y-%m-%d')}"

        today = datetime.today()
        mid = today - timedelta(days=365 * 5)
        start = today - timedelta(days=365 * 10)

        ranges = [
            (start, mid),  # First 5 years
            (mid, today)  # Last 5 years
        ]

        frames = []

        for r_start, r_end in ranges:
            tf = range_str(r_start, r_end)

            attempts = 0
            max_attempts = 10

            while attempts < max_attempts:
                try:
                    logger_man.log(f"⏳ Fetching range: {tf}", logger_man.INFO)

                    if country == "UK":
                        country = "GB"
                    elif country == "US":
                        country = "US"
                    elif country == "worldwide":
                        country = ""

                    # pytrends = TrendReq(hl='en-US', tz=360)
                    pytrends.build_payload(keywords, geo=country, timeframe=tf)

                    df = pytrends.interest_over_time()

                    if df.empty:
                        logger_man.log(f"No data for range: {tf}", logger_man.INFO)
                    else:
                        df.reset_index(inplace=True)
                        if "isPartial" in df.columns:
                            df.drop(columns=["isPartial"], inplace=True)
                        frames.append(df)

                    break  # success → exit retry loop

                except Exception as e:
                    if "429" in str(e):
                        attempts += 1
                        wait_time = 60 + attempts * 15  # exponential backoff
                        logger_man.log(
                            f"429 RATE LIMIT for range {tf}. Waiting {wait_time}s and retrying… (attempt {attempts}/{max_attempts})",
                            logger_man.INFO
                        )
                        time.sleep(wait_time)
                    else:
                        logger_man.log(f"Failed range {tf}: {e}", logger_man.INFO)
                        break

            else:
                error_msg = f"Max retries reached for range {tf}"
                logger_man.log(error_msg, logger_man.INFO)
                raise RuntimeError(error_msg)

        if not frames:
            return pd.DataFrame()

            # --- Combine both 5-year windows ---
        full_df = pd.concat(frames).drop_duplicates(subset=['date'])

        df_melt = full_df.melt(id_vars=["date"], var_name="Keyword", value_name="Value")
        # Assign original geo code first
        df_melt["Country"] = country

        # -----------------------------------
        # NORMALIZE COUNTRY BEFORE SAVE
        # -----------------------------------
        country_replace_map = {
            "GB": "UK",
            "US": "US",
            "": "worldwide"
        }

        df_melt["Country"] = (
            df_melt["Country"]
            .fillna("")
            .str.strip()
            .replace(country_replace_map)
        )
        df_melt["Ticker"] = ticker
        df_melt["Date_Scraped"] = todayDateInDash
        return df_melt[["Date_Scraped", "date", "Country", "Ticker", "Keyword", "Value"]]

    except Exception as e:
        logger_man.log(f"Error in fetch_trends(): {e}", logger_man.INFO)
        raise


def read_log_as_html(file_path, title):
    if not file_path or not os.path.exists(file_path):
        return ""

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read().strip()

    if not content:
        return ""

    return f"""
    <hr>
    <h3 style="color:#b00020;">{title}</h3>
    <pre style="
        background:#f6f6f6;
        padding:10px;
        border:1px solid #ddd;
        white-space:pre-wrap;
        font-family:monospace;
        font-size:13px;">
{content}
    </pre>
    """

def create_sftp_connection(logger_man):
    """Create a fresh SFTP connection."""
    logger_man.log(
        f"Connecting to SFTP server {SFTP_HOST_NAME}:{SFTP_PORT}",
        logger_man.INFO
    )

    transport = paramiko.Transport((SFTP_HOST_NAME, int(SFTP_PORT)))
    transport.connect(
        username=SFTP_USER_NAME,
        password=SFTP_PASSWORD
    )

    if not transport.is_active():
        raise ConnectionError("SFTP transport is not active.")

    sftp = paramiko.SFTPClient.from_transport(transport)

    logger_man.log(
        "SFTP connection established successfully.",
        logger_man.SUCCESS
    )

    return transport, sftp

def upload_with_retry(
        local_path,
        remote_path,
        description,
        logger_man,
        max_attempts=5):
    """
    Upload file with automatic retry and incremental backoff.
    """

    retry_delays = [0, 60, 300, 900, 1800]  # seconds

    last_exception = None

    for attempt in range(1, max_attempts + 1):

        delay = retry_delays[attempt - 1]

        if delay > 0:
            logger_man.log(
                f"Waiting {delay//60} minute(s) before retry attempt {attempt} "
                f"for {description}",
                logger_man.INFO
            )
            time.sleep(delay)

        transport = None
        sftp = None

        try:
            logger_man.log(
                f"Upload attempt {attempt}/{max_attempts} "
                f"for {description}",
                logger_man.INFO
            )

            transport, sftp = create_sftp_connection(logger_man)

            upload_with_progress(
                sftp=sftp,
                local_path=local_path,
                remote_path=remote_path,
                logger_man=logger_man
            )

            logger_man.log(
                f"{description} uploaded successfully on attempt {attempt}",
                logger_man.SUCCESS
            )

            return True

        except Exception as e:
            last_exception = e

            logger_man.log(
                f"Upload attempt {attempt}/{max_attempts} failed "
                f"for {description}: {str(e)}",
                logger_man.INFO
            )

        finally:
            try:
                if sftp:
                    sftp.close()
            except:
                pass

            try:
                if transport:
                    transport.close()
            except:
                pass

    raise Exception(
        f"All {max_attempts} upload attempts failed "
        f"for {description}. Last error: {last_exception}"
    )

# -----------------------------------
# MAIN
# -----------------------------------
def main():
    try:
        header_columns = ["Date_Scraped", "Date", "Country", "Ticker", "Keyword", "Value"]

        df_in = pd.read_csv(INPUT_FILE, on_bad_lines="skip")

        completed_count = 0
        current_vpn_country = None

        for row in df_in.itertuples(index=False):
            keyword = str(row.keywords).strip()
            country = str(row.country).strip()
            ticker = str(row.ticker).strip()

            if country == "UK":
                target_country = "GB"
            elif country == "US":
                target_country = "US"
            elif country.lower() == "worldwide":
                target_country = ""
            else:
                target_country = country

            # Only reconnect if country changed
            if target_country in ["GB", "US"]:
                if current_vpn_country != target_country:
                    logger_man.log(f"Switching VPN to {target_country}", logger_man.INFO)

                    disconnect_vpn()
                    time.sleep(5)

                    if target_country == "GB":
                        logger_man.log('UK - GB', logger_man.INFO)
                        connect_uk_vpn()
                    elif target_country == "US":
                        connect_us_vpn()

                    current_vpn_country = target_country
                else:
                    logger_man.log(f"VPN already connected to {target_country}, skipping reconnect", logger_man.INFO)

            logger_man.log(f"Fetching Google Trends for: {keyword} | {country} | {ticker}", logger_man.SUCCESS)
            trends_df = fetch_trends(country, [keyword], ticker)

            if not trends_df.empty:
                # -----------------------------------
                # EXPLODE TICKERS AFTER FETCH
                # -----------------------------------
                ticker_list = [t.strip() for t in ticker.split(",")]

                exploded_frames = []

                for single_ticker in ticker_list:
                    temp_df = trends_df.copy()
                    temp_df["Ticker"] = single_ticker
                    exploded_frames.append(temp_df)

                final_df = pd.concat(exploded_frames, ignore_index=True)

                final_df.to_csv(
                    OUTPUT_FILE,
                    mode="a",
                    header=header_columns if not os.path.exists(OUTPUT_FILE) else False,
                    index=False
                )

                logger_man.log(
                    f"Data saved for {keyword} | {country} | {', '.join(ticker_list)}",
                    logger_man.SUCCESS
                )

            else:
                logger_man.log(f"No data to save for {keyword} | {country} | {ticker}", logger_man.INFO)

            # -----------------------------------
            # PROGRESS TRACKING
            # -----------------------------------
            completed_count += 1

            if completed_count % 10 == 0:
                print("STOP VPN SLEEP FOR 30 SEC AND RECONNECT...")
                logger_man.log(
                    f"{completed_count} keywords completed so far...",
                    logger_man.SUCCESS
                )


            sleep_time = randint(30, 90)
            logger_man.log(f"Sleeping {sleep_time} seconds…", logger_man.SUCCESS)
            sleep(sleep_time)

        logger_man.log("\nGoogle Trends Data Updated Successfully", logger_man.SUCCESS)

        # Load scraped data
        dfs = pd.read_csv(OUTPUT_FILE)
        dfs = dfs.drop_duplicates()
        dfs = dfs.reset_index(drop=True)
        dfs.to_csv(OUTPUT_FILE, index=False)
        time.sleep(2)

        df = pd.read_csv(OUTPUT_FILE)
        prev_df = pd.read_csv(PREV_OUTPUT_FILE) if os.path.exists(PREV_OUTPUT_FILE) else None

        # Run validation
        std_validator = Standard_DataValidator(df, prev_df)
        validated_df, std_errors, std_warnings = std_validator.run_all()

        validator = Custom_DataValidator(df, prev_df)
        validated_df, cus_errors, cus_warnings = validator.run_all()

        # =========================
        # Write Errors Log
        # =========================
        logger_man.log("=== STANDARD VALIDATION ===", logger_man.ERROR)
        if std_errors:
            for e in std_errors:
                logger_man.log(e, logger_man.ERROR)
        else:
            logger_man.log("None", logger_man.ERROR)

        logger_man.log("=== CUSTOM VALIDATION ===", logger_man.ERROR)
        if cus_errors:
            for e in cus_errors:
                logger_man.log(e, logger_man.ERROR)
        else:
            logger_man.log("None", logger_man.ERROR)

        # =========================
        # Write Warnings Log
        # =========================
        logger_man.log("=== STANDARD VALIDATION ===", logger_man.WARNING)
        if std_warnings:
            for w in std_warnings:
                logger_man.log(w, logger_man.WARNING)
        else:
            logger_man.log("None", logger_man.WARNING)

        logger_man.log("=== CUSTOM VALIDATION ===", logger_man.WARNING)
        if cus_warnings:
            for w in cus_warnings:
                logger_man.log(w, logger_man.WARNING)
        else:
            logger_man.log("None", logger_man.WARNING)

        has_errors = bool(cus_errors or std_errors)
        has_warnings = bool(cus_warnings or std_warnings)

        df = validated_df.astype(str)
        df.to_parquet(OUTPUT_PARQUET_FILE, engine="fastparquet")

        df_IN = pd.read_csv(INPUT_FILE)
        df_IN.to_parquet(INPUT_PARQUET_FILE, engine="fastparquet")

        # ================================
        # VPN Disconnection
        # ================================
        disconnect_vpn()

        # ================================
        # Establish SFTP Connection
        # ================================
        logger_man.log("Establishing SFTP connection...", logger_man.INFO)

        max_attempts = 5
        retry_delay = 25  # seconds to wait between retries
        sftp_connected = False
        transport = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger_man.log(f"SFTP connection attempt {attempt}/{max_attempts}...", logger_man.INFO)
                
                transport = paramiko.Transport((SFTP_HOST_NAME, int(SFTP_PORT)))
                transport.connect(username=SFTP_USER_NAME, password=SFTP_PASSWORD)
                
                if transport.is_active():
                    logger_man.log(
                        f"SFTP connection established successfully with {SFTP_HOST_NAME}:{SFTP_PORT}",
                        logger_man.SUCCESS
                    )
                    sftp_connected = True
                    break
                else:
                    raise ConnectionError("SFTP transport created but failed to activate.")
                    
            except (paramiko.ssh_exception.AuthenticationException, Exception) as auth_err:
                logger_man.log(
                    f"Attempt {attempt} failed. Error: {auth_err}", 
                    logger_man.INFO
                )
                
                # Clean up transport if created but failed
                if transport:
                    try:
                        transport.close()
                    except:
                        pass
                
                if attempt < max_attempts:
                    logger_man.log(f"Retrying SFTP connection in {retry_delay} seconds...", logger_man.INFO)
                    time.sleep(retry_delay)
                else:
                    logger_man.log("All 5 SFTP connection attempts failed.", logger_man.INFO)
                    raise auth_err

        sftp = paramiko.SFTPClient.from_transport(transport)

        # ================================
        # Define Remote Paths
        # ================================
        remote_data_file_path = os.path.join(SFTP_FILE_UPLOAD_PATH, f"TABLE_1_{currentDatetime}.parquet")
        remote_data_error_file_path = os.path.join(SFTP_ERROR_FILE_UPLOAD_PATH, f"TABLE_1_{currentDatetime}.parquet")
        remote_input_file_path = os.path.join(SFTP_INPUT_DOWNLOAD_PATH, f"TABLE_1_{currentDatetime}.parquet")
        remote_error_file_path = os.path.join(SFTP_LOG_UPLOAD_PATH, f"Google_trends_error_{todayDate}.txt")
        remote_warning_file_path = os.path.join(SFTP_LOG_UPLOAD_PATH, f"Google_trends_warning_{todayDate}.txt")

        def try_upload(local_path, remote_path, description):
            """
            Upload file with retry mechanism.
            """

            if not os.path.exists(local_path):
                logger_man.log(
                    f"Local file not found: {local_path}",
                    logger_man.INFO
                )
                return

            if not DataScraper_sftp_enabled:
                logger_man.log(
                    f"Upload skipped for {description} "
                    f"(flag disabled).",
                    logger_man.INFO
                )
                return

            upload_with_retry(
                local_path=local_path,
                remote_path=remote_path,
                description=description,
                logger_man=logger_man
            )

        if has_errors:
            logger_man.log(f"Uploading files to remote directory: {SFTP_ERROR_FILE_UPLOAD_PATH}", logger_man.INFO)
            try_upload(OUTPUT_PARQUET_FILE, remote_data_error_file_path, "TABLE_1 parquet")
        else:
            logger_man.log(f"Uploading files to remote directory: {SFTP_FILE_UPLOAD_PATH}", logger_man.INFO)
            try_upload(OUTPUT_PARQUET_FILE, remote_data_file_path, "TABLE_1 parquet")

        try_upload(INPUT_PARQUET_FILE, remote_input_file_path, "TABLE_1 Input parquet")
        try_upload(error_log, remote_error_file_path,    "Error log")
        try_upload(warning_log, remote_warning_file_path, "Warning log")

        sftp.close()
        transport.close()
        logger_man.log("connection closed.", logger_man.INFO)

        # ========================
        # CLIENT EMAIL
        # ========================

        scrape_name = "Google Trends"

        # ------------------------
        # SUBJECT
        # ------------------------
        if has_errors and has_warnings:
            client_subject = (
                f"{scrape_name} run succeeded but validation checks failed, with warnings"
            )

        elif has_errors:
            client_subject = (
                f"{scrape_name} run succeeded but validation checks failed"
            )

        elif has_warnings:
            client_subject = (
                f"{scrape_name} run succeeded with validation warnings"
            )
        else:
            client_subject = f"{scrape_name} run succeeded"

        client_attachments = [OUTPUT_PARQUET_FILE]

        # ------------------------
        # HTML BODY
        # ------------------------
        html_body = f"""
                <p>{client_subject} for <b>{formatted_date}</b>.</p>
                """

        # Embed error content
        if has_errors:
            html_body += read_log_as_html(
                logger_man.error_log_file,
                "Validation Errors"
            )

        # Embed warning content
        if has_warnings:
            html_body += read_log_as_html(
                logger_man.warning_log_file,
                "Validation Warnings"
            )

        if SEND_CLIENT_EMAIL:
            postmark.emails.send(
                From=FROM_EMAIL,
                To=TO_EMAIL,
                Cc=CC_EMAIL,
                Subject=client_subject,
                HtmlBody=html_body
                # Attachments=client_attachments
            )
            logger_man.log("Client email sent successfully...", logger_man.SUCCESS)
        else:
            logger_man.log("Client email skipped (SEND_CLIENT_EMAIL=False).", logger_man.INFO)

        # ========================
        # TEAM EMAIL
        # ========================
        if SEND_TEAM_EMAIL:
            postmark.emails.send(
                From=FROM_EMAIL,
                To=CC_EMAIL,
                Subject=SUBJECT,
                HtmlBody=html_body,
                Attachments=[logger_man.main_log_file, OUTPUT_FILE, OUTPUT_PARQUET_FILE]
            )
            logger_man.log("Team email sent successfully...", logger_man.SUCCESS)
        else:
            logger_man.log("Team email skipped (SEND_TEAM_EMAIL=False).", logger_man.INFO)

    except Exception as e:

        # ========================
        # 10. ERROR HANDLING
        # ========================
        """
        Send failure notification email with log file attached.
        """
        error_msg = traceback.format_exc()
        logger_man.log(f"Error Exception: {str(error_msg)}", logger_man.INFO)

        attachments = [logger_man.main_log_file]

        if os.path.exists(OUTPUT_FILE):
            attachments.append(OUTPUT_FILE)
            
        try:
            if SEND_FAILURE_EMAIL:
                postmark.emails.send(
                    From=FROM_EMAIL,
                    To=TO_EMAIL_FAILURE,
                    Cc=CC_EMAIL_FAILURE,
                    Subject=SUBJECT_FAILURE,
                    HtmlBody='Kindly check the log file.',
                    Attachments=attachments
                )
                logger_man.log("Failure mail sent...", logger_man.INFO)
            else:
                logger_man.log("Failure mail skipped (SEND_FAILURE_EMAIL=False).", logger_man.INFO)
        except Exception as mail_error:
            logger_man.log(
                f"Failure email itself failed: {mail_error}",
                logger_man.INFO
            )
        
    finally:
        disconnect_vpn()

if __name__ == "__main__":
    main()
