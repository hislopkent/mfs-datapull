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
    
    # --- STEALTH SETTINGS (CRITICAL FOR LOGGING IN) ---
    chrome_options.add_argument("--headless") 
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    
    # 1. Spoof User Agent (Look like a real PC)
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # 2. Hide Automation Flags
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
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
    
    # 3. Execute script to further hide selenium
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# --- 3. THE SCRAPING LOGIC ---
def run_scrape(username, password):
    status_text = st.empty()
    status_text.info("Initiating Stealth Browser...")
    
    driver = get_driver()
    wait = WebDriverWait(driver, 20)
    
    try:
        # A. LOGIN
        status_text.info("Logging into FlightScope...")
        driver.get("https://myflightscope.com/wp-login.php")
        
        # Wait for fields
        try:
            user_field = wait.until(EC.element_to_be_clickable((By.NAME, "log")))
            pass_field = driver.find_element(By.NAME, "pwd")
            
            # Clear fields just in case
            user_field.clear()
            pass_field.clear()
            
            # Type slowly (mimic human)
            user_field.send_keys(username)
            time.sleep(0.5)
            pass_field.send_keys(password)
            time.sleep(0.5)
            
            # FIND AND CLICK THE SUBMIT BUTTON EXPLICITLY
            # Standard WordPress ID for the submit button is "wp-submit"
            submit_btn = driver.find_element(By.ID, "wp-submit")
            submit_btn.click()
            
        except Exception as e:
            driver.save_screenshot("login_field_error.png")
            st.image("login_field_error.png", caption="Error finding login fields")
            raise Exception("Could not find login box.")

        # Wait for redirect
        time.sleep(5)
        
        # --- LOGIN DEBUG CHECK ---
        # If we are still on the login page, it failed.
        if "wp-login" in driver.current_url:
            driver.save_screenshot("login_failed.png")
            st.image("login_failed.png", caption="Login Failed: This is what the screen looks like.")
            
            # Check for common error messages in the page source
            if "ERROR" in driver.page_source.upper():
                st.error("The website reported an error (e.g. Invalid Password).")
            elif "ROBOT" in driver.page_source.upper() or "CAPTCHA" in driver.page_source.upper():
                st.error("The website flagged this as a Bot/Spam.")
            
            raise Exception("Login did not redirect. Credentials might be wrong or bot detected.")

        # B. NAVIGATE TO SESSIONS
        status_text.info("Login Successful! Going to Sessions...")
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # C. SELECT SESSION
        status_text.info("Opening most recent session...")
        try:
            # Wait for the specific FS Golf View button
            view_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, '/fs-golf/') and contains(text(), 'View')]")
            ))
            # Scroll to it
            driver.execute_script("arguments[0].scrollIntoView();", view_link)
            time.sleep(1)
            view_link.click()
        except:
            driver.save_screenshot("session_error.png")
            st.image("session_error.png", caption="I can't find the 'View' button.")
            raise Exception("Could not find the session list.")
        
        # D. CLICK EXPORT (Vuetify Button)
        status_text.info("Locating Export button...")
        try:
            # Look for the exact text you found in the inspection
            export_span = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[contains(text(), 'Export Table to CSV')]"
            )))
            driver.execute_script("arguments[0].scrollIntoView();", export_span)
            time.sleep(2) # Extra wait for animation
            export_span.click()
        except:
            driver.save_screenshot("export_error.png")
            st.image("export_error.png", caption="I can't find the Export button.")
            raise Exception("Could not find 'Export Table to CSV' button.")

        status_text.info("Downloading...")
        time.sleep(10) # Generous time for download
        
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
            st.dataframe(df_clean.head())

            csv_clean = df_clean.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Cleaned CSV", csv_clean, "flightscope_clean.csv", "text/csv")
            
            with open(csv_path, "rb") as f:
                st.download_button("📄 Download Original CSV", f, "flightscope_raw.csv", "text/csv")
        except Exception as e:
            st.warning(f"Preview failed: {e}")
            with open(csv_path, "rb") as f:
                st.download_button("Download Raw File", f, "data.raw")
