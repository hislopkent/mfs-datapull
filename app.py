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
import shutil
import re

# --- CONFIGURATION ---
DOWNLOAD_DIR = "/tmp/fs_downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# --- 1. DATA CLEANING UTILITY ---
def clean_flightscope_data(df):
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
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
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

# --- HELPER: ROBUST FILL ---
def robust_fill(driver, element, value):
    try:
        element.click()
        element.clear()
        element.send_keys(value)
        time.sleep(0.2)
    except: pass
    driver.execute_script("arguments[0].value = arguments[1];", element, value)
    driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", element)
    driver.execute_script("arguments[0].dispatchEvent(new Event('change', { bubbles: true }));", element)
    driver.execute_script("arguments[0].dispatchEvent(new Event('blur', { bubbles: true }));", element)
    time.sleep(0.5)

# --- 3. HELPER: LOGIN ---
def login_to_flightscope(driver, username, password):
    wait = WebDriverWait(driver, 30)
    driver.get("https://myflightscope.com/wp-login.php")
    
    try:
        if "wp-login" not in driver.current_url:
            return 

        wait.until(EC.presence_of_element_located((By.NAME, "log")))
        user_input = driver.find_element(By.NAME, "log")
        pass_input = driver.find_element(By.NAME, "pwd")

        robust_fill(driver, user_input, username)
        robust_fill(driver, pass_input, password)
        
        try:
            submit_btn = driver.find_element(By.XPATH, "//*[contains(text(), 'LOG IN')]")
            driver.execute_script("arguments[0].click();", submit_btn)
        except:
            submit_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            driver.execute_script("arguments[0].click();", submit_btn)
        
        wait.until(EC.url_changes("https://myflightscope.com/wp-login.php"))
        
        if "wp-login" in driver.current_url:
            driver.save_screenshot("login_still_stuck.png")
            raise Exception("Login failed. See login_still_stuck.png")

    except Exception as e:
        driver.save_screenshot("login_crash.png")
        raise Exception(f"Login Failed: {e}")

# --- 4. ACTION: FETCH SESSION LIST ---
def fetch_session_list(username, password):
    driver = get_driver()
    wait = WebDriverWait(driver, 45)
    sessions = []
    
    try:
        login_to_flightscope(driver, username, password)
        driver.get("https://myflightscope.com/sessions/#APP=FS_GOLF")
        
        rows = wait.until(EC.presence_of_all_elements_located((
            By.CSS_SELECTOR, "#sessions-datatable table tbody tr"
        )))

        for row in rows[:20]:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) > 4:
                    raw_date = cols[1].text.replace("\n", " ")
                    name_text = cols[2].text
                    link_el = row.find_element(By.TAG_NAME, "a")
                    url = link_el.get_attribute("href")
                    
                    sessions.append({
                        "display": f"{raw_date} | {name_text}",
                        "date_only": raw_date.split("|")[0].strip(),
                        "url": url
                    })
            except:
                continue
        return sessions

    except Exception as e:
        driver.save_screenshot("fetch_error.png")
        st.error(f"Error fetching list: {e}")
        return []
    finally:
        driver.quit()

