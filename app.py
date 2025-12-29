import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import pandas as pd
import time
import os
import re

# --- CONFIGURATION ---
DOWNLOAD_DIR = "/tmp/fs_downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 1. DATA CLEANING UTILITY ---
def clean_flightscope_data(df):
    """
    Cleans the raw FlightScope CSV:
    1. Removes 'Avg' and 'Dev' rows.
    2. Converts '5.2 L' -> -5.2 and '5.2 R' -> 5.2 for key columns.
    3. Converts numeric columns to proper float types.
    """
    # 1. Remove Summary Rows (Avg/Dev in the 'Shot' column)
    if 'Shot' in df.columns:
        df = df[~df['Shot'].isin(['Avg', 'Dev', 'Average', 'Deviation'])]

    # 2. Helper to convert "10.5 L" to -10.5
    def parse_directional(val):
        if not isinstance(val, str):
            return val
        val = val.strip()
        # Check for L/R suffix
        if val.endswith('L'):
            try:
                return -float(re.sub(r'[^\d\.]', '', val))
            except:
                return 0.0
        elif val.endswith('R'):
            try:
                return float(re.sub(r'[^\d\.]', '', val))
            except:
                return 0.0
        else:
            # Just try to clean any non-numeric chars except . and -
            try:
                clean_val = re.sub(r'[^\d\.-]', '', val)
                return float(clean_val) if clean_val else 0.0
            except:
                return val

    # Columns that typically have L/R directions
    directional_cols = ['Swing H (°)', 'Lateral (yds)', 'Spin Axis (°)', 
                        'Club Path (°)', 'Launch H (°)', 'FTP (°)', 'FTT (°)']
    
    for col in directional_cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_directional)

    # 3. Convert other numeric columns (stripping ' yds', ' mph', etc if present)
    for col in df.columns:
        if col not in ['club', 'Shot', 'Shot Type', 'Mode', 'Location']:
            # Force conversion to numeric, coercing errors
            df[col] = pd.to_numeric(df[col], errors='ignore')

    return df

# --- 2. SETUP HEADLESS BROWSER ---
def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    service = Service(executable_path="/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

# --- 3. THE SCRAPING LOGIC ---
def run_scrape(username, password):
    status_text = st.empty()
    status_text.info("Initiating Browser...")
    
    driver = get_driver()
    wait = WebDriverWait(driver, 25)
    
    try:
        # A. LOGIN
        status_text.info("Logging into FlightScope...")
        driver.get("https://myflightscope.com/wp-login.php")
        
        user_field = wait.until(EC.presence_of_element_located((By.NAME, "log")))
        pass_field = driver.find_element(By.NAME, "pwd")
        
        user_field.send_keys(username)
        pass_field.send_keys(password)
        pass_field.send_keys(Keys.RETURN)
        
        time.sleep(5)

        # B. NAVIGATE
        status_text.info("Navigating to Sessions...")
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # C. SELECT SESSION
        status_text.info("Opening most recent session...")
        try:
            view_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, '/fs-golf/') and contains(text(), 'View')]")
            ))
            view_link.click()
        except:
            driver.save_screenshot("error_view.png")
            st.image("error_view.png")
            raise Exception("Could not find 'View' button.")
        
        # D. CLICK EXPORT (Vuetify Button)
        status_text.info("Locating Export button...")
        try:
            export_span = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[contains(text(), 'Export Table to CSV')]"
            )))
            driver.execute_script("arguments[0].scrollIntoView();", export_span)
            time.sleep(1)
            export_span.click()
        except:
            driver.save_screenshot("error_export.png")
            st.image("error_export.png")
            raise Exception("Could not find 'Export Table to CSV' button.")

        status_text.info("Downloading...")
        time.sleep(8)
        
        # E. RETURN FILE
        files = os.listdir(DOWNLOAD_DIR)
        if not files:
            raise Exception("No file downloaded.")
        
        latest_file = max([os.path.join(DOWNLOAD_DIR, f) for f in files], key=os.path.getctime)
        return latest_file

    except Exception as e:
        st.error(f"Error: {e}")
        return None
    finally:
        driver.quit()

# --- 4. STREAMLIT UI ---
st.title("⛳ FlightScope Data Downloader")

with st.form("login_form"):
    user = st.text_input("FlightScope Email")
    pw = st.text_input("Password", type="password")
    submitted = st.form_submit_button("Fetch Latest Data")

if submitted and user and pw:
    csv_path = run_scrape(user, pw)
    
    if csv_path:
        st.success("Success! Session downloaded.")
        
        # Load Data
        try:
            df_raw = pd.read_csv(csv_path)
            
            # --- PREVIEW SECTION ---
            st.subheader("Session Summary")
            
            # Create a Cleaned Version
            df_clean = clean_flightscope_data(df_raw.copy())
            
            # Show Stats
            shots_count = len(df_clean)
            avg_carry = df_clean['Carry (yds)'].mean() if 'Carry (yds)' in df_clean else 0
            avg_speed = df_clean['Ball (mph)'].mean() if 'Ball (mph)' in df_clean else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Shots", shots_count)
            col2.metric("Avg Carry", f"{avg_carry:.1f} yds")
            col3.metric("Avg Ball Speed", f"{avg_speed:.1f} mph")
            
            st.dataframe(df_clean.head())

            # --- DOWNLOAD OPTIONS ---
            st.write("### Download Options")
            
            # Option 1: Cleaned Data (Best for analysis apps)
            csv_clean = df_clean.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Cleaned CSV (Ready for Analysis)",
                data=csv_clean,
                file_name="flightscope_clean.csv",
                mime="text/csv"
            )
            
            # Option 2: Raw Data (Original file)
            with open(csv_path, "rb") as f:
                st.download_button(
                    label="📄 Download Original Raw CSV",
                    data=f,
                    file_name="flightscope_raw.csv",
                    mime="text/csv"
                )
                
        except Exception as e:
            st.warning(f"Could not parse CSV for preview: {e}")
            with open(csv_path, "rb") as f:
                st.download_button("Download Raw File", f, "data.raw")
