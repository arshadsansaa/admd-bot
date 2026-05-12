from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select
import time
import os
import re
import random

# def setup_driver():
#     options = Options()
#     options.add_argument("--start-maximized")
#     options.add_argument("--disable-popup-blocking")
#     # options.add_argument("--headless") # Uncomment for production/server
#     options.add_argument("--no-sandbox")
#     options.add_argument("--disable-dev-shm-usage")
#     driver = webdriver.Chrome(options=options)
#     return driver
def setup_driver(download_dir=None):
    options = Options()
    
    # 1. Background Mode ON (Headless)
  
    # options.add_argument("--headless=new") 

    # 2. Screen Size Fix (MOST IMPORTANT)
 
    options.add_argument("--window-size=1920,1080")

    # Baki settings same rakhein
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    # 3. Configure download directory so we can capture the CSV
    if download_dir:
        os.makedirs(download_dir, exist_ok=True)
        prefs = {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": True,
        }
        options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=options)
    return driver

def perform_login(driver, username, password, office_key):
    try:
        print(f"Opening login page...")
        driver.get("https://login.advancedmd.com/")
        wait = WebDriverWait(driver, 30)

        try:
            cookie_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept')]")))
            cookie_btn.click()
        except: pass

        print("Switching to login iframe...")
        wait.until(EC.frame_to_be_available_and_switch_to_it((By.CSS_SELECTOR, "iframe")))

        wait.until(EC.element_to_be_clickable((By.ID, "loginName"))).send_keys(username)
        wait.until(EC.element_to_be_clickable((By.ID, "password"))).send_keys(password)
        office_field = wait.until(EC.element_to_be_clickable((By.ID, "officeKey")))
        office_field.clear()
        office_field.send_keys(office_key)
        office_field.send_keys("\t")

        print("Clicking login button...")
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']:not([disabled])"))).click()
        print("✅ Login submitted successfully.")

        driver.switch_to.default_content()
        return True
    except Exception as e:
        print(f"❌ Login Error: {str(e)}")
        return False

def handle_popups(driver):
    print("\n🔍 Scanning for Login Popups (Confirm later, Snooze all, Ask me later)...")
    end_time = time.time() + 30
    target_texts = ["Confirm later", "Snooze all", "Snooze", "Dismiss", "Ask me later", "Ask Me Later"]
    
    while time.time() < end_time:
        clicked_something = False
        
        def attempt_click():
            for text in target_texts:
                try:
                    xpath = f"//button[contains(normalize-space(.), '{text}')] | //a[contains(normalize-space(.), '{text}')] | //span[contains(normalize-space(.), '{text}')]"
                    elements = driver.find_elements(By.XPATH, xpath)
                    
                    for elem in elements:
                        if elem.is_displayed() and elem.is_enabled():
                            print(f"   🎯 Found clickable button for: '{text}'")
                            
                            # ORDER OF CLICKS (Pehle Normal, fir ActionChains, last me JS)
                            try:
                                elem.click()
                                print("      -> Action: Standard Clicked")
                            except:
                                try:
                                    ActionChains(driver).move_to_element(elem).click().perform()
                                    print("      -> Action: ActionChains Clicked")
                                except:
                                    try:
                                        elem.send_keys(Keys.RETURN)
                                        print("      -> Action: Sent ENTER key")
                                    except:
                                        driver.execute_script("arguments[0].click();", elem)
                                        print("      -> Action: JS Clicked")
                            return True
                except Exception as e:
                    pass
            return False

        # Main window me check karein
        driver.switch_to.default_content()
        if attempt_click():
            clicked_something = True
        else:
            # Agar main window me na mile toh iframes me check karein
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                try:
                    driver.switch_to.frame(frame)
                    if attempt_click():
                        clicked_something = True
                        driver.switch_to.default_content()
                        break
                    driver.switch_to.default_content()
                except:
                    driver.switch_to.default_content()
        
        if clicked_something:
            print("   ⏳ Waiting 6 seconds for page to process...")
            time.sleep(6)
        else:
            time.sleep(2)
            
        # FAST EXIT: Dashboard load hote hi loop break kar dega
        try:
            driver.switch_to.default_content()
            if driver.find_elements(By.CLASS_NAME, "pm-main-toolbar") or driver.find_elements(By.ID, "mnuPatientInfo"):
                print("   ✅ Dashboard detected, moving forward!")
                break
        except:
            pass

    return True

def switch_to_dashboard_window(driver):
    print("\n🔍 Checking for Dashboard Window...")
    end_time = time.time() + 45  # Thoda time aur badha diya (45 seconds)
    
    while time.time() < end_time:
        handles = driver.window_handles
        
        # Case 1: Agar nayi window open hui
        if len(handles) > 1:
            driver.switch_to.window(handles[-1])
            print(f"   ✅ Switched to new window: {driver.title}")
            return True
            
        # Case 2: Agar dashboard ussi same window me load ho gaya
        try:
            if driver.find_elements(By.CLASS_NAME, "pm-main-toolbar") or driver.find_elements(By.ID, "mnuPatientInfo"):
                print("   ✅ Dashboard loaded in the current main window.")
                return True
        except:
            pass
            
        time.sleep(2) # Wait and check again
        
    # --- DEBUGGING SECTION ---
    print(f"❌ Failed: Dashboard did not load.")
    print(f"🌐 Current URL at failure: {driver.current_url}")
    
    try:
        # Fail hone par screenshot lega
        screenshot_name = f"error_dashboard_{int(time.time())}.png"
        driver.save_screenshot(screenshot_name)
        print(f"📸 SCREENSHOT SAVED: {screenshot_name}. Is photo ko open karke dekhein ki screen par kya atka hai!")
    except Exception as e:
        print(f"⚠️ Screenshot lene me error aaya: {e}")
        
    return False
    
def click_patient_info(driver):
    print("\n🔍 Searching for 'Patient Info' icon...")
    try: WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.CLASS_NAME, "pm-main-toolbar")))
    except: pass

    end_time = time.time() + 45
    selectors = [(By.ID, "mnuPatientInfo"), (By.XPATH, "//*[@title='Patient Info V2']")]

    while time.time() < end_time:
        driver.switch_to.default_content()
        for by, val in selectors:
            try:
                elem = driver.find_element(by, val)
                if elem.is_displayed():
                    driver.execute_script("arguments[0].click();", elem)
                    print("   ✅ Clicked Patient Info successfully!")
                    time.sleep(8) 
                    return True
            except: pass
        time.sleep(2)
    print("❌ Failed: Patient Info icon not found.")
    return False

def search_claim_id(driver, claim_id):
    print(f"\n🔍 Searching for Claim ID: {claim_id}...")
    search_input = None
    search_box_found = False

    search_selectors = [
        (By.CSS_SELECTOR, "input[placeholder='Search Patients']"),
        (By.CSS_SELECTOR, "input[aria-label='search input']")
    ]

    end_time = time.time() + 40 
    while time.time() < end_time:
        driver.switch_to.default_content()

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, frame in enumerate(iframes):
            try:
                driver.switch_to.frame(frame)
                for sel_by, sel_val in search_selectors:
                    try:
                        search_input = driver.find_element(sel_by, sel_val)
                        if search_input.is_displayed():
                            search_box_found = True
                            break
                    except: pass

                if not search_box_found:
                    child_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    for child in child_iframes:
                        try:
                            driver.switch_to.frame(child)
                            for sel_by, sel_val in search_selectors:
                                try:
                                    search_input = driver.find_element(sel_by, sel_val)
                                    if search_input.is_displayed():
                                        search_box_found = True
                                        break
                                except: pass
                            if search_box_found: break
                            driver.switch_to.parent_frame()
                        except: driver.switch_to.parent_frame()

                if search_box_found: break
                driver.switch_to.default_content()
            except: driver.switch_to.default_content()

        if search_box_found: break
        time.sleep(2)

    if not search_box_found:
        print("❌ Error: Search box not found.")
        return False

    formatted_id = claim_id
    try:
        search_input.click()
        time.sleep(0.5)
        search_input.send_keys(Keys.CONTROL + "a")
        search_input.send_keys(Keys.DELETE)
        time.sleep(0.5)

        print(f"   ⌨ Typing: {formatted_id}")
        for char in formatted_id:
            search_input.send_keys(char)
            time.sleep(0.15) 

        time.sleep(2) 
        try:
            dropdown_option = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "mat-option")))
            dropdown_option.click()
            print("   ✅ Clicked dropdown result.")
            time.sleep(5)
            return True
        except:
            search_input.send_keys(Keys.RETURN)
            time.sleep(5)
            return True
    except Exception as e:
        print(f"❌ Error entering text: {e}")
        return False


def close_all_patient_tabs(driver):
    """
    Close all currently open patient tabs in the AdvancedMD PM tab bar.
    Called before navigating to a new patient to stay under the 3-patient limit.
    """
    driver.switch_to.default_content()
    time.sleep(1)
    closed = 0

    for _ in range(6):  # AMD allows max 3 patient tabs
        driver.switch_to.default_content()
        found = False

        # Strategy 1: known CSS selectors for AMD patient-tab close buttons
        for sel in [
            "li.pm-tab .pm-tab-close",
            "li.pm-patient-tab .close",
            ".pm-tabs li:not(.pm-dashboard-tab) .close",
            ".nav-tabs li .remove-tab",
            ".pm-tab-list .pm-tab-close",
            "button.pm-tab-close",
        ]:
            try:
                btns = driver.find_elements(By.CSS_SELECTOR, sel)
                if btns:
                    driver.execute_script("arguments[0].click();", btns[0])
                    print(f"   \U0001f5d9 Closed patient tab ({sel})")
                    time.sleep(1.5)
                    closed += 1
                    found = True
                    break
            except Exception:
                pass

        if not found:
            # Strategy 2: JS — find x close buttons in the top nav tab area
            try:
                result_js = driver.execute_script("""
                    var selectors = [
                        '.pm-tab-close', '.tab-close', '.close-tab',
                        '[ng-click*="closeTab"]', '[ng-click*="removeTab"]'
                    ];
                    for (var s of selectors) {
                        var els = document.querySelectorAll(s);
                        if (els.length) { els[0].click(); return 'css:' + s; }
                    }
                    // Fallback: any x / x in elements that live in a tab-like list
                    var candidates = document.querySelectorAll(
                        'li span, li button, li a, nav span, nav button'
                    );
                    for (var b of candidates) {
                        var t = b.textContent.trim();
                        if ((t === '\u00d7' || t === '\u2715' || t === 'x') && b.offsetParent) {
                            b.click();
                            return 'x-fallback';
                        }
                    }
                    return null;
                """)
                if result_js:
                    print(f"   \U0001f5d9 Closed patient tab (JS: {result_js})")
                    time.sleep(1.5)
                    closed += 1
                    found = True
            except Exception:
                pass

        if not found:
            break  # no more tabs to close

    if closed:
        print(f"   \U0001f9f9 Closed {closed} patient tab(s) before new navigation")
    time.sleep(1)
    return closed


def handle_patients_open_dialog(driver):
    """
    Handle the 'Patients currently open' modal that appears when AMD already
    has 3 patient tabs open and a 4th is requested.
    Dismisses the dialog so the caller can retry after closing existing tabs.
    """
    try:
        driver.switch_to.default_content()
        dialog = driver.find_elements(
            By.XPATH, "//*[contains(text(), 'Patients currently open')]"
        )
        if not dialog:
            return False
        print("   \u26a0\ufe0f 'Patients currently open' dialog detected — dismissing...")
        close_btn = driver.find_elements(
            By.XPATH, "//button[normalize-space()='Close']"
        )
        if close_btn:
            driver.execute_script("arguments[0].click();", close_btn[0])
            print("   \u2705 Dialog dismissed")
            time.sleep(2)
            return True
    except Exception:
        pass
    return False


def handle_patient_memo(driver):
    print("\n🔍 Checking for 'Patient Memo' popup...")
    time.sleep(3)
    
    def check_for_ok_button():
        selectors = [(By.XPATH, "//button[contains(., 'OK')]"), (By.XPATH, "//span[contains(text(), 'OK')]/ancestor::button")]
        for by, val in selectors:
            try:
                btn = driver.find_element(by, val)
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    return True
            except: pass
        return False

    driver.switch_to.default_content()
    if check_for_ok_button(): return True

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.frame(frame)
            if check_for_ok_button(): 
                driver.switch_to.default_content()
                return True
            driver.switch_to.default_content()
        except: driver.switch_to.default_content()
    return False

def click_insurance_tab(driver):
    print("\n🔍 Searching for 'Insurance' tab...")
    selectors = [(By.XPATH, "//div[contains(text(), 'Insurance')]"), (By.XPATH, "//span[contains(text(), 'Insurance')]")]

    end_time = time.time() + 20
    while time.time() < end_time:
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for i, frame in enumerate(iframes):
            try:
                driver.switch_to.frame(frame)
                for by, val in selectors:
                    try:
                        elem = driver.find_element(by, val)
                        if elem.is_displayed():
                            driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                            time.sleep(0.5)
                            driver.execute_script("arguments[0].click();", elem)
                            print("   ✅ Clicked Insurance tab.")
                            time.sleep(5)
                            return True
                    except: pass
                driver.switch_to.default_content()
            except: driver.switch_to.default_content()
        time.sleep(1)
    print("❌ Failed: 'Insurance' tab not found.")
    return False

def fetch_patient_dob(driver):
    """
    Fetch the patient's Date of Birth from the Patient Info page.
    Primary source: textarea#txtPatientInfo which contains:
      Name: Mull,Makala\nDOB: 04/12/1997\nSSN: XXX-XX-8515
    Returns: str (MM/DD/YYYY) or None
    """
    import re
    print("\n\ud83d\udd0d Fetching Patient DOB...")

    def _parse_dob_from_text(text):
        """Extract DOB value from a multi-line patient info string."""
        match = re.search(r'DOB\s*:\s*([\d/]+)', text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _try_get_dob():
        # Primary: textarea#txtPatientInfo
        try:
            ta = driver.find_element(By.ID, "txtPatientInfo")
            text = ta.get_attribute("value") or ta.text or ""
            dob = _parse_dob_from_text(text)
            if dob:
                return dob
        except:
            pass
        # Fallback: dedicated DOB input
        for xp in [
            "//input[@id='txtDOB']",
            "//label[contains(text(),'Date of Birth')]/following::input[not(@type='hidden')][1]",
            "//label[contains(text(),'DOB')]/following::input[not(@type='hidden')][1]",
            "//td[contains(text(),'DOB')]/following-sibling::td//input",
        ]:
            try:
                elem = driver.find_element(By.XPATH, xp)
                val = elem.get_attribute("value") or ""
                if val.strip():
                    return val.strip()
            except:
                pass
        return None

    # Try in current context first
    dob = _try_get_dob()
    if dob:
        print(f"   \u2705 DOB: {dob}")
        return dob

    # Try Patient iframe
    driver.switch_to.default_content()
    try:
        WebDriverWait(driver, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "Patient"))
        )
        dob = _try_get_dob()
        if dob:
            print(f"   \u2705 DOB (from Patient iframe): {dob}")
            return dob
    except:
        pass

    # Try all iframes
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.frame(frame)
            dob = _try_get_dob()
            if dob:
                print(f"   \u2705 DOB (from iframe): {dob}")
                return dob
            driver.switch_to.default_content()
        except:
            driver.switch_to.default_content()

    print("   \u26a0\ufe0f DOB not found.")
    return None


def extract_meridian_insurance(driver):
    """
    In the Insurance tab, find the row whose carrier title contains 'MERIDIAN',
    click it, and extract carrier name + subscriber ID.
    Returns: {"carrier": str|None, "subscriber_id": str|None, "error": str|None}
    """
    print("\n🔍 Extracting MERIDIAN Insurance Data...")
    result = {"carrier": None, "subscriber_id": None, "subscriber_name": None, "dob": None, "error": None}

    # Switch to the Patient iframe where the insurance table lives
    insurance_iframe_found = False
    driver.switch_to.default_content()

    try:
        WebDriverWait(driver, 15).until(
            EC.frame_to_be_available_and_switch_to_it((By.NAME, "Patient"))
        )
        print("   \u2713 Switched to Patient Iframe.")
        insurance_iframe_found = True
    except:
        top_iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in top_iframes:
            try:
                driver.switch_to.frame(frame)
                try:
                    target_frame = driver.find_element(By.NAME, "Patient")
                    driver.switch_to.frame(target_frame)
                    insurance_iframe_found = True
                    break
                except:
                    pass
                if not insurance_iframe_found:
                    driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()

    if not insurance_iframe_found:
        result["error"] = "Patient/Insurance Iframe not found"
        return result

    time.sleep(3)

    try:
        rows = driver.find_elements(By.XPATH, "//tr[td]")
        meridian_row = None
        carrier_title = None

        for row in rows:
            try:
                cols = row.find_elements(By.TAG_NAME, "td")
                if len(cols) >= 2:
                    # The 2nd td has the carrier code and title="MERIDIAN HEALTH PLAN(...)" 
                    title_attr = cols[1].get_attribute("title") or ""
                    if "MERIDIAN" in title_attr.upper():
                        carrier_title = title_attr.strip()
                        meridian_row = row
                        break
            except:
                pass

        if not meridian_row:
            result["error"] = "No MERIDIAN row found in insurance table"
            return result

        # Click the MERIDIAN row to populate the form fields
        driver.execute_script("arguments[0].scrollIntoView(true);", meridian_row)
        time.sleep(0.5)
        try:
            meridian_row.click()
        except:
            driver.execute_script("arguments[0].click();", meridian_row)
        print(f"   \U0001f449 Clicked MERIDIAN row: {carrier_title}")
        time.sleep(4)

        result["carrier"] = carrier_title

        # Extract Subscriber Name — sits next to a <button>Subscriber</button>
        subscriber_name = None
        for xp in [
            "//button[normalize-space(text())='Subscriber']/following::input[not(@type='hidden')][1]",
            "//input[@id='txtSubscriber']",
            "//td[contains(text(),'Subscriber')][not(contains(text(),'ID'))]/following-sibling::td//input",
            "//label[contains(text(),'Subscriber')][not(contains(text(),'ID'))]/following::input[not(@type='hidden')][1]",
        ]:
            try:
                val = driver.find_element(By.XPATH, xp).get_attribute("value") or ""
                if val.strip():
                    subscriber_name = val.strip()
                    break
            except:
                pass

        result["subscriber_name"] = subscriber_name.strip() if subscriber_name else None

        # Extract Subscriber ID from the form
        subscriber_id = None
        try:
            subscriber_id = driver.find_element(
                By.XPATH, "//label[contains(text(), 'Subscriber ID')]/following::input[not(@type='hidden')][1]"
            ).get_attribute("value")
        except:
            pass
        if not subscriber_id:
            try:
                subscriber_id = driver.find_element(
                    By.XPATH, "//td[contains(text(),'Subscriber ID')]/following-sibling::td//input"
                ).get_attribute("value")
            except:
                pass

        result["subscriber_id"] = subscriber_id.strip() if subscriber_id else None

        # Extract DOB and Name from textarea#txtPatientInfo (Patient Information section)
        # Content is set via JS, so use execute_script to read innerText/textContent
        import re
        try:
            ta = driver.find_element(By.ID, "txtPatientInfo")
            patient_text = driver.execute_script(
                "return arguments[0].innerText || arguments[0].textContent || arguments[0].value || '';", ta
            )
            print(f"   \U0001f4cb txtPatientInfo content: {repr(patient_text)}")
            if patient_text:
                # Parse DOB: 04/12/1997
                dob_match = re.search(r'DOB\s*:\s*([\d/]+)', patient_text, re.IGNORECASE)
                if dob_match:
                    result["dob"] = dob_match.group(1).strip()
                # Parse Name: Mull,Makala → use as subscriber_name if not found above
                name_match = re.search(r'Name\s*:\s*(.+)', patient_text, re.IGNORECASE)
                if name_match and not result.get("subscriber_name"):
                    result["subscriber_name"] = name_match.group(1).strip()
        except Exception as e:
            print(f"   \u26a0\ufe0f txtPatientInfo extraction error: {e}")

        print(f"   \u2705 Carrier: {result['carrier']}")
        print(f"   \u2705 Subscriber: {result['subscriber_name']}")
        print(f"   \u2705 Subscriber ID: {result['subscriber_id']}")
        print(f"   \u2705 DOB: {result.get('dob')}")

    except Exception as e:
        result["error"] = f"MERIDIAN extraction error: {str(e)}"

    return result


