import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
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
    """Cleans FlightScope data for analysis."""
    if 'Shot' in df.columns:
        df = df[~df['Shot'].isin(['Avg', 'Dev', 'Average', 'Deviation'])]

    def parse_directional(val):
        if not isinstance(val, str): return val
        val = val.strip()
        if val.endswith('L'):
            try: return -float(re.sub(r'[^\d\.]', '', val))
            except: return 0.0
        elif val.endswith('R'):
            try: return float(re.sub(r'[^\d\.]', '', val))
            except: return 0.0
        else:
            try:
                clean_val = re.sub(r'[^\d\.-]', '', val)
                return float(clean_val) if clean_val else 0.0
            except: return val

    directional_cols = ['Swing H (°)', 'Lateral (yds)', 'Spin Axis (°)', 
                        'Club Path (°)', 'Launch H (°)', 'FTP (°)', 'FTT (°)']
    
    for col in directional_cols:
        if col in df.columns:
            df[col] = df[col].apply(parse_directional)
            
    return df

# --- 2. SETUP STEALTH BROWSER ---
def get_driver():
    chrome_options = Options()
    
    # --- STEALTH SETTINGS ---
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # Spoof User Agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    chrome_options.add_argument("--window-size=1920,1080")
    
    prefs = {
        "download.default_directory": DOWNLOAD_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False
    }
    chrome_options.add_experimental_option("prefs", prefs)

    service = Service(executable_path="/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide automation flag
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# --- 3. THE SCRAPING LOGIC ---
def run_scrape(username, password):
    status_text = st.empty()
    status_text.info("Initiating Stealth Browser...")
    
    driver = get_driver()
    wait = WebDriverWait(driver, 30) # Increased timeout to 30s
    
    try:
        # A. LOGIN
        status_text.info("Logging into FlightScope...")
        driver.get("https://myflightscope.com/wp-login.php")
        
        try:
            user_field = wait.until(EC.element_to_be_clickable((By.NAME, "log")))
            pass_field = driver.find_element(By.NAME, "pwd")
            
            user_field.clear()
            user_field.send_keys(username)
            time.sleep(0.5)
            pass_field.clear()
            pass_field.send_keys(password)
            time.sleep(0.5)
            
            submit_btn = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//button[contains(., 'Log In')]"
            )))
            submit_btn.click()
            
        except Exception as e:
            driver.save_screenshot("login_error.png")
            st.image("login_error.png", caption="Error during login interaction.")
            raise Exception("Could not interact with login form.")

        # Wait for redirect
        time.sleep(5)
        
        if "wp-login" in driver.current_url:
            driver.save_screenshot("login_failed.png")
            st.image("login_failed.png", caption="Login Page (Failed to Redirect)")
            raise Exception("Login failed. Check credentials.")

        # B. NAVIGATE TO SESSIONS
        status_text.info("Login Successful! Going to Sessions...")
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # C. SELECT SESSION (FIXED)
        status_text.info("Waiting for session list to populate...")
        try:
            # FIX: Wait specifically for TR elements inside the table
            rows = wait.until(EC.presence_of_all_elements_located((
                By.CSS_SELECTOR, "#sessions-datatable table tbody tr"
            )))

            if not rows:
                raise Exception("Table loaded but returned empty list.")

            latest_row = rows[0]
            view_link = latest_row.find_element(By.TAG_NAME, "a")
            session_url = view_link.get_attribute("href")
            
            status_text.info("Session found! Opening...")
            driver.get(session_url)
            
        except Exception as e:
            driver.save_screenshot("session_error.png")
            st.image("session_error.png", caption="Session List Error")
            raise Exception(f"Could not find session rows: {e}")
        
        # D. CLICK EXPORT
        status_text.info("Locating Export button...")
        try:
            export_span = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[contains(text(), 'Export Table to CSV')]"
            )))
            driver.execute_script("arguments[0].scrollIntoView();", export_span)
            time.sleep(2)
            export_span.click()
        except:
            driver.save_screenshot("export_error.png")
            st.image("export_error.png")
            raise Exception("Could not find 'Export Table to CSV' button.")

        status_text.info("Downloading...")
        time.sleep(10)
        
        # E. RETURN FILE
        files = os.listdir(DOWNLOAD_DIR)
        if not files:
            raise Exception("Button clicked, but no file appeared.")
        
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
        try:
            df_raw = pd.read_csv(csv_path)
            st.subheader("Session Summary")
            
            df_clean = clean_flightscope_data(df_raw.copy())
            if not df_clean.empty:
                cols = st.columns(3)
                cols[0].metric("Shots", len(df_clean))
                if 'Carry (yds)' in df_clean.columns:
                    cols[1].metric("Avg Carry", f"{df_clean['Carry (yds)'].mean():.1f} yds")
                if 'Ball (mph)' in df_clean.columns:
                    cols[2].metric("Avg Ball Speed", f"{df_clean['Ball (mph)'].mean():.1f} mph")
            
            st.dataframe(df_clean.head())

            csv_clean = df_clean.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Cleaned CSV", csv_clean, "flightscope_clean.csv", "text/csv")
            
            with open(csv_path, "rb") as f:
                st.download_button("📄 Download Original CSV", f, "flightscope_raw.csv", "text/csv")
        except Exception as e:
            st.warning(f"Preview failed: {e}")
            with open(csv_path, "rb") as f:
                st.download_button("Download Raw File", f, "data.raw")
