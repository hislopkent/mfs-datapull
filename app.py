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

# --- CONFIGURATION ---
DOWNLOAD_DIR = "/tmp/fs_downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 1. SETUP HEADLESS BROWSER ---
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

# --- 2. THE SCRAPING LOGIC ---
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

        # B. NAVIGATE TO SESSIONS
        status_text.info("Navigating to Sessions List...")
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # C. CLICK 'VIEW'
        status_text.info("Locating most recent session...")
        try:
            # Matches the link from your earlier screenshot
            view_link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, "//a[contains(@href, '/fs-golf/') and contains(text(), 'View')]")
            ))
            view_link.click()
            status_text.info("Session found. Loading dashboard...")
        except Exception:
            driver.save_screenshot("session_error.png")
            st.image("session_error.png")
            raise Exception("Could not find the 'View' button.")
        
        # D. CLICK 'Export Table to CSV' (FIXED!)
        status_text.info("Looking for Export button...")
        
        try:
            # We target the SPAN text exactly as you pasted it: "Export Table to CSV"
            # We use 'contains' to be safe, but preserve the casing.
            export_span = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//span[contains(text(), 'Export Table to CSV')]"
            )))
            
            # Scroll it into view just in case
            driver.execute_script("arguments[0].scrollIntoView();", export_span)
            time.sleep(1)
            
            # Click the span (which bubbles up to the button)
            export_span.click()
            
        except Exception:
            driver.save_screenshot("export_error.png")
            st.image("export_error.png", caption="Error: Button not found.")
            raise Exception("Could not find the 'Export Table to CSV' button.")

        status_text.info("Downloading file...")
        time.sleep(8) 
        
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

# --- 3. STREAMLIT UI ---
st.title("⛳ FlightScope Data Puller")

with st.form("login_form"):
    user = st.text_input("FlightScope Email")
    pw = st.text_input("Password", type="password")
    submitted = st.form_submit_button("Fetch Latest Data")

if submitted and user and pw:
    csv_path = run_scrape(user, pw)
    
    if csv_path:
        st.success("Data Retrieved Successfully!")
        try:
            df = pd.read_csv(csv_path)
            st.dataframe(df.head())
            
            with open(csv_path, "rb") as file:
                st.download_button(
                    label="Download CSV to Computer",
                    data=file,
                    file_name="flightscope_data.csv",
                    mime="text/csv"
                )
        except:
            st.warning("File downloaded but preview failed.")
            with open(csv_path, "rb") as file:
                st.download_button("Download Raw File", file, file_name="flightscope_data.raw")