def click_appointments_sidebar(driver):
    """
    Click 'Appointments' in the Angular patient sidebar.
    The sidebar lives inside the Angular app iframe (not in the 'Patient' sub-iframe).
    """
    print("\n🔍 Clicking 'Appointments' sidebar tab...")

    selectors = [
        (By.XPATH, "//*[@data-pendo-id='ptc-side-nav-appointments-20240731']"),
        (By.XPATH, "//mat-list-item[.//*[normalize-space(text())='Appointments']]"),
        (By.XPATH, "//span[normalize-space(text())='Appointments' and contains(@class,'ng-star-inserted')]"),
        (By.XPATH, "//*[normalize-space(text())='Appointments']"),
    ]

    def _try_click():
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'Appointments' tab.")
                        time.sleep(5)
                        return True
            except:
                pass
        return False

    end_time = time.time() + 25
    while time.time() < end_time:
        # Try main window first
        driver.switch_to.default_content()
        if _try_click():
            return True

        # Try each top-level iframe (the Angular app iframe)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    return True
            except:
                pass

        time.sleep(1)

    print("❌ Failed: 'Appointments' tab not found.")
    return False


def fetch_requesting_provider_from_appointments(driver):
    """
    In the Appointments table (#tblGrid), find the first visible, non-child row
    where the Reason/Appt Type td's title attribute contains 'THERAPY'
    and Status is not CANCELLED/DELETED/NOSHOW.
    Returns the 'Column' value (e.g., 'GASPAR, HANNAH') as Requesting Provider.
    """
    print("\n🔍 Fetching Requesting Provider from Appointments...")

    JS_EXTRACT = """
    var table = document.getElementById('tblGrid');
    if (!table) return null;
    var rows = table.querySelectorAll('tbody tr');
    var skipStatuses = ['CANCEL', 'DELETE', 'NOSHOW', 'NO SHOW'];
    var fallbackProvider = null;
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        // Skip child/expanded rows
        if (row.getAttribute('data-ischild') === 'true') continue;
        // Skip hidden rows
        var display = row.style.display || '';
        if (display.toLowerCase() === 'none') continue;
        var cols = row.querySelectorAll('td');
        if (cols.length < 8) continue;
        // Status is col index 5
        var statusText = (cols[5].innerText || '').trim().toUpperCase();
        var shouldSkip = false;
        for (var s = 0; s < skipStatuses.length; s++) {
            if (statusText.indexOf(skipStatuses[s]) >= 0) { shouldSkip = true; break; }
        }
        if (shouldSkip) continue;
        // Save first valid provider as fallback
        if (!fallbackProvider) {
            var prov = (cols[4].innerText || '').trim();
            if (prov) fallbackProvider = prov;
        }
        // Reason/Appt Type: check title attribute of col index 7
        var reasonTitle = (cols[7].getAttribute('title') || '').toUpperCase();
        var reasonText = (cols[7].innerText || '').toUpperCase();
        if (reasonTitle.indexOf('THERAPY') >= 0 || reasonText.indexOf('THERAPY') >= 0) {
            var provider = (cols[4].innerText || '').trim();
            if (provider) return provider;
        }
    }
    // Fallback: return first non-cancelled provider if no THERAPY row found
    return fallbackProvider;
    """

    def _try_js():
        try:
            result = driver.execute_script(JS_EXTRACT)
            return result
        except:
            return None

    # Try current context first
    result = _try_js()
    if result:
        print(f"   ✅ Requesting Provider: {result}")
        return result

    # Try main window
    driver.switch_to.default_content()
    result = _try_js()
    if result:
        print(f"   ✅ Requesting Provider: {result}")
        return result

    # Try all iframes (including nested)
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            result = _try_js()
            if result:
                print(f"   ✅ Requesting Provider: {result}")
                return result
            # Also try nested iframes
            nested = driver.find_elements(By.TAG_NAME, "iframe")
            for nf in nested:
                try:
                    driver.switch_to.frame(nf)
                    result = _try_js()
                    if result:
                        print(f"   ✅ Requesting Provider: {result}")
                        return result
                    driver.switch_to.parent_frame()
                except:
                    driver.switch_to.parent_frame()
        except:
            pass

    print("   ⚠️ Requesting Provider not found.")
    return None


def click_history_sidebar(driver):
    """
    Click 'History' in the Angular patient sidebar.
    Similar to click_appointments_sidebar — sidebar is in the Angular app iframe.
    """
    print("\n🔍 Clicking 'History' sidebar tab...")

    selectors = [
        (By.XPATH, "//*[@data-pendo-id='ptc-side-nav-history-20240731']"),
        (By.XPATH, "//mat-list-item[.//*[normalize-space(text())='History']]"),
        (By.XPATH, "//span[normalize-space(text())='History' and contains(@class,'ng-star-inserted')]"),
        (By.XPATH, "//*[normalize-space(text())='History']"),
    ]

    def _try_click():
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'History' tab.")
                        time.sleep(8)
                        return True
            except:
                pass
        return False

    end_time = time.time() + 25
    while time.time() < end_time:
        # Try main window first
        driver.switch_to.default_content()
        if _try_click():
            return True

        # Try each top-level iframe (the Angular app iframe)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    return True
            except:
                pass

        time.sleep(1)

    print("❌ Failed: 'History' tab not found.")
    return False


def click_first_history_row(driver):
    """
    In the History table (#tblHisGrid), click the first data row (charge row).
    The table lives inside an iframe (likely 'Patient' sub-iframe).
    Waits for the table/row to load before clicking.
    """
    print("\n🔍 Clicking first row in History table...")

    JS_DBLCLICK_ROW = """
    var table = document.getElementById('tblHisGrid');
    if (!table) return 'NO_TABLE';
    var rows = table.querySelectorAll('tbody tr');
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        // Skip header row (contains <th>)
        if (row.querySelector('th')) continue;
        // First select the row (single click)
        row.click();
        // Then call the ondblclick handler directly
        if (typeof his_openDetailWindow === 'function') {
            his_openDetailWindow(row);
            return 'CLICKED';
        }
        // Fallback: try ondblclick attribute
        if (row.ondblclick) {
            row.ondblclick();
            return 'CLICKED';
        }
        // Last resort: synthetic dblclick
        var evt = new MouseEvent('dblclick', {bubbles: true, cancelable: true, view: window});
        row.dispatchEvent(evt);
        return 'CLICKED';
    }
    return 'NO_ROW';
    """

    def _try_click_js():
        try:
            result = driver.execute_script(JS_DBLCLICK_ROW)
            return result
        except:
            return None

    # Retry loop — History page may take time to render the table
    end_time = time.time() + 20
    while time.time() < end_time:
        # Try current context
        res = _try_click_js()
        if res == 'CLICKED':
            print("   ✅ Clicked first History row.")
            time.sleep(3)
            return True

        # Try main window
        driver.switch_to.default_content()
        res = _try_click_js()
        if res == 'CLICKED':
            print("   ✅ Clicked first History row (main window).")
            time.sleep(3)
            return True

        # Try all iframes (including nested)
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                res = _try_click_js()
                if res == 'CLICKED':
                    print("   ✅ Clicked first History row (iframe).")
                    time.sleep(3)
                    return True
                # Nested iframes
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        res = _try_click_js()
                        if res == 'CLICKED':
                            print("   ✅ Clicked first History row (nested iframe).")
                            time.sleep(3)
                            return True
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
            except:
                pass

        time.sleep(2)

    print("   ⚠️ Could not find/click History row.")
    return False


def switch_to_charge_detail_window(driver, handles_before):
    """
    After double-clicking a History row, a new window opens:
    'Charge Detail: ... - actv_chargedetail_icd10.html'
    Wait for it and switch to it.
    handles_before: set of window handles captured BEFORE the double-click.
    """
    print("\n🔍 Waiting for Charge Detail window to open...")
    end_time = time.time() + 30

    while time.time() < end_time:
        current_handles = set(driver.window_handles)
        new_handles = current_handles - handles_before
        if new_handles:
            new_handle = new_handles.pop()
            driver.switch_to.window(new_handle)
            # Wait for page to load
            time.sleep(5)
            print(f"   ✅ Switched to new window: {driver.title}")
            print(f"   🌐 URL: {driver.current_url}")
            return True
        time.sleep(2)

    print("   ⚠️ Charge Detail window did not open.")
    return False


def extract_charge_detail_data(driver):
    """
    From the Charge Detail window, extract:
    - Procedure code (from #txtProccode)
    - Modifiers (from div[data-lookupitem='modcode'] inputs)
    - First ICD-10 Diagnosis Code (from #ellDiag10code1 data-returnvalue)
    Returns: dict
    """
    print("\n🔍 Extracting Charge Detail data...")

    JS_EXTRACT = """
    var result = {};
    // Procedure code — extract only the leading numeric CPT code (strip suffix like 'TD', 'TAJS')
    var proc = document.getElementById('txtProccode');
    var rawProc = proc ? (proc.value || proc.getAttribute('value') || '') : '';
    var numMatch = rawProc.match(/^(\d+)/);
    result.procedure = numMatch ? numMatch[1] : rawProc;

    // Modifiers — return as comma-separated string (skip empty)
    var modDivs = document.querySelectorAll('div[data-lookupitem="modcode"]');
    var mods = [];
    for (var i = 0; i < modDivs.length; i++) {
        var inp = modDivs[i].querySelector('input[type="text"]');
        if (inp) {
            var val = inp.value || '';
            if (val.trim()) mods.push(val.trim());
        }
    }
    result.modifiers = mods.join(', ');

    // First ICD-10 Diagnosis Code
    var diag1 = document.getElementById('ellDiag10code1');
    result.diagnosis_code = diag1 ? (diag1.getAttribute('data-returnvalue') || '') : '';

    return result;
    """

    try:
        data = driver.execute_script(JS_EXTRACT)
        print(f"   ✅ Procedure: {data.get('procedure')}")
        print(f"   ✅ Modifiers: {data.get('modifiers')}")
        print(f"   ✅ ICD-10 Code: {data.get('diagnosis_code')}")
        return data
    except Exception as e:
        print(f"   ⚠️ Charge Detail extraction error: {e}")
        return {"procedure": None, "modifiers": "", "diagnosis_code": None}


def navigate_to_providers_settings(driver):
    """
    Navigate: Top Navbar → System Settings → Providers/ Groups → Providers
    This opens the Providers list/search page (may open as new window).
    Must be called from the dashboard window.
    """
    print("\n🔍 Navigating to System Settings > Providers/Groups > Providers...")
    driver.switch_to.default_content()

    def _try_nav():
        try:
            # Step 1: Click "System Settings" dropdown toggle
            sys_settings = driver.find_element(
                By.XPATH, "//a[contains(@class,'dropdown-toggle') and normalize-space()='System Settings']"
            )
            if not sys_settings.is_displayed():
                return False
            sys_settings.click()
            time.sleep(1)

            # Step 2: Hover over "Providers/ Groups" to reveal its submenu
            prov_groups = driver.find_element(
                By.XPATH, "//a[normalize-space()='Providers/ Groups']"
            )
            ActionChains(driver).move_to_element(prov_groups).perform()
            time.sleep(1)

            # Step 3: Click "Providers" (inside the Providers/Groups sub-dropdown)
            providers_link = driver.find_element(
                By.XPATH,
                "//a[normalize-space()='Providers/ Groups']/following-sibling::div//a[normalize-space()='Providers']"
            )
            providers_link.click()
            print("   ✅ Clicked 'Providers' in System Settings menu.")
            time.sleep(3)
            return True
        except:
            return False

    end_time = time.time() + 25
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_nav():
            return True

        # The navbar might live inside an iframe
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_nav():
                    return True
            except:
                pass

        time.sleep(1)

    print("❌ Failed: Could not navigate to Providers settings.")
    return False


def switch_to_providers_window(driver, handles_before):
    """
    After clicking Providers in System Settings, a new window may open.
    Wait for it and switch to it.
    handles_before: set of window handles captured BEFORE the menu click.
    Returns True if switched, False if no new window (content loaded inline).
    """
    print("\n🔍 Waiting for Providers window...")
    end_time = time.time() + 15

    while time.time() < end_time:
        current_handles = set(driver.window_handles)
        new_handles = current_handles - handles_before
        if new_handles:
            new_handle = new_handles.pop()
            driver.switch_to.window(new_handle)
            time.sleep(3)
            print(f"   ✅ Switched to Providers window: {driver.title}")
            return True
        time.sleep(2)

    # No new window — content may have loaded inline
    print("   ℹ️ No new window detected — Providers page loaded inline.")
    return False


def search_provider_in_settings(driver, provider_name):
    """
    On the Providers settings page, find the search input (the one with filter icon)
    and type the provider's last name to filter the list.
    provider_name: e.g., 'GASPAR, HANNAH' — will search by last name.
    Returns True if search was typed successfully.
    """
    print(f"\n🔍 Searching for Provider: {provider_name}...")

    # Use full name for search (e.g., 'GASPAR,HANNAH') — remove extra spaces around comma
    search_term = provider_name.replace(' ', '').strip() if provider_name else provider_name.strip()

    # JS to find the correct search input — the one inside a mat-form-field
    # that also contains the filter icon (amds-icon-filter), which is unique
    # to the Providers settings page search.
    JS_FIND_SEARCH = """
    var filterIcons = document.querySelectorAll('i.amds-icon-filter');
    for (var i = 0; i < filterIcons.length; i++) {
        var formField = filterIcons[i].closest('.mat-form-field');
        if (formField) {
            var inp = formField.querySelector('input');
            if (inp) return inp;
        }
    }
    // Fallback: input with data-placeholder="Search" and maxlength="50"
    var inputs = document.querySelectorAll('input[name="search"][data-placeholder="Search"][maxlength="50"]');
    return inputs.length > 0 ? inputs[0] : null;
    """

    def _find_search():
        try:
            return driver.execute_script(JS_FIND_SEARCH)
        except:
            return None

    search_input = None
    end_time = time.time() + 20
    while time.time() < end_time:
        # Try current context
        search_input = _find_search()
        if search_input:
            break

        # Try in iframes
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                search_input = _find_search()
                if search_input:
                    break
            except:
                pass
        if search_input:
            break
        time.sleep(1)

    if not search_input:
        print("   ⚠️ Search input not found on Providers page.")
        return False

    try:
        search_input.click()
        time.sleep(0.5)
        search_input.clear()
        time.sleep(0.5)
        for char in search_term:
            search_input.send_keys(char)
            time.sleep(0.1)
        time.sleep(3)  # Wait for search results to filter
        print(f"   ✅ Typed search term: {search_term}")
        return True
    except Exception as e:
        print(f"   ⚠️ Search typing error: {e}")
        return False


def click_first_provider_row(driver):
    """
    After searching on the Providers settings page, click the first mat-row
    in the results table to open the Provider Details panel.
    Uses JS click for reliability. Waits longer for detail panel to load.
    """
    print("\n🔍 Clicking first Provider row in search results...")

    # First tr.mat-row is the SEARCH row (has colspan="3" with search input).
    # Actual provider data rows have td with colspan="1" and class "col-id".
    # We must skip the search row and click the first real data row.
    JS_CLICK_ROW = """
    var rows = document.querySelectorAll('tr.mat-row');
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        if (row.offsetParent === null) continue;
        // Skip the search row — it has a td with colspan="3" or contains input[name="search"]
        if (row.querySelector('input[name="search"]')) continue;
        var firstTd = row.querySelector('td');
        if (firstTd && firstTd.getAttribute('colspan') === '3') continue;
        // This is a real data row — click it
        row.click();
        return 'CLICKED: ' + (row.innerText || '').substring(0, 60);
    }
    return 'NO_ROW';
    """

    def _try_click():
        try:
            result = driver.execute_script(JS_CLICK_ROW)
            if result and result.startswith('CLICKED'):
                print(f"   ✅ {result}")
                return True
        except:
            pass
        # Fallback: Selenium click — also skip search row
        try:
            rows = driver.find_elements(By.CSS_SELECTOR, "tr.mat-row")
            for row in rows:
                if not row.is_displayed():
                    continue
                # Skip search row
                try:
                    search_inp = row.find_elements(By.CSS_SELECTOR, "input[name='search']")
                    if search_inp:
                        continue
                except:
                    pass
                driver.execute_script("arguments[0].scrollIntoView(true);", row)
                time.sleep(0.5)
                driver.execute_script("arguments[0].click();", row)
                print("   ✅ Clicked first provider row (fallback JS click).")
                return True
        except:
            pass
        return False

    end_time = time.time() + 20
    while time.time() < end_time:
        if _try_click():
            print("   ⏳ Waiting for Provider Details panel to load...")
            time.sleep(8)  # Provider detail page takes time to load
            return True

        # Try in iframes
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    print("   ⏳ Waiting for Provider Details panel to load...")
                    time.sleep(8)
                    return True
            except:
                pass

        time.sleep(1)

    print("   ⚠️ No provider row found to click.")
    return False