# --- 5. ACTION: BATCH DOWNLOAD (UPDATED FOR ID) ---
def process_batch_downloads(username, password, selected_sessions):
    driver = get_driver()
    wait = WebDriverWait(driver, 45)
    
    master_df = pd.DataFrame()
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        status_text.info("Logging in...")
        login_to_flightscope(driver, username, password)
        
        total = len(selected_sessions)
        
        for idx, session in enumerate(selected_sessions):
            display_name = session['display']
            session_url = session['url']
            session_date = session['display'].split("|")[0].strip()
            
            status_text.info(f"Processing ({idx+1}/{total}): {display_name}")
            
            for f in os.listdir(DOWNLOAD_DIR):
                try: os.remove(os.path.join(DOWNLOAD_DIR, f))
                except: pass

            driver.get(session_url)
            time.sleep(5) 

            # --- CLICK "DATA" TAB ---
            try:
                data_tab = wait.until(EC.element_to_be_clickable((
                    By.XPATH, "//*[contains(text(), 'DATA') or contains(text(), 'Data')]"
                )))
                data_tab.click()
                time.sleep(3) 
            except:
                print("Could not find DATA tab, assuming we are on it...")

            # --- PAGINATION ---
            try:
                pagination_select = driver.find_element(By.CSS_SELECTOR, ".v-data-footer__select .v-select")
                pagination_select.click()
                time.sleep(1)
                all_option = driver.find_element(By.XPATH, "//div[contains(@class, 'v-list-item') and .//span[contains(text(), 'All')]]")
                all_option.click()
                time.sleep(3)
            except:
                pass

            # --- EXPORT (FIXED: USING ID) ---
            try:
                # We target the ID "exportAllTablesCsv" directly
                export_btn = wait.until(EC.element_to_be_clickable((
                    By.ID, "exportAllTablesCsv"
                )))
                
                # JS Click to be safe
                driver.execute_script("arguments[0].scrollIntoView();", export_btn)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", export_btn)
                
            except Exception as e:
                filename = f"fail_{idx}.png"
                driver.save_screenshot(filename)
                st.warning(f"Could not find Export button (ID: exportAllTablesCsv). See screenshot below.")
                st.image(filename)
                continue

            time.sleep(5)
            files = os.listdir(DOWNLOAD_DIR)
            if not files:
                st.warning(f"Download timed out for {display_name}")
                continue
            
            latest_file = max([os.path.join(DOWNLOAD_DIR, f) for f in files], key=os.path.getctime)
            
            try:
                temp_df = pd.read_csv(latest_file)
                temp_df.insert(0, 'Session Date', session_date)
                temp_df['Session Name'] = session['display']
                master_df = pd.concat([master_df, temp_df], ignore_index=True)
            except Exception as e:
                st.warning(f"CSV Read Error: {e}")

            progress_bar.progress((idx + 1) / total)

        return master_df

    except Exception as e:
        driver.save_screenshot("batch_error.png")
        st.error(f"Batch Error: {e}")
        st.image("batch_error.png")
        return pd.DataFrame()
    finally:
        driver.quit()
        status_text.empty()

# --- 6. STREAMLIT UI ---
st.set_page_config(page_title="FlightScope Cloud Manager", page_icon="⛳")
st.title("⛳ FlightScope Multi-Session Manager")

if "sessions" not in st.session_state:
    st.session_state["sessions"] = []

with st.sidebar:
    st.header("1. Login")
    user = st.text_input("Email")
    pw = st.text_input("Password", type="password")
    
    if st.button("🔄 Fetch Session List"):
        if user and pw:
            # Clear old screenshots
            for f in os.listdir("."):
                if f.endswith(".png"): os.remove(f)

            with st.spinner("Fetching from FlightScope Cloud..."):
                found = fetch_session_list(user, pw)
                if found:
                    st.session_state["sessions"] = found
                    st.success(f"Found {len(found)} sessions!")
                else:
                    st.error("No sessions found or Login Failed.")
        else:
            st.warning("Please enter credentials.")

if st.session_state["sessions"]:
    st.header("2. Select Sessions to Merge")
    
    session_map = {s["display"]: s for s in st.session_state["sessions"]}
    
    selected_names = st.multiselect(
        "Choose sessions to combine:",
        options=list(session_map.keys())
    )
    
    if selected_names:
        st.info(f"Selected {len(selected_names)} sessions.")
        
        if st.button("📥 Download & Merge Selected"):
            target_sessions = [session_map[name] for name in selected_names]
            
            with st.spinner("Processing..."):
                final_df = process_batch_downloads(user, pw, target_sessions)
            
            if not final_df.empty:
                st.success("Success!")
                
                clean_df = clean_flightscope_data(final_df)
                
                st.markdown("### 📊 Combined Stats")
                c1, c2 = st.columns(2)
                c1.metric("Total Shots", len(clean_df))
                if 'Carry (yds)' in clean_df.columns:
                    c2.metric("Avg Carry", f"{clean_df['Carry (yds)'].mean():.1f}")
                
                st.dataframe(clean_df.head())
                
                csv_data = clean_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Master CSV",
                    data=csv_data,
                    file_name="flightscope_master.csv",
                    mime="text/csv"
                )
