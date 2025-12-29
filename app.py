import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
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
    # Filter out average/deviation rows if they exist
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
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# --- 3. THE SCRAPING LOGIC ---
def run_scrape(username, password, session_index=0):
    status_text = st.empty()
    status_text.info("Initiating Stealth Browser...")
    
    driver = get_driver()
    wait = WebDriverWait(driver, 30)
    
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
            st.image("login_error.png", caption="Login Error")
            raise Exception("Could not interact with login form.")

        time.sleep(5)
        if "wp-login" in driver.current_url:
            raise Exception("Login failed. Check credentials.")

        # B. NAVIGATE TO SESSIONS
        status_text.info("Going to Sessions List...")
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # C. SELECT SESSION
        status_text.info(f"Looking for session #{session_index + 1}...")
        try:
            # Wait for rows to populate
            rows = wait.until(EC.presence_of_all_elements_located((
                By.CSS_SELECTOR, "#sessions-datatable table tbody tr"
            )))

            if len(rows) <= session_index:
                raise Exception(f"You asked for session #{session_index+1}, but only found {len(rows)} sessions.")

            # Grab the specific row user requested
            target_row = rows[session_index]
            
            # Extract info for the user to verify
            cols = target_row.find_elements(By.TAG_NAME, "td")
            if len(cols) > 2:
                session_date = cols[1].text.replace("\n", " ")
                session_name = cols[2].text
                st.info(f"**Target Session:** {session_date} | {session_name}")
            
            view_link = target_row.find_element(By.TAG_NAME, "a")
            session_url = view_link.get_attribute("href")
            
            status_text.info("Opening session details...")
            driver.get(session_url)
            
        except Exception as e:
            driver.save_screenshot("session_error.png")
            st.image("session_error.png", caption="Session Selection Error")
            raise Exception(f"Could not select session: {e}")
        
        # D. HANDLE PAGINATION & EXPORT
        status_text.info("Checking for pagination...")
        time.sleep(5) # Let the session detail table load
        
        # Optional: Try to expand rows to "All" if a dropdown exists
        try:
            # This is a generic attempt to find a "Rows per page" dropdown in Vuetify
            # If it doesn't exist or fails, we just continue to export
            pagination_select = driver.find_element(By.CSS_SELECTOR, ".v-data-footer__select .v-select")
            pagination_select.click()
            time.sleep(1)
            all_option = driver.find_element(By.XPATH, "//div[contains(@class, 'v-list-item') and .//span[contains(text(), 'All')]]")
            all_option.click()
            time.sleep(3) # Wait for table to reload with all data
            status_text.info("Expanded table to show all rows.")
        except:
            # It's okay if this fails, the export button usually handles it, 
            # but sometimes "Export" only grabs visible rows.
            pass

        status_text.info("Clicking Export...")
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

        status_text.info("Downloading file...")
        time.sleep(10)
        
        # E. RETURN FILE
        files = os.listdir(DOWNLOAD_DIR)
        if not files:
            raise Exception("Download initiated but no file found.")
        
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
    c1, c2 = st.columns(2)
    with c1:
        user = st.text_input("FlightScope Email")
    with c2:
        pw = st.text_input("Password", type="password")
    
    # NEW: Dropdown to pick which session
    session_option = st.selectbox(
        "Which session to download?",
        options=[0, 1, 2, 3, 4],
        format_func=lambda x: "Latest Session" if x == 0 else f"{x+1}th Most Recent"
    )
    
    submitted = st.form_submit_button("Fetch Data")

if submitted and user and pw:
    # Clear old downloads
    for f in os.listdir(DOWNLOAD_DIR):
        os.remove(os.path.join(DOWNLOAD_DIR, f))

    csv_path = run_scrape(user, pw, session_index=session_option)
    
    if csv_path:
        st.success("Success! Session downloaded.")
        try:
            df_raw = pd.read_csv(csv_path)
            
            st.markdown("### 📊 Data Preview")
            st.write(f"**Total Rows in CSV:** {len(df_raw)}")
            
            df_clean = clean_flightscope_data(df_raw.copy())
            
            if not df_clean.empty:
                cols = st.columns(3)
                cols[0].metric("Valid Shots", len(df_clean))
                if 'Carry (yds)' in df_clean.columns:
                    cols[1].metric("Avg Carry", f"{df_clean['Carry (yds)'].mean():.1f} yds")
                if 'Ball (mph)' in df_clean.columns:
                    cols[2].metric("Avg Ball Speed", f"{df_clean['Ball (mph)'].mean():.1f} mph")
            
                st.dataframe(df_clean.head())
            else:
                st.warning("Data was downloaded, but 'Valid Shots' is 0. Check the raw file below.")

            # Downloads
            csv_clean = df_clean.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Cleaned CSV", csv_clean, "flightscope_clean.csv", "text/csv")
            
            with open(csv_path, "rb") as f:
                st.download_button("📄 Download Original CSV", f, "flightscope_raw.csv", "text/csv")
        except Exception as e:
            st.error(f"Error reading CSV: {e}")
            with open(csv_path, "rb") as f:
                st.download_button("Download Raw File", f, "data.raw")