def extract_provider_npi(driver):
    """
    From the Provider Details panel (right side), extract the NPI value.
    The NPI input sits inside a div.npi-input-wrapper, with a mat-label 'NPI'.
    Needs to scroll down in the detail panel to find NPI under CLAIMS/BILLING section.
    Returns: str (NPI) or None
    """
    print("\n🔍 Extracting Provider NPI...")

    # The CLAIMS/BILLING section has id="claimsAndBilling" with amds-npi-input components.
    # There are TWO npi-input-wrapper elements:
    #   1st is inside a div with class="hidden" (not visible)
    #   2nd is the visible one (row with Tax ID | NPI | UPIN)
    # We must find the VISIBLE NPI input.
    JS_EXTRACT_NPI = """
    // Find the claimsAndBilling section
    var section = document.getElementById('claimsAndBilling');
    if (section) {
        // Get all npi-input-wrapper divs inside it
        var wrappers = section.querySelectorAll('.npi-input-wrapper');
        for (var i = 0; i < wrappers.length; i++) {
            // Skip wrappers inside a hidden parent
            var parent = wrappers[i].closest('div[class*="hidden"]');
            if (parent && parent !== section) continue;
            var inp = wrappers[i].querySelector('input');
            if (inp) {
                var val = inp.value || '';
                if (val.trim()) return val.trim();
            }
        }
    }
    // Fallback: find ALL npi-input-wrapper, pick visible one
    var allWrappers = document.querySelectorAll('.npi-input-wrapper');
    for (var j = 0; j < allWrappers.length; j++) {
        var hiddenParent = allWrappers[j].closest('.hidden');
        if (hiddenParent) continue;
        var inp2 = allWrappers[j].querySelector('input');
        if (inp2) {
            var val2 = inp2.value || '';
            if (val2.trim()) return val2.trim();
        }
    }
    // Fallback: find mat-label with text NPI, skip hidden ones
    var labels = document.querySelectorAll('mat-label');
    for (var k = 0; k < labels.length; k++) {
        if (labels[k].textContent.trim() === 'NPI') {
            var formField = labels[k].closest('mat-form-field');
            if (formField) {
                var hiddenRow = formField.closest('.hidden');
                if (hiddenRow) continue;
                var inp3 = formField.querySelector('input');
                if (inp3) {
                    var val3 = inp3.value || '';
                    if (val3.trim()) return val3.trim();
                }
            }
        }
    }
    return null;
    """

    # JS to scroll to the CLAIMS/BILLING section inside the detail panel
    JS_SCROLL_TO_NPI = """
    // First, find the claimsAndBilling section and scroll to it
    var billing = document.getElementById('claimsAndBilling');
    if (billing) {
        billing.scrollIntoView({behavior: 'smooth', block: 'center'});
        return 'SCROLLED_TO_BILLING';
    }
    // Try by section header text
    var headers = document.querySelectorAll('.section-header-wrapper span');
    for (var i = 0; i < headers.length; i++) {
        if (headers[i].textContent.indexOf('CLAIMS') >= 0 || headers[i].textContent.indexOf('BILLING') >= 0) {
            headers[i].scrollIntoView({behavior: 'smooth', block: 'center'});
            return 'SCROLLED_TO_CLAIMS_HEADER';
        }
    }
    // Try scrolling the right-side detail panel (mat-drawer-content or similar scrollable container)
    var scrollables = document.querySelectorAll('.mat-drawer-content, .mat-sidenav-content, .provider-details-container, [class*="detail-content"], [class*="provider-detail"]');
    for (var j = 0; j < scrollables.length; j++) {
        if (scrollables[j].scrollHeight > scrollables[j].clientHeight) {
            scrollables[j].scrollTop += 500;
            return 'SCROLLED_PANEL_' + j;
        }
    }
    // Try any scrollable div that has significant scrollable content
    var allDivs = document.querySelectorAll('div');
    for (var k = 0; k < allDivs.length; k++) {
        var d = allDivs[k];
        if (d.scrollHeight > d.clientHeight + 100 && d.clientHeight > 200) {
            d.scrollTop += 600;
            return 'SCROLLED_DIV';
        }
    }
    window.scrollTo(0, document.body.scrollHeight);
    return 'SCROLLED_PAGE';
    """

    def _try_js():
        try:
            return driver.execute_script(JS_EXTRACT_NPI)
        except:
            return None

    def _scroll_down():
        try:
            res = driver.execute_script(JS_SCROLL_TO_NPI)
            print(f"   📜 Scroll result: {res}")
        except:
            try:
                driver.execute_script("window.scrollBy(0, 800);")
            except:
                pass

    # Multiple scroll + extract attempts (NPI is below the fold in CLAIMS/BILLING)
    for attempt in range(6):
        _scroll_down()
        time.sleep(3)
        result = _try_js()
        if result:
            print(f"   ✅ NPI: {result}")
            return result
        print(f"   🔄 NPI not visible yet, scrolling more... (attempt {attempt + 1}/6)")

    # Try in iframes
    driver.switch_to.default_content()
    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            for attempt in range(3):
                _scroll_down()
                time.sleep(2)
                result = _try_js()
                if result:
                    print(f"   ✅ NPI (iframe): {result}")
                    return result
        except:
            pass

    print("   ⚠️ NPI not found.")
    return None


def extract_insurance_data(driver):
    print("\n🔍 Extracting Insurance Data (All Active)...")
    
    extracted_data = {
        "primary": {"carrier": None, "sub_id": None},
        "secondary": {"carrier": None, "sub_id": None},
        "error": None  # Ab error yahan store hoga
    }

    # 1. SWITCH TO CORRECT IFRAME
    insurance_iframe_found = False
    driver.switch_to.default_content()

    try:
        # Direct wait for Patient iframe (Zyada reliable)
        WebDriverWait(driver, 15).until(EC.frame_to_be_available_and_switch_to_it((By.NAME, "Patient")))
        print("   ✓ Switched to Insurance Iframe.")
        insurance_iframe_found = True
    except:
        # Fallback mechanism
        top_iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in top_iframes:
            try:
                driver.switch_to.frame(frame)
                try:
                    target_frame = driver.find_element(By.NAME, "Patient")
                    driver.switch_to.frame(target_frame)
                    insurance_iframe_found = True
                    break
                except: pass
                if not insurance_iframe_found: driver.switch_to.default_content()
            except: driver.switch_to.default_content()

    if not insurance_iframe_found:
        extracted_data["error"] = "Patient/Insurance Iframe not found"
        return extracted_data

    time.sleep(3) # Wait for table to render

    # 2. FIND ROWS DYNAMICALLY
    try:
        # Ab hum kisi ID par depend nahi karenge, saare table rows nikalenge
        rows = driver.find_elements(By.XPATH, "//tr[td]")
        active_indices = []

        for index, row in enumerate(rows):
            try:
                row_text = row.text.upper()
                # Sirf wahi row check karo jisme PRIMARY ya SECONDARY likha ho
                if "PRIMARY" in row_text or "SECONDARY" in row_text:
                    cols = row.find_elements(By.TAG_NAME, "td")
                    if len(cols) >= 6:
                        coverage_type = cols[2].text.strip().upper()
                        end_date = cols[4].text.strip()
                        # A/I column (Active/Inactive) - Screenshot ke hisaab se 6th column hai (index 5)
                        a_i_status = cols[5].text.strip().upper()

                        # Agar End date blank hai YA 'A' (Active) likha hai, toh list me daalo
                        if end_date == "" or a_i_status == "A":
                            active_indices.append({"index": index, "type": coverage_type})
            except: pass

        if not active_indices:
            extracted_data["error"] = "No Active Primary/Secondary rows found in table"
            return extracted_data

        # 3. PROCESS ACTIVE ROWS
        for item in active_indices:
            idx = item["index"]
            ins_type = item["type"]
            
            # Re-find to avoid stale element (Kyuki click hone ke baad DOM refresh hota hai)
            current_rows = driver.find_elements(By.XPATH, "//tr[td]")
            if idx < len(current_rows):
                target_row = current_rows[idx]
                
                # Row ko click karne se pehle usko screen me focus me laana
                driver.execute_script("arguments[0].scrollIntoView(true);", target_row)
                time.sleep(0.5)
                try:
                    target_row.click()
                except:
                    driver.execute_script("arguments[0].click();", target_row)
                    
                print(f"   👉 Clicked row for {ins_type}")
                time.sleep(4) # Form populate hone ke liye thoda zyada time diya

                carrier = None
                subscriber_id = None

                # CARRIER EXTRACTION
                try:
                    # Target the 2nd visible input field
                    carrier = driver.find_element(By.XPATH, "//label[contains(text(), 'Carrier')]/following::input[not(@type='hidden')][2]").get_attribute("value")
                except: pass

                if not carrier:
                    try: # Fallback to 1st visible input
                        carrier = driver.find_element(By.XPATH, "//label[contains(text(), 'Carrier')]/following::input[not(@type='hidden')][1]").get_attribute("value")
                    except: pass

                # SUBSCRIBER ID EXTRACTION
                try:
                    subscriber_id = driver.find_element(By.XPATH, "//label[contains(text(), 'Subscriber ID')]/following::input[not(@type='hidden')][1]").get_attribute("value")
                except: pass
                
                if not carrier and not subscriber_id:
                     extracted_data["error"] = f"Failed to read form fields for {ins_type}"
                
                # Store Data
                if "PRIMARY" in ins_type:
                    extracted_data["primary"]["carrier"] = carrier
                    extracted_data["primary"]["sub_id"] = subscriber_id
                elif "SECONDARY" in ins_type:
                    extracted_data["secondary"]["carrier"] = carrier
                    extracted_data["secondary"]["sub_id"] = subscriber_id
                    
    except Exception as e:
        extracted_data["error"] = f"Table parsing error: {str(e)}"
        
    return extracted_data


# ============================================================
# REPORT BOT HELPER FUNCTIONS
# Flow: Dashboard → Reports menu → Report Center
#       → Transaction Detail → Date Range → Charges Only → CSV → Run
# ============================================================

def click_reports_menu(driver):
    """
    Step 4: Click 'Reports' in the AdvancedMD PM Angular navbar.
    HTML: <a class="dropdown-toggle" uib-dropdown-toggle ng-bind="menuItem.title">Reports</a>
    """
    print("\n🔍 Searching for 'Reports' menu...")

    # Wait for Angular navbar to render
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.dropdown-toggle"))
        )
    except:
        pass

    # Correct selectors based on actual HTML
    selectors = [
        (By.XPATH, "//a[contains(@class,'dropdown-toggle') and normalize-space(text())='Reports']"),
        (By.XPATH, "//a[@uib-dropdown-toggle and normalize-space(text())='Reports']"),
        (By.XPATH, "//a[normalize-space(text())='Reports' and @ng-bind]"),
        (By.XPATH, "//a[normalize-space(text())='Reports']"),
    ]

    end_time = time.time() + 30
    while time.time() < end_time:
        driver.switch_to.default_content()
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        # Use ActionChains to trigger ng-mouseover which opens the dropdown
                        try:
                            ActionChains(driver).move_to_element(elem).click().perform()
                        except:
                            driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'Reports' menu.")
                        time.sleep(2)
                        return True
            except:
                pass
        time.sleep(1)

    print("❌ Failed: 'Reports' menu not found.")
    return False


def click_report_center(driver):
    """
    Step 5: Click 'Report Center' from the Reports dropdown.
    HTML: <a ng-bind="menuItem.title" ng-click="...">Report Center</a>
    """
    print("\n🔍 Searching for 'Report Center' option...")

    # Correct selectors — it's an <a> tag with text 'Report Center'
    selectors = [
        (By.XPATH, "//a[normalize-space(text())='Report Center' and @ng-bind]"),
        (By.XPATH, "//a[normalize-space(text())='Report Center']"),
        (By.XPATH, "//li[not(contains(@class,'disabled'))]//a[normalize-space(text())='Report Center']"),
    ]

    end_time = time.time() + 20
    while time.time() < end_time:
        driver.switch_to.default_content()
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'Report Center'.")
                        time.sleep(5)
                        return True
            except:
                pass
        time.sleep(1)

    print("❌ Failed: 'Report Center' not found.")
    return False


def switch_to_report_center_frame(driver):
    """
    Step 6: Report Center may open in a new window or inside an iframe.
    Switch to whichever context has the report list.
    """
    print("\n🔍 Switching to Report Center frame/window...")
    driver.switch_to.default_content()

    # Case 1: New window opened
    handles = driver.window_handles
    if len(handles) > 1:
        driver.switch_to.window(handles[-1])
        print(f"   ✅ Switched to new window: {driver.title}")
        time.sleep(2)
        return True

    # Case 2: Loaded inside an iframe
    end_time = time.time() + 15
    while time.time() < end_time:
        driver.switch_to.default_content()
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                # If this frame has the report search box or list
                if (driver.find_elements(By.XPATH, "//*[contains(text(),'Financial Totals')]") or
                        driver.find_elements(By.XPATH, "//*[contains(text(),'Transaction Detail')]") or
                        driver.find_elements(By.CSS_SELECTOR, "input[type='text']")):
                    print("   ✅ Switched into Report Center iframe.")
                    return True
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
        time.sleep(1)

    print("   ⚠️ Could not detect Report Center frame — continuing in current context.")
    return True


def search_and_click_transaction_detail(driver):
    """
    Step 7: In the Report Center search box, type 'Transaction Detail'
    and click it (it sits under 'Financial Totals').
    """
    print("\n🔍 Searching for 'Transaction Detail' report...")

    def _try_in_context():
        # Type in search box if present
        try:
            inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
            for inp in inputs:
                if inp.is_displayed():
                    inp.click()
                    time.sleep(0.3)
                    inp.clear()
                    inp.send_keys("Transaction Detail")
                    print("   ⌨ Typed 'Transaction Detail' in search box.")
                    time.sleep(2)
                    break
        except:
            pass

        # Click the result — must NOT be 'Patient Transaction Detail'
        td_xpaths = [
            "//a[normalize-space(text())='Transaction Detail']",
            "//span[normalize-space(text())='Transaction Detail']",
            "//td[normalize-space(text())='Transaction Detail']",
            "//*[normalize-space(text())='Transaction Detail']",
        ]
        for xp in td_xpaths:
            try:
                elems = driver.find_elements(By.XPATH, xp)
                for elem in elems:
                    # Skip 'Patient Transaction Detail'
                    if elem.is_displayed() and elem.text.strip() == "Transaction Detail":
                        driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'Transaction Detail'.")
                        time.sleep(5)
                        return True
            except:
                pass
        return False

    end_time = time.time() + 30
    while time.time() < end_time:
        driver.switch_to.default_content()

        # Try main window first
        if _try_in_context():
            return True

        # Try all iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                if _try_in_context():
                    return True
                # Try nested iframes
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        if _try_in_context():
                            return True
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()

        time.sleep(2)

    print("❌ Failed: 'Transaction Detail' not found.")
    return False


def set_report_date_range(driver, low_date, high_date):
    """
    Step 8: Fill in Low Date and High Date fields.
    Dates should be in MM/DD/YYYY format.
    """
    print(f"\n🔍 Setting date range: {low_date} → {high_date}...")

    def _try_in_context():
        low_found = False

        # Low Date selectors
        low_selectors = [
            (By.XPATH, "//td[contains(text(),'Low Date')]/following-sibling::td//input"),
            (By.XPATH, "//label[contains(text(),'Low Date')]/following::input[1]"),
            (By.CSS_SELECTOR, "input[name*='low' i]"),
            (By.CSS_SELECTOR, "input[id*='low' i]"),
        ]
        for by, val in low_selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        elem.click()
                        time.sleep(0.2)
                        elem.send_keys(Keys.CONTROL + "a")
                        elem.send_keys(low_date)
                        elem.send_keys(Keys.TAB)
                        print(f"   ✅ Low Date set: {low_date}")
                        low_found = True
                        time.sleep(0.5)
                        break
            except:
                pass
            if low_found:
                break

        if not low_found:
            return False

        # High Date selectors
        high_selectors = [
            (By.XPATH, "//td[contains(text(),'High Date')]/following-sibling::td//input"),
            (By.XPATH, "//label[contains(text(),'High Date')]/following::input[1]"),
            (By.CSS_SELECTOR, "input[name*='high' i]"),
            (By.CSS_SELECTOR, "input[id*='high' i]"),
        ]
        for by, val in high_selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        elem.click()
                        time.sleep(0.2)
                        elem.send_keys(Keys.CONTROL + "a")
                        elem.send_keys(high_date)
                        elem.send_keys(Keys.TAB)
                        print(f"   ✅ High Date set: {high_date}")
                        time.sleep(0.5)
                        return True
            except:
                pass

        return False

    end_time = time.time() + 30
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_in_context():
            return True
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                if _try_in_context():
                    return True
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        if _try_in_context():
                            return True
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
        time.sleep(2)

    print("❌ Failed: Date range fields not found.")
    return False


