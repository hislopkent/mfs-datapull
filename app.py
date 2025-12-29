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
import shutil

# --- CONFIGURATION ---
DOWNLOAD_DIR = "/tmp/fs_downloads"
# Ensure directory exists and is empty to start
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

# --- 2. BROWSER SETUP ---
def get_driver():
    chrome_options = Options()
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

# --- 3. HELPER: LOGIN ROUTINE ---
def login_to_flightscope(driver, username, password):
    wait = WebDriverWait(driver, 30)
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
        
        time.sleep(5)
        if "wp-login" in driver.current_url:
            raise Exception("Login failed.")
            
    except Exception as e:
        raise Exception(f"Login Failed: {e}")

# --- 4. ACTION: FETCH SESSION LIST ---
def fetch_session_list(username, password):
    driver = get_driver()
    wait = WebDriverWait(driver, 30)
    sessions = []
    
    try:
        login_to_flightscope(driver, username, password)
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        # Wait for table rows
        rows = wait.until(EC.presence_of_all_elements_located((
            By.CSS_SELECTOR, "#sessions-datatable table tbody tr"
        )))

        # Grab top 20 sessions
        for row in rows[:20]:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) > 4:
                    # Clean the date text for the label
                    raw_date = cols[1].text.replace("\n", " ")
                    name_text = cols[2].text
                    
                    link_el = row.find_element(By.TAG_NAME, "a")
                    url = link_el.get_attribute("href")
                    
                    sessions.append({
                        "display": f"{raw_date} | {name_text}",
                        "date_only": raw_date.split("|")[0].strip(), # Extract just the date part if needed
                        "url": url
                    })
            except:
                continue
        return sessions

    except Exception as e:
        st.error(f"Error fetching list: {e}")
        return []
    finally:
        driver.quit()

# --- 5. ACTION: BATCH DOWNLOAD ---
def process_batch_downloads(username, password, selected_sessions):
    """
    Logs in ONCE, then iterates through the list of session dictionaries.
    Returns a single merged DataFrame.
    """
    driver = get_driver()
    wait = WebDriverWait(driver, 30)
    
    master_df = pd.DataFrame()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        status_text.info("Logging in for batch download...")
        login_to_flightscope(driver, username, password)
        
        total = len(selected_sessions)
        
        for idx, session in enumerate(selected_sessions):
            display_name = session['display']
            session_url = session['url']
            session_date = session['display'].split("|")[0].strip() # Use the date from the list
            
            status_text.info(f"Processing ({idx+1}/{total}): {display_name}")
            
            # 1. Clear download folder to avoid confusion
            for f in os.listdir(DOWNLOAD_DIR):
                try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                except: pass

            # 2. Navigate
            driver.get(session_url)
            
            # 3. Handle Pagination (Attempt "All")
            time.sleep(2)
            try:
                pagination_select = driver.find_element(By.CSS_SELECTOR, ".v-data-footer__select .v-select")
                pagination_select.click()
                time.sleep(0.5)
                all_option = driver.find_element(By.XPATH, "//div[contains(@class, 'v-list-item') and .//span[contains(text(), 'All')]]")
                all_option.click()
                time.sleep(2)
            except:
                pass

            # 4. Export
            try:
                export_span = wait.until(EC.element_to_be_clickable((
                    By.XPATH, "//span[contains(text(), 'Export Table to CSV')]"
                )))
                driver.execute_script("arguments[0].scrollIntoView();", export_span)
                time.sleep(1)
                export_span.click()
            except:
                st.warning(f"Skipping {display_name} - Export button not found.")
                continue

            # 5. Wait for file
            time.sleep(5)
            files = os.listdir(DOWNLOAD_DIR)
            if not files:
                st.warning(f"Skipping {display_name} - Download timed out.")
                continue
            
            # 6. Read CSV and Append
            latest_file = max([os.path.join(DOWNLOAD_DIR, f) for f in files], key=os.path.getctime)
            
            try:
                temp_df = pd.read_csv(latest_file)
                # INSERT THE DATE COLUMN
                temp_df.insert(0, 'Session Date', session_date)
                temp_df['Session Name'] = session['display']
                
                master_df = pd.concat([master_df, temp_df], ignore_index=True)
            except Exception as e:
                st.warning(f"Error reading CSV for {display_name}: {e}")

            # Update progress
            progress_bar.progress((idx + 1) / total)

        return master_df

    except Exception as e:
        st.error(f"Batch Error: {e}")
        return pd.DataFrame() # Return empty on fatal error
    finally:
        driver.quit()
        status_text.empty()

# --- 6. STREAMLIT UI ---
st.set_page_config(page_title="FlightScope Merger", page_icon="⛳", layout="wide")
st.title("⛳ FlightScope Multi-Session Manager")

if "sessions" not in st.session_state:
    st.session_state["sessions"] = []

with st.sidebar:
    st.header("1. Login")
    user = st.text_input("Email")
    pw = st.text_input("Password", type="password")
    
    if st.button("🔄 Fetch Session List"):
        if user and pw:
            with st.spinner("Fetching sessions..."):
                found = fetch_session_list(user, pw)
                if found:
                    st.session_state["sessions"] = found
                    st.success(f"Found {len(found)} sessions!")
                else:
                    st.error("No sessions found.")

# Main Interface
if st.session_state["sessions"]:
    st.header("2. Select Sessions to Merge")
    
    # Create mapping for Multiselect
    # We store the whole session object in the list
    session_map = {s["display"]: s for s in st.session_state["sessions"]}
    
    selected_names = st.multiselect(
        "Choose sessions (The resulting CSV will combine all of them)",
        options=list(session_map.keys())
    )
    
    if selected_names:
        st.info(f"You have selected {len(selected_names)} sessions to merge.")
        
        if st.button("📥 Download & Merge Selected"):
            # Reconstruct list of selected objects
            target_sessions = [session_map[name] for name in selected_names]
            
            with st.spinner("Running batch download... this may take a minute..."):
                final_df = process_batch_downloads(user, pw, target_sessions)
            
            if not final_df.empty:
                st.success("Batch processing complete!")
                
                # Clean Data
                clean_df = clean_flightscope_data(final_df)
                
                # Show Stats
                st.markdown("### 📊 Combined Stats")
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Shots", len(clean_df))
                
                if 'Carry (yds)' in clean_df.columns:
                    avg_carry = clean_df['Carry (yds)'].mean()
                    c2.metric("Avg Carry", f"{avg_carry:.1f} yds")
                
                if 'Club Speed (mph)' in clean_df.columns:
                    avg_club = clean_df['Club Speed (mph)'].mean()
                    c3.metric("Avg Club Speed", f"{avg_club:.1f} mph")

                # Preview
                st.markdown("#### Preview Data (with new Date column)")
                st.dataframe(clean_df.head())
                
                # Download Button
                csv_data = clean_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Master CSV",
                    data=csv_data,
                    file_name="flightscope_merged_sessions.csv",
                    mime="text/csv"
                )
            else:
                st.error("No data was collected. Please check the logs.")
else:
    st.info("👈 Login on the sidebar to get started.")