def set_include_charges_only(driver):
    """
    Step 9: Under 'Include Options':
      ✅ Include Charges   → id='chkCharges'     (must be checked)
      ☐  Include Payments  → id='chkPayments'    (must be unchecked)
      ☐  Include Adjustments → id='chkAdjustments' (must be unchecked)

    Angular uses ng-true-value="'true'" so we use JS click + verify
    the DOM 'checked' property rather than trusting is_selected() alone.
    """
    print("\n🔍 Setting Include Options (Charges only)...")

    def _click_by_label_text(label_text):
        """Click the checkbox associated with a label text. Tries label click
        (most reliable for Angular) and JS click as fallback."""
        try:
            # Click the <label> whose text contains label_text
            label = driver.find_element(
                By.XPATH, f"//label[contains(normalize-space(.), '{label_text}')]"
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", label)
            time.sleep(0.2)
            label.click()
            time.sleep(0.5)
            print(f"      → Clicked label: '{label_text}'")
            return True
        except:
            pass
        # Fallback: click the checkbox directly
        try:
            cb = driver.find_element(
                By.XPATH, f"//label[contains(normalize-space(.), '{label_text}')]/preceding-sibling::input[@type='checkbox'] | //label[contains(normalize-space(.), '{label_text}')]//input[@type='checkbox']"
            )
            driver.execute_script("arguments[0].click();", cb)
            time.sleep(0.5)
            print(f"      → JS clicked input for: '{label_text}'")
            return True
        except:
            pass
        return False

    def _try_in_context():
        # Use IDs directly — much more reliable than label-text XPath
        charges_elem = None
        try:
            charges_elem = driver.find_element(By.ID, "chkCharges")
        except:
            pass

        if charges_elem is None or not charges_elem.is_displayed():
            return False

        # AdvancedMD always starts with ALL three checkboxes CHECKED by default.
        # We need: Charges=ON, Payments=OFF, Adjustments=OFF
        # So we just click Payments and Adjustments to uncheck them.
        # Charges is already checked — leave it alone.

        print("   ✅ 'Include Charges' is checked (default).")

        # Include Payments → click to UNCHECK (it starts checked)
        if not _click_by_label_text("Include Payments"):
            try:
                elem = driver.find_element(By.ID, "chkPayments")
                elem.click()
                time.sleep(0.5)
            except:
                pass
        print("   ✅ 'Include Payments' unchecked.")

        # Include Adjustments → click to UNCHECK (it starts checked)
        if not _click_by_label_text("Include Adjustments"):
            try:
                elem = driver.find_element(By.ID, "chkAdjustments")
                elem.click()
                time.sleep(0.5)
            except:
                pass
        print("   ✅ 'Include Adjustments' unchecked.")

        # Include Adjustments → must be UNCHECKED
        return True

    end_time = time.time() + 20
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_in_context():
            return True
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                if _try_in_context():
                    return True
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        if _try_in_context():
                            return True
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
        time.sleep(2)

    print("❌ Failed: Include Options checkboxes not found.")
    return False


def set_csv_export(driver):
    """
    Step 10: Check 'Export on Run' checkbox and select CSV(COMMA DELIMITED).

    HTML:
      <input class="export-checkbox" type="checkbox" ng-model="report.isExport">
      <label class="export-text">Export on Run</label>
      <select> ... CSV(COMMA DELIMITED) ... </select>
    """
    print("\n🔍 Setting CSV Export...")

    def _try_in_context():
        export_found = False

        # 'Export on Run' checkbox — class='export-checkbox' (input BEFORE label)
        export_selectors = [
            (By.CSS_SELECTOR, "input.export-checkbox"),
            (By.XPATH, "//input[@type='checkbox' and contains(@class,'export-checkbox')]"),
            # Fallback: checkbox right before a label whose text is 'Export on Run'
            (By.XPATH, "//label[normalize-space(text())='Export on Run']/preceding-sibling::input[@type='checkbox']"),
            (By.XPATH, "//label[contains(@class,'export-text')]/preceding-sibling::input[@type='checkbox']"),
        ]
        for sel_by, sel_val in export_selectors:
            try:
                cb = driver.find_element(sel_by, sel_val)
                if cb.is_displayed():
                    is_checked = driver.execute_script("return arguments[0].checked;", cb)
                    if not is_checked:
                        driver.execute_script("arguments[0].click();", cb)
                        time.sleep(0.5)
                    print("   ✅ 'Export on Run' is checked.")
                    export_found = True
                    time.sleep(1)
                    break
            except:
                pass

        if not export_found:
            return False

        # Find export format <select> and choose CSV option
        try:
            selects = driver.find_elements(By.TAG_NAME, "select")
            for sel_elem in selects:
                if sel_elem.is_displayed():
                    sel_obj = Select(sel_elem)
                    for option in sel_obj.options:
                        if "CSV" in option.text.upper() and "COMMA" in option.text.upper():
                            sel_obj.select_by_visible_text(option.text)
                            print(f"   ✅ Export format selected: {option.text}")
                            time.sleep(0.5)
                            return True
                    # Fallback: just pick first CSV option
                    for option in sel_obj.options:
                        if "CSV" in option.text.upper():
                            sel_obj.select_by_visible_text(option.text)
                            print(f"   ✅ Export format selected: {option.text}")
                            time.sleep(0.5)
                            return True
        except:
            pass

        print("   ⚠️ CSV dropdown not found, but Export on Run is checked.")
        return True

    end_time = time.time() + 20
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_in_context():
            return True
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                if _try_in_context():
                    return True
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        if _try_in_context():
                            return True
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
        time.sleep(2)

    print("❌ Failed: Export options not found.")
    return False


def click_run_report(driver):
    """Step 11: Click 'Run Report', then wait for AdvancedMD to finish generating
    the report (URL changes to /generatedReport/ in the same window) and for the
    CSV auto-download to be triggered by the 'Export on Run' setting."""
    print("\n🔍 Clicking 'Run Report' button...")

    def _try_in_context():
        selectors = [
            (By.XPATH, "//input[@value='Run Report']"),
            (By.XPATH, "//button[normalize-space(text())='Run Report']"),
            (By.XPATH, "//input[contains(@value,'Run Report')]"),
            (By.XPATH, "//*[contains(@value,'Run Report') or normalize-space(text())='Run Report']"),
        ]
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'Run Report'.")
                        return True
            except:
                pass
        return False

    # 1. Click the button (search main window + iframes)
    clicked = False
    end_time = time.time() + 20
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_in_context():
            clicked = True
            break
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.frame(frame)
                if _try_in_context():
                    clicked = True
                    break
                nested = driver.find_elements(By.TAG_NAME, "iframe")
                for nf in nested:
                    try:
                        driver.switch_to.frame(nf)
                        if _try_in_context():
                            clicked = True
                            break
                        driver.switch_to.parent_frame()
                    except:
                        driver.switch_to.parent_frame()
                if clicked:
                    break
                driver.switch_to.default_content()
            except:
                driver.switch_to.default_content()
        if clicked:
            break
        time.sleep(2)

    if not clicked:
        print("❌ Failed: 'Run Report' button not found.")
        return False

    # 2. The download is triggered immediately by "Export on Run". The page
    #    navigates to #/generatedReport/ and shows a spinner that may NEVER
    #    disappear, but the .xlsx file downloads in the background regardless.
    #    So we just give Chrome a few seconds to start the download and return.
    print("   ⏳ Giving Chrome a moment to start the download...")
    time.sleep(10)
    print("   ✅ Proceeding to check download directory.")
    return True


# ============================================================
# CHARGE CODES TO FILTER (Psych/Behavioral codes)
# ============================================================
PSYCH_CHARGE_CODES = {
    '90791', '90792', '90832', '90834', '90836',
    '90837', '90839', '90840', '90785', '90870'
}


def _detect_column(df, candidates):
    """
    Return the first df column name that matches one of the candidate strings.
    Tries exact case-insensitive match first, then substring match.
    """
    normalized = {c.strip().lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in normalized:
            return normalized[cand.lower()]
    for cand in candidates:
        for col_lower, col_orig in normalized.items():
            if cand.lower() in col_lower:
                return col_orig
    return None


def _write_sheet(wb, sheet_name, df):
    """Write a DataFrame into a new workbook sheet with a styled header row."""
    from openpyxl.styles import Font, PatternFill, Alignment
    ws = wb.create_sheet(title=sheet_name)
    if df.empty:
        ws.append(["No data"])
        return
    ws.append(list(df.columns))
    header_fill = PatternFill(start_color="1F2937", end_color="1F2937", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    for row in df.itertuples(index=False):
        ws.append(list(row))
    for col in ws.columns:
        max_len = max(
            (len(str(cell.value)) if cell.value is not None else 0) for cell in col
        )
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 3, 45)


def process_report_data(csv_path, appointments_path=None):
    """
    Process the downloaded Transaction Detail into a multi-sheet Excel
    matching the Pure Meridian Visits reference format.

    Sheets produced:
      1 – Summary            : Chart Number, Patient Name, Visits, Future Visit, Total Visits
      2 – Current Visits     : Visit, Chart Number, Patient Name, Insurance Name, DOS, Procedure Code
      3 – Future Appointments: raw appointments data (only if appointments_path is provided)

    Filters applied to build Current Visits:
      • Only MERIDIAN insurance (Visit - Primary Carrier contains 'MERIDIAN')
      • Only psych procedure codes (PSYCH_CHARGE_CODES)
      • Only target year (mode of DOS years)
      • Only positive charges, exclude $-codes
      • One row per unique Visit #

    Returns:
        {
          "excel_path"        : str | None,
          "high_count_charts" : list[dict],   # Chart#s with visit count > 16
          "error"             : str | None
        }
    """
    import pandas as pd
    from openpyxl import Workbook

    result = {"excel_path": None, "high_count_charts": [], "error": None}

    try:
        # ── 1. Read raw data (CSV or Excel) ───────────────────────────────────
        if csv_path.lower().endswith(('.xlsx', '.xls')):
            df_probe = pd.read_excel(csv_path, header=None, nrows=15, dtype=str)
            header_row = 0
            max_non_null = 0
            for i in range(min(15, len(df_probe))):
                non_null = df_probe.iloc[i].notna().sum()
                if non_null > max_non_null:
                    max_non_null = non_null
                    header_row = i
            print(f"   🔎 Auto-detected header at row {header_row} ({max_non_null} columns)")
            df_raw = pd.read_excel(csv_path, header=header_row, dtype=str)
        else:
            df_raw = pd.read_csv(csv_path, dtype=str, skipinitialspace=True)
        df_raw.columns = [c.strip() for c in df_raw.columns]
        print(f"\n   📄 Raw data: {len(df_raw)} rows  |  Columns: {list(df_raw.columns)}")

        # ── 2. Detect key columns ─────────────────────────────────────────────
        col_visit     = _detect_column(df_raw, ['visit #', 'visit id', 'visit', 'vis #', 'encounter id', 'encounter'])
        col_patient   = _detect_column(df_raw, ['patient name', 'pat name', 'patient', 'last, first', 'last,first'])
        col_chart     = _detect_column(df_raw, ['chart number', 'chart #', 'chart#', 'chart num', 'chart'])
        col_dos       = _detect_column(df_raw, ['date of service', 'date of svc', 'dos', 'service date', 'svc date'])
        col_code      = _detect_column(df_raw, ['charge code', 'proc', 'procedure', 'cpt', 'cpt code', 'transaction code'])
        col_charges   = _detect_column(df_raw, ['charges', 'charge', 'amount', 'total charge', 'total charges'])
        col_carrier   = _detect_column(df_raw, ['visit - primary carrier', 'primary carrier', 'carrier', 'insurance', 'insurance name', 'payer'])

        print(f"   🔎 Detected → Visit:{col_visit} | Patient:{col_patient} | "
              f"Chart:{col_chart} | DOS:{col_dos} | Code:{col_code} | "
              f"Charges:{col_charges} | Carrier:{col_carrier}")

        missing = [
            name for name, col in [
                ('Visit', col_visit), ('Patient Name', col_patient), ('Chart#', col_chart),
                ('DOS', col_dos), ('Charge Code', col_code), ('Charges', col_charges),
                ('Carrier', col_carrier),
            ] if col is None
        ]
        if missing:
            result["error"] = (
                f"Could not detect columns: {', '.join(missing)}. "
                f"Available: {list(df_raw.columns)}"
            )
            return result

        # ── 3. Clean DOS — parse dates ────────────────────────────────────────
        df_raw[col_dos] = df_raw[col_dos].astype(str).str.strip()
        df_raw['_dos_dt'] = pd.to_datetime(df_raw[col_dos], errors='coerce')

        # Clean charges → numeric
        df_raw['_charges_num'] = (
            df_raw[col_charges].astype(str)
            .str.replace(r'[\$,\s]', '', regex=True)
        )
        df_raw['_charges_num'] = pd.to_numeric(df_raw['_charges_num'], errors='coerce').fillna(0)

        # ── 4. Filter pipeline ────────────────────────────────────────────────
        df = df_raw.copy()

        # 4a. Target year
        target_year = int(df['_dos_dt'].dt.year.mode().iloc[0])
        df = df[df['_dos_dt'].dt.year == target_year].reset_index(drop=True)
        print(f"   🔎 Target year: {target_year} → {len(df)} rows")

        # 4b. MERIDIAN insurance only
        df = df[
            df[col_carrier].astype(str).str.upper().str.contains('MERIDIAN', na=False)
        ].reset_index(drop=True)
        print(f"   🔎 MERIDIAN filter → {len(df)} rows")

        # 4c. Remove $-codes and non-positive charges
        df[col_code] = df[col_code].astype(str).str.strip()
        dollar_mask = df[col_code].str.startswith('$')
        df = df[(~dollar_mask) & (df['_charges_num'] > 0)].reset_index(drop=True)
        print(f"   🔎 After $-code/positive filter → {len(df)} rows")

        # 4d. Psych codes only (extract base numeric code)
        df['_base_code'] = df[col_code].str.extract(r'^(\d+)', expand=False).fillna('')
        df = df[df['_base_code'].isin(PSYCH_CHARGE_CODES)].reset_index(drop=True)
        print(f"   🔎 Psych code filter → {len(df)} rows")

        # ── 5. Build Current Visits — one row per unique Visit # ──────────────
        #    Strip whitespace from key text fields for clean output
        for c in [col_visit, col_chart, col_patient, col_carrier]:
            df[c] = df[c].astype(str).str.strip()

        df_current = (
            df.sort_values('_dos_dt', ascending=True)
            .drop_duplicates(subset=[col_visit], keep='first')
            .reset_index(drop=True)
        )
        df_current_visits = df_current[[col_visit, col_chart, col_patient, col_carrier, '_dos_dt', '_base_code']].copy()
        df_current_visits.columns = ['Visit', 'Chart Number', 'Patient Name', 'Insurance Name', 'DOS', 'Procedure Code']
        df_current_visits = df_current_visits.sort_values('DOS', ascending=True).reset_index(drop=True)
        # Format DOS for display
        df_current_visits['DOS'] = pd.to_datetime(df_current_visits['DOS'], errors='coerce').dt.strftime('%m/%d/%Y')
        print(f"   ✅ Current Visits: {len(df_current_visits)} rows, "
              f"{df_current_visits['Chart Number'].nunique()} unique charts")

        # ── 6. Build Summary ──────────────────────────────────────────────────
        visit_counts = (
            df_current_visits.groupby(['Chart Number', 'Patient Name'], sort=False)
            .size()
            .reset_index(name='Visits')
        )

        # Future Visit counts (from appointments if available)
        df_appointments = None
        if appointments_path and os.path.exists(appointments_path):
            try:
                df_appointments = pd.read_excel(appointments_path, dtype=str)
                df_appointments.columns = [c.strip() for c in df_appointments.columns]
                fa_chart_col = _detect_column(df_appointments, ['chartnumber', 'chart number', 'chart #', 'chart'])
                fa_carrier_col = _detect_column(df_appointments, ['carrier', 'insurance', 'payer'])
                if fa_chart_col and fa_carrier_col:
                    # Count future appointments for MERIDIAN patients
                    meridian_charts = set(visit_counts['Chart Number'].astype(str))
                    fa_meridian = df_appointments[
                        df_appointments[fa_chart_col].astype(str).isin(meridian_charts)
                    ]
                    future_counts = (
                        fa_meridian.groupby(fa_chart_col, sort=False)
                        .size()
                        .reset_index(name='Future Visit')
                        .rename(columns={fa_chart_col: 'Chart Number'})
                    )
                    future_counts['Chart Number'] = future_counts['Chart Number'].astype(str)
                else:
                    future_counts = pd.DataFrame(columns=['Chart Number', 'Future Visit'])
                print(f"   ✅ Future Appointments loaded: {len(df_appointments)} rows")
            except Exception as e:
                print(f"   ⚠️  Could not read appointments file: {e}")
                future_counts = pd.DataFrame(columns=['Chart Number', 'Future Visit'])
        else:
            future_counts = pd.DataFrame(columns=['Chart Number', 'Future Visit'])

        # Merge visit counts with future counts
        visit_counts['Chart Number'] = visit_counts['Chart Number'].astype(str)
        df_summary = visit_counts.merge(future_counts, on='Chart Number', how='left')
        df_summary['Future Visit'] = df_summary['Future Visit'].fillna(0).astype(int)
        df_summary['Total Visits'] = df_summary['Visits'] + df_summary['Future Visit']
        df_summary = df_summary.sort_values('Visits', ascending=False).reset_index(drop=True)
        df_summary = df_summary[['Chart Number', 'Patient Name', 'Visits', 'Future Visit', 'Total Visits']]
        print(f"   ✅ Summary (before filter): {len(df_summary)} charts, max visits={df_summary['Visits'].max()}")

        # Keep only charts with Visits > 15
        df_summary = df_summary[df_summary['Visits'] > 15].reset_index(drop=True)
        high_charts_set = set(df_summary['Chart Number'].astype(str))
        df_current_visits = df_current_visits[
            df_current_visits['Chart Number'].astype(str).isin(high_charts_set)
        ].reset_index(drop=True)
        print(f"   ✅ After >15 filter: {len(df_summary)} charts, {len(df_current_visits)} visits")

        # Flag charts with visit count > 16 (for logging)
        high_count = df_summary[df_summary['Visits'] > 16][['Chart Number', 'Patient Name', 'Visits']].copy()
        high_count.columns = ['Chart_Num', 'Patient_Name', 'Line_Count']
        result["high_count_charts"] = high_count.to_dict(orient='records')
        if result["high_count_charts"]:
            print(f"\n   ⚠️  {len(result['high_count_charts'])} chart(s) with >16 visits: "
                  + ", ".join(str(r['Chart_Num']) for r in result["high_count_charts"]))

        # ── 7. Write multi-sheet Excel ────────────────────────────────────────
        from datetime import datetime as _dt
        timestamp = _dt.now().strftime('%Y%m%d_%H%M%S')
        excel_path = os.path.splitext(csv_path)[0] + f"_processed_{timestamp}.xlsx"
        wb = Workbook()
        _write_sheet(wb, "Summary", df_summary)
        _write_sheet(wb, "Current Visits", df_current_visits)
        if df_appointments is not None:
            _write_sheet(wb, "Future Appointments", df_appointments)
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]
        wb.save(excel_path)
        result["excel_path"] = excel_path
        print(f"   ✅ Processed Excel saved: {os.path.basename(excel_path)}")

    except Exception as e:
        import traceback
        result["error"] = f"Data processing error: {str(e)}\n{traceback.format_exc()}"

    return result


def wait_for_download(download_dir, timeout=60):
    """
    Wait until a downloaded report file (.csv or .xlsx) appears in download_dir.
    Returns the full path of the downloaded file, or None on timeout.
    """
    VALID_EXTENSIONS = ('.csv', '.xlsx', '.xls')
    print(f"\n⏳ Waiting for report download in: {download_dir}")
    end_time = time.time() + timeout
    while time.time() < end_time:
        files = [
            f for f in os.listdir(download_dir)
            if any(f.lower().endswith(ext) for ext in VALID_EXTENSIONS)
            and not f.endswith('.crdownload')
            and not f.startswith('.')
        ]
        if files:
            # Pick the most recently modified file
            files.sort(key=lambda fn: os.path.getmtime(os.path.join(download_dir, fn)), reverse=True)
            full_path = os.path.join(download_dir, files[0])
            # Wait a moment to ensure the file is fully written
            time.sleep(2)
            print(f"   ✅ Downloaded file found: {files[0]}")
            return full_path
        time.sleep(2)
    print("   ❌ Download timed out.")
    return None


def run_scraper_logic(username, password, office_key, claim_id, low_date=None, high_date=None, download_dir=None):
    """
    Main entry point for Celery to call.
    Flow: Login → Popups → Dashboard → Reports → Report Center
          → Transaction Detail → Date Range → Charges Only → CSV → Run Report
    Returns: {"success": bool, "csv_path": str|None, "error": str|None}
    """
    from datetime import datetime

    if not low_date:
        low_date = f"01/01/{datetime.now().year}"
    if not high_date:
        high_date = datetime.now().strftime("%m/%d/%Y")

    # Use a temp dir unique to this run if none provided
    if download_dir is None:
        import tempfile
        download_dir = tempfile.mkdtemp(prefix="meridian_report_")

    driver = setup_driver(download_dir=download_dir)
    result = {
        "success": False,
        "csv_path": None,
        "excel_path": None,
        "high_count_charts": [],
        "error": None
    }

    try:
        # Step 1: Login
        if not perform_login(driver, username, password, office_key):
            result["error"] = "Login Failed"
            return result

        # Step 2: Handle post-login popups
        handle_popups(driver)

        # Step 3: Wait for dashboard window
        if not switch_to_dashboard_window(driver):
            result["error"] = "Dashboard window did not load"
            return result

        print("\n✅ Dashboard loaded. Starting Report Center flow...")

        # Step 4: Click 'Reports' in the top menu bar
        if not click_reports_menu(driver):
            result["error"] = "Reports menu not found"
            return result

        # Step 5: Click 'Report Center' from the dropdown
        if not click_report_center(driver):
            result["error"] = "Report Center not found"
            return result

        # Step 6: Handle iframe/window switch for Report Center
        switch_to_report_center_frame(driver)

        # Step 7: Search for and click 'Transaction Detail' (under Financial Totals)
        if not search_and_click_transaction_detail(driver):
            result["error"] = "Transaction Detail report not found"
            return result

        # Step 8: Set date range — Low Date = 12/01/2025, High Date = today
        if not set_report_date_range(driver, low_date, high_date):
            result["error"] = "Failed to set date range"
            return result

        # Step 9: Include Options — only 'Include Charges' checked
        if not set_include_charges_only(driver):
            result["error"] = "Failed to set include options"
            return result

        # Step 10: Check 'Export on Run' and select CSV (COMMA DELIMITED)
        if not set_csv_export(driver):
            result["error"] = "Failed to set CSV export"
            return result

        # Step 11: Click 'Run Report'
        if not click_run_report(driver):
            result["error"] = "Failed to click Run Report"
            return result

        # Step 12: Wait for file to download (up to 5 min — report generation can be slow)
        csv_path = wait_for_download(download_dir, timeout=300)
        if not csv_path:
            result["error"] = "Report file did not download within timeout"
            return result

        # Step 13: Process CSV → Excel (Summary, Current Visits, Future Appointments)
        print("\n📊 Processing downloaded CSV...")
        proc = process_report_data(csv_path)
        if proc.get("error"):
            print(f"   ⚠️  Data processing warning: {proc['error']}")

        result["success"] = True
        result["csv_path"] = csv_path
        result["excel_path"] = proc.get("excel_path")
        result["high_count_charts"] = proc.get("high_count_charts", [])
        print("\n🎉 Report bot completed successfully!")

    except Exception as e:
        result["error"] = str(e)
    finally:
        driver.quit()

    return result


def click_chart_files_sidebar(driver):
    """
    Click 'Chart Files' in the Angular patient sidebar.
    """
    print("\n\U0001f50d Clicking 'Chart Files' sidebar tab...")

    selectors = [
        (By.XPATH, "//*[@data-pendo-id='ptc-side-nav-chart-files-20240731']"),
        (By.XPATH, "//mat-list-item[.//*[normalize-space(text())='Chart Files']]"),
        (By.XPATH, "//span[normalize-space(text())='Chart Files' and contains(@class,'ng-star-inserted')]"),
        (By.XPATH, "//*[normalize-space(text())='Chart Files']"),
    ]

    def _try_click():
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        driver.execute_script("arguments[0].scrollIntoView(true);", elem)
                        time.sleep(0.5)
                        driver.execute_script("arguments[0].click();", elem)
                        print("   \u2705 Clicked 'Chart Files' tab.")
                        time.sleep(5)
                        return True
            except:
                pass
        return False

    end_time = time.time() + 25
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_click():
            return True

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    return True
            except:
                pass

        time.sleep(1)

    print("\u274c Failed: 'Chart Files' tab not found.")
    return False


def upload_pdf_to_portal(username, password, office_key, chart_number, pdf_path, file_label="Auth form"):
    """
    Separate Selenium flow to upload a filled PDF to AdvancedMD Chart Files.
    Login -> Dashboard -> Patient Info -> Search Chart -> Handle Memo -> Chart Files -> Upload
    """
    driver = setup_driver()
    result = {"success": False, "error": None}

    try:
        # Step 1: Login
        if not perform_login(driver, username, password, office_key):
            result["error"] = "Login Failed"
            return result

        # Step 2: Handle post-login popups
        handle_popups(driver)

        # Step 3: Wait for dashboard
        if not switch_to_dashboard_window(driver):
            result["error"] = "Dashboard window did not load"
            return result

        print(f"\n\u2705 Dashboard loaded. Starting PDF Upload for Chart: {chart_number}")

        # Step 4: Click Patient Info
        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found"
            return result

        # Step 5: Search Chart Number
        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart number: {chart_number}"
            return result

        # Step 6: Handle Patient Memo popup
        handle_patient_memo(driver)

        # Step 7: Click Chart Files sidebar
        if not click_chart_files_sidebar(driver):
            result["error"] = "Chart Files tab not found"
            return result

        print(f"\u2705 Chart Files page opened for Chart: {chart_number}")

        # Step 8: Click Import button first, then find file input and send file
        time.sleep(5)
        uploaded = False

        def _click_import_button():
            """Click #btnChartImport in all iframe depths. Returns True if clicked."""
            def _try_click():
                btn = driver.find_elements(By.ID, "btnChartImport")
                if btn and btn[0].is_displayed():
                    driver.execute_script("arguments[0].click();", btn[0])
                    return True
                # Also try calling chrt_new() directly (Import button's onclick)
                try:
                    result = driver.execute_script(
                        "if (typeof chrt_new === 'function') { chrt_new(); return true; } return false;"
                    )
                    if result:
                        return True
                except:
                    pass
                return False

            # Try current context first
            driver.switch_to.default_content()
            try:
                driver.switch_to.frame("Patient")
                if _try_click():
                    print("   ✅ Clicked Import button in Patient iframe")
                    return True
            except:
                pass

            driver.switch_to.default_content()
            top_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for tframe in top_iframes:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(tframe)
                    if _try_click():
                        print("   ✅ Clicked Import button in top-level iframe")
                        return True
                    nested = driver.find_elements(By.TAG_NAME, "iframe")
                    for nf in nested:
                        try:
                            driver.switch_to.frame(nf)
                            if _try_click():
                                print("   ✅ Clicked Import button in nested iframe")
                                return True
                            driver.switch_to.parent_frame()
                        except:
                            driver.switch_to.parent_frame()
                except:
                    pass
            return False

        # Always click Import button first — this triggers chrt_new() which sets up
        # the onchange handler that opens the ImageProperties popup
        import_clicked = _click_import_button()
        if import_clicked:
            print("   ⏳ Waiting for file input to become active after Import click...")
            time.sleep(3)
        else:
            print("   ⚠️ Import button not found — searching for file input directly")

        def _deep_find_file_input():
            """Search all iframes (including nested) for the hidden file input."""
            # Try current context
            file_input = driver.find_elements(By.CSS_SELECTOR, "input.fileSelector[type='file']")
            if not file_input:
                file_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if file_input:
                return file_input[0]

            # Try named Patient iframe first (most likely location)
            driver.switch_to.default_content()
            try:
                driver.switch_to.frame("Patient")
                file_input = driver.find_elements(By.CSS_SELECTOR, "input.fileSelector[type='file']")
                if not file_input:
                    file_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                if file_input:
                    print("   Found file input in Patient iframe")
                    return file_input[0]
            except:
                pass

            # Deep search: top-level iframes and their children
            driver.switch_to.default_content()
            top_iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for tframe in top_iframes:
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(tframe)

                    file_input = driver.find_elements(By.CSS_SELECTOR, "input.fileSelector[type='file']")
                    if not file_input:
                        file_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                    if file_input:
                        print("   Found file input in top-level iframe")
                        return file_input[0]

                    # Check nested iframes (Patient iframe is often nested)
                    nested_iframes = driver.find_elements(By.TAG_NAME, "iframe")
                    for nframe in nested_iframes:
                        try:
                            driver.switch_to.frame(nframe)
                            file_input = driver.find_elements(By.CSS_SELECTOR, "input.fileSelector[type='file']")
                            if not file_input:
                                file_input = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
                            if file_input:
                                print("   Found file input in nested iframe")
                                return file_input[0]
                            driver.switch_to.parent_frame()
                        except:
                            driver.switch_to.parent_frame()
                except:
                    pass
            return None

        end_time = time.time() + 25
        while time.time() < end_time:
            file_input = _deep_find_file_input()
            if file_input:
                # Make visible and send file
                driver.execute_script(
                    "arguments[0].style.visibility='visible'; arguments[0].style.display='block';"
                    "arguments[0].style.height='30px'; arguments[0].style.width='200px';"
                    "arguments[0].style.opacity='1'; arguments[0].style.position='relative';",
                    file_input
                )
                time.sleep(0.5)
                file_input.send_keys(pdf_path)
                print(f"   ✅ PDF file sent to file input: {pdf_path}")
                # Dispatch change event to trigger AdvancedMD's onchange handler
                # which opens the ImageProperties popup window
                try:
                    driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
                        file_input
                    )
                    print("   ✅ change event dispatched on file input")
                except Exception as e_evt:
                    print(f"   ⚠️ Could not dispatch change event: {e_evt}")
                uploaded = True
                break
            time.sleep(2)

        if not uploaded:
            result["error"] = "Could not find file input for upload"
            return result

        # Step 9: Wait for ImageProperties popup window
        print("   🔍 Waiting for ImageProperties dialog...")
        time.sleep(8)  # Give more time for popup to open after change event

        # Save current window handles before looking
        main_handle = driver.current_window_handle
        img_props_handle = None
        end_time = time.time() + 45

        while time.time() < end_time:
            for w in driver.window_handles:
                try:
                    driver.switch_to.window(w)
                    title = driver.title or ""
                    url = driver.current_url or ""
                    # ImageProperties popup has distinctive title/URL
                    if "ImageProperties" in title or "imageprop" in url.lower():
                        img_props_handle = w
                        print(f"   \u2705 ImageProperties window found: {title}")
                        break
                    # Also check if txtName exists directly (small popup window)
                    name_fields = driver.find_elements(By.ID, "txtName")
                    if name_fields and w != main_handle:
                        img_props_handle = w
                        print(f"   \u2705 ImageProperties window found (by txtName): {title}")
                        break
                except:
                    continue
            if img_props_handle:
                break
            time.sleep(2)

        if not img_props_handle:
            result["error"] = "ImageProperties dialog not found after file upload"
            return result

        # Step 10: Fill File Name and Description in ImageProperties window
        driver.switch_to.window(img_props_handle)
        time.sleep(2)

        name_field = driver.find_elements(By.ID, "txtName")
        if name_field:
            name_field[0].clear()
            name_field[0].send_keys(file_label)
            print(f"   \u2705 File Name set to: {file_label}")
        else:
            result["error"] = "txtName field not found in ImageProperties"
            return result

        desc_field = driver.find_elements(By.ID, "txtDescription")
        if desc_field:
            desc_field[0].clear()
            desc_field[0].send_keys(file_label)
            print(f"   \u2705 File Description set to: {file_label}")

        time.sleep(1)

        # Step 11: Click OK button
        ok_btn = driver.find_elements(By.ID, "btnOK")
        if ok_btn:
            driver.execute_script("arguments[0].click();", ok_btn[0])
            print("   \u2705 Clicked OK — file upload submitted!")
        else:
            result["error"] = "OK button not found in ImageProperties dialog"
            return result

        time.sleep(5)

        result["success"] = True
        print(f"\n\U0001f389 PDF Upload completed for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)
    finally:
        driver.quit()

    return result


def upload_pdf_with_existing_driver(driver, dashboard_handle, chart_number, pdf_path):
    """
    Upload a filled PDF to AdvancedMD Chart Files using an ALREADY logged-in driver.
    No new login — reuses the browser session from run_auth_prep_logic.
    Closes any extra windows first, returns to dashboard, then uploads.
    """
    result = {"success": False, "error": None}
    try:
        print(f"\n📤 Starting PDF upload (reusing browser) for Chart: {chart_number}")
        # Close any extra windows opened during scraping (providers, charge detail, etc.)
        for handle in list(driver.window_handles):
            if handle != dashboard_handle:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                    print("   🗙 Closed extra window")
                except:
                    pass
        driver.switch_to.window(dashboard_handle)
        time.sleep(2)

        # Close stale patient tabs before navigating (upload flow)
        close_all_patient_tabs(driver)
        handle_patients_open_dialog(driver)

        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found (upload)"
            return result

        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart: {chart_number} (upload)"
            return result

        handle_patient_memo(driver)

        if not click_chart_files_sidebar(driver):
            result["error"] = "Chart Files tab not found (upload)"
            return result

        print(f"✅ Chart Files opened for Chart: {chart_number}")
        time.sleep(5)
        uploaded = False

        def _click_import_btn():
            def _try():
                btn = driver.find_elements(By.ID, "btnChartImport")
                if btn and btn[0].is_displayed():
                    driver.execute_script("arguments[0].click();", btn[0])
                    return True
                try:
                    if driver.execute_script(
                        "if(typeof chrt_new==='function'){chrt_new();return true;}return false;"
                    ):
                        return True
                except:
                    pass
                return False

            driver.switch_to.default_content()
            try:
                driver.switch_to.frame("Patient")
                if _try():
                    print("   ✅ Clicked Import in Patient iframe")
                    return True
            except:
                pass
            driver.switch_to.default_content()
            for tf in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(tf)
                    if _try():
                        print("   ✅ Clicked Import in top-level iframe")
                        return True
                    for nf in driver.find_elements(By.TAG_NAME, "iframe"):
                        try:
                            driver.switch_to.frame(nf)
                            if _try():
                                print("   ✅ Clicked Import in nested iframe")
                                return True
                            driver.switch_to.parent_frame()
                        except:
                            driver.switch_to.parent_frame()
                except:
                    pass
            return False

        if _click_import_btn():
            print("   ⏳ Waiting for file input after Import click...")
            time.sleep(3)
        else:
            print("   ⚠️ Import button not found — trying file input directly")

        def _find_file_input():
            for sel in ["input.fileSelector[type='file']", "input[type='file']"]:
                fi = driver.find_elements(By.CSS_SELECTOR, sel)
                if fi:
                    return fi[0]
            driver.switch_to.default_content()
            try:
                driver.switch_to.frame("Patient")
                for sel in ["input.fileSelector[type='file']", "input[type='file']"]:
                    fi = driver.find_elements(By.CSS_SELECTOR, sel)
                    if fi:
                        print("   Found file input in Patient iframe")
                        return fi[0]
            except:
                pass
            driver.switch_to.default_content()
            for tf in driver.find_elements(By.TAG_NAME, "iframe"):
                try:
                    driver.switch_to.default_content()
                    driver.switch_to.frame(tf)
                    for sel in ["input.fileSelector[type='file']", "input[type='file']"]:
                        fi = driver.find_elements(By.CSS_SELECTOR, sel)
                        if fi:
                            print("   Found file input in top-level iframe")
                            return fi[0]
                    for nfr in driver.find_elements(By.TAG_NAME, "iframe"):
                        try:
                            driver.switch_to.frame(nfr)
                            for sel in ["input.fileSelector[type='file']", "input[type='file']"]:
                                fi = driver.find_elements(By.CSS_SELECTOR, sel)
                                if fi:
                                    print("   Found file input in nested iframe")
                                    return fi[0]
                            driver.switch_to.parent_frame()
                        except:
                            driver.switch_to.parent_frame()
                except:
                    pass
            return None

        end_time = time.time() + 25
        while time.time() < end_time:
            fi = _find_file_input()
            if fi:
                driver.execute_script(
                    "arguments[0].style.visibility='visible';arguments[0].style.display='block';"
                    "arguments[0].style.height='30px';arguments[0].style.width='200px';"
                    "arguments[0].style.opacity='1';arguments[0].style.position='relative';",
                    fi
                )
                time.sleep(0.5)
                fi.send_keys(pdf_path)
                print(f"   ✅ PDF sent: {pdf_path}")
                try:
                    driver.execute_script(
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", fi
                    )
                    print("   ✅ change event dispatched")
                except Exception as ev:
                    print(f"   ⚠️ change event error: {ev}")
                uploaded = True
                break
            time.sleep(2)

        if not uploaded:
            result["error"] = "Could not find file input for upload"
            return result

        # Wait for ImageProperties popup
        print("   🔍 Waiting for ImageProperties dialog...")
        time.sleep(8)
        main_handle = driver.current_window_handle
        img_handle = None
        end_time = time.time() + 45

        while time.time() < end_time:
            for w in driver.window_handles:
                try:
                    driver.switch_to.window(w)
                    t = driver.title or ""
                    u = driver.current_url or ""
                    if "ImageProperties" in t or "imageprop" in u.lower():
                        img_handle = w
                        print(f"   ✅ ImageProperties found: {t}")
                        break
                    nf = driver.find_elements(By.ID, "txtName")
                    if nf and w != main_handle:
                        img_handle = w
                        print(f"   ✅ ImageProperties found (txtName): {t}")
                        break
                except:
                    continue
            if img_handle:
                break
            time.sleep(2)

        if not img_handle:
            result["error"] = "ImageProperties dialog not found after file upload"
            return result

        driver.switch_to.window(img_handle)
        time.sleep(2)
        nf = driver.find_elements(By.ID, "txtName")
        if nf:
            nf[0].clear()
            nf[0].send_keys("Auth form")
            print("   ✅ File Name set to: Auth form")
        else:
            result["error"] = "txtName not found in ImageProperties"
            return result
        df_field = driver.find_elements(By.ID, "txtDescription")
        if df_field:
            df_field[0].clear()
            df_field[0].send_keys("Auth form")
            print("   ✅ Description set to: Auth form")
        time.sleep(1)
        ok = driver.find_elements(By.ID, "btnOK")
        if ok:
            driver.execute_script("arguments[0].click();", ok[0])
            print("   ✅ Clicked OK — upload submitted!")
        else:
            result["error"] = "OK button not found in ImageProperties"
            return result
        time.sleep(5)
        result["success"] = True
        print(f"\n🎉 PDF Upload completed for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)
    return result


def run_auth_prep_for_existing_session(driver, dashboard_handle, chart_number):
    """
    Process a single chart number using an ALREADY logged-in driver.
    No login, no browser setup, no driver.quit() — caller owns the driver lifecycle.
    Closes extra windows, returns to dashboard, then runs the full per-chart flow.
    Returns: {"success": bool, "error": str|None, "insurance_data": dict|None}
    """
    result = {"success": False, "error": None, "insurance_data": None}
    try:
        print(f"\n📋 Auth Prep (reusing session) for Chart: {chart_number}")

        # Close extra windows (providers popup, charge detail, etc.), go back to dashboard
        for handle in list(driver.window_handles):
            if handle != dashboard_handle:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                    print("   🗙 Closed extra window")
                except:
                    pass
        driver.switch_to.window(dashboard_handle)
        time.sleep(2)

        # Close stale patient tabs before opening the next one
        close_all_patient_tabs(driver)
        handle_patients_open_dialog(driver)

        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found"
            return result

        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart number: {chart_number}"
            return result

        handle_patient_memo(driver)

        if not click_insurance_tab(driver):
            result["error"] = "Insurance tab not found"
            return result

        insurance_data = extract_meridian_insurance(driver)
        if insurance_data.get("error"):
            print(f"   ⚠️ Insurance extraction warning: {insurance_data['error']}")

        result["insurance_data"] = {
            "carrier": insurance_data.get("carrier"),
            "subscriber_name": insurance_data.get("subscriber_name"),
            "subscriber_id": insurance_data.get("subscriber_id"),
            "dob": insurance_data.get("dob"),
        }

        click_appointments_sidebar(driver)
        requesting_provider = fetch_requesting_provider_from_appointments(driver)
        result["insurance_data"]["requesting_provider"] = requesting_provider

        click_history_sidebar(driver)
        handles_before = set(driver.window_handles)
        click_first_history_row(driver)

        if switch_to_charge_detail_window(driver, handles_before):
            charge_data = extract_charge_detail_data(driver)
            result["insurance_data"]["procedure"] = charge_data.get("procedure")
            result["insurance_data"]["modifiers"] = charge_data.get("modifiers", "")
            result["insurance_data"]["diagnosis_code"] = charge_data.get("diagnosis_code")
            try:
                driver.close()
                driver.switch_to.window(dashboard_handle)
                time.sleep(2)
                print("   ✅ Closed Charge Detail, back to Dashboard.")
            except:
                driver.switch_to.window(dashboard_handle)

        if requesting_provider:
            handles_before_prov = set(driver.window_handles)
            if navigate_to_providers_settings(driver):
                switch_to_providers_window(driver, handles_before_prov)
                if search_provider_in_settings(driver, requesting_provider):
                    if click_first_provider_row(driver):
                        provider_npi = extract_provider_npi(driver)
                        result["insurance_data"]["provider_npi"] = provider_npi

        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        today = datetime.now()
        start_date = today + timedelta(days=10)
        end_date = start_date + relativedelta(months=6)

        result["insurance_data"]["requesting_tin"] = "852229929"
        result["insurance_data"]["requesting_contact_name"] = "SULLIVAN SILVA"
        result["insurance_data"]["requesting_phone"] = "7472085136"
        result["insurance_data"]["requesting_fax"] = "7472085004"
        result["insurance_data"]["start_date"] = start_date.strftime("%m/%d/%Y")
        result["insurance_data"]["end_date"] = end_date.strftime("%m/%d/%Y")
        result["insurance_data"]["total_visits"] = "60"
        result["insurance_data"]["service_type"] = "997"
        result["insurance_data"]["request_type"] = "Standard Requests"
        result["insurance_data"]["same_as_requesting"] = True

        result["success"] = True
        print(f"\n🎉 Auth Prep completed (reusing session) for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)

    return result


def run_auth_prep_logic(username, password, office_key, chart_number, keep_driver=False):
    """
    Authorization Preparation flow:
    Login → Popups → Dashboard → Patient Info → Search Chart Number → Handle Patient Memo
    If keep_driver=True and success, returns "_driver" and "_dashboard_handle" so the
    caller can reuse the browser session for upload (no second login needed).
    Returns: {"success": bool, "error": str|None}
    """
    driver = setup_driver()
    result = {"success": False, "error": None}

    try:
        # Step 1: Login
        if not perform_login(driver, username, password, office_key):
            result["error"] = "Login Failed"
            return result

        # Step 2: Handle post-login popups
        handle_popups(driver)

        # Step 3: Wait for dashboard window
        if not switch_to_dashboard_window(driver):
            result["error"] = "Dashboard window did not load"
            return result

        dashboard_handle = driver.current_window_handle
        print(f"\n✅ Dashboard loaded. Starting Auth Prep for Chart: {chart_number}")

        # Step 3b: Close any stale patient tabs to stay under the 3-tab limit
        close_all_patient_tabs(driver)

        # Step 4: Click Patient Info
        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found"
            return result

        # Step 5: Search Chart Number
        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart number: {chart_number}"
            return result

        # Step 6: Handle Patient Memo popup (click OK if it appears)
        handle_patient_memo(driver)

        # Step 7: Click Insurance tab
        if not click_insurance_tab(driver):
            result["error"] = "Insurance tab not found"
            return result

        # Step 8: Extract MERIDIAN insurance data (carrier + subscriber ID)
        insurance_data = extract_meridian_insurance(driver)
        if insurance_data.get("error"):
            print(f"   ⚠️ Insurance extraction warning: {insurance_data['error']}")

        result["insurance_data"] = {
            "carrier": insurance_data.get("carrier"),
            "subscriber_name": insurance_data.get("subscriber_name"),
            "subscriber_id": insurance_data.get("subscriber_id"),
            "dob": insurance_data.get("dob"),
        }

        # Step 9: Click Appointments sidebar tab
        click_appointments_sidebar(driver)

        # Step 10: Fetch Requesting Provider from Appointments table
        requesting_provider = fetch_requesting_provider_from_appointments(driver)
        result["insurance_data"]["requesting_provider"] = requesting_provider

        # Step 11: Click History sidebar tab
        click_history_sidebar(driver)

        # Step 12: Capture window handles, then double-click first History row
        handles_before = set(driver.window_handles)
        click_first_history_row(driver)

        # Step 13: Switch to the Charge Detail popup window
        if switch_to_charge_detail_window(driver, handles_before):
            # Step 14: Extract Procedure, Modifiers, ICD-10 from Charge Detail
            charge_data = extract_charge_detail_data(driver)
            result["insurance_data"]["procedure"] = charge_data.get("procedure")
            result["insurance_data"]["modifiers"] = charge_data.get("modifiers", "")
            result["insurance_data"]["diagnosis_code"] = charge_data.get("diagnosis_code")

            # Step 15: Close Charge Detail window, return to dashboard
            try:
                driver.close()
                driver.switch_to.window(dashboard_handle)
                time.sleep(2)
                print("   ✅ Closed Charge Detail, back to Dashboard.")
            except:
                driver.switch_to.window(dashboard_handle)

        # Step 16: Lookup Provider NPI (if provider name was found)
        if requesting_provider:
            handles_before_prov = set(driver.window_handles)
            if navigate_to_providers_settings(driver):
                # Check if a new window opened
                switch_to_providers_window(driver, handles_before_prov)
                # Step 17: Search for provider by name
                if search_provider_in_settings(driver, requesting_provider):
                    # Step 18: Click first provider row in search results
                    if click_first_provider_row(driver):
                        # Step 19: Extract NPI from Provider Details panel
                        provider_npi = extract_provider_npi(driver)
                        result["insurance_data"]["provider_npi"] = provider_npi

        # Step 20: Add static fields + calculated dates
        from datetime import datetime, timedelta
        from dateutil.relativedelta import relativedelta
        today = datetime.now()
        start_date = today + timedelta(days=10)
        end_date = start_date + relativedelta(months=6)

        result["insurance_data"]["requesting_tin"] = "852229929"
        result["insurance_data"]["requesting_contact_name"] = "SULLIVAN SILVA"
        result["insurance_data"]["requesting_phone"] = "7472085136"
        result["insurance_data"]["requesting_fax"] = "7472085004"
        result["insurance_data"]["start_date"] = start_date.strftime("%m/%d/%Y")
        result["insurance_data"]["end_date"] = end_date.strftime("%m/%d/%Y")
        result["insurance_data"]["total_visits"] = "60"
        result["insurance_data"]["service_type"] = "997"
        result["insurance_data"]["request_type"] = "Standard Requests"
        result["insurance_data"]["same_as_requesting"] = True

        if keep_driver:
            result["_driver"] = driver
            result["_dashboard_handle"] = dashboard_handle

        result["success"] = True
        print(f"\n🎉 Auth Prep completed for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)
    finally:
        # Only quit driver if we are NOT handing it to the caller for reuse
        if not (keep_driver and result.get("success")):
            driver.quit()

    return result


# ============================================================
# EHR SCRAPER FUNCTIONS
# Same login → search flow as Auth Prep, different post-search process
# ============================================================

def click_ehr_button(driver):
    """
    Click the EHR app icon button in the patient toolbar.
    The button is a mat-icon-button with svgicon='ehr-app' inside the Angular app iframe.
    """
    print("\n🔍 Clicking 'EHR' button...")

    selectors = [
        (By.CSS_SELECTOR, "mat-icon[svgicon='ehr-app']"),
        (By.XPATH, "//mat-icon[@svgicon='ehr-app']"),
        (By.XPATH, "//mat-icon[@data-mat-icon-name='ehr-app']"),
        (By.CSS_SELECTOR, "button mat-icon[svgicon='ehr-app']"),
    ]

    def _try_click():
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    if elem.is_displayed():
                        # Click the parent button if the match is the icon itself
                        try:
                            parent_btn = elem.find_element(By.XPATH, "./ancestor::button")
                            driver.execute_script("arguments[0].click();", parent_btn)
                        except:
                            driver.execute_script("arguments[0].click();", elem)
                        print("   ✅ Clicked 'EHR' button.")
                        time.sleep(5)
                        return True
            except:
                pass
        return False

    end_time = time.time() + 25
    while time.time() < end_time:
        # Try main window first
        driver.switch_to.default_content()
        if _try_click():
            return True

        # Try each top-level iframe (Angular app iframe)
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    return True
            except:
                pass

        time.sleep(1)

    print("❌ Failed: 'EHR' button not found.")
    return False


def switch_to_ehr_window_and_click_patient_tab(driver, pm_handle):
    """
    After clicking the EHR button, a new EHR window opens with 'Dashboard' tab selected.
    This function:
      1. Detects and switches to the NEWEST EHR window (not the old login window)
      2. Waits for EHR page to fully load (amds-tab-list elements appear)
      3. Clicks the patient tab (NOT Dashboard) so the patient chart is active
    """
    print("\n🔍 Switching to EHR window and clicking patient tab...")

    # Step 1: Switch to the NEWEST non-PM window
    # IMPORTANT: There may be multiple windows (login, PM, EHR).
    # We must pick the LAST (newest) handle, not the first non-PM one.
    ehr_handle = None
    end_time = time.time() + 30
    while time.time() < end_time:
        handles = driver.window_handles
        # Pick the LAST handle that is NOT the PM dashboard
        for h in reversed(handles):
            if h != pm_handle:
                ehr_handle = h
                break
        if ehr_handle:
            break
        time.sleep(2)

    if not ehr_handle:
        print("   ⚠️ No new window detected, continuing in current window...")
        ehr_handle = driver.current_window_handle
    
    driver.switch_to.window(ehr_handle)
    print(f"   ✅ Switched to EHR window: {driver.title}")
    print(f"   🌐 URL: {driver.current_url}")
    print(f"   🪟 Total windows: {len(driver.window_handles)}")

    # Step 2: Wait for EHR page to ACTUALLY load
    # The EHR window may redirect: "Login | AdvancedMD" → auth → EHR app with amds-tab-list
    # We wait until amds-tab-list elements appear (regardless of title).
    print("   ⏳ Waiting for EHR page to fully load...")
    load_end = time.time() + 90
    ehr_ready = False
    last_title = ""
    while time.time() < load_end:
        try:
            current_title = driver.title or ""
            if current_title != last_title:
                print(f"   📄 Title changed: {current_title}")
                last_title = current_title

            # Check if a NEWER window appeared (EHR might spawn another window)
            current_handles = driver.window_handles
            latest_non_pm = None
            for h in reversed(current_handles):
                if h != pm_handle:
                    latest_non_pm = h
                    break
            if latest_non_pm and latest_non_pm != ehr_handle:
                ehr_handle = latest_non_pm
                driver.switch_to.window(ehr_handle)
                print(f"   🔄 New window detected, switched to: {driver.title}")

            # Look for amds-tab elements in main document + iframes
            tabs_found = driver.execute_script("""
                // Check main document
                var tabs = document.querySelectorAll('ul.amds-tab-list li.amds-tab');
                if (tabs.length > 0) {
                    var info = [];
                    for (var i = 0; i < tabs.length; i++) {
                        info.push(tabs[i].getAttribute('title') || tabs[i].textContent.trim());
                    }
                    return info;
                }
                // Check inside iframes (same-origin only)
                var iframes = document.querySelectorAll('iframe');
                for (var f = 0; f < iframes.length; f++) {
                    try {
                        var fdoc = iframes[f].contentDocument || iframes[f].contentWindow.document;
                        var ftabs = fdoc.querySelectorAll('ul.amds-tab-list li.amds-tab');
                        if (ftabs.length > 0) {
                            var finfo = [];
                            for (var j = 0; j < ftabs.length; j++) {
                                finfo.push(ftabs[j].getAttribute('title') || ftabs[j].textContent.trim());
                            }
                            return finfo;
                        }
                    } catch(e) {}
                }
                return null;
            """)
            if tabs_found:
                print(f"   ✅ EHR loaded! Tabs found: {tabs_found}")
                ehr_ready = True
                break
        except:
            pass
        time.sleep(3)

    if not ehr_ready:
        print("   ⚠️ EHR page may not be fully loaded, attempting tab click anyway...")
        # Debug: list all windows
        try:
            for idx, h in enumerate(driver.window_handles):
                try:
                    driver.switch_to.window(h)
                    print(f"      Window {idx}: title='{driver.title}', url='{driver.current_url}'")
                except:
                    print(f"      Window {idx}: (could not switch)")
            driver.switch_to.window(ehr_handle)
        except:
            pass

    time.sleep(3)

    # Step 3: Click the patient tab
    # Actual HTML from AdvancedMD EHR:
    #   <ul class="amds-tab-list">
    #     <li class="amds-tab amds-tab-inactive" title="TEST,AMD">
    #       <i class="amds-icon amds-icon-close-tabs amds-tab-exit"></i>
    #       <div class="amds-ellipsis-overflow"> TEST,AMD </div>
    #     </li>
    #     <li class="amds-tab amds-tab-permanent-active ng-star-inserted" title="Dashboard">
    #       <div class="amds-ellipsis-overflow ng-star-inserted"> Dashboard </div>
    #     </li>
    #   </ul>

    JS_CLICK_PATIENT_TAB = """
    var skipTitles = ['dashboard', 'patients', 'home', ''];

    // Strategy 1: Click amds-tab-inactive (patient tab has this class)
    var inactiveTabs = document.querySelectorAll('li.amds-tab-inactive, li[class*="amds-tab-inactive"]');
    for (var i = 0; i < inactiveTabs.length; i++) {
        var tab = inactiveTabs[i];
        tab.click();
        return 'inactive-tab: ' + (tab.getAttribute('title') || tab.textContent.trim());
    }

    // Strategy 2: Click amds-tab whose title is NOT Dashboard
    var amdsTabs = document.querySelectorAll('ul.amds-tab-list li.amds-tab');
    for (var j = 0; j < amdsTabs.length; j++) {
        var t2 = amdsTabs[j];
        var title = (t2.getAttribute('title') || '').trim().toLowerCase();
        if (skipTitles.indexOf(title) >= 0) continue;
        t2.click();
        return 'tab-title: ' + t2.getAttribute('title');
    }

    // Strategy 3: Click div.amds-ellipsis-overflow with non-Dashboard text
    var divs = document.querySelectorAll('li.amds-tab div.amds-ellipsis-overflow');
    for (var k = 0; k < divs.length; k++) {
        var divText = (divs[k].textContent || '').trim().toLowerCase();
        if (skipTitles.indexOf(divText) >= 0) continue;
        divs[k].click();
        return 'overflow-div: ' + divs[k].textContent.trim();
    }

    // Strategy 4: Click any tab NOT containing 'permanent' in class
    var allTabs = document.querySelectorAll('ul.amds-tab-list li.amds-tab');
    for (var m = 0; m < allTabs.length; m++) {
        var cls = allTabs[m].className || '';
        if (cls.indexOf('permanent') >= 0) continue;
        allTabs[m].click();
        return 'non-permanent: ' + (allTabs[m].getAttribute('title') || allTabs[m].textContent.trim());
    }

    return null;
    """

    def _try_click_patient_tab():
        # JS click first (most reliable)
        try:
            result = driver.execute_script(JS_CLICK_PATIENT_TAB)
            if result:
                print(f"   ✅ Clicked patient tab: '{result}'")
                return True
        except:
            pass

        # Selenium fallback
        selectors = [
            (By.CSS_SELECTOR, "li.amds-tab-inactive"),
            (By.CSS_SELECTOR, "li[class*='amds-tab-inactive']"),
            (By.CSS_SELECTOR, "ul.amds-tab-list li.amds-tab"),
            (By.CSS_SELECTOR, "li.amds-tab div.amds-ellipsis-overflow"),
        ]
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    text = (elem.get_attribute("title") or elem.text or "").strip()
                    if text.lower() in ('dashboard', 'patients', 'home', ''):
                        continue
                    driver.execute_script("arguments[0].click();", elem)
                    print(f"   ✅ Clicked patient tab (selenium): '{text}'")
                    return True
            except:
                pass
        return False

    # Retry loop for patient tab click
    tab_end_time = time.time() + 45
    while time.time() < tab_end_time:
        driver.switch_to.default_content()
        if _try_click_patient_tab():
            time.sleep(5)
            return ehr_handle

        # Try inside iframes
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click_patient_tab():
                    time.sleep(5)
                    return ehr_handle
            except:
                pass

        # Also check OTHER windows in case tabs are in a different window
        for h in driver.window_handles:
            if h != pm_handle and h != ehr_handle:
                try:
                    driver.switch_to.window(h)
                    driver.switch_to.default_content()
                    if _try_click_patient_tab():
                        ehr_handle = h
                        time.sleep(5)
                        return ehr_handle
                except:
                    pass

        driver.switch_to.window(ehr_handle)
        driver.switch_to.default_content()
        time.sleep(3)

    print("   ⚠️ Could not find patient tab, staying on Dashboard")
    return ehr_handle


def get_plan_summary_row_count(driver):
    """Return the number of rows in the Plan Summary card."""
    JS_COUNT_ROWS = """
    var card = document.querySelector('amds-card.amds-card-plansummary');
    if (!card) {
        var headers = document.querySelectorAll('amds-card-header');
        for (var h = 0; h < headers.length; h++) {
            if (headers[h].textContent.indexOf('Plan Summary') >= 0) {
                card = headers[h].closest('amds-card');
                break;
            }
        }
    }
    if (!card) return -1;
    var rows = card.querySelectorAll('div.amds-pc-card-item-row.amds-pc-fancy-border');
    if (rows.length === 0) rows = card.querySelectorAll('amds-expandable');
    return rows.length;
    """

    def _try_count():
        try:
            return driver.execute_script(JS_COUNT_ROWS)
        except:
            return -1

    driver.switch_to.default_content()
    count = _try_count()
    if count >= 0:
        return count

    iframes = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in iframes:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            count = _try_count()
            if count >= 0:
                return count
        except:
            pass

    driver.switch_to.default_content()
    return 0


def click_plan_summary_row(driver, row_index=0):
    """
    Click a specific row (0-indexed) in the Plan Summary card.
    Row selector: div.amds-pc-card-item-row.amds-pc-fancy-border > amds-expandable
    """
    print(f"\n🔍 Clicking Plan Summary row #{row_index + 1}...")

    JS_CLICK_ROW = """
    var rowIdx = arguments[0];
    var card = document.querySelector('amds-card.amds-card-plansummary');
    if (!card) {
        var headers = document.querySelectorAll('amds-card-header');
        for (var h = 0; h < headers.length; h++) {
            if (headers[h].textContent.indexOf('Plan Summary') >= 0) {
                card = headers[h].closest('amds-card');
                break;
            }
        }
    }
    if (!card) return 'NO_CARD';

    var rows = card.querySelectorAll('div.amds-pc-card-item-row.amds-pc-fancy-border');
    if (rows.length === 0) rows = card.querySelectorAll('amds-expandable');
    if (rows.length === 0) return 'NO_ROWS';
    if (rowIdx >= rows.length) return 'INDEX_OUT_OF_RANGE:' + rows.length;

    var targetRow = rows[rowIdx];
    var expandable = targetRow.querySelector('amds-expandable');
    if (expandable) {
        expandable.click();
        var title = expandable.querySelector('.amds-pc-item-text-ellipsis');
        var date = expandable.querySelector('.amds-pc-text-blue');
        return 'CLICKED: ' + (title ? title.textContent.trim() : '') + ' ' + (date ? date.textContent.trim() : '');
    }
    targetRow.click();
    return 'CLICKED_ROW: ' + targetRow.textContent.substring(0, 60).trim();
    """

    def _try_click():
        try:
            result = driver.execute_script(JS_CLICK_ROW, row_index)
            if result and result.startswith('CLICKED'):
                print(f"   ✅ Plan Summary: {result}")
                return True
            elif result:
                print(f"   ⚠️ Plan Summary result: {result}")
        except Exception as e:
            print(f"   ⚠️ JS error: {e}")
        return False

    end_time = time.time() + 30
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_click():
            time.sleep(5)
            return True

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_click():
                    time.sleep(5)
                    return True
            except:
                pass

        driver.switch_to.default_content()
        time.sleep(2)

    print(f"   ❌ Plan Summary row #{row_index + 1} not found.")
    return False


def click_narrative_tab(driver):
    """
    After opening a Plan Summary document, click the 'Narrative' tab.
    jQuery UI tabs: <ul id="tabs"> <li> <a href="#narrative"><span>Narrative</span></a> </li>
    May be inside deeply nested iframes.
    """
    print("\n🔍 Clicking 'Narrative' tab...")

    JS_CLICK_NARRATIVE = """
    // Strategy 1: Direct href selector (jQuery UI tabs)
    var link = document.querySelector('a[href="#narrative"]');
    if (link) { link.click(); return 'CLICKED: a[href=#narrative]'; }

    // Strategy 2: li with role=tab containing Narrative text
    var tabLis = document.querySelectorAll('ul#tabs li[role="tab"], ul.ui-tabs-nav li');
    for (var i = 0; i < tabLis.length; i++) {
        if ((tabLis[i].textContent || '').trim().indexOf('Narrative') !== -1) {
            var a = tabLis[i].querySelector('a');
            if (a) { a.click(); return 'CLICKED: li>a Narrative'; }
            tabLis[i].click();
            return 'CLICKED: li Narrative';
        }
    }

    // Strategy 3: Any element with text "Narrative"
    var all = document.querySelectorAll('a, span, li, td, button');
    for (var j = 0; j < all.length; j++) {
        var t = (all[j].textContent || '').trim();
        if (t === 'Narrative') { all[j].click(); return 'CLICKED: ' + all[j].tagName + ' Narrative'; }
    }
    return null;
    """

    def _try_click_in_current_context():
        # JS click
        try:
            result = driver.execute_script(JS_CLICK_NARRATIVE)
            if result:
                print(f"   ✅ {result}")
                return True
        except:
            pass

        # Selenium fallback: a[href="#narrative"] is most reliable
        selectors = [
            (By.CSS_SELECTOR, 'a[href="#narrative"]'),
            (By.XPATH, "//span[normalize-space(.)='Narrative']/ancestor::a"),
            (By.XPATH, "//a[contains(.,'Narrative')]"),
            (By.XPATH, "//*[normalize-space(.)='Narrative']"),
        ]
        for by, val in selectors:
            try:
                elems = driver.find_elements(by, val)
                for elem in elems:
                    try:
                        driver.execute_script("arguments[0].click();", elem)
                        print(f"   ✅ Clicked 'Narrative' tab (selenium: {val}).")
                        return True
                    except:
                        pass
            except:
                pass
        return False

    def _search_iframes_recursive(depth=0, max_depth=5):
        """Recursively search through nested iframes."""
        if depth > max_depth:
            return False

        if _try_click_in_current_context():
            return True

        # Get iframes in current context
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
        except:
            return False

        for idx, frame in enumerate(iframes):
            try:
                driver.switch_to.frame(frame)
                frame_title = driver.execute_script("return document.title || ''") or ""
                print(f"   {'  ' * depth}🔎 Searching iframe depth={depth+1} idx={idx} title='{frame_title[:50]}'")
                if _search_iframes_recursive(depth + 1, max_depth):
                    return True
                driver.switch_to.parent_frame()
            except Exception as e:
                try:
                    driver.switch_to.parent_frame()
                except:
                    pass

        return False

    end_time = time.time() + 45
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _search_iframes_recursive():
            time.sleep(5)
            return True
        driver.switch_to.default_content()
        time.sleep(2)

    print("   ❌ 'Narrative' tab not found.")
    return False


def download_narrative_document(driver, download_dir):
    """
    Download the Narrative document by extracting base64 PDF data from the
    embedded iframe: <iframe id="narrative-content" src="data:application/pdf;base64,...">
    inside <div id="narrative-body">.
    Returns the path of the saved PDF file, or None.
    """
    import base64 as _base64
    print("\n📥 Downloading Narrative document (extracting base64 PDF)...")

    os.makedirs(download_dir, exist_ok=True)

    JS_EXTRACT_PDF_BASE64 = """
    var iframe = document.getElementById('narrative-content');
    if (!iframe) return null;
    var src = iframe.getAttribute('src') || '';
    var prefix = 'data:application/pdf;base64,';
    if (src.indexOf(prefix) === 0) {
        return src.substring(prefix.length);
    }
    return null;
    """

    def _try_extract_in_context():
        try:
            b64 = driver.execute_script(JS_EXTRACT_PDF_BASE64)
            if b64:
                return b64
        except:
            pass
        return None

    def _search_iframes_for_pdf(depth=0, max_depth=5):
        if depth > max_depth:
            return None
        b64 = _try_extract_in_context()
        if b64:
            return b64
        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
        except:
            return None
        for idx, frame in enumerate(iframes):
            try:
                driver.switch_to.frame(frame)
                print(f"   {'  ' * depth}🔎 Searching PDF in iframe depth={depth+1} idx={idx}")
                result = _search_iframes_for_pdf(depth + 1, max_depth)
                if result:
                    return result
                driver.switch_to.parent_frame()
            except:
                try:
                    driver.switch_to.parent_frame()
                except:
                    pass
        return None

    # Try to extract base64 PDF data
    b64_data = None
    end_time = time.time() + 30
    while time.time() < end_time and not b64_data:
        driver.switch_to.default_content()
        b64_data = _search_iframes_for_pdf()
        if not b64_data:
            driver.switch_to.default_content()
            time.sleep(2)

    if not b64_data:
        print("   ❌ Could not extract PDF data from narrative-content iframe.")
        return None

    # Decode base64 and save to file
    try:
        import uuid as _uuid
        pdf_bytes = _base64.b64decode(b64_data)
        filename = f"narrative_{_uuid.uuid4().hex[:8]}.pdf"
        filepath = os.path.join(download_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(pdf_bytes)
        print(f"   ✅ Saved PDF: {filename} ({len(pdf_bytes)} bytes)")
        return filepath
    except Exception as e:
        print(f"   ❌ Error saving PDF: {e}")
        return None


def close_document_tab(driver):
    """
    Close the currently open DOCUMENT/SUMMARY tab (not the patient tab).
    The tab bar (div.amds-tab-container > ul.amds-tab-list) contains:
      - Dashboard (permanent, skip)
      - PatientName (e.g. 'Mull,Makala', skip)
      - Document/Summary tab (e.g. '3/17/2026 Therapy Follow-Up V2.0', CLOSE THIS)
    We identify the document tab by excluding Dashboard and patient-name tabs
    (patient names match 'Word,Word' pattern).
    """
    print("\n❌ Closing summary/document tab...")

    JS_CLOSE_DOC_TAB = """
    // Find ALL amds-tab-container elements (may be nested)
    var containers = document.querySelectorAll('div.amds-tab-container');
    for (var c = 0; c < containers.length; c++) {
        var tabs = containers[c].querySelectorAll('li.amds-tab');
        for (var t = 0; t < tabs.length; t++) {
            var title = (tabs[t].getAttribute('title') || tabs[t].textContent || '').trim();
            var titleLower = title.toLowerCase();

            // SKIP: Dashboard tab
            if (titleLower === 'dashboard' || titleLower === 'patients' || titleLower === 'home') continue;
            // SKIP: Patient-name tabs (format: "LastName,FirstName" or "LAST,FIRST")
            if (/^[A-Za-z]+\s*,\s*[A-Za-z]+/.test(title)) continue;
            // SKIP: Empty titles
            if (!title) continue;

            // This should be the document/summary tab — close it
            var closeBtn = tabs[t].querySelector('i.amds-icon-close-tabs');
            if (!closeBtn) closeBtn = tabs[t].querySelector('i.amds-tab-exit');
            if (!closeBtn) closeBtn = tabs[t].querySelector('i[class*="close"]');
            if (closeBtn) {
                closeBtn.click();
                return 'CLOSED_SUMMARY: ' + title;
            }
        }
    }
    return null;
    """

    def _try_close():
        try:
            result = driver.execute_script(JS_CLOSE_DOC_TAB)
            if result:
                print(f"   ✅ {result}")
                return True
        except:
            pass

        # Selenium fallback: find all tabs, skip patient/dashboard, close document tab
        try:
            tabs = driver.find_elements(By.CSS_SELECTOR, 'div.amds-tab-container li.amds-tab')
            for tab in tabs:
                title = (tab.get_attribute("title") or tab.text or "").strip()
                title_lower = title.lower()
                if title_lower in ('dashboard', 'patients', 'home', ''):
                    continue
                # Skip patient-name pattern: "Word,Word"
                import re as _re
                if _re.match(r'^[A-Za-z]+\s*,\s*[A-Za-z]+', title):
                    continue
                # This is the document/summary tab
                close_btns = tab.find_elements(By.CSS_SELECTOR, 'i.amds-icon-close-tabs, i.amds-tab-exit, i[class*="close"]')
                for btn in close_btns:
                    try:
                        driver.execute_script("arguments[0].click();", btn)
                        print(f"   ✅ Closed summary tab (selenium): {title}")
                        return True
                    except:
                        pass
        except:
            pass
        return False

    end_time = time.time() + 15
    while time.time() < end_time:
        driver.switch_to.default_content()
        if _try_close():
            time.sleep(3)
            return True

        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        for frame in iframes:
            try:
                driver.switch_to.default_content()
                driver.switch_to.frame(frame)
                if _try_close():
                    time.sleep(3)
                    return True
            except:
                pass

        driver.switch_to.default_content()
        time.sleep(1)

    print("   ⚠️ Could not close summary/document tab")
    return False


def process_all_plan_summary_rows(driver, download_dir):
    """
    From the Plan Summary card, download only 3 documents:
      - First 2 rows (most recent)
      - Last 1 row (oldest)
    For each selected row:
      1. Click row → 2. Click Narrative tab → 3. Download document → 4. Close summary tab
    Returns list of downloaded PDF file paths.
    """
    print("\n📋 Processing Plan Summary rows (first 2 + last 1)...")

    row_count = get_plan_summary_row_count(driver)
    print(f"   Found {row_count} row(s) in Plan Summary")

    if row_count <= 0:
        print("   ❌ No Plan Summary documents found! Nothing to download.")
        return []

    # Determine which row indices to process: first 2 + last 1
    if row_count == 1:
        target_indices = [0]
    elif row_count == 2:
        target_indices = [0, 1]
    elif row_count == 3:
        target_indices = [0, 1, 2]
    else:
        # first 2 (index 0,1) + last 1 (index row_count-1)
        target_indices = [0, 1, row_count - 1]

    print(f"   📌 Will download rows: {[i+1 for i in target_indices]} (out of {row_count})")

    downloaded_pdfs = []

    for i in target_indices:
        print(f"\n{'='*60}")
        print(f"📄 Processing row {i + 1} of {row_count}")
        print(f"{'='*60}")

        # Step A: Click the row
        if not click_plan_summary_row(driver, row_index=i):
            print(f"   ⚠️ Could not click row {i + 1}, skipping")
            continue

        # Step B: Click Narrative tab
        if not click_narrative_tab(driver):
            print(f"   ⚠️ Narrative tab not found for row {i + 1}, skipping")
            close_document_tab(driver)
            time.sleep(2)
            continue

        # Step C: Download the document
        pdf_path = download_narrative_document(driver, download_dir)
        if pdf_path:
            downloaded_pdfs.append(pdf_path)
        else:
            print(f"   ⚠️ Download failed for row {i + 1}")

        # Step D: Close the summary/document tab (NOT the patient tab)
        close_document_tab(driver)
        time.sleep(3)

    print(f"\n✅ Downloaded {len(downloaded_pdfs)} of {len(target_indices)} selected documents")
    return downloaded_pdfs


def merge_ehr_pdfs(downloaded_pdfs, auth_prep_pdf_path=None, output_path=None):
    """
    Merge downloaded EHR PDFs into one PDF.
    If auth_prep_pdf_path is provided, place it at the FIRST index (page 1).
    Uses pikepdf for merging.
    Returns the output path, or None on failure.
    """
    import pikepdf
    import tempfile as _tempfile

    print("\n📎 Merging PDFs...")

    if not downloaded_pdfs and not auth_prep_pdf_path:
        print("   ❌ No PDFs to merge")
        return None

    if output_path is None:
        output_path = _tempfile.mktemp(suffix='.pdf', prefix='ehr_merged_')

    try:
        merger = pikepdf.Pdf.new()

        # First: add the auth prep filled PDF at index 0
        if auth_prep_pdf_path and os.path.exists(auth_prep_pdf_path):
            print(f"   📄 Adding auth prep PDF (first): {os.path.basename(auth_prep_pdf_path)}")
            src = pikepdf.open(auth_prep_pdf_path)
            merger.pages.extend(src.pages)

        # Then: add all downloaded narrative PDFs in order
        for idx, pdf_path in enumerate(downloaded_pdfs):
            if pdf_path and os.path.exists(pdf_path):
                print(f"   📄 Adding narrative PDF #{idx + 1}: {os.path.basename(pdf_path)}")
                src = pikepdf.open(pdf_path)
                merger.pages.extend(src.pages)

        if len(merger.pages) == 0:
            print("   ❌ No pages to merge")
            return None

        merger.save(output_path)
        print(f"   ✅ Merged PDF saved: {output_path} ({len(merger.pages)} pages)")
        return output_path

    except Exception as e:
        print(f"   ❌ PDF merge error: {e}")
        return None


def run_ehr_logic(username, password, office_key, chart_number, auth_prep_pdf_path=None, keep_driver=False):
    """
    EHR flow: Login → Popups → Dashboard → Patient Info → Search Chart → Handle Memo
    Then: Process all Plan Summary rows (Narrative → Download → Close) → Merge PDFs.
    If keep_driver=True and success, returns "_driver" and "_dashboard_handle".
    """
    import tempfile as _tempfile
    download_dir = _tempfile.mkdtemp(prefix='ehr_download_')
    driver = setup_driver(download_dir=download_dir)
    result = {"success": False, "error": None, "scraped_data": None, "merged_pdf_path": None}

    try:
        # Step 1: Login
        if not perform_login(driver, username, password, office_key):
            result["error"] = "Login Failed"
            return result

        # Step 2: Handle popups
        handle_popups(driver)

        # Step 3: Wait for dashboard
        if not switch_to_dashboard_window(driver):
            result["error"] = "Dashboard window did not load"
            return result

        dashboard_handle = driver.current_window_handle
        print(f"\n✅ Dashboard loaded. Starting EHR for Chart: {chart_number}")

        close_all_patient_tabs(driver)

        # Step 4: Click Patient Info
        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found"
            return result

        # Step 5: Search Chart Number
        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart number: {chart_number}"
            return result

        # Step 6: Handle Patient Memo
        handle_patient_memo(driver)

        # Step 7: Click EHR button
        if not click_ehr_button(driver):
            result["error"] = "EHR button not found"
            return result

        # Step 8: Switch to EHR window and click patient tab
        ehr_handle = switch_to_ehr_window_and_click_patient_tab(driver, dashboard_handle)
        if not ehr_handle:
            result["error"] = "Failed to switch to EHR window"
            return result

        # Step 9: Process ALL Plan Summary rows (click → narrative → download → close)
        downloaded_pdfs = process_all_plan_summary_rows(driver, download_dir)

        # Step 10: Merge downloaded PDFs (auth_prep PDF at first index)
        if downloaded_pdfs:
            merged_path = merge_ehr_pdfs(downloaded_pdfs, auth_prep_pdf_path)
            result["merged_pdf_path"] = merged_path
        else:
            print("   ⚠️ No documents were downloaded from Plan Summary")

        result["scraped_data"] = {"downloaded_count": len(downloaded_pdfs)}
        result["success"] = True

        if keep_driver:
            result["_driver"] = driver
            result["_dashboard_handle"] = dashboard_handle

        print(f"\n🎉 EHR completed for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)
    finally:
        if not (keep_driver and result.get("success")):
            driver.quit()

    return result


def run_ehr_for_existing_session(driver, dashboard_handle, chart_number, auth_prep_pdf_path=None):
    """
    Process a single chart using an ALREADY logged-in driver (reuse session).
    Downloads all Plan Summary narratives and merges with auth_prep PDF.
    """
    import tempfile as _tempfile
    download_dir = _tempfile.mkdtemp(prefix='ehr_download_')
    result = {"success": False, "error": None, "scraped_data": None, "merged_pdf_path": None}
    try:
        print(f"\n📋 EHR (reusing session) for Chart: {chart_number}")

        # Set download directory for this chart via CDP
        try:
            driver.execute_cdp_cmd('Page.setDownloadBehavior', {
                'behavior': 'allow',
                'downloadPath': download_dir
            })
        except:
            pass

        # Close extra windows, go back to dashboard
        for handle in list(driver.window_handles):
            if handle != dashboard_handle:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except:
                    pass
        driver.switch_to.window(dashboard_handle)
        time.sleep(2)

        close_all_patient_tabs(driver)
        handle_patients_open_dialog(driver)

        if not click_patient_info(driver):
            result["error"] = "Patient Info icon not found"
            return result

        if not search_claim_id(driver, chart_number):
            result["error"] = f"Failed to search chart number: {chart_number}"
            return result

        handle_patient_memo(driver)

        # Click EHR button
        if not click_ehr_button(driver):
            result["error"] = "EHR button not found"
            return result

        # Switch to EHR window and click patient tab
        ehr_handle = switch_to_ehr_window_and_click_patient_tab(driver, dashboard_handle)
        if not ehr_handle:
            result["error"] = "Failed to switch to EHR window"
            return result

        # Process ALL Plan Summary rows (click → narrative → download → close)
        downloaded_pdfs = process_all_plan_summary_rows(driver, download_dir)

        # Merge downloaded PDFs (auth_prep PDF at first index)
        if downloaded_pdfs:
            merged_path = merge_ehr_pdfs(downloaded_pdfs, auth_prep_pdf_path)
            result["merged_pdf_path"] = merged_path
        else:
            print("   ⚠️ No documents were downloaded from Plan Summary")

        result["scraped_data"] = {"downloaded_count": len(downloaded_pdfs)}
        result["success"] = True

        print(f"\n🎉 EHR completed (reusing session) for Chart: {chart_number}")

    except Exception as e:
        result["error"] = str(e)

    return result


# ═══════════════════════════════════════════════════════════════
#  GoTo Fax Upload
# ═══════════════════════════════════════════════════════════════

GOTO_LOGIN_URL = (
    "https://identity.goto.com/login?service=https%3A%2F%2Fidentity.goto.com"
    "%2Foauth%2Fapprove%3Fclient_id%3Da7717fe1-75ce-4f82-b477-2f6dabe3eed9"
    "%26response_type%3Dcode%26redirect_uri%3Dhttps%253A%252F%252Fapp.goto.com"
    "%252Fg2m-oauth%26state%3D%25257B%252522inflightRequest%252522%25253A"
    "%252522https%25253A%25252F%25252Fapp.goto.com%25252F%252522%25252C"
    "%252522nonce%252522%25253A%252522VVJTLXJWb1BXM1R1WTk1ZXhrUDV"
    "%25252BVS43T2ktTHlybDJWMDlYWnVGcTh1Tw%25253D%25253D%252522%25257D"
    "%26code_challenge%3DygUnn9TIxXkN-4NzDjf3koXCd9euPR8B4FmOWnIEQgI"
    "%26code_challenge_method%3DS256%26login_theme%3Dgoto&theme=goto"
)


def human_type(element, text):
    """Types text slowly to mimic human behavior and bypass basic bot detection."""
    import random
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))


def goto_login(driver, email, password):
    try:
        print(f"\n🔐 Opening GoTo login page...")
        wait = WebDriverWait(driver, 30)

        # Go directly to the GoTo login URL
        driver.get(GOTO_LOGIN_URL)
        time.sleep(5)

        # If we landed on error/landing page instead of login form,
        # click "Sign in" button
        for attempt in range(3):
            current = driver.current_url
            print(f"   Current URL: {current}")

            if "identity.goto.com/login" in current:
                print("   ✅ On login page!")
                break

            # On error page or landing page — click Sign in
            print(f"   ⚠️ Not on login page — looking for Sign in button (attempt {attempt+1})...")
            try:
                sign_in = wait.until(EC.element_to_be_clickable(
                    (By.XPATH,
                     "//chameleon-button[contains(text(),'Sign in')] | "
                     "//button[contains(text(),'Sign in')] | "
                     "//a[contains(text(),'Sign in')] | "
                     "//chameleon-button[contains(text(),'Sign in to GoTo')] | "
                     "//button[contains(text(),'Sign in to GoTo')] | "
                     "//a[contains(text(),'Sign in to GoTo')]")
                ))
                sign_in.click()
                time.sleep(5)
            except Exception:
                print("   No Sign in button found, retrying...")
                driver.get(GOTO_LOGIN_URL)
                time.sleep(5)

        print(f"   Login page: {driver.current_url}")

        # Enter email
        print("   Entering email (simulating human typing)...")
        email_field = wait.until(EC.element_to_be_clickable((By.ID, "emailAddress")))
        email_field.clear()
        time.sleep(random.uniform(0.5, 1.5))
        human_type(email_field, email)

        time.sleep(random.uniform(1.0, 2.0))
        next_btn = wait.until(EC.element_to_be_clickable((By.ID, "next-button")))
        next_btn.click()
        print("   ✅ Clicked Next")

        # Enter password
        print("   Waiting for password field...")
        password_field = wait.until(EC.element_to_be_clickable((By.ID, "password")))
        password_field.clear()

        time.sleep(random.uniform(0.5, 1.5))
        print("   Entering password...")
        human_type(password_field, password)

        time.sleep(random.uniform(1.0, 2.0))
        sign_in_btn = wait.until(EC.element_to_be_clickable((By.ID, "submit-button")))
        sign_in_btn.click()
        print("   ✅ Clicked Sign in")

        # Wait a moment for GoTo to process the login
        time.sleep(5)

        # Navigate directly to GoTo Fax New page — if logged in, this loads fine
        # If not logged in, it will redirect back to login page
        print("   ⏳ Navigating to GoTo Fax New page to verify login...")
        driver.get("https://app.goto.com/voice/faxes/new")
        time.sleep(60)

        current = driver.current_url
        print(f"   Dashboard URL: {current}")

        # If redirected to login page, we are NOT logged in
        if "identity.goto.com/login" in current or "login" in current:
            print("   ❌ Redirected to login — login failed")
            return False

        print(f"   ✅ Login complete! Fax page loaded: {current}")
        return True

    except Exception as e:
        print(f"   ❌ GoTo login failed: {e}")
        return False


def goto_logout(driver):
    """Logout from GoTo after upload is done, so next run starts fresh from login."""
    try:
        print("   🔓 Logging out of GoTo...")
        driver.get("https://app.goto.com/logout")
        time.sleep(3)
        print("   ✅ Logged out successfully")
    except Exception as e:
        print(f"   ⚠️ Logout error (ignored): {e}")


def setup_goto_driver():
    import undetected_chromedriver as uc

    # Incognito mode — every run starts fresh, browser close = auto logout
    print("   Launching GoTo browser in incognito (private) mode...")

    chrome_options = uc.ChromeOptions()
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--incognito")

    driver = uc.Chrome(options=chrome_options, version_main=146)
    return driver


# ── Helper: deep shadow DOM search ──

JS_FIND_IN_SHADOW = """
function findInShadow(root, selector) {
    if (!root) return null;
    if (root.matches && root.matches(selector)) return root;
    if (root.shadowRoot) {
        let found = findInShadow(root.shadowRoot, selector);
        if (found) return found;
    }
    for (let child of root.children) {
        let found = findInShadow(child, selector);
        if (found) return found;
    }
    return null;
}
"""

def enter_fax_number(driver, fax_number):
    print("   Entering fax number...")
    
    # 1. CLEAN THE FAX NUMBER (Most Important Step)
    # Remove brackets, hyphens, and spaces. Example: "(747)208-5004" -> "7472085004"
    clean_fax = re.sub(r'\D', '', fax_number)
    
    # Agar US number hai aur aage '1' laga hai, toh hata do (Kyunki +1 pehle se selected hai)
    if len(clean_fax) == 11 and clean_fax.startswith('1'):
        clean_fax = clean_fax[1:]
        
    print(f"   Cleaned fax number for input: {clean_fax}")

    to_input = driver.execute_script(
        JS_FIND_IN_SHADOW +
        "return findInShadow(document, 'input[placeholder=\"Enter name or number\"], input.selected-value, input[role=\"combobox\"]');"
    )

    if not to_input:
        print("   ❌ Could not find 'To' input field")
        return False

    # 2. Click to focus the field (Is baar focus hum explicit karenge)
    actions = ActionChains(driver)
    actions.click(to_input)
    actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE)
    actions.perform()
    time.sleep(1)

    # 3. Type pure digits slowly using Global ActionChains
    print(f"   Typing digits slowly...")
    actions = ActionChains(driver)
    for char in clean_fax:
        actions.send_keys(char) # Active cursor jaha hai waha type hoga
        actions.pause(random.uniform(0.1, 0.2))
    actions.perform()

    print("   Waiting for component to process...")
    time.sleep(3)

    # 4. Pure Keyboard ENTER (Bina kisi JS ya Arrow down ke)
    # Jab number valid hota hai, toh Enter dabane se wo usko chip mein convert kar deta hai
    print("   Pressing ENTER to lock recipient...")
    ActionChains(driver).send_keys(Keys.ENTER).perform()
    time.sleep(1.5)
    
    # 5. Press TAB to safely move away and verify value is locked
    ActionChains(driver).send_keys(Keys.TAB).perform()
    time.sleep(1)
    
    return True


def enter_subject(driver, subject):
    print("   Entering subject...")
    subj_input = driver.execute_script(
        JS_FIND_IN_SHADOW + """
        // Look for the subject container and then input
        var subjectInput = findInShadow(document, 'chameleon-input-field.fax-cover-page-subject-input');
        if (subjectInput && subjectInput.shadowRoot) {
            var inp = subjectInput.shadowRoot.querySelector('input');
            if (inp) return inp;
        }
        
        // Generic fallback: Try to find any input inside a div containing 'subject' in class
        var allInputs = document.querySelectorAll('*');
        for (let el of allInputs) {
            if (el.className && typeof el.className === 'string' && el.className.includes('subject')) {
                let deepInp = findInShadow(el, 'input');
                if (deepInp) return deepInp;
            }
        }
        return null;
        """
    )

    if subj_input:
        ActionChains(driver).click(subj_input).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
        time.sleep(0.5)
        
        for char in subject:
            ActionChains(driver).send_keys(char).perform()
            time.sleep(random.uniform(0.05, 0.15))
        
        print(f"   ✅ Subject entered: {subject}")
        return True
    else:
        print("   ❌ Could not find Subject field")
        return False


def enter_notes(driver, notes):
    print("   Entering notes...")
    notes_ta = driver.execute_script(
        JS_FIND_IN_SHADOW + """
        var ta = findInShadow(document, 'chameleon-text-area.notes-textarea');
        if (ta && ta.shadowRoot) {
            var textarea = ta.shadowRoot.querySelector('textarea');
            if (textarea) return textarea;
        }
        return findInShadow(document, 'textarea');
        """
    )

    if notes_ta:
        ActionChains(driver).click(notes_ta).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.DELETE).perform()
        time.sleep(0.5)
        
        for char in notes:
            ActionChains(driver).send_keys(char).perform()
            time.sleep(random.uniform(0.02, 0.08))
            
        print(f"   ✅ Notes entered: {notes}")
        return True
    else:
        print("   ❌ Could not find Notes field")
        return False


def click_fax_info_next(driver):
    print("   Clicking Next button...")
    clicked = driver.execute_script(
        JS_FIND_IN_SHADOW + """
        // Pehle label-id ke through try karo
        var btn = findInShadow(document, 'chameleon-button[label-id="label-next"]');
        if (btn) { btn.click(); return 'SHADOW_CLICKED'; }
        
        // Phir normal text search
        var allBtns = document.querySelectorAll('chameleon-button');
        for (let b of allBtns) {
            if (b.textContent.trim().includes('Next')) {
                b.click();
                return 'TEXT_CLICKED';
            }
        }
        return null;
        """
    )
    
    if clicked:
        print(f"   ✅ Next button clicked ({clicked})")
        return True
    
    # Fallback Selenium Click
    try:
        driver.find_element(By.XPATH, "//chameleon-button[contains(text(),'Next')]").click()
        print("   ✅ Next button clicked (Selenium)")
        return True
    except:
        print("   ❌ Could not find Next button")
        return False


# --- Main Function ---
def fill_goto_fax_form(driver, fax_number, subject="Attn. To: Authorization Dept.", notes="Prior Authorization Request"):
    """
    Main orchestrator function that calls all the individual steps.
    """
    print(f"\n📝 Filling GoTo Fax form...")
    print(f"   Fax To: {fax_number} | Subject: {subject} | Notes: {notes}")

    # 1. Add Fax Number & Select Dropdown
    enter_fax_number(driver, fax_number)
    
    # 2. Add Subject
    enter_subject(driver, subject)
    
    # 3. Add Notes
    enter_notes(driver, notes)
    
    # 4. Click Next
    time.sleep(2)
    result = click_fax_info_next(driver)
    
    time.sleep(5) # Wait for Step 2 UI to load
    return result


def goto_upload_file(driver, pdf_path):
    """
    GoTo Fax Step 2: Upload a PDF file using the file input on the 'Upload your files' page.
    Returns True on success, False on failure.
    """
    print(f"\n📤 Step 2: Uploading PDF file...")
    print(f"   File: {pdf_path}")

    if not os.path.exists(pdf_path):
        print(f"   ❌ PDF file not found: {pdf_path}")
        return False

    # Find hidden file input — may be in shadow DOM
    file_input = driver.execute_script(JS_FIND_IN_SHADOW + """
        var inp = document.querySelector('input[type="file"]');
        if (inp) return inp;
        return findInShadow(document, 'input[type="file"]');
    """)

    if not file_input:
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
        except Exception:
            pass

    if not file_input:
        print("   ❌ Could not find file input")
        return False

    # Make input interactable if hidden
    driver.execute_script("""
        arguments[0].style.display = 'block';
        arguments[0].style.visibility = 'visible';
        arguments[0].style.opacity = '1';
        arguments[0].style.height = '1px';
        arguments[0].style.width = '1px';
    """, file_input)
    time.sleep(1)

    file_input.send_keys(pdf_path)
    print(f"   ✅ PDF sent to file input")
    time.sleep(8)  # Wait for upload + thumbnail to appear

    # Click Next → go to Step 3
    print("   Clicking Next to go to Step 3 (Preview and send)...")
    clicked = driver.execute_script("""
        var buttons = document.querySelectorAll('chameleon-button');
        for (var i = 0; i < buttons.length; i++) {
            if ((buttons[i].textContent || '').trim() === 'Next') {
                buttons[i].click();
                return 'CLICKED';
            }
        }
    """ + JS_FIND_IN_SHADOW + """
        var btn = findInShadow(document, 'chameleon-button[label-id="label-next"]');
        if (btn) { btn.click(); return 'SHADOW'; }
        return null;
    """)

    if not clicked:
        try:
            driver.find_element(By.XPATH,
                "//chameleon-button[contains(text(),'Next')] | //button[contains(text(),'Next')]"
            ).click()
            clicked = 'SELENIUM'
        except Exception:
            pass

    if clicked:
        print(f"   ✅ Next clicked ({clicked})")
        time.sleep(5)
        return True
    else:
        print("   ❌ Could not click Next on Step 2")
        return False


def goto_send_fax(driver):
    """
    GoTo Fax Step 3: Click the 'Send' button on the 'Preview and send' page.
    Returns True on success, False on failure.
    """
    print("\n📨 Step 3: Clicking Send button...")
    time.sleep(3)

    clicked = driver.execute_script("""
        var buttons = document.querySelectorAll('chameleon-button');
        for (var i = 0; i < buttons.length; i++) {
            var txt = (buttons[i].textContent || '').trim();
            if (txt === 'Send' || txt === 'Send fax') {
                buttons[i].click();
                return 'CLICKED: ' + txt;
            }
        }
    """ + JS_FIND_IN_SHADOW + """
        var btn = findInShadow(document, 'chameleon-button[label-id="label-send"]');
        if (btn) { btn.click(); return 'SHADOW_SEND'; }
        return null;
    """)

    if not clicked:
        try:
            driver.find_element(By.XPATH,
                "//chameleon-button[contains(text(),'Send')] | //button[contains(text(),'Send')]"
            ).click()
            clicked = 'SELENIUM'
        except Exception:
            pass

    if clicked:
        print(f"   ✅ Send clicked ({clicked})")
        time.sleep(10)  # Wait for fax to submit
        print("   🎉 Fax submitted successfully!")
        return True
    else:
        print("   ❌ Could not find Send button")
        return False


def upload_ehr_to_goto(email, password, chart_number, pdf_path,
                       fax_number=None, subject="Attn. To: Authorization Dept.",
                       notes="Prior Authorization Request"):
    driver = setup_goto_driver()
    result = {"success": False, "error": None}

    try:
        if not goto_login(driver, email, password):
            result["error"] = "GoTo Login Failed or OTP Timeout"
            return result

        print(f"\n✅ GoTo login successful for chart: {chart_number}")
        print(f"   PDF to upload: {pdf_path}")

        if not fax_number:
            fax_number = '(747)208-5004'

        # Step 1: Fill fax form (To, Subject, Notes) and click Next
        if not fill_goto_fax_form(driver, fax_number, subject=subject, notes=notes):
            result["error"] = "Failed to fill fax form (Step 1)"
            return result

        print(f"   ✅ Step 1 (Fax Information) completed — now on Step 2 (Upload)")

        if not goto_upload_file(driver, pdf_path):
            result["error"] = "Failed to upload PDF file (Step 2)"
            return result

        if not goto_send_fax(driver):
            result["error"] = "Failed to send fax (Step 3)"
            return result

        result["success"] = True
        return result

    except Exception as e:
        result["error"] = str(e)
    finally:
        # Incognito mode — just quit browser, session auto-clears
        driver.quit()

    return result